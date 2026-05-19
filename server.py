from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from config import HOST, PM_TOKEN, PM_URL, PORT, RELOAD, SECRET_KEY
from helpers import affiliated_as, api_error_message, flash, redirect, render

BASE_DIR = Path(__file__).parent

# Module-level state populated at startup
client: httpx.AsyncClient


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Startup: open the API client and fetch the affiliated AS."""
    global client  # noqa: PLW0603
    client = httpx.AsyncClient(
        base_url=f"{PM_URL}/api/peering/portal/",
        headers={"Authorization": f"Token {PM_TOKEN}"},
        timeout=30.0,
    )

    resp = await client.get("affiliated")
    if not resp.is_success:
        await client.aclose()
        raise RuntimeError(
            "Failed to fetch the affiliated AS from Peering Manager. "
            "Make sure to use an API token that belongs to a user who has selected an affiliated AS in their preferences."
        )
    affiliated_as.update(resp.json())

    yield
    await client.aclose()


app = FastAPI(title="Peering Portal", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=30 * 60)


# Welcome


@app.get("/")
async def welcome(request: Request):
    return render(request, "welcome.html")


@app.post("/lookup")
async def lookup(
    request: Request,
    asn: int = Form(...),
    email: str = Form(""),
    peer_type: str = Form("public"),
):
    if peer_type not in ("public", "private"):
        flash(request, "Invalid peering type.")
        return redirect("/")

    resp = await client.get(f"network/{asn}")
    if not resp.is_success:
        if resp.status_code == 404:
            flash(
                request,
                f"ASN {asn} was not found in the local PeeringDB cache. "
                "Make sure your network is registered on "
                '<a href="https://www.peeringdb.com" target="_blank" rel="noopener">PeeringDB</a>.',
            )
        else:
            flash(request, api_error_message(resp, "Failed to look up network."))
        return redirect("/")

    request.session["wizard"] = {
        "asn": asn,
        "name": resp.json().get("name", ""),
        "email": email,
        "peer_type": peer_type,
    }
    return redirect("/discover")


# Shared locations (IXPs and facilities)


async def _fetch_locations(asn: int, peer_type: str) -> list[dict[str, Any]]:
    resp = await client.get(
        "locations", params={"asn": asn, "location_type": peer_type}
    )
    if not resp.is_success:
        return []
    return resp.json().get("locations", [])


@app.get("/discover")
async def discover(request: Request):
    wizard = request.session.get("wizard")
    if not wizard:
        return redirect("/")

    asn = wizard["asn"]
    peer_type = wizard["peer_type"]

    net_resp = await client.get(f"network/{asn}")
    network = net_resp.json() if net_resp.is_success else {}
    locations = await _fetch_locations(asn, peer_type)

    return render(
        request,
        "discover.html",
        {"wizard": wizard, "network": network, "locations": locations},
    )


@app.post("/discover")
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


# BGP sessions selection


@app.get("/sessions")
async def sessions(request: Request):
    wizard = request.session.get("wizard")
    if not wizard or not wizard.get("selected_locations"):
        return redirect("/")

    locations = await _fetch_locations(wizard["asn"], wizard["peer_type"])
    selected_ids = set(wizard["selected_locations"])
    selected_locations = [loc for loc in locations if loc["location"] in selected_ids]

    return render(
        request, "sessions.html", {"wizard": wizard, "locations": selected_locations}
    )


@app.post("/sessions")
async def sessions_submit(request: Request):
    wizard = request.session.get("wizard")
    if not wizard:
        return redirect("/")

    form = await request.form()
    chosen: list[dict[str, Any]] = []

    # Map location id back to its name so the review page can show it.
    location_names = {
        loc["location"]: loc["name"]
        for loc in await _fetch_locations(wizard["asn"], wizard["peer_type"])
    }

    if wizard["peer_type"] == "public":
        # Values come as "<location>|<local_ip>|<peer_ip>".  peer_ip pins which
        # operator Connection at the IX the session lands on.
        for value in form.getlist("session"):
            parts = value.split("|", 2)
            if len(parts) != 3 or not all(parts):
                continue
            location, local_ip, peer_ip = parts
            secret = (form.get(f"secret|{location}|{local_ip}|{peer_ip}") or "").strip()
            chosen.append(
                {
                    "location": location,
                    "location_name": location_names.get(location, location),
                    "local_ip": local_ip,
                    "peer_ip": peer_ip,
                    "session_secret": secret,
                }
            )
    else:
        # private: parallel lists of local_ip / peer_ip / secret per facility,
        # one row per index. peer_ip is mandatory because the operator IP on a
        # private interconnect cannot be guessed except for /31s and /127s.
        for location in wizard["selected_locations"]:
            local_ips = form.getlist(f"private_local_ip|{location}")
            peer_ips = form.getlist(f"private_peer_ip|{location}")
            secrets = form.getlist(f"private_secret|{location}")
            for idx, local_ip in enumerate(local_ips):
                local_ip = local_ip.strip()
                if not local_ip:
                    continue
                peer_ip = (peer_ips[idx] if idx < len(peer_ips) else "").strip()
                if not peer_ip:
                    flash(
                        request,
                        f"Peer IP is required for {local_ip} at {location_names.get(location, location)}.",
                    )
                    return redirect("/sessions")
                secret = (secrets[idx] if idx < len(secrets) else "").strip()
                chosen.append(
                    {
                        "location": location,
                        "location_name": location_names.get(location, location),
                        "local_ip": local_ip,
                        "peer_ip": peer_ip,
                        "session_secret": secret,
                    }
                )

    if not chosen:
        flash(request, "Please select at least one session.")
        return redirect("/sessions")

    wizard["chosen_sessions"] = chosen
    request.session["wizard"] = wizard
    return redirect("/review")


# Review and submit


@app.get("/review")
async def review(request: Request):
    wizard = request.session.get("wizard")
    if not wizard or not wizard.get("chosen_sessions"):
        return redirect("/")
    return render(request, "review.html", {"wizard": wizard})


@app.post("/submit")
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

    resp = await client.post("sessions", json=payload)
    if not resp.is_success:
        flash(
            request,
            api_error_message(
                resp,
                (
                    "The peering request could not be submitted."
                    if resp.status_code != 409
                    else "A conflicting peering request already exists."
                ),
            ),
        )
        return redirect("/review")

    request_id = resp.json()["request_id"]
    request.session.pop("wizard", None)
    return redirect(f"/success/{quote(request_id, safe='')}")


@app.get("/success/{request_id}")
async def success(request: Request, request_id: str):
    return render(request, "success.html", {"request_id": request_id})


# Request tracking (view/detail/cancel)


@app.get("/requests")
async def requests_index(request: Request):
    unknown = request.session.pop("unknown_request_id", "")
    return render(request, "requests.html", {"unknown_request_id": unknown})


@app.post("/requests/lookup")
async def requests_lookup(request: Request, request_id: str = Form(...)):
    request_id = request_id.strip()
    if not request_id:
        flash(request, "Please enter a tracking ID.")
        return redirect("/requests")
    return redirect(f"/requests/{quote(request_id, safe='')}")


@app.get("/requests/{request_id}")
async def request_detail(request: Request, request_id: str):
    resp = await client.get(f"sessions/{request_id}")
    if not resp.is_success:
        if resp.status_code == 404:
            flash(request, "Request not found. The tracking ID may be invalid.")
            request.session["unknown_request_id"] = request_id
        else:
            flash(request, api_error_message(resp, "Failed to fetch request status."))
        return redirect("/requests")

    return render(request, "request_detail.html", {"data": resp.json()})


@app.post("/requests/{request_id}/cancel")
async def request_cancel(request: Request, request_id: str):
    resp = await client.delete(f"sessions/{request_id}")
    if resp.status_code == 204:
        flash(request, "Request cancelled.", "success")
    elif resp.status_code == 409:
        flash(
            request,
            api_error_message(
                resp, "This request has already been processed and cannot be cancelled."
            ),
        )
    elif resp.status_code == 404:
        flash(request, "Request not found.")
    else:
        flash(request, api_error_message(resp, "Failed to cancel request."))
    return redirect(f"/requests/{quote(request_id, safe='')}")


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host=HOST, port=PORT, reload=RELOAD)
