"""FastAPI application."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from claw_router import __version__
from claw_router.breaker import CircuitBreaker
from claw_router.config import AppConfig, load_config
from claw_router.dashboard import render_dashboard
from claw_router.health import HealthChecker
from claw_router.router import has_image_content, parse_model, resolve_target
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
    upstream, model_id, target_model = resolve_target(body, cfg, _breaker)

    logger.info(
        f"[route] -> {upstream}:{model_id} "
        f"(req: {body.get('model', 'none')}, stream: {stream})"
    )

    try:
        result = await call_upstream(
            _client, cfg, upstream, model_id, body, stream, target_model, _breaker
        )
    except UpstreamError as e:
        return JSONResponse(status_code=e.status_code, content=e.body)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": {"message": str(e)}})
    except Exception as e:
        logger.error(f"[upstream] unexpected error: {e}")
        return JSONResponse(
            status_code=502,
            content={"error": {"message": f"Upstream error: {e}", "type": "proxy_error"}},
        )

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
    result = {"routes": {}, "hub": {}}
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
