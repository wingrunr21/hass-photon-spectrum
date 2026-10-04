"""Compare the Python send contract with Photon's pinned TypeScript SDK."""

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.photon_spectrum.client import SharedLineClient
from custom_components.photon_spectrum.proto import message_pb2

SDK_DIR = Path(__file__).parent


def test_shared_line_sdk_parity():
    result = subprocess.run(
        ["node", str(SDK_DIR / "official.mjs")],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.fail(
            f"Install the pinned SDK with npm ci --prefix tests/sdk_parity\n{result.stderr}"
        )
    official = json.loads(result.stdout)

    async def check():
        response = MagicMock()
        response.json = AsyncMock(
            return_value={"succeed": True, "data": official["token"]}
        )
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
        with (
            patch(
                "custom_components.photon_spectrum.client.async_get_clientsession",
                return_value=session,
            ),
            patch(
                "custom_components.photon_spectrum.client.grpc.aio.secure_channel",
                return_value=channel,
            ),
        ):
            client = SharedLineClient(MagicMock(), "project", "secret")
            await client.send("+15551234567", "Smoke test")
            assert call.await_args is not None
            request = call.await_args.args[0]
            post = session.post.call_args
            assert official["tokenRequest"] == {
                "url": post.args[0],
                "method": "POST",
                "authorization": post.kwargs["auth"].encode(),
            }
            assert official["chatGuid"] == request.chat_guid
            assert request.text == "Smoke test"
            assert official["method"] == channel.unary_unary.call_args.args[0]
            assert all(
                official["fields"][field.name] == field.number
                for field in request.DESCRIPTOR.fields
            )
            assert call.await_args.kwargs["metadata"][0] == (
                "authorization",
                f"Bearer {official['token']['token']}",
            )
            await client.close()

    asyncio.run(check())
