__all__ = ("NotAuthenticatedError", "OAuthError", "PeeringManagerError")


class PeeringManagerError(Exception):
    """The Peering Manager API cannot be reached."""


class NotAuthenticatedError(Exception):
    """The visitor must sign in with PeeringDB."""


class OAuthError(Exception):
    """The PeeringDB sign-in failed."""
