"""Background health checker for upstream endpoints."""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from claw_router.config import AppConfig

logger = logging.getLogger(__name__)


class HealthChecker:
    def __init__(self, config: AppConfig, interval: int = 30):
        self.config = config
        self.interval = interval
        self.status: dict[str, dict] = {}
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            await self._check_all()
            await asyncio.sleep(self.interval)

    async def _check_all(self) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            for name, hub in self.config.hubs.items():
                start = time.monotonic()
                try:
                    resp = await client.get(f"{hub.base}/v1/models")
                    latency = (time.monotonic() - start) * 1000
                    self.status[name] = {
                        "ok": resp.status_code < 400,
                        "status_code": resp.status_code,
                        "latency_ms": round(latency, 1),
                        "checked_at": time.time(),
                    }
                except Exception as e:
                    self.status[name] = {
                        "ok": False,
                        "error": str(e),
                        "latency_ms": -1,
                        "checked_at": time.time(),
                    }

            for name, upstream in self.config.upstreams.items():
                start = time.monotonic()
                try:
                    resp = await client.get(upstream.base, follow_redirects=True)
                    latency = (time.monotonic() - start) * 1000
                    self.status[f"upstream:{name}"] = {
                        "ok": resp.status_code < 500,
                        "status_code": resp.status_code,
                        "latency_ms": round(latency, 1),
                        "checked_at": time.time(),
                    }
                except Exception as e:
                    self.status[f"upstream:{name}"] = {
                        "ok": False,
                        "error": str(e),
                        "latency_ms": -1,
                        "checked_at": time.time(),
                    }

    def get_status(self) -> dict:
        return dict(self.status)
