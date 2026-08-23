from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, TomlConfigSettingsSource

# Read `.env` before the settings, so PORTAL_CONFIG itself can live there
load_dotenv()
CONFIG_FILE = Path(os.getenv("PORTAL_CONFIG", "config.toml"))


class Settings(BaseSettings):
    """Everything the portal reads, from the environment first and from the TOML file second."""

    model_config = SettingsConfigDict(extra="ignore", toml_file=CONFIG_FILE)

    pm_url: str
    pm_token: str
    secret_key: str = ""
    session_cookie_secure: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    reload: bool = False

    pdb_client_id: str = ""
    pdb_client_secret: str = ""
    pdb_redirect_uri: str = ""
    pdb_authorize_url: str = "https://auth.peeringdb.com/oauth2/authorize/"
    pdb_token_url: str = "https://auth.peeringdb.com/oauth2/token/"
    pdb_userinfo_url: str = "https://auth.peeringdb.com/profile/v1"
    # PeeringDB grants 0x01 read, 0x02 update, 0x04 create and 0x08 delete. Zero takes any affiliation.
    pdb_required_perms: int = 0

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return env_settings, TomlConfigSettingsSource(settings_cls)

    @field_validator("session_cookie_secure", "reload", mode="before")
    @classmethod
    def _blank_is_off(cls, value: Any) -> Any:
        return False if value == "" else value

    @field_validator("pm_url")
    @classmethod
    def _no_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _ephemeral_secret_key(self) -> Settings:
        # A key per process beats a public default: a restart signs everybody out, nothing worse
        if not self.secret_key:
            self.secret_key = secrets.token_hex(32)
        return self

    @property
    def oauth_enabled(self) -> bool:
        """Whether the portal holds the credentials it needs to check who owns an ASN."""
        return bool(self.pdb_client_id and self.pdb_client_secret)


def _load() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        missing = [str(error["loc"][0]).upper() for error in exc.errors() if error["type"] == "missing"]
        if not missing:
            raise
        names = ", ".join(missing[:-1]) + (" and " if missing[:-1] else "") + missing[-1]
        verb = "is" if len(missing) == 1 else "are"
        raise RuntimeError(
            f"{names} {verb} not set. The portal reads a setting from the environment, or from "
            f"{CONFIG_FILE} under its lower case name."
        ) from exc


settings = _load()
