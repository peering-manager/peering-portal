from __future__ import annotations

from typing import ClassVar

__all__ = (
    "ChoiceSet",
    "PeeringRequestStatus",
    "PeeringRequestType",
    "RequestedSessionStatus",
    "status_colour",
)


class ChoiceSetMeta(type):
    """
    Metaclass for `ChoiceSet`.
    """

    def __new__(mcs, name, bases, attrs):
        # Split the choice tuples into value/label pairs and a value/colour map
        choices = attrs.get("CHOICES", ())
        attrs["_choices"] = tuple((c[0], c[1]) for c in choices)
        attrs["colours"] = {c[0]: c[2] for c in choices if len(c) == 3}  # noqa: PLR2004
        return super().__new__(mcs, name, bases, attrs)

    def __iter__(cls):
        return iter(getattr(cls, "_choices", ()))


class ChoiceSet(metaclass=ChoiceSetMeta):
    """
    Holds an iterable of choice tuples, each one a value, a label and an optional Bootstrap colour.
    """

    CHOICES = ()

    _choices: ClassVar[tuple[tuple[str, str], ...]]
    colours: ClassVar[dict[str, str]]

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(c[0] for c in cls._choices)

    @classmethod
    def label(cls, value: str) -> str:
        """Return the human-readable label of `value`, falling back to `value` itself."""
        return dict(cls._choices).get(value, value)


class PeeringRequestType(ChoiceSet):
    PUBLIC_PEERING = "public"
    PRIVATE_PEERING = "private"

    CHOICES = ((PUBLIC_PEERING, "Public Peering"), (PRIVATE_PEERING, "Private Peering"))


class PeeringRequestStatus(ChoiceSet):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    CANCELLED = "cancelled"

    CHOICES = (
        (PENDING, "Pending", "info"),
        (ACCEPTED, "Accepted", "success"),
        (REFUSED, "Refused", "danger"),
        (CANCELLED, "Cancelled", "warning"),
    )


class RequestedSessionStatus(ChoiceSet):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    CHOICES = (
        (PENDING, "Pending", "info"),
        (ACCEPTED, "Accepted", "success"),
        (REJECTED, "Rejected", "danger"),
        (CANCELLED, "Cancelled", "warning"),
    )


def status_colour(status: str) -> str:
    """
    Return the Bootstrap colour of a peering request or a requested session status.

    A request is refused where a session is rejected; the statuses the two share carry the same
    colour, so one lookup over both sets stays unambiguous.
    """
    return PeeringRequestStatus.colours.get(status) or RequestedSessionStatus.colours.get(status, "secondary")
