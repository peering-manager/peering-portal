from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_FILE_PATH = Path(os.getenv("PORTAL_CONFIG", "config.toml"))
_FILE_DATA: dict[str, Any] = {}
if _FILE_PATH.is_file():
    with _FILE_PATH.open("rb") as f:
        _FILE_DATA = tomllib.load(f)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _resolve(env_key: str, *, default: Any = None, required: bool = False) -> Any:
    """Resolve a single config value following the precedence rules."""
    if env_key in os.environ:
        return os.environ[env_key]
    file_value = _FILE_DATA.get(env_key.lower())
    if file_value is not None:
        return file_value
    if required:
        raise RuntimeError(
            f"{env_key} is not set. Provide it via the {env_key} environment variable or as {env_key.lower()!r} in {_FILE_PATH}."
        )
    return default


PM_URL: str = _resolve("PM_URL", required=True).rstrip("/")
PM_TOKEN: str = _resolve("PM_TOKEN", required=True)
SECRET_KEY: str = _resolve("SECRET_KEY", default="change-me-in-production")
HOST: str = _resolve("HOST", default="0.0.0.0")  # noqa: S104
PORT: int = int(_resolve("PORT", default=8080))
RELOAD: bool = _truthy(_resolve("RELOAD", default=False))
