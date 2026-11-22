"""Request gate: size limit, then signature, before anything is parsed or stored."""

import structlog
from fastapi import Request

from app.core.errors import PayloadTooLarge, Unauthorized
from app.core.security import any_signature_is_valid

log = structlog.get_logger()


async def verified_body(request: Request) -> bytes:
    """The raw bytes of a correctly signed request. Raises before the handler body runs."""
    settings = request.app.state.settings
    metrics = request.app.state.metrics

    provided = request.headers.get("x-signature")
    if not provided:
        metrics.webhook("invalid_signature")
        log.warning("webhook_rejected", reason="missing_signature")
        raise Unauthorized("Missing X-Signature header")

    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > settings.max_body_bytes:
        metrics.webhook("payload_too_large")
        raise PayloadTooLarge("Body too large")

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > settings.max_body_bytes:
            metrics.webhook("payload_too_large")
            raise PayloadTooLarge("Body too large")
        chunks.append(chunk)
    body = b"".join(chunks)

    if not any_signature_is_valid(settings.webhook_secrets, body, provided):
        metrics.webhook("invalid_signature")
        log.warning("webhook_rejected", reason="invalid_signature")
        raise Unauthorized("Invalid signature")
    return body
