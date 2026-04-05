"""Local YAML-based storage for SWARM CLI state."""

import yaml
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".swarm"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def get(key: str, default: Any = None) -> Any:
    """Dot-notation key access, e.g. 'auth.github_handle'."""
    cfg = load()
    for k in key.split("."):
        if not isinstance(cfg, dict):
            return default
        cfg = cfg.get(k)
        if cfg is None:
            return default
    return cfg


def set_val(key: str, value: Any) -> None:
    """Set a dot-notation key."""
    cfg = load()
    keys = key.split(".")
    d = cfg
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    d[keys[-1]] = value
    save(cfg)


def is_logged_in() -> bool:
    return bool(get("auth.github_token"))


def has_discord() -> bool:
    return bool(get("profile.discord"))
