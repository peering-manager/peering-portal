from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import httpx

from config import settings
from exceptions import PeeringManagerError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI

__all__ = ("affiliated_as", "api_request", "lifespan")

logger = logging.getLogger("peering.portal")

API_BASE_PATH = "/api/peering/portal/"
CLIENT_TIMEOUT = 30.0
CLIENT_RETRIES = 3
STARTUP_ATTEMPTS = 5

client: httpx.AsyncClient
affiliated_as: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Open the API client and fetch the affiliated AS on startup, close the client on shutdown."""
    global client  # noqa: PLW0603
    client = httpx.AsyncClient(
        base_url=f"{settings.pm_url}{API_BASE_PATH}",
        headers={"Authorization": f"Token {settings.pm_token}"},
        timeout=CLIENT_TIMEOUT,
        transport=httpx.AsyncHTTPTransport(retries=CLIENT_RETRIES),
    )

    resp: httpx.Response | None = None
    for attempt in range(1, STARTUP_ATTEMPTS + 1):
        if attempt > 1:
            await asyncio.sleep(2 * (attempt - 1))
        try:
            resp = await client.get("affiliated")
        except httpx.HTTPError as exc:
            logger.warning(f"peering manager is unreachable (attempt {attempt}/{STARTUP_ATTEMPTS}): {exc}")
            continue
        if resp.is_success or resp.status_code < HTTPStatus.INTERNAL_SERVER_ERROR:
            break
        logger.warning(
            f"fetching the affiliated as returned HTTP {resp.status_code} (attempt {attempt}/{STARTUP_ATTEMPTS})"
        )

    if resp is None or not resp.is_success:
        await client.aclose()
        raise RuntimeError(
            "Failed to fetch the affiliated AS from Peering Manager. Make sure to use an API token that belongs "
            "to a user who has selected an affiliated AS in their preferences."
        )
    affiliated_as.update(resp.json())

    yield
    await client.aclose()


async def api_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Call the Peering Manager API, raising `PeeringManagerError` when it cannot be reached."""
    try:
        resp = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        logger.error(f"{method} {path} against peering manager failed: {exc}")
        raise PeeringManagerError from exc
    if not resp.is_success:
        logger.info(f"{method} {path} against peering manager returned HTTP {resp.status_code}")
    return resp
