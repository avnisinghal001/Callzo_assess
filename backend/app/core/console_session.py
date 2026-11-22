"""Password-less console session: a signed, expiring, stateless token kept in an HttpOnly cookie.

Issued automatically when CONSOLE_OPEN_ACCESS is on. That makes "can reach the console" mean "may
operate it", so it belongs on localhost or behind an identity-aware proxy, never on a public
address. Off by default; docker-compose turns it on and binds the port to 127.0.0.1.

Stateless, so any API server accepts a session another one issued.
"""

import hashlib
import hmac
import time

COOKIE = "metering_console"
LIFETIME_SECONDS = 12 * 3600
# Browsers cannot send a custom header cross-site without a CORS preflight, which we never allow:
# together with SameSite=Strict this is the CSRF protection.
CSRF_HEADER = "x-console"


def _signature(secret: str, expires: str) -> str:
    key = hashlib.sha256(b"console-session:" + secret.encode()).digest()
    return hmac.new(key, expires.encode(), hashlib.sha256).hexdigest()


def issue(secret: str, now: float | None = None) -> str:
    expires = str(int((now or time.time()) + LIFETIME_SECONDS))
    return f"{expires}.{_signature(secret, expires)}"


def is_valid(secret: str, token: str | None, now: float | None = None) -> bool:
    expires, _, signature = (token or "").partition(".")
    if not expires.isascii() or not expires.isdigit():
        return False
    genuine = hmac.compare_digest(_signature(secret, expires).encode(), signature.encode())
    return genuine and int(expires) > (now or time.time())
