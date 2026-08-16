from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, urlparse

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from api import lifespan
from config import HOST, OAUTH_ENABLED, PORT, RELOAD, SECRET_KEY, SESSION_COOKIE_SECURE
from exceptions import NotAuthenticatedError, OAuthError, PeeringManagerError
from templating import flash, redirect
from views import auth_router, requests_router, wizard_router

if TYPE_CHECKING:
    from fastapi import Request

BASE_DIR = Path(__file__).parent
SESSION_MAX_AGE = 30 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("peering.portal")

if not OAUTH_ENABLED:
    logger.warning(
        "PeeringDB OAuth is off: any visitor can file a request for any ASN. Set PDB_CLIENT_ID and "
        "PDB_CLIENT_SECRET to make the portal check that the requester owns the network."
    )

app = FastAPI(title="Peering Portal", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_MAX_AGE, same_site="lax", https_only=SESSION_COOKIE_SECURE
)


@app.exception_handler(PeeringManagerError)
async def handle_peering_manager_error(request: Request, _: PeeringManagerError):
    flash(request, "Could not reach Peering Manager. Please try again in a moment.")
    # Referer path only, so the redirect cannot leave this app
    return redirect(urlparse(request.headers.get("referer", "")).path or "/")


@app.exception_handler(NotAuthenticatedError)
async def handle_not_authenticated(request: Request, _: NotAuthenticatedError):
    flash(request, "Please sign in with PeeringDB to continue.", "info")
    target = request.url.path if request.method == "GET" else "/"
    return redirect(f"/login?next={quote(target, safe='/')}")


@app.exception_handler(OAuthError)
async def handle_oauth_error(request: Request, exc: OAuthError):
    flash(request, str(exc))
    return redirect("/")


app.include_router(auth_router)
app.include_router(wizard_router)
app.include_router(requests_router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host=HOST, port=PORT, reload=RELOAD)
