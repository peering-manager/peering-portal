from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from markupsafe import Markup

from api import api_request
from constants import ASN_MAX, ASN_MIN
from enums import PeeringRequestType
from functions import api_error_message, conflicting_ips
from sessions import deduplicate_sessions, parse_private_sessions, parse_public_sessions
from templating import flash, redirect, render

router = APIRouter()


async def _fetch_locations(request: Request, asn: int, peer_type: str) -> list[dict[str, Any]] | None:
    """Return the locations shared with `asn`, or `None` when the API call failed."""
    resp = await api_request("GET", "locations", params={"asn": asn, "location_type": peer_type})
    if not resp.is_success:
        flash(request, api_error_message(resp, "Failed to fetch peering locations."))
        return None
    return resp.json().get("locations", [])


# Welcome
@router.get("/")
async def welcome(request: Request):
    return render(request, "welcome.html", {"wizard": request.session.get("wizard", {})})


@router.post("/lookup")
async def lookup(
    request: Request,
    asn: str = Form(...),
    email: str = Form(""),
    peer_type: str = Form(PeeringRequestType.PUBLIC_PEERING),
):
    if peer_type not in PeeringRequestType.values():
        flash(request, "Invalid peering type.")
        return redirect("/")

    # Parsed by hand instead of `Form(int)` so a bad value flashes instead of returning raw JSON;
    # a leading "AS" is tolerated as networks are often written down that way
    try:
        number = int(asn.strip().upper().removeprefix("AS"))
    except ValueError:
        flash(request, f"{asn!r} is not a valid AS number.")
        return redirect("/")

    if not ASN_MIN <= number <= ASN_MAX:
        flash(request, f"An AS number must be between {ASN_MIN} and {ASN_MAX}.")
        return redirect("/")

    resp = await api_request("GET", f"network/{number}")
    if not resp.is_success:
        if resp.status_code == 404:
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
        "email": email,
        "peer_type": peer_type,
    }
    return redirect("/discover")


# Shared locations, IXPs or facilities
@router.get("/discover")
async def discover(request: Request):
    wizard = request.session.get("wizard")
    if not wizard:
        return redirect("/")

    asn = wizard["asn"]
    peer_type = wizard["peer_type"]

    net_resp = await api_request("GET", f"network/{asn}")
    network = net_resp.json() if net_resp.is_success else {}
    locations = await _fetch_locations(request, asn, peer_type)

    return render(request, "discover.html", {"wizard": wizard, "network": network, "locations": locations})


@router.post("/discover")
async def discover_submit(request: Request):
    wizard = request.session.get("wizard")
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


# BGP session selection
@router.get("/sessions")
async def sessions(request: Request):
    wizard = request.session.get("wizard")
    if not wizard or not wizard.get("selected_locations"):
        return redirect("/")

    locations = await _fetch_locations(request, wizard["asn"], wizard["peer_type"])
    if locations is None:
        return redirect("/discover")
    selected_ids = set(wizard["selected_locations"])
    selected_locations = [loc for loc in locations if loc["location"] in selected_ids]

    return render(request, "sessions.html", {"wizard": wizard, "locations": selected_locations})


@router.post("/sessions")
async def sessions_submit(request: Request):
    wizard = request.session.get("wizard")
    if not wizard:
        return redirect("/")

    form = await request.form()

    # Map location id back to its name so the review page can show it
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


# Review and submit
@router.get("/review")
async def review(request: Request):
    wizard = request.session.get("wizard")
    if not wizard or not wizard.get("chosen_sessions"):
        return redirect("/")
    return render(request, "review.html", {"wizard": wizard})


@router.post("/submit")
async def submit(request: Request):
    wizard = request.session.get("wizard")
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
            if resp.status_code == 409
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


@router.get("/success/{request_id}")
async def success(request: Request, request_id: str):
    return render(request, "success.html", {"request_id": request_id})
