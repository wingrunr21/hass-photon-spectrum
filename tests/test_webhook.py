"""Only signed Photon requests become Home Assistant events."""

import asyncio
import hashlib
import hmac
import logging
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import webhook
from homeassistant.components.notify import DATA_COMPONENT, NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.util.aiohttp import MockRequest

from custom_components.photon_spectrum import async_setup_entry, async_unload_entry
from custom_components.photon_spectrum.notify import (
    PhotonNotifyEntity,
)
from custom_components.photon_spectrum.webhook import (
    EVENT_WEBHOOK,
    MAX_BODY_BYTES,
    webhook_id,
)
from custom_components.photon_spectrum.webhook import (
    async_handle_webhook as verify_webhook,
)


def test_project_webhook_verification(tmp_path):
    async def check():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.data[DATA_COMPONENT] = EntityComponent[NotifyEntity](
            logging.getLogger(__name__), "notify", hass
        )
        entry = MagicMock()
        entry.entry_id = "entry-one"
        entry.data = {
            "project_id": "project-one",
            "project_secret": "project-secret",
            "recipients": ["+15551234567"],
        }
        secret = "a" * 64
        entry.options = {"webhook_signing_secret": secret}
        client = SimpleNamespace(close=AsyncMock())
        with patch(
            "custom_components.photon_spectrum.SharedLineClient", return_value=client
        ):
            await async_setup_entry(hass, entry)
        assert webhook_id(entry) in hass.data[webhook.DOMAIN]
        assert hass.data[webhook.DOMAIN][webhook_id(entry)][
            "allowed_methods"
        ] == frozenset({"POST"})
        assert hass.data[webhook.DOMAIN][webhook_id(entry)]["local_only"] is False
        assert hass.config_entries.async_forward_entry_setups.await_args.args[1] == [
            "notify"
        ]
        entity = PhotonNotifyEntity(entry)
        assert entity.extra_state_attributes is None

        events = []
        hass.bus.async_listen(EVENT_WEBHOOK, lambda event: events.append(event.data))
        now = 1_700_000_000
        body = b'{ "event": "messages", "message": {"id":"one"} }'

        def request(
            secret=secret,
            body=body,
            timestamp=None,
            signature=None,
            headers=True,
            signed_body=None,
        ):
            timestamp = str(now if timestamp is None else timestamp)
            signed = (
                b"v0:"
                + timestamp.encode()
                + b":"
                + (body if signed_body is None else signed_body)
            )
            digest = (
                "v0=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
            )
            return MockRequest(
                content=body,
                mock_source="test",
                method="POST",
                headers={
                    "X-Spectrum-Timestamp": timestamp,
                    "X-Spectrum-Signature": signature or digest,
                }
                if headers
                else {},
            )

        with patch(
            "custom_components.photon_spectrum.webhook.time.time", return_value=now
        ):
            path = webhook_id(entry)
            response = await webhook.async_handle_webhook(hass, path, request())
            assert response.status == HTTPStatus.OK
            await hass.async_block_till_done()
            assert events == [
                {
                    "project_id": "project-one",
                    "payload": {"event": "messages", "message": {"id": "one"}},
                }
            ]
            other = MagicMock()
            other.entry_id = "entry-two"
            other.data = {**entry.data, "project_id": "project-two"}
            other.options = {"webhook_signing_secret": "b" * 64}
            with patch(
                "custom_components.photon_spectrum.SharedLineClient",
                return_value=client,
            ):
                await async_setup_entry(hass, other)
            assert (
                await webhook.async_handle_webhook(hass, webhook_id(other), request())
            ).status == HTTPStatus.UNAUTHORIZED
            assert (
                await webhook.async_handle_webhook(
                    hass, webhook_id(other), request(secret="b" * 64)
                )
            ).status == HTTPStatus.OK
            await hass.async_block_till_done()
            assert events[-1]["project_id"] == "project-two"

            for invalid in (
                request(body=body + b" ", signed_body=body),
                request(secret="b" * 64),
                request(timestamp=now - 301),
                request(timestamp=now + 301),
                request(timestamp="not-a-timestamp"),
                request(signature="v0=" + "0" * 64),
                request(signature="v0=" + "é" * 64),
                request(headers=False),
            ):
                assert (
                    await webhook.async_handle_webhook(hass, path, invalid)
                ).status == HTTPStatus.UNAUTHORIZED
            assert (
                await webhook.async_handle_webhook(
                    hass, path, request(body=b"not JSON")
                )
            ).status == HTTPStatus.BAD_REQUEST
            assert (
                await webhook.async_handle_webhook(hass, path, request(body=b"\xff"))
            ).status == HTTPStatus.BAD_REQUEST
            assert (
                await webhook.async_handle_webhook(
                    hass, path, request(body=b"x" * (MAX_BODY_BYTES + 1))
                )
            ).status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
            await hass.async_block_till_done()
            assert len(events) == 2

        entry.options = {}
        with patch(
            "custom_components.photon_spectrum.webhook.time.time", return_value=now
        ):
            assert (
                await webhook.async_handle_webhook(hass, webhook_id(entry), request())
            ).status == HTTPStatus.UNAUTHORIZED
        assert await async_unload_entry(hass, entry)
        assert webhook_id(entry) not in hass.data[webhook.DOMAIN]
        assert webhook_id(other) in hass.data[webhook.DOMAIN]
        assert await async_unload_entry(hass, other)
        assert webhook_id(other) not in hass.data[webhook.DOMAIN]
        assert entry.options == {}
        with patch(
            "custom_components.photon_spectrum.SharedLineClient", return_value=client
        ):
            await async_setup_entry(hass, entry)
        assert webhook_id(entry) not in hass.data[webhook.DOMAIN]
        assert (
            PhotonNotifyEntity(entry).extra_state_attributes
            == entity.extra_state_attributes
        )
        assert await async_unload_entry(hass, entry)

    asyncio.run(check())


