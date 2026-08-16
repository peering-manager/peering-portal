from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import escape

from api import affiliated_as
from config import OAUTH_ENABLED
from enums import status_colour
from functions import format_datetime
from oauth import current_user

if TYPE_CHECKING:
    from fastapi import Request
    from starlette.responses import Response

__all__ = ("flash", "pop_flashes", "redirect", "render", "templates")

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["datetime"] = format_datetime
templates.env.filters["status_colour"] = status_colour


def flash(request: Request, message: str, category: str = "danger") -> None:
    """
    Queue a flash message for the next page render.

    Messages are HTML-escaped at queueing time because the template renders them with `|safe`; pass a
    `markupsafe.Markup` to include trusted HTML.
    """
    request.session.setdefault("_flashes", []).append([category, str(escape(message))])


def pop_flashes(request: Request) -> list[tuple[str, str]]:
    """Return and clear the queued flash messages."""
    return [(c, m) for c, m in request.session.pop("_flashes", [])]


def render(request: Request, name: str, ctx: dict[str, Any] | None = None) -> Response:
    """Render a template with the common context, the affiliated AS, the visitor and the queued flashes."""
    base_ctx: dict[str, Any] = {
        "affiliated": affiliated_as,
        "oauth_enabled": OAUTH_ENABLED,
        "user": current_user(request),
        "get_flashed_messages": lambda with_categories=False: (
            pop_flashes(request) if with_categories else [m for _, m in pop_flashes(request)]
        ),
    }
    if ctx:
        base_ctx.update(ctx)
    return templates.TemplateResponse(request, name, base_ctx)


def redirect(url: str) -> RedirectResponse:
    """Return a 303 redirect, the POST/Redirect/GET pattern."""
    return RedirectResponse(url=url, status_code=303)
