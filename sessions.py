from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from functions import valid_ip

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.datastructures import FormData

__all__ = ("deduplicate_sessions", "parse_private_sessions", "parse_public_sessions")


def _text(value: object) -> str:
    """Return a submitted form value as text. The portal has no file input, so anything else is not ours."""
    return value if isinstance(value, str) else ""


def _text_values(form: FormData, key: str) -> list[str]:
    """Return every text value submitted under `key`, skipping uploaded files."""
    return [value for value in form.getlist(key) if isinstance(value, str)]


def parse_public_sessions(*, form: FormData, location_names: dict[str, str]) -> tuple[list[dict[str, Any]], str | None]:
    """
    Turn a public peering form into session rows.

    Values come as `<location>|<local_ip>|<peer_ip>`, where `peer_ip` pins the operator Connection
    the session lands on. A malformed row is skipped instead of reported: the form offers a fixed
    set of checkboxes, so only a tampered submission can produce one.
    """
    chosen: list[dict[str, Any]] = []

    for value in _text_values(form, "session"):
        try:
            location, local_ip, peer_ip = value.split("|", 2)
        except ValueError:
            continue
        if not all((location, local_ip, peer_ip)) or not valid_ip(local_ip) or not valid_ip(peer_ip):
            continue
        secret = _text(form.get(f"secret|{location}|{local_ip}|{peer_ip}")).strip()
        chosen.append(
            {
                "location": location,
                "location_name": location_names.get(location, location),
                "local_ip": local_ip,
                "peer_ip": peer_ip,
                "session_secret": secret,
            }
        )

    return chosen, None


def parse_private_sessions(
    *, form: FormData, locations: Sequence[str], location_names: dict[str, str]
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Turn a private peering form into session rows, or return the first problem found.

    Each facility submits parallel lists of local IP, peer IP and secret, one row per index. The
    peer IP is mandatory here because the operator IP on a private interconnect cannot be guessed,
    except for /31s and /127s.
    """
    chosen: list[dict[str, Any]] = []

    for location in locations:
        local_ips = _text_values(form, f"private_local_ip|{location}")
        peer_ips = _text_values(form, f"private_peer_ip|{location}")
        session_secrets = _text_values(form, f"private_secret|{location}")
        location_name = location_names.get(location, location)

        for idx, value in enumerate(local_ips):
            local_ip = value.strip()
            if not local_ip:
                continue

            peer_ip = (peer_ips[idx] if idx < len(peer_ips) else "").strip()
            if not peer_ip:
                return [], f"Peer IP is required for {local_ip} at {location_name}."

            for ip in (local_ip, peer_ip):
                if not valid_ip(ip):
                    return [], f"{ip!r} at {location_name} is not a valid IP address."
                # The prefix length is needed to configure the interconnect interfaces on both routers
                if "/" not in ip:
                    return [], f"{ip!r} at {location_name} needs a prefix length, e.g. 192.0.2.1/30."

            secret = (session_secrets[idx] if idx < len(session_secrets) else "").strip()
            chosen.append(
                {
                    "location": location,
                    "location_name": location_name,
                    "local_ip": local_ip,
                    "peer_ip": peer_ip,
                    "session_secret": secret,
                }
            )

    return chosen, None


def deduplicate_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows repeating a location and host address pair, the API rejects submissions holding any."""
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []

    for session in sessions:
        key = (
            session["location"],
            str(ipaddress.ip_interface(session["local_ip"]).ip),
            str(ipaddress.ip_interface(session["peer_ip"]).ip) if session["peer_ip"] else "",
        )
        if key not in seen:
            seen.add(key)
            unique.append(session)

    return unique
