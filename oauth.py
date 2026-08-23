from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Request  # noqa: TC002

from config import settings
from exceptions import NotAuthenticatedError, OAuthError
from functions import parse_asn

__all__ = (
    "allowed_asns",
    "asn_allowed",
    "authorisation_url",
    "current_user",
    "fetch_profile",
    "redirect_uri",
    "require_user",
    "sign_out",
    "store_user",
    "take_pending_login",
    "touch",
)

logger = logging.getLogger("peering.portal")

# `networks` carries the affiliations that become the allowlist, without it there is nothing to enforce
SCOPE = "profile email networks"

USER_KEY = "pdb_user"
PENDING_KEY = "pdb_login"
SEEN_KEY = "seen"
TOUCH_INTERVAL = 5 * 60
SESSION_LIFETIME = 12 * 60 * 60
# A browser silently drops a cookie over 4096 bytes, so the network list has to stay under this
NETWORKS_BUDGET = 2500
HTTP_TIMEOUT = 15.0
GENERIC_FAILURE = "The PeeringDB sign-in failed. Please try again in a moment."


def redirect_uri(request: Request) -> str:
    """Return the callback URL, which a proxied deployment has to configure: PeeringDB matches it exactly."""
    return settings.pdb_redirect_uri or str(request.url_for("oauth_callback"))


def _pkce_pair() -> tuple[str, str]:
    """Return a PKCE verifier and its S256 challenge."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorisation_url(request: Request, *, callback: str, next_path: str) -> str:
    """Remember what this sign-in attempt needs to finish, then return where to send the visitor."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(32)
    request.session[PENDING_KEY] = {"state": state, "verifier": verifier, "callback": callback, "next": next_path}

    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.pdb_client_id,
            "redirect_uri": callback,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{settings.pdb_authorize_url}?{query}"


def take_pending_login(request: Request, state: str) -> dict[str, str]:
    """Return the stored attempt matching `state`, which ties this callback to the browser that began it."""
    pending = request.session.pop(PENDING_KEY, None)
    if not isinstance(pending, dict):
        raise OAuthError("The sign-in attempt expired. Please try again.")
    if not state or not secrets.compare_digest(str(pending.get("state", "")), state):
        raise OAuthError("The sign-in attempt did not start here. Please try again.")
    return pending


async def fetch_profile(*, code: str, verifier: str, callback: str) -> dict[str, Any]:
    """Trade the authorisation code for a token, then read the PeeringDB profile it gives access to."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        token = await _fetch_token(client, code=code, verifier=verifier, callback=callback)
        return await _fetch_userinfo(client, token)


async def _fetch_token(client: httpx.AsyncClient, *, code: str, verifier: str, callback: str) -> str:
    try:
        resp = await client.post(
            settings.pdb_token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback,
                "client_id": settings.pdb_client_id,
                "client_secret": settings.pdb_client_secret,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.error(f"the peeringdb token endpoint is unreachable: {exc}")
        raise OAuthError(GENERIC_FAILURE) from exc

    if not resp.is_success:
        # The body can echo the client secret, so it stays in the log
        logger.error(f"the peeringdb token endpoint returned HTTP {resp.status_code}: {resp.text[:500]}")
        raise OAuthError(GENERIC_FAILURE)

    try:
        token = resp.json().get("access_token")
    except ValueError as exc:
        raise OAuthError(GENERIC_FAILURE) from exc
    if not isinstance(token, str) or not token:
        logger.error("the peeringdb token endpoint returned no access token")
        raise OAuthError(GENERIC_FAILURE)
    return token


async def _fetch_userinfo(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
    try:
        resp = await client.get(settings.pdb_userinfo_url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        logger.error(f"the peeringdb profile endpoint is unreachable: {exc}")
        raise OAuthError(GENERIC_FAILURE) from exc

    if not resp.is_success:
        logger.error(f"the peeringdb profile endpoint returned HTTP {resp.status_code}")
        raise OAuthError(GENERIC_FAILURE)

    try:
        profile = resp.json()
    except ValueError as exc:
        raise OAuthError(GENERIC_FAILURE) from exc
    if not isinstance(profile, dict):
        raise OAuthError(GENERIC_FAILURE)
    return profile


def _networks(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the networks the profile may act for, one per AS number. This list is the allowlist."""
    networks: dict[int, dict[str, Any]] = {}

    for entry in profile.get("networks") or []:
        if not isinstance(entry, dict):
            continue
        asn = parse_asn(entry.get("asn"))
        if asn is None or asn in networks:
            continue
        perms = entry.get("perms")
        perms = perms if isinstance(perms, int) else 0
        if settings.pdb_required_perms and perms & settings.pdb_required_perms != settings.pdb_required_perms:
            continue
        networks[asn] = {"asn": asn, "name": str(entry.get("name") or "")}

    return sorted(networks.values(), key=lambda network: network["asn"])


