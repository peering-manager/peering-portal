from __future__ import annotations

from fastapi import APIRouter, Form, Request

from api import api_request
from functions import api_error_message, parse_tracking_id
from templating import flash, redirect, render

router = APIRouter(prefix="/requests")


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

    resp = await api_request("GET", f"sessions/{tracking_id}")
    if not resp.is_success:
        if resp.status_code == 404:
            flash(request, "Request not found. The tracking ID may be invalid.")
            request.session["unknown_request_id"] = tracking_id
        else:
            flash(request, api_error_message(resp, "Failed to fetch request status."))
        return redirect("/requests")

    return render(request, "request_detail.html", {"data": resp.json()})


@router.post("/{request_id}/cancel")
async def request_cancel(request: Request, request_id: str):
    tracking_id = parse_tracking_id(request_id)
    if tracking_id is None:
        flash(request, "This does not look like a valid tracking ID.")
        return redirect("/requests")

    resp = await api_request("DELETE", f"sessions/{tracking_id}")
    if resp.status_code == 204:
        flash(request, "Request cancelled.", "success")
    elif resp.status_code == 409:
        flash(request, api_error_message(resp, "This request has already been processed and cannot be cancelled."))
    elif resp.status_code == 404:
        # The detail page would 404 again and stack a second flash, go back to the index instead
        flash(request, "Request not found.")
        return redirect("/requests")
    else:
        flash(request, api_error_message(resp, "Failed to cancel request."))
    return redirect(f"/requests/{tracking_id}")
