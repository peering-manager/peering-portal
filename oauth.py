from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import Request  # noqa: TC002

from config import (
    OAUTH_ENABLED,
    PDB_AUTHORIZE_URL,
    PDB_CLIENT_ID,
    PDB_CLIENT_SECRET,
    PDB_REDIRECT_URI,
    PDB_REQUIRED_PERMS,
    PDB_TOKEN_URL,
    PDB_USERINFO_URL,
)
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
)

logger = logging.getLogger("peering.portal")

# `networks` is the scope that adds the affiliations to the profile, without it the portal has no
# ASN allowlist to enforce. `openid` is left out on purpose: the portal reads the profile endpoint
# and never has to validate an ID token.
SCOPE = "profile email networks"
USER_KEY = "pdb_user"
PENDING_KEY = "pdb_login"
HTTP_TIMEOUT = 15.0
GENERIC_FAILURE = "The PeeringDB sign-in failed. Please try again in a moment."


def redirect_uri(request: Request) -> str:
    """
    Return the callback URL PeeringDB must send the visitor back to.

    PeeringDB matches it against the registered one, so a deployment behind a reverse proxy has to
    configure it: the URL the app builds carries the scheme and host uvicorn sees, not the public ones.
    """
    return PDB_REDIRECT_URI or str(request.url_for("oauth_callback"))


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
            "client_id": PDB_CLIENT_ID,
            "redirect_uri": callback,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{PDB_AUTHORIZE_URL}?{query}"


def take_pending_login(request: Request, state: str) -> dict[str, str]:
    """
    Return the stored sign-in attempt matching `state` and drop it from the session.

    The state ties the callback to the browser that started the sign-in, which is what stops an
    attacker from having a visitor finish somebody else's authorisation.
    """
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
            PDB_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback,
                "client_id": PDB_CLIENT_ID,
                "client_secret": PDB_CLIENT_SECRET,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.error(f"the peeringdb token endpoint is unreachable: {exc}")
        raise OAuthError(GENERIC_FAILURE) from exc

    if not resp.is_success:
        # The body can hold the client secret back, so it stays in the log and never reaches a page
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
        resp = await client.get(PDB_USERINFO_URL, headers={"Authorization": f"Bearer {token}"})
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
    """
    Return the networks the profile may act on behalf of, one entry per AS number.

    PeeringDB lists an affiliation with the rights it grants. A row without a usable ASN, or short of
    the rights the operator asks for, is dropped: the list becomes the allowlist of the session.
    """
    networks: dict[int, dict[str, Any]] = {}

    for entry in profile.get("networks") or []:
        if not isinstance(entry, dict):
            continue
        asn = parse_asn(entry.get("asn"))
        if asn is None or asn in networks:
            continue
        perms = entry.get("perms")
        perms = perms if isinstance(perms, int) else 0
        if PDB_REQUIRED_PERMS and perms & PDB_REQUIRED_PERMS != PDB_REQUIRED_PERMS:
            continue
        networks[asn] = {"asn": asn, "name": str(entry.get("name") or ""), "perms": perms}

    return sorted(networks.values(), key=lambda network: network["asn"])


def store_user(request: Request, profile: dict[str, Any]) -> dict[str, Any]:
    """Keep the identity and the networks of the profile in the session, and return them."""
    user = {
        "name": str(profile.get("name") or profile.get("given_name") or "PeeringDB user"),
        "email": str(profile.get("email") or ""),
        "verified_email": bool(profile.get("verified_email") or profile.get("email_verified")),
        "networks": _networks(profile),
    }
    request.session[USER_KEY] = user
    return user


def sign_out(request: Request) -> None:
    """Drop the sign-in and everything it authorised."""
    for key in (USER_KEY, PENDING_KEY, "wizard"):
        request.session.pop(key, None)


def current_user(request: Request) -> dict[str, Any] | None:
    """Return the signed-in PeeringDB user, or `None` when there is none."""
    if not OAUTH_ENABLED:
        return None
    user = request.session.get(USER_KEY)
    return user if isinstance(user, dict) else None


def allowed_asns(request: Request) -> list[int]:
    """Return the AS numbers the visitor may file a request for."""
    user = current_user(request)
    return [network["asn"] for network in user["networks"]] if user else []


def asn_allowed(request: Request, asn: object) -> bool:
    """
    Return whether the visitor may act on behalf of `asn`.

    Without OAuth credentials the portal cannot tell one visitor from another, so it accepts every
    ASN. That is the behaviour the portal had before, and the startup log says so.
    """
    if not OAUTH_ENABLED:
        return True
    number = parse_asn(asn)
    return number is not None and number in allowed_asns(request)


def require_user(request: Request) -> dict[str, Any] | None:
    """Route dependency: let the request through only once PeeringDB vouched for the visitor."""
    if not OAUTH_ENABLED:
        return None
    user = current_user(request)
    if user is None:
        raise NotAuthenticatedError
    return user
