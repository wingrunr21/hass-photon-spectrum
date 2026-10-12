"""Shared-line token and send contract checks."""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest
import voluptuous as vol
from homeassistant.components.notify import DATA_COMPONENT, NotifyEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.helpers.service import async_get_cached_service_description
from voluptuous_serialize import convert

from custom_components.photon_spectrum import async_setup_entry, async_unload_entry
from custom_components.photon_spectrum.client import SharedLineClient
from custom_components.photon_spectrum.config_flow import (
    PhotonSpectrumConfigFlow,
    PhotonSpectrumOptionsFlow,
    parse_recipients,
)
from custom_components.photon_spectrum.notify import PhotonNotifyEntity
from custom_components.photon_spectrum.proto import message_pb2


def test_shared_line_send_and_token_refresh():
    async def check():
        response = MagicMock()
        response.json = AsyncMock(
            return_value={
                "succeed": True,
                "data": {"type": "shared", "token": "line-token", "expiresIn": 100},
            }
        )
        response.raise_for_status.return_value = None
        session = MagicMock()
        session.post.return_value.__aenter__ = AsyncMock(return_value=response)
        session.post.return_value.__aexit__ = AsyncMock(return_value=None)
        call = AsyncMock(
            return_value=message_pb2.MessageResponse(
                message=message_pb2.Message(guid="sent-message")
            )
        )
        channel = MagicMock()
        channel.unary_unary.return_value = call
        channel.close = AsyncMock()
        clock = [1000.0]
        with (
            patch(
                "custom_components.photon_spectrum.client.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.photon_spectrum.client.grpc.aio.secure_channel",
                return_value=channel,
            ),
            patch(
                "custom_components.photon_spectrum.client.time.monotonic",
                side_effect=lambda: clock[0],
            ),
        ):
            client = SharedLineClient(MagicMock(), "project", "secret")
            await client.send("+15551234567", "Smoke test")
            assert call.await_args is not None
            request = call.await_args.args[0]
            assert request.chat_guid == "any;-;+15551234567"
            assert request.text == "Smoke test"
            assert call.await_args.kwargs["metadata"][0] == (
                "authorization", "Bearer line-token"
            )
            assert call.await_args.kwargs["metadata"][1][1] == request.client_message_id
            await client.send("+15557654321", "Again")
            assert call.await_args.args[0].chat_guid == "any;-;+15557654321"
            assert session.post.call_count == 1
            clock[0] += 81
            await client.send("+15551234567", "Renewed")
            assert session.post.call_count == 2
            call.return_value = message_pb2.MessageResponse()
            with pytest.raises(HomeAssistantError, match="no sent message"):
                await client.send("+15551234567", "Failed")
            response.json.return_value["data"]["type"] = "dedicated"
            clock[0] += 81
            with pytest.raises(HomeAssistantError, match="no shared iMessage line"):
                await client.send("+15551234567", "Wrong plan")
            response.json.return_value["data"]["type"] = "shared"
            clock[0] += 81
            call.side_effect = grpc.aio.AioRpcError(
                grpc.StatusCode.PERMISSION_DENIED,
                grpc.aio.Metadata(),
                grpc.aio.Metadata(),
                "Target not allowed for this project",
            )
            with pytest.raises(
                HomeAssistantError, match="PERMISSION_DENIED: Target not allowed"
            ):
                await client.send("+15551234567", "Rejected")
            await client.close()

    asyncio.run(check())


def test_notify_title():
    async def check():
        client = SimpleNamespace(send=AsyncMock())
        entry = MagicMock()
        entry.entry_id = "one"
        entry.runtime_data = client
        entry.options = {}
        entry.data = {"recipients": ["+15551234567", "+15557654321"]}
        entity = PhotonNotifyEntity(entry)
        await entity.async_send_message("Door open", "Alert")
        assert [call.args for call in client.send.await_args_list] == [
            ("+15551234567", "Alert\nDoor open"),
            ("+15557654321", "Alert\nDoor open"),
        ]
        client.send.reset_mock()
        client.send.side_effect = [HomeAssistantError("failed"), None]
        with pytest.raises(HomeAssistantError, match="1 of 2 recipients: failed"):
            await entity.async_send_message("Door open")
        assert client.send.await_count == 2
        client.send.reset_mock(side_effect=True)
        entry.options = {"recipients": ["+15557654321"]}
        await PhotonNotifyEntity(entry).async_send_message("Door closed")
        client.send.assert_awaited_once_with("+15557654321", "Door closed")

    asyncio.run(check())


def test_config_form_serializes():
    async def check():
        result = await PhotonSpectrumConfigFlow().async_step_user()
        assert "data_schema" in result
        fields = convert(result["data_schema"])
        assert [field["name"] for field in fields if isinstance(field, dict)] == [
            "project_id", "project_secret", "recipients"
        ]

    asyncio.run(check())


