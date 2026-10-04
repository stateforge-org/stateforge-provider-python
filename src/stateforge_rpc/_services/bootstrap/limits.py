"""Define serialized-message limits for Provider bootstrap calls."""

from typing import Final

MAX_REQUEST_BYTES: Final = 64 * 1024
MAX_RESPONSE_BYTES: Final = 8 * 1024
