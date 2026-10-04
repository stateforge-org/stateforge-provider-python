"""Define public errors raised by private Provider runtime machinery."""


class ProviderServerError(RuntimeError):
    """Report failure to start or publish a Provider SFP server."""