def test_recipient_options():
    assert parse_recipients("+15551234567, +15557654321\n+15551234567") == [
        "+15551234567", "+15557654321"
    ]
    for value in ("", "not a phone", "+15551234567, not a phone"):
        with pytest.raises(ValueError):
            parse_recipients(value)

    async def check():
        flow = PhotonSpectrumOptionsFlow()
        flow.handler = "entry-id"
        flow.hass = MagicMock()
        flow.hass.config_entries.async_get_known_entry.return_value = MagicMock(
            options={}, data={"recipients": ["+15551234567"]}
        )
        flow.hass.config_entries.async_get_known_entry.return_value.entry_id = "project-one"
        result = await flow.async_step_init()
        assert "data_schema" in result
        assert result.get("description_placeholders") == {
            "webhook_path": "/api/webhook/photon_spectrum_project-one"
        }
        fields = convert(result["data_schema"], custom_serializer=cv.custom_serializer)
        assert isinstance(fields, list)
        assert next(
            field for field in fields if field["name"] == "webhook_signing_secret"
        )["selector"]["text"]["type"] == "password"
        result = await flow.async_step_init(
            {"recipients": "+15551234567, +15557654321"}
        )
        assert "data" in result
        assert result["data"] == {
            "recipients": ["+15551234567", "+15557654321"]
        }
        entry = flow.hass.config_entries.async_get_known_entry.return_value
        entry.options = result["data"]
        result = await flow.async_step_init(
            {"recipients": "+15551234567", "webhook_signing_secret": "a" * 64}
        )
        assert "data" in result
        assert result["data"]["webhook_signing_secret"] == "a" * 64
        entry.options = result["data"]
        result = await flow.async_step_init({"recipients": "+15551234567"})
        assert "data" in result
        assert result["data"]["webhook_signing_secret"] == "a" * 64
        result = await flow.async_step_init(
            {"recipients": "+15551234567", "webhook_signing_secret": "short"}
        )
        assert "errors" in result and result["errors"] is not None
        assert result["errors"]["webhook_signing_secret"] == "invalid_webhook_secret"
        result = await flow.async_step_init(
            {"recipients": "+15551234567", "disable_webhook": True}
        )
        assert "data" in result
        assert "webhook_signing_secret" not in result["data"]

    asyncio.run(check())


def test_project_entry_has_all_recipients():
    async def check():
        flow = PhotonSpectrumConfigFlow()
        flow.hass = MagicMock()
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        with patch(
            "custom_components.photon_spectrum.config_flow.SharedLineClient"
        ) as client_type:
            client_type.return_value._get_token = AsyncMock()
            client_type.return_value.close = AsyncMock()
            result = await flow.async_step_user(
                {
                    "project_id": "12345678-1234-1234-1234-123456789abc",
                    "project_secret": "secret",
                    "recipients": "+15551234567,+15557654321",
                }
            )
        flow.async_set_unique_id.assert_awaited_once_with(
            "12345678-1234-1234-1234-123456789abc"
        )
        assert "data" in result
        assert result["data"]["recipients"] == [
            "+15551234567", "+15557654321"
        ]

    asyncio.run(check())


def test_project_scoped_notify_action(tmp_path):
    async def check():
        hass = HomeAssistant(str(tmp_path))
        hass.config_entries = MagicMock()
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
        hass.data[DATA_COMPONENT] = EntityComponent[NotifyEntity](
            logging.getLogger(__name__), "notify", hass
        )
        clients = [
            SimpleNamespace(send=AsyncMock(), close=AsyncMock()) for _ in range(2)
        ]
        entries = []
        with patch(
            "custom_components.photon_spectrum.SharedLineClient",
            side_effect=clients,
        ):
            for index in (0, 1):
                entry = MagicMock()
                entry.entry_id = str(index)
                entry.data = {
                    "project_id": str(index),
                    "project_secret": "secret",
                    "recipients": [f"+1555123456{index}"],
                }
                entry.options = {}
                entries.append(entry)
                await async_setup_entry(hass, entry)
        assert hass.services.has_service("notify", "photon_spectrum")
        description = async_get_cached_service_description(
            hass, "notify", "photon_spectrum"
        )
        assert description is not None
        assert "target" in description["fields"]
        assert hass.data["photon_spectrum"] == {"0", "1"}
        entities = hass.data[DATA_COMPONENT]._entities
        for index, entry in enumerate(entries):
            entity = PhotonNotifyEntity(entry)
            entity.hass = hass
            entity.entity_id = f"notify.project_{index}"
            entity.async_write_ha_state = MagicMock()
            entities[entity.entity_id] = entity
        other = NotifyEntity()
        other.hass = hass
        other.entity_id = "notify.other"
        entities[other.entity_id] = other

        await hass.services.async_call(
            "notify", "photon_spectrum",
            {
                "entity_id": "notify.project_1",
                "message": "Door open",
                "title": "Alert",
                "target": ["+15557654321", "+15557654321"],
            },
            blocking=True,
        )
        clients[0].send.assert_not_awaited()
        clients[1].send.assert_awaited_once_with(
            "+15557654321", "Alert\nDoor open"
        )
        clients[1].send.reset_mock()
        await hass.services.async_call(
            "notify", "photon_spectrum",
            {"entity_id": "notify.project_1", "message": "Default"},
            blocking=True,
        )
        clients[1].send.assert_awaited_once_with("+15551234561", "Default")
        with pytest.raises(HomeAssistantError, match="Photon Spectrum notify entity"):
            await hass.services.async_call(
                "notify", "photon_spectrum",
                {"entity_id": "notify.other", "message": "Not allowed"},
                blocking=True,
            )
        for target in ([], ["5551234567"]):
            with pytest.raises(vol.Invalid):
                await hass.services.async_call(
                    "notify", "photon_spectrum",
                    {
                        "entity_id": "notify.project_1",
                        "message": "Bad",
                        "target": target,
                    },
                    blocking=True,
                )
        assert clients[1].send.await_count == 1
        await async_unload_entry(hass, entries[0])
        assert hass.services.has_service("notify", "photon_spectrum")
        await async_unload_entry(hass, entries[1])
        assert not hass.services.has_service("notify", "photon_spectrum")
        hass.services.async_register("notify", "photon_spectrum", AsyncMock())
        with pytest.raises(HomeAssistantError, match="already registered"):
            await async_setup_entry(hass, entries[0])

    asyncio.run(check())
