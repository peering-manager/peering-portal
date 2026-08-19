from __future__ import annotations

import os
import secrets
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
# Sessions hold the wizard state and the PeeringDB sign-in, so an ephemeral key beats a well-known
# default: worst case a restart signs everybody out instead of leaving cookies signed with a public value
SECRET_KEY: str = _resolve("SECRET_KEY", default="") or secrets.token_hex(32)
# Set this on any deployment served over HTTPS: the session cookie carries the PeeringDB sign-in
SESSION_COOKIE_SECURE: bool = _truthy(_resolve("SESSION_COOKIE_SECURE", default=False))
HOST: str = _resolve("HOST", default="0.0.0.0")
PORT: int = int(_resolve("PORT", default=8080))
RELOAD: bool = _truthy(_resolve("RELOAD", default=False))

# PeeringDB OAuth. Register an application on https://www.peeringdb.com/oauth2/applications/ as a
# confidential client with the authorization code grant. The endpoints come from
# https://auth.peeringdb.com/.well-known/openid-configuration and only need a value here when
# PeeringDB moves them.
PDB_CLIENT_ID: str = _resolve("PDB_CLIENT_ID", default="")
PDB_CLIENT_SECRET: str = _resolve("PDB_CLIENT_SECRET", default="")
PDB_REDIRECT_URI: str = _resolve("PDB_REDIRECT_URI", default="")
PDB_AUTHORIZE_URL: str = _resolve("PDB_AUTHORIZE_URL", default="https://auth.peeringdb.com/oauth2/authorize/")
PDB_TOKEN_URL: str = _resolve("PDB_TOKEN_URL", default="https://auth.peeringdb.com/oauth2/token/")
PDB_USERINFO_URL: str = _resolve("PDB_USERINFO_URL", default="https://auth.peeringdb.com/profile/v1")
# Bitmask a network must grant the user before the portal accepts a request for it. PeeringDB grants
# 0x01 read, 0x02 update, 0x04 create and 0x08 delete. Zero accepts any affiliation.
PDB_REQUIRED_PERMS: int = int(_resolve("PDB_REQUIRED_PERMS", default=0))

OAUTH_ENABLED: bool = bool(PDB_CLIENT_ID and PDB_CLIENT_SECRET)
