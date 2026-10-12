"""Configure a Photon Spectrum shared-line destination."""

import re
from uuid import UUID

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .client import SharedLineClient
from .webhook import webhook_path

DOMAIN = "photon_spectrum"
RECIPIENT = re.compile(r"\+[1-9][0-9]{7,14}\Z")


def parse_recipients(value: str) -> list[str]:
    """Parse comma- or newline-separated international phone numbers."""
    numbers = [part.strip() for part in re.split(r"[,\n]+", value) if part.strip()]
    if not numbers or any(not RECIPIENT.fullmatch(number) for number in numbers):
        raise ValueError("Invalid recipient phone number")
    return list(dict.fromkeys(numbers))


class PhotonSpectrumConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one notification entity per Photon project."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Allow the project's recipients to be changed."""
        return PhotonSpectrumOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Validate the project and its shared-line recipients."""
        errors = {}
        if user_input is not None:
            project_id = None
            recipients = []
            try:
                project_id = str(UUID(user_input["project_id"]))
            except ValueError:
                errors["project_id"] = "invalid_project_id"
            try:
                recipients = parse_recipients(user_input["recipients"])
            except ValueError:
                errors["recipients"] = "invalid_recipients"
            if not errors and project_id is not None and recipients:
                client = SharedLineClient(
                    self.hass, project_id, user_input["project_secret"]
                )
                try:
                    await client._get_token()
                except HomeAssistantError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(project_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="Photon Spectrum",
                        data={
                            "project_id": project_id,
                            "project_secret": user_input["project_secret"],
                            "recipients": recipients,
                        },
                    )
                finally:
                    await client.close()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("project_id"): str,
                    vol.Required("project_secret"): vol.All(str, vol.Length(min=1)),
                    vol.Required("recipients"): str,
                }
            ),
            errors=errors,
        )


class PhotonSpectrumOptionsFlow(config_entries.OptionsFlow):
    """Edit recipients and the project's webhook signing secret."""

    async def async_step_init(self, user_input=None):
        """Validate and save project options."""
        errors = {}
        if user_input is not None:
            try:
                recipients = parse_recipients(user_input["recipients"])
            except ValueError:
                errors["recipients"] = "invalid_recipients"
            secret = user_input.get("webhook_signing_secret", "").strip()
            if secret and (len(secret) != 64 or not secret.isascii()):
                errors["webhook_signing_secret"] = "invalid_webhook_secret"
            if not errors:
                options = {**self.config_entry.options, "recipients": recipients}
                if user_input.get("disable_webhook"):
                    options.pop("webhook_signing_secret", None)
                elif secret:
                    options["webhook_signing_secret"] = secret
                return self.async_create_entry(title="", data=options)

        current = self.config_entry.options.get(
            "recipients", self.config_entry.data["recipients"]
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required("recipients", default=", ".join(current)): str,
                    vol.Optional("webhook_signing_secret"): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Optional("disable_webhook", default=False): bool,
                }
            ),
            errors=errors,
            description_placeholders={"webhook_path": webhook_path(self.config_entry)},
        )
