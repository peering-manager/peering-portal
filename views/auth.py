from __future__ import annotations

from fastapi import APIRouter, Query, Request
from markupsafe import Markup

from config import OAUTH_ENABLED
from exceptions import OAuthError
from functions import safe_path
from oauth import authorisation_url, current_user, fetch_profile, redirect_uri, sign_out, store_user, take_pending_login
from templating import flash, redirect

router = APIRouter()

NO_NETWORK_MESSAGE = Markup(
    "Your PeeringDB account is not affiliated with any network the portal can accept a request for. "
    "Ask an administrator of your organisation to affiliate you on "
    '<a href="https://www.peeringdb.com" target="_blank" rel="noopener">PeeringDB</a>, then sign in again.'
)


@router.get("/login")
async def login(request: Request, next_path: str = Query("/", alias="next")):
    if not OAUTH_ENABLED:
        return redirect("/")

    destination = safe_path(next_path)
    if current_user(request):
        return redirect(destination)

    return redirect(authorisation_url(request, callback=redirect_uri(request), next_path=destination))


@router.get("/auth/callback", name="oauth_callback")
async def oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not OAUTH_ENABLED:
        return redirect("/")

    # Taken first so a denied sign-in clears the attempt too, and cannot be replayed
    pending = take_pending_login(request, state)
    if error:
        raise OAuthError(
            "You did not allow the portal to read your PeeringDB profile."
            if error == "access_denied"
            else "PeeringDB refused the sign-in. Please try again."
        )
    if not code:
        raise OAuthError("PeeringDB sent no authorisation code. Please try again.")

    profile = await fetch_profile(code=code, verifier=pending["verifier"], callback=pending["callback"])
    # A wizard started by whoever used this browser before must not survive a new sign-in
    request.session.pop("wizard", None)
    user = store_user(request, profile)

    if not user["networks"]:
        flash(request, NO_NETWORK_MESSAGE, "warning")
        return redirect("/")

    flash(request, f"Signed in as {user['name']}.", "success")
    return redirect(pending.get("next") or "/")


@router.post("/logout")
async def logout(request: Request):
    sign_out(request)
    flash(request, "You are signed out.", "info")
    return redirect("/")
