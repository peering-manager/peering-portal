from __future__ import annotations

from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from markupsafe import Markup

from api import api_request
from constants import ASN_MAX, ASN_MIN
from enums import PeeringRequestType
from functions import api_error_message, conflicting_ips, parse_asn
from oauth import asn_allowed, current_user, require_user
from sessions import deduplicate_sessions, parse_private_sessions, parse_public_sessions
from templating import flash, redirect, render

router = APIRouter()
signed_in = APIRouter(dependencies=[Depends(require_user)])


def _wizard(request: Request) -> dict[str, Any] | None:
    """Return the wizard in progress, re-checking its ASN: nobody inherits the previous visitor's."""
    wizard = request.session.get("wizard")
    if not wizard:
        return None
    if not asn_allowed(request, wizard.get("asn")):
        request.session.pop("wizard", None)
        return None
    return wizard


async def _fetch_locations(request: Request, asn: int, peer_type: str) -> list[dict[str, Any]] | None:
    """Return the locations shared with `asn`, or `None` when the API call failed."""
    resp = await api_request("GET", "locations", params={"asn": asn, "location_type": peer_type})
    if not resp.is_success:
        flash(request, api_error_message(resp, "Failed to fetch peering locations."))
        return None
    return resp.json().get("locations", [])


@router.get("/")
async def welcome(request: Request):
    return render(request, "welcome.html", {"wizard": _wizard(request) or {}})


@signed_in.post("/lookup")
async def lookup(
    request: Request,
    asn: str = Form(...),
    email: str = Form(""),
    peer_type: str = Form(PeeringRequestType.PUBLIC_PEERING),
):
    if peer_type not in PeeringRequestType.values():
        flash(request, "Invalid peering type.")
        return redirect("/")

    # Parsed by hand instead of `Form(int)` so a bad value flashes instead of returning raw JSON
    number = parse_asn(asn)
    if number is None:
        flash(request, f"{asn!r} is not a valid AS number, it must be between {ASN_MIN} and {ASN_MAX}.")
        return redirect("/")

    # The form only offers their own networks, so a rejection here means a tampered submission
    if not asn_allowed(request, number):
        flash(request, f"Your PeeringDB account is not affiliated with AS{number}.")
        return redirect("/")

    resp = await api_request("GET", f"network/{number}")
    if not resp.is_success:
        if resp.status_code == HTTPStatus.NOT_FOUND:
            flash(
                request,
                Markup(
                    "ASN {} was not found in the local PeeringDB cache. "
                    "Make sure your network is registered on "
                    '<a href="https://www.peeringdb.com" target="_blank" rel="noopener">PeeringDB</a>.'
                ).format(number),
            )
        else:
            flash(request, api_error_message(resp, "Failed to look up network."))
        return redirect("/")

    request.session["wizard"] = {
        "asn": number,
        "name": resp.json().get("name", ""),
        # The PeeringDB address is the one the operator can trust, so it stands in for a blank field
        "email": email.strip() or (current_user(request) or {}).get("email", ""),
        "peer_type": peer_type,
    }
    return redirect("/discover")


@signed_in.get("/discover")
async def discover(request: Request):
    wizard = _wizard(request)
    if not wizard:
        return redirect("/")

    asn = wizard["asn"]
    peer_type = wizard["peer_type"]

    net_resp = await api_request("GET", f"network/{asn}")
    network = net_resp.json() if net_resp.is_success else {}
    locations = await _fetch_locations(request, asn, peer_type)

    return render(request, "discover.html", {"wizard": wizard, "network": network, "locations": locations})


@signed_in.post("/discover")
async def discover_submit(request: Request):
    wizard = _wizard(request)
    if not wizard:
        return redirect("/")

    form = await request.form()
    selected = [s for s in form.getlist("location") if s]
    if not selected:
        flash(request, "Please select at least one location.")
        return redirect("/discover")

    wizard["selected_locations"] = selected
    request.session["wizard"] = wizard
    return redirect("/sessions")


@signed_in.get("/sessions")
async def sessions(request: Request):
    wizard = _wizard(request)
    if not wizard or not wizard.get("selected_locations"):
        return redirect("/")

    locations = await _fetch_locations(request, wizard["asn"], wizard["peer_type"])
    if locations is None:
        return redirect("/discover")
    selected_ids = set(wizard["selected_locations"])
    selected_locations = [loc for loc in locations if loc["location"] in selected_ids]

    return render(request, "sessions.html", {"wizard": wizard, "locations": selected_locations})


@signed_in.post("/sessions")
async def sessions_submit(request: Request):
    wizard = _wizard(request)
    if not wizard:
        return redirect("/")

    form = await request.form()

    locations = await _fetch_locations(request, wizard["asn"], wizard["peer_type"])
    if locations is None:
        return redirect("/sessions")
    location_names = {loc["location"]: loc["name"] for loc in locations}

    if wizard["peer_type"] == PeeringRequestType.PUBLIC_PEERING:
        chosen, error = parse_public_sessions(form=form, location_names=location_names)
    else:
        chosen, error = parse_private_sessions(
            form=form, locations=wizard["selected_locations"], location_names=location_names
        )
    if error:
        flash(request, error)
        return redirect("/sessions")

    chosen = deduplicate_sessions(chosen)
    if not chosen:
        flash(request, "Please select at least one session.")
        return redirect("/sessions")

    wizard["chosen_sessions"] = chosen
    request.session["wizard"] = wizard
    return redirect("/review")


@signed_in.get("/review")
async def review(request: Request):
    wizard = _wizard(request)
    if not wizard or not wizard.get("chosen_sessions"):
        return redirect("/")
    return render(request, "review.html", {"wizard": wizard})


@signed_in.post("/submit")
async def submit(request: Request):
    wizard = _wizard(request)
    if not wizard or not wizard.get("chosen_sessions"):
        return redirect("/")

    payload = {
        "local_asn": wizard["asn"],
        "peer_type": wizard["peer_type"],
        "email": wizard.get("email", ""),
        "sessions": [
            {
                "local_ip": s["local_ip"],
                "location": s["location"],
                "peer_ip": s.get("peer_ip", ""),
                "session_secret": s.get("session_secret", ""),
            }
            for s in wizard["chosen_sessions"]
        ],
    }

    resp = await api_request("POST", "sessions", json=payload)
    if not resp.is_success:
        default = (
            "A conflicting peering request already exists."
            if resp.status_code == HTTPStatus.CONFLICT
            else "The peering request could not be submitted."
        )
        message = api_error_message(resp, default)
        conflicting = conflicting_ips(resp)
        if conflicting:
            message = f"{message} Conflicting IPs: {', '.join(conflicting)}."
        flash(request, message)
        return redirect("/review")

    request_id = resp.json()["request_id"]
    request.session.pop("wizard", None)
    return redirect(f"/success/{quote(str(request_id), safe='')}")


@signed_in.get("/success/{request_id}")
async def success(request: Request, request_id: str):
    return render(request, "success.html", {"request_id": request_id})


router.include_router(signed_in)