def test_existing_webhook_is_not_replaced(tmp_path):
    async def check():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.data[DATA_COMPONENT] = EntityComponent[NotifyEntity](
            logging.getLogger(__name__), "notify", hass
        )
        entry = MagicMock()
        entry.entry_id = "same-id"
        entry.data = {
            "project_id": "project-one",
            "project_secret": "project-secret",
            "recipients": ["+15551234567"],
        }
        entry.options = {}
        client = SimpleNamespace(close=AsyncMock())
        with patch(
            "custom_components.photon_spectrum.SharedLineClient", return_value=client
        ):
            await async_setup_entry(hass, entry)

        async def stock_handler(hass, webhook_id, request):
            return None

        webhook.async_register(
            hass, "other", "Stock webhook", webhook_id(entry), stock_handler
        )
        entry.options = {"webhook_signing_secret": "a" * 64}
        assert await async_unload_entry(hass, entry)
        assert hass.data[webhook.DOMAIN][webhook_id(entry)]["domain"] == "other"
        with (
            patch(
                "custom_components.photon_spectrum.SharedLineClient",
                return_value=client,
            ),
            pytest.raises(ValueError, match="already defined"),
        ):
            await async_setup_entry(hass, entry)
        assert client.close.await_count == 2
        assert hass.data[webhook.DOMAIN][webhook_id(entry)]["domain"] == "other"

    asyncio.run(check())


def test_fragmented_body_is_verified_in_full(tmp_path):
    async def check():
        hass = HomeAssistant(str(tmp_path))
        entry = MagicMock()
        entry.data = {"project_id": "project-one"}
        entry.options = {"webhook_signing_secret": "a" * 64}
        now = 1_700_000_000
        body = b'{"event":"messages"}'
        signature = (
            "v0="
            + hmac.new(
                b"a" * 64, b"v0:" + str(now).encode() + b":" + body, hashlib.sha256
            ).hexdigest()
        )
        events = []
        hass.bus.async_listen(EVENT_WEBHOOK, lambda event: events.append(event.data))

        def request(chunks):
            incoming = MagicMock()
            incoming.headers = {
                "X-Spectrum-Timestamp": str(now),
                "X-Spectrum-Signature": signature,
            }
            incoming.content.read = AsyncMock(side_effect=[*chunks, b""])
            return incoming

        with patch(
            "custom_components.photon_spectrum.webhook.time.time", return_value=now
        ):
            response = await verify_webhook(
                hass, "id", request([body[:5], body[5:]]), entry=entry
            )
            assert response.status == HTTPStatus.OK
            response = await verify_webhook(
                hass, "id", request([body, b"unsigned suffix"]), entry=entry
            )
            assert response.status == HTTPStatus.UNAUTHORIZED
        with patch(
            "custom_components.photon_spectrum.webhook.time.time",
            side_effect=[now, now + 3600],
        ):
            response = await verify_webhook(hass, "id", request([body]), entry=entry)
            assert response.status == HTTPStatus.UNAUTHORIZED
        await hass.async_block_till_done()
        assert len(events) == 1

    asyncio.run(check())
