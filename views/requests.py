from __future__ import annotations

from http import HTTPStatus
from typing import Any

from fastapi import APIRouter, Depends, Form, Request

from api import api_request
from functions import api_error_message, parse_tracking_id
from oauth import asn_allowed, require_user
from templating import flash, redirect, render

router = APIRouter(prefix="/requests", dependencies=[Depends(require_user)])

NOT_YOURS = "This peering request belongs to another network."


async def _fetch_request(request: Request, tracking_id: str) -> dict[str, Any] | None:
    """
    Return the peering request `tracking_id` points at, or `None` once the visitor got a flash.

    A tracking ID is the only key to a request, so it is checked against the networks of the
    signed-in user: knowing an ID is not a right to read or cancel the request it names.
    """
    resp = await api_request("GET", f"sessions/{tracking_id}")
    if not resp.is_success:
        if resp.status_code == HTTPStatus.NOT_FOUND:
            flash(request, "Request not found. The tracking ID may be invalid.")
            request.session["unknown_request_id"] = tracking_id
        else:
            flash(request, api_error_message(resp, "Failed to fetch request status."))
        return None

    data = resp.json()
    if not asn_allowed(request, data.get("local_asn")):
        flash(request, NOT_YOURS)
        return None
    return data


@router.get("")
async def requests_index(request: Request):
    unknown = request.session.pop("unknown_request_id", "")
    return render(request, "requests.html", {"unknown_request_id": unknown})


@router.post("/lookup")
async def requests_lookup(request: Request, request_id: str = Form(...)):
    tracking_id = parse_tracking_id(request_id)
    if tracking_id is None:
        flash(request, "This does not look like a valid tracking ID.")
        return redirect("/requests")
    return redirect(f"/requests/{tracking_id}")


@router.get("/{request_id}")
async def request_detail(request: Request, request_id: str):
    tracking_id = parse_tracking_id(request_id)
    if tracking_id is None:
        flash(request, "This does not look like a valid tracking ID.")
        return redirect("/requests")

    data = await _fetch_request(request, tracking_id)
    if data is None:
        return redirect("/requests")

    return render(request, "request_detail.html", {"data": data})


@router.post("/{request_id}/cancel")
async def request_cancel(request: Request, request_id: str):
    tracking_id = parse_tracking_id(request_id)
    if tracking_id is None:
        flash(request, "This does not look like a valid tracking ID.")
        return redirect("/requests")

    # Read the request first: the API knows nothing of the visitor, so ownership is settled here
    if await _fetch_request(request, tracking_id) is None:
        return redirect("/requests")

    resp = await api_request("DELETE", f"sessions/{tracking_id}")
    if resp.status_code == HTTPStatus.NO_CONTENT:
        flash(request, "Request cancelled.", "success")
    elif resp.status_code == HTTPStatus.CONFLICT:
        flash(request, api_error_message(resp, "This request has already been processed and cannot be cancelled."))
    elif resp.status_code == HTTPStatus.NOT_FOUND:
        # The detail page would 404 again and stack a second flash, go back to the index instead
        flash(request, "Request not found.")
        return redirect("/requests")
    else:
        flash(request, api_error_message(resp, "Failed to cancel request."))
    return redirect(f"/requests/{tracking_id}")
