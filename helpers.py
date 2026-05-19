from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Populated by the FastAPI lifespan handler
affiliated_as: dict[str, Any] = {}


def flash(request: Request, message: str, category: str = "danger") -> None:
    """Queue a flash message for the next page render."""
    request.session.setdefault("_flashes", []).append([category, message])


def pop_flashes(request: Request) -> list[tuple[str, str]]:
    """Return and clear the queued flash messages."""
    return [(c, m) for c, m in request.session.pop("_flashes", [])]


def render(request: Request, name: str, ctx: dict[str, Any] | None = None):
    """Render a template with the common context (affiliated AS + flashes)."""
    base_ctx: dict[str, Any] = {
        "affiliated": affiliated_as,
        "get_flashed_messages": lambda with_categories=False: (
            pop_flashes(request)
            if with_categories
            else [m for _, m in pop_flashes(request)]
        ),
    }
    if ctx:
        base_ctx.update(ctx)
    return templates.TemplateResponse(request, name, base_ctx)


def redirect(url: str) -> RedirectResponse:
    """Return a 303 redirect (POST/Redirect/GET pattern)."""
    return RedirectResponse(url=url, status_code=303)


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
        text = resp.text.strip()
        return text[:500] if text else default

    if isinstance(data, dict):
        for key in ("detail", "error"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value

    flattened = flatten_errors(data)
    if flattened:
        return " | ".join(flattened)[:500]
    return default
