"""Configuration loading from YAML + .env"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class UpstreamConfig:
    name: str
    base: str
    protocol: str  # "openai" or "anthropic"
    auth: str
    timeout: int = 120


@dataclass
class HubConfig:
    name: str
    base: str
    model: str
    auth: str


@dataclass
class AppConfig:
    upstreams: dict[str, UpstreamConfig] = field(default_factory=dict)
    hubs: dict[str, HubConfig] = field(default_factory=dict)
    routes: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    no_vision: set[str] = field(default_factory=set)
    signals: dict[str, re.Pattern] = field(default_factory=dict)


def _resolve_env(value: str) -> str:
    """Replace ${VAR} or ${VAR:-default} with environment variable value."""
    if not isinstance(value, str):
        return value
    match = re.fullmatch(r'\$\{(\w+)(?::-([^}]*))?\}', value)
    if match:
        return os.getenv(match.group(1), match.group(2) or "")
    return value


def _find_config_dir() -> Path:
    """Find config directory, checking common locations."""
    candidates = [
        Path.cwd() / "config",
        Path(__file__).resolve().parent.parent.parent / "config",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return candidates[0]


def load_config(config_dir: Path | None = None, env_file: Path | None = None) -> AppConfig:
    """Load full configuration from YAML files and .env."""
    if config_dir is None:
        config_dir = _find_config_dir()

    # Load .env
    if env_file is None:
        for candidate in [config_dir.parent / ".env", config_dir / ".env", Path.cwd() / ".env"]:
            if candidate.exists():
                env_file = candidate
                break
    if env_file and env_file.exists():
        load_dotenv(env_file)

    cfg = AppConfig()

    # Load hubs.yaml
    hubs_path = config_dir / "hubs.yaml"
    if hubs_path.exists():
        raw = yaml.safe_load(hubs_path.read_text(encoding="utf-8"))

        for name, u in (raw.get("upstreams") or {}).items():
            cfg.upstreams[name] = UpstreamConfig(
                name=name,
                base=u["base"],
                protocol=u.get("protocol", "openai"),
                auth=_resolve_env(u.get("auth", "")),
                timeout=u.get("timeout", 120),
            )

        for name, h in (raw.get("hubs") or {}).items():
            cfg.hubs[name] = HubConfig(
                name=name,
                base=h["base"],
                model=h["model"],
                auth=_resolve_env(h.get("auth", "")),
            )

    # Load routes.yaml
    routes_path = config_dir / "routes.yaml"
    if routes_path.exists():
        raw = yaml.safe_load(routes_path.read_text(encoding="utf-8"))

        cfg.routes = raw.get("routes", {})
        cfg.aliases = raw.get("aliases", {})
        cfg.no_vision = set(raw.get("no_vision", []))

        for name, pattern in (raw.get("signals") or {}).items():
            cfg.signals[name] = re.compile(pattern, re.IGNORECASE)

    return cfg
