"""Instance-bound authenticated cursors. No state file or database writes."""

import base64
import hashlib
import hmac

from .models import canonical
from .read_models import ReadFailure
from .verification import parse


def encode_cursor(key: bytes, document: dict) -> str:
    raw = canonical(document).encode()
    signature = hmac.digest(key, raw, hashlib.sha256)
    return base64.urlsafe_b64encode(signature + raw).decode().rstrip("=")


def decode_cursor(key: bytes, token: str) -> dict:
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(raw).decode().rstrip("=") != token:
            raise ValueError
        signature, body = raw[:32], raw[32:]
        if not hmac.compare_digest(signature, hmac.digest(key, body, hashlib.sha256)):
            raise ValueError
        document = parse(body)
        if not isinstance(document, dict):
            raise ValueError
        return document
    except (ValueError, TypeError):
        raise ReadFailure("INVALID_CURSOR", "Cursor authentication failed") from None
