"""Shared-line iMessage transport for Photon Spectrum."""

import asyncio
import time
from uuid import uuid4

import grpc
from aiohttp import BasicAuth, ClientError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .proto import message_pb2

TOKEN_URL = "https://spectrum.photon.codes/projects/{project_id}/imessage/tokens"
ADDRESS = "imessage.spectrum.photon.codes:443"
METHOD = "/photon.imessage.v1.MessageService/SendTextMessage"


class SharedLineClient:
    """Send text using a Photon shared iMessage line."""

    def __init__(
        self, hass: HomeAssistant, project_id: str, project_secret: str
    ) -> None:
        self._hass = hass
        self._project_id = project_id
        self._project_secret = project_secret
        self._token = ""
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._channel = grpc.aio.secure_channel(ADDRESS, grpc.ssl_channel_credentials())

    async def _get_token(self) -> str:
        async with self._lock:
            if time.monotonic() < self._expires_at:
                return self._token
            try:
                async with asyncio.timeout(15):
                    async with async_get_clientsession(self._hass).post(
                        TOKEN_URL.format(project_id=self._project_id),
                        auth=BasicAuth(self._project_id, self._project_secret),
                    ) as response:
                        response.raise_for_status()
                        payload = await response.json()
                data = payload["data"]
                if not payload["succeed"] or data["type"] != "shared":
                    raise HomeAssistantError(
                        "Photon project has no shared iMessage line"
                    )
                token = data["token"]
                lifetime = int(data["expiresIn"])
                if not token or lifetime <= 0:
                    raise ValueError("Invalid Photon token response")
            except (
                ClientError, TimeoutError, KeyError, TypeError, ValueError
            ) as err:
                raise HomeAssistantError(
                    "Could not obtain Photon iMessage token"
                ) from err
            self._token = token
            self._expires_at = time.monotonic() + lifetime * 0.8
            return token

    async def send(self, recipient: str, message: str) -> None:
        """Send a message and require an accepted message response."""
        token = await self._get_token()
        request = message_pb2.SendTextMessageRequest(
            chat_guid=f"any;-;{recipient}",
            text=message,
            client_message_id=str(uuid4()),
        )
        call = self._channel.unary_unary(
            METHOD,
            request_serializer=message_pb2.SendTextMessageRequest.SerializeToString,
            response_deserializer=message_pb2.MessageResponse.FromString,
        )
        try:
            response = await call(
                request,
                metadata=(
                    ("authorization", f"Bearer {token}"),
                    ("x-idempotency-key", request.client_message_id),
                ),
                timeout=20,
            )
        except grpc.aio.AioRpcError as err:
            detail = err.details()
            suffix = f": {detail}" if detail else ""
            raise HomeAssistantError(
                f"Photon iMessage send failed: {err.code().name}{suffix}"
            ) from err
        if not response.HasField("message") or not response.message.guid:
            raise HomeAssistantError("Photon returned no sent message")

    async def close(self) -> None:
        """Close the gRPC channel."""
        await self._channel.close()
