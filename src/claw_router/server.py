"""FastAPI application."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from claw_router import __version__
from claw_router.breaker import CircuitBreaker
from claw_router.config import AppConfig, load_config
from claw_router.dashboard import render_dashboard
from claw_router.health import HealthChecker
from claw_router.router import (
    get_fallback_candidates,
    has_image_content,
    parse_model,
    resolve_target,
)
from claw_router.upstream import UpstreamError, call_upstream

logger = logging.getLogger(__name__)

# Global state
_config: AppConfig | None = None
_breaker = CircuitBreaker()
_health: HealthChecker | None = None
_client: httpx.AsyncClient | None = None


def get_config() -> AppConfig:
    global _config
    if _config is None:
        _config = load_config()
    return _config


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client, _health
    cfg = get_config()
    _client = httpx.AsyncClient()
    _health = HealthChecker(cfg)
    _health.start()
    logger.info(f"[router] Claw Router v{__version__} started")
    logger.info(f"[router] classifier={'ON' if cfg.classifier_enabled else 'OFF'} "
                f"model={cfg.classifier_model} fallback_retries={cfg.fallback_max_retries}")
    for cap, ms in cfg.routes.items():
        logger.info(f"[router]   {cap}: {' > '.join(ms)}")
    yield
    await _health.stop()
    await _client.aclose()


app = FastAPI(title="Claw Router", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    cfg = get_config()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": {"message": "Invalid JSON"}})

    stream = body.get("stream", False)
    upstream, model_id, target_model, capability = await resolve_target(body, cfg, _breaker, _client)

    logger.info(
        f"[route] -> {upstream}:{model_id} "
        f"(req: {body.get('model', 'none')}, cap: {capability}, stream: {stream})"
    )

    # Try primary target, then fallback chain
    tried = set()
    last_error = None

    for attempt in range(cfg.fallback_max_retries + 1):
        try:
            result = await call_upstream(
                _client, cfg, upstream, model_id, body, stream, target_model, _breaker
            )
        except UpstreamError as e:
            tried.add(target_model)
            last_error = e
            logger.warning(
                f"[fallback] {target_model} failed ({e.status_code}), "
                f"attempt {attempt + 1}/{cfg.fallback_max_retries + 1}"
            )
            # Try next candidate in fallback chain
            if not capability:
                break  # Explicit model requested, no fallback
            candidates = get_fallback_candidates(capability, cfg.routes, _breaker, tried)
            if not candidates:
                break
            target_model = candidates[0]
            upstream, model_id = parse_model(target_model, set(cfg.hubs.keys()))
            logger.info(f"[fallback] trying {upstream}:{model_id}")
            continue
        except ValueError as e:
            return JSONResponse(status_code=400, content={"error": {"message": str(e)}})
        except Exception as e:
            tried.add(target_model)
            last_error = e
            logger.error(f"[upstream] unexpected error: {e}")
            if not capability:
                break
            candidates = get_fallback_candidates(capability, cfg.routes, _breaker, tried)
            if not candidates:
                break
            target_model = candidates[0]
            upstream, model_id = parse_model(target_model, set(cfg.hubs.keys()))
            logger.info(f"[fallback] trying {upstream}:{model_id}")
            continue

        # Success
        if stream:
            from starlette.responses import StreamingResponse

            async def event_generator():
                async for chunk in result:
                    if isinstance(chunk, str):
                        yield chunk.encode()
                    else:
                        yield chunk

            return StreamingResponse(
                event_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        else:
            return JSONResponse(content=result)

    # All attempts exhausted
    if isinstance(last_error, UpstreamError):
        return JSONResponse(status_code=last_error.status_code, content=last_error.body)
    return JSONResponse(
        status_code=502,
        content={"error": {
            "message": f"All models exhausted ({len(tried)} tried: {', '.join(tried)})",
            "type": "proxy_error",
        }},
    )


@app.get("/v1/models")
@app.get("/models")
async def list_models():
    cfg = get_config()
    models = []
    seen = set()

    for cap, ms in cfg.routes.items():
        for m in ms:
            if m not in seen:
                seen.add(m)
                upstream, model_id = parse_model(m, set(cfg.hubs.keys()))
                models.append({
                    "id": m,
                    "object": "model",
                    "owned_by": {"ark": "volcengine", "cli": "cliproxy", "hub": "free-llm-hub"}.get(upstream, upstream),
                    "upstream": upstream,
                    "model_id": model_id,
                    "capability": cap,
                    "vision": m not in cfg.no_vision,
                    "circuit_open": _breaker.is_open(m),
                })

    for hub_name in cfg.hubs:
        hub_id = f"hub:{hub_name}"
        if hub_id not in seen:
            seen.add(hub_id)
            models.append({
                "id": hub_id,
                "object": "model",
                "owned_by": "free-llm-hub",
                "upstream": "hub",
                "model_id": cfg.hubs[hub_name].model,
                "capability": "manual",
                "circuit_open": _breaker.is_open(hub_id),
            })

    return {"object": "list", "data": models}


@app.get("/status")
async def status():
    cfg = get_config()
    result = {
        "classifier": {
            "enabled": cfg.classifier_enabled,
            "model": cfg.classifier_model,
        },
        "routes": {},
        "hub": {},
    }
    for cap, ms in cfg.routes.items():
        result["routes"][cap] = {m: "OPEN" if _breaker.is_open(m) else "ok" for m in ms}
    for hub_name, hub_cfg in cfg.hubs.items():
        hub_id = f"hub:{hub_name}"
        result["hub"][hub_name] = {
            "base": hub_cfg.base,
            "model": hub_cfg.model,
            "circuit": "OPEN" if _breaker.is_open(hub_id) else "ok",
        }
    return result


@app.get("/health")
async def health():
    health_data = _health.get_status() if _health else {}
    return {
        "ok": True,
        "service": "claw-router",
        "version": __version__,
        "endpoints": health_data,
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    cfg = get_config()
    return render_dashboard(cfg, _breaker, _health)


# --- Admin API ---

_ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")


def _check_admin(authorization: str | None) -> JSONResponse | None:
    if not _ADMIN_TOKEN:
        return JSONResponse(status_code=403, content={"error": "ADMIN_TOKEN not configured"})
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "Missing Bearer token"})
    if authorization[7:] != _ADMIN_TOKEN:
        return JSONResponse(status_code=401, content={"error": "Invalid token"})
    return None


@app.post("/admin/hubs", status_code=201)
async def admin_add_hub(request: Request, authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    body = await request.json()
    name = body.get("name")
    if not name or not body.get("base") or not body.get("model"):
        return JSONResponse(status_code=400, content={"error": "name, base, model required"})
    cfg = get_config()
    cfg.add_hub(name, body["base"], body["model"], body.get("auth", ""))
    return {"ok": True, "hub": name}


@app.delete("/admin/hubs/{name}")
async def admin_remove_hub(name: str, authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    cfg = get_config()
    if not cfg.remove_hub(name):
        return JSONResponse(status_code=404, content={"error": f"Hub '{name}' not found"})
    return {"ok": True, "removed": name}


@app.patch("/admin/hubs/{name}")
async def admin_update_hub(name: str, request: Request, authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    body = await request.json()
    cfg = get_config()
    if not cfg.update_hub(name, **{k: body.get(k) for k in ("base", "model", "auth")}):
        return JSONResponse(status_code=404, content={"error": f"Hub '{name}' not found"})
    return {"ok": True, "updated": name}


@app.post("/admin/routes/{cap}")
async def admin_add_route(cap: str, request: Request, authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    body = await request.json()
    model = body.get("model")
    if not model:
        return JSONResponse(status_code=400, content={"error": "model required"})
    cfg = get_config()
    cfg.add_route(cap, model)
    return {"ok": True, "cap": cap, "model": model}


@app.delete("/admin/routes/{cap}/{model:path}")
async def admin_remove_route(cap: str, model: str, authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    cfg = get_config()
    if not cfg.remove_route(cap, model):
        return JSONResponse(status_code=404, content={"error": f"Route '{model}' not in '{cap}'"})
    return {"ok": True, "removed": model, "cap": cap}


@app.post("/admin/reload")
async def admin_reload(authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    global _config
    _config = load_config()
    return {"ok": True, "message": "Config reloaded from disk"}


@app.get("/admin/config")
async def admin_get_config(authorization: str | None = Header(None)):
    if err := _check_admin(authorization):
        return err
    cfg = get_config()
    return {
        "upstreams": {n: {"base": u.base, "protocol": u.protocol} for n, u in cfg.upstreams.items()},
        "hubs": {n: {"base": h.base, "model": h.model} for n, h in cfg.hubs.items()},
        "routes": cfg.routes,
        "aliases": cfg.aliases,
        "classifier": {
            "enabled": cfg.classifier_enabled,
            "model": cfg.classifier_model,
            "timeout": cfg.classifier_timeout,
        },
    }