def _fit(networks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Trim the list to what a cookie carries, names first, and say how many networks did not fit."""
    if len(json.dumps(networks)) <= NETWORKS_BUDGET:
        return networks, 0

    bare = [{"asn": network["asn"]} for network in networks]
    if len(json.dumps(bare)) <= NETWORKS_BUDGET:
        logger.info(f"a profile carries {len(networks)} networks, dropping their names to fit the session cookie")
        return bare, 0

    kept: list[dict[str, Any]] = []
    for entry in bare:
        kept.append(entry)
        if len(json.dumps(kept)) > NETWORKS_BUDGET:
            kept.pop()
            break
    dropped = len(bare) - len(kept)
    logger.warning(f"a profile carries {len(networks)} networks, {dropped} do not fit the session cookie")
    return kept, dropped


def store_user(request: Request, profile: dict[str, Any]) -> dict[str, Any]:
    """Keep the identity and the networks of the profile in the session, and return them."""
    networks, dropped = _fit(_networks(profile))
    user = {
        "name": str(profile.get("name") or profile.get("given_name") or "PeeringDB user"),
        "email": str(profile.get("email") or ""),
        "signed_in": int(time.time()),
        "networks": networks,
    }
    if dropped:
        user["dropped"] = dropped
    request.session[USER_KEY] = user
    return user


def sign_out(request: Request) -> None:
    """Drop the sign-in and everything it authorised."""
    for key in (USER_KEY, PENDING_KEY, SEEN_KEY, "wizard"):
        request.session.pop(key, None)


def current_user(request: Request) -> dict[str, Any] | None:
    """Return the signed-in PeeringDB user, or `None` once there is none or the sign-in went stale."""
    if not settings.oauth_enabled:
        return None
    user = request.session.get(USER_KEY)
    if not isinstance(user, dict):
        return None
    signed_in = user.get("signed_in")
    if int(time.time()) - (signed_in if isinstance(signed_in, int) else 0) >= SESSION_LIFETIME:
        sign_out(request)
        return None
    return user


def allowed_asns(request: Request) -> list[int]:
    """Return the AS numbers the visitor may file a request for."""
    user = current_user(request)
    return [network["asn"] for network in user["networks"]] if user else []


def asn_allowed(request: Request, asn: object) -> bool:
    """Return whether the visitor may act for `asn`. Without OAuth credentials every ASN is accepted."""
    if not settings.oauth_enabled:
        return True
    number = parse_asn(asn)
    return number is not None and number in allowed_asns(request)


def touch(request: Request) -> None:
    """Write a stamp now and then, so the session cookie outlives a run of pages that only read it."""
    stamp = request.session.get(SEEN_KEY)
    now = int(time.time())
    if now - (stamp if isinstance(stamp, int) else 0) >= TOUCH_INTERVAL:
        request.session[SEEN_KEY] = now


def require_user(request: Request) -> dict[str, Any] | None:
    """Route dependency: let the request through, and keep the visitor signed in, once vouched for."""
    if not settings.oauth_enabled:
        return None
    user = current_user(request)
    if user is None:
        raise NotAuthenticatedError
    touch(request)
    return user
