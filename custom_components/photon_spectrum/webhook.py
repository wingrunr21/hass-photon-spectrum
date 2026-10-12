"""Verify Photon webhook deliveries before publishing them to Home Assistant."""

import hashlib
import hmac
import time
from http import HTTPStatus

from aiohttp import web
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util.json import json_loads

DOMAIN = "photon_spectrum"
EVENT_WEBHOOK = f"{DOMAIN}_webhook"
MAX_BODY_BYTES = 1024 * 1024


def webhook_id(entry: ConfigEntry) -> str:
    """Return the stable, project-specific webhook identifier."""
    return f"{DOMAIN}_{entry.entry_id}"


def webhook_path(entry: ConfigEntry) -> str:
    """Return the path to append to the user's public Home Assistant URL."""
    return webhook.async_generate_path(webhook_id(entry))


async def async_handle_webhook(
    hass: HomeAssistant, _webhook_id: str, request: web.Request, *, entry: ConfigEntry
) -> web.Response:
    """Reject unverified deliveries without exposing them to automations."""
    timestamp = request.headers.get("X-Spectrum-Timestamp", "")
    signature = request.headers.get("X-Spectrum-Signature", "")
    if not timestamp.isascii() or not timestamp.isdigit() or len(timestamp) > 20:
        return web.Response(status=HTTPStatus.UNAUTHORIZED)
    if abs(int(time.time()) - int(timestamp)) > 300:
        return web.Response(status=HTTPStatus.UNAUTHORIZED)
    if (
        len(signature) != 67
        or not signature.isascii()
        or not signature.startswith("v0=")
    ):
        return web.Response(status=HTTPStatus.UNAUTHORIZED)
    signing_secret = entry.options.get("webhook_signing_secret")
    if not signing_secret:
        return web.Response(status=HTTPStatus.UNAUTHORIZED)

    stream = request.content
    body = bytearray()
    while chunk := await stream.read(MAX_BODY_BYTES + 1 - len(body)):
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            return web.Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
    raw_body = bytes(body)
    if abs(int(time.time()) - int(timestamp)) > 300:
        return web.Response(status=HTTPStatus.UNAUTHORIZED)
    secret = signing_secret.encode("utf-8")
    signed = b"v0:" + timestamp.encode("ascii") + b":" + raw_body
    expected = "v0=" + hmac.new(secret, signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return web.Response(status=HTTPStatus.UNAUTHORIZED)

    try:
        payload = json_loads(raw_body)
    except ValueError:
        return web.Response(status=HTTPStatus.BAD_REQUEST)
    if not isinstance(payload, dict):
        return web.Response(status=HTTPStatus.BAD_REQUEST)
    hass.bus.async_fire(
        EVENT_WEBHOOK, {"project_id": entry.data["project_id"], "payload": payload}
    )
    return web.Response(status=HTTPStatus.OK)
