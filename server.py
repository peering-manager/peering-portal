from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from api import lifespan
from config import HOST, PORT, RELOAD, SECRET_KEY
from exceptions import PeeringManagerError
from templating import flash, redirect
from views import requests_router, wizard_router

if TYPE_CHECKING:
    from fastapi import Request

BASE_DIR = Path(__file__).parent
SESSION_MAX_AGE = 30 * 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Peering Portal", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=SESSION_MAX_AGE)


@app.exception_handler(PeeringManagerError)
async def handle_peering_manager_error(request: Request, _: PeeringManagerError):
    flash(request, "Could not reach Peering Manager. Please try again in a moment.")
    # Referer path only, so the redirect cannot leave this app
    return redirect(urlparse(request.headers.get("referer", "")).path or "/")


app.include_router(wizard_router)
app.include_router(requests_router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host=HOST, port=PORT, reload=RELOAD)
