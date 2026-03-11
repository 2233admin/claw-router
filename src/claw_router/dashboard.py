"""HTML status dashboard."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claw_router.breaker import CircuitBreaker
    from claw_router.config import AppConfig
    from claw_router.health import HealthChecker


def render_dashboard(config: AppConfig, breaker: CircuitBreaker, health: HealthChecker) -> str:
    """Render HTML dashboard showing routes, breaker status, and health."""
    rows_routes = ""
    for cap, models in config.routes.items():
        for m in models:
            status = "OPEN" if breaker.is_open(m) else "ok"
            color = "#e74c3c" if status == "OPEN" else "#2ecc71"
            rows_routes += f"<tr><td>{cap}</td><td>{m}</td><td style='color:{color}'>{status}</td></tr>\n"

    rows_hubs = ""
    for name, hub in config.hubs.items():
        hub_id = f"hub:{name}"
        circuit = "OPEN" if breaker.is_open(hub_id) else "ok"
        color = "#e74c3c" if circuit == "OPEN" else "#2ecc71"
        h = health.status.get(name, {})
        latency = f"{h.get('latency_ms', '-')}ms" if h.get("ok") else h.get("error", "unknown")
        rows_hubs += (
            f"<tr><td>{name}</td><td>{hub.base}</td><td>{hub.model}</td>"
            f"<td style='color:{color}'>{circuit}</td><td>{latency}</td></tr>\n"
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Claw Router Dashboard</title>
<meta http-equiv="refresh" content="10">
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 1000px; margin: 2em auto; background: #1a1a2e; color: #eee; }}
h1 {{ color: #e94560; }}
h2 {{ color: #0f3460; background: #16213e; padding: 8px 16px; border-radius: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin: 1em 0; }}
th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #333; }}
th {{ background: #16213e; }}
tr:hover {{ background: #16213e55; }}
.ts {{ color: #888; font-size: 0.85em; }}
</style></head><body>
<h1>Claw Router v3.0</h1>
<p class="ts">Updated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Route Table</h2>
<table><tr><th>Capability</th><th>Model</th><th>Circuit</th></tr>
{rows_routes}</table>

<h2>Hub Status</h2>
<table><tr><th>Hub</th><th>Base</th><th>Model</th><th>Circuit</th><th>Latency</th></tr>
{rows_hubs}</table>
</body></html>"""
