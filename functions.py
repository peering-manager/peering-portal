from __future__ import annotations

import ipaddress
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from constants import ASN_MAX, ASN_MIN

if TYPE_CHECKING:
    import httpx

__all__ = (
    "api_error_message",
    "conflicting_ips",
    "flatten_errors",
    "format_datetime",
    "parse_asn",
    "parse_tracking_id",
    "safe_path",
    "valid_ip",
)


def format_datetime(value: str) -> str:
    """Format an ISO 8601 timestamp from the API as a short human-readable string."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC")


def parse_tracking_id(value: str) -> str | None:
    """Return the normalised tracking ID, or `None` if it is not a valid UUID."""
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return None


def parse_asn(value: object) -> int | None:
    """
    Return `value` as an AS number, or `None` when it is not one.

    A leading "AS" is tolerated as networks are often written down that way.
    """
    try:
        number = int(str(value).strip().upper().removeprefix("AS"))
    except (TypeError, ValueError):
        return None
    return number if ASN_MIN <= number <= ASN_MAX else None


def safe_path(value: str, default: str = "/") -> str:
    """
    Return `value` when it is a path inside this app, `default` otherwise.

    The value reaches the portal as a query parameter, so it must not send the visitor to another
    site. A backslash is rejected too: some browsers read it as a slash.
    """
    value = value.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    return value


def valid_ip(value: str) -> bool:
    """Return whether `value` is an IP address, with or without a prefix length."""
    try:
        ipaddress.ip_interface(value)
    except ValueError:
        return False
    return True


def flatten_errors(data: Any, prefix: str = "") -> list[str]:
    """Flatten a DRF validation error tree into a list of "path: msg" lines."""
    out: list[str] = []
    if isinstance(data, dict):
        for field, value in data.items():
            path = f"{prefix}.{field}" if prefix else str(field)
            out.extend(flatten_errors(value, path))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            path = f"{prefix}[{i}]" if prefix else str(i)
            out.extend(flatten_errors(item, path))
    elif data not in (None, ""):
        out.append(f"{prefix}: {data}" if prefix else str(data))
    return out


def api_error_message(resp: httpx.Response, default: str) -> str:
    """Extract a useful error message from a non-success Peering Manager API response."""
    try:
        data = resp.json()
    except ValueError:
        return default

    if isinstance(data, dict):
        for key in ("detail", "error"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

    flattened = flatten_errors(data)
    if flattened:
        return " | ".join(flattened)[:500]
    return default


def conflicting_ips(resp: httpx.Response) -> list[str]:
    """Extract the conflicting IPs reported alongside a 409 response, if any."""
    try:
        data = resp.json()
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    value = data.get("conflicting_ips")
    if isinstance(value, list):
        return [str(ip) for ip in value]
    return []
