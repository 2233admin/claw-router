"""CLI interface for claw-router."""

from __future__ import annotations

import click


@click.group()
def cli():
    """Claw Router - Intelligent LLM API Router"""
    pass


@cli.command()
@click.option("--port", default=3456, help="Listen port")
@click.option("--host", default="0.0.0.0", help="Listen host")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(port: int, host: str, reload: bool):
    """Start the router server."""
    import logging
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    uvicorn.run(
        "claw_router.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


@cli.command()
def status():
    """Show route table and breaker status."""
    from claw_router.config import load_config
    cfg = load_config()
    for cap, models in cfg.routes.items():
        click.echo(f"\n  {cap}:")
        for m in models:
            click.echo(f"    {m}")
    click.echo(f"\n  Aliases: {len(cfg.aliases)}")
    click.echo(f"  Hubs: {len(cfg.hubs)}")


@cli.command()
def health():
    """Ping all hubs and check health."""
    import asyncio
    import httpx

    from claw_router.config import load_config

    cfg = load_config()

    async def _check():
        async with httpx.AsyncClient(timeout=10) as client:
            for name, hub in cfg.hubs.items():
                try:
                    resp = await client.get(f"{hub.base}/v1/models")
                    click.echo(f"  {name}: {resp.status_code} ({hub.base})")
                except Exception as e:
                    click.echo(f"  {name}: FAIL - {e}")

    asyncio.run(_check())


@cli.command()
def deploy():
    """Deploy to production (43.156.202.94)."""
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent.parent / "deploy" / "deploy.sh"
    if not script.exists():
        click.echo(f"Deploy script not found: {script}")
        sys.exit(1)
    subprocess.run(["bash", str(script)], check=True)
