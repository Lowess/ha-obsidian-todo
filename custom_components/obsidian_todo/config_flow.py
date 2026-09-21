"""Config flow for Obsidian Markdown To-do."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME

from .const import (
    CONF_NOTE_PATH,
    CONF_VAULT_PATH,
    DEFAULT_NAME,
    DEFAULT_NOTE_PATH,
    DOMAIN,
)
from .markdown_store import InvalidPathError, MarkdownTodoStore


class ObsidianTodoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle an Obsidian Markdown To-do config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create an Obsidian Markdown To-do list."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                store = MarkdownTodoStore(
                    vault_path=user_input[CONF_VAULT_PATH],
                    note_path=user_input[CONF_NOTE_PATH],
                    title=user_input[CONF_NAME],
                )
                await self.hass.async_add_executor_job(store.validate_access)
            except InvalidPathError:
                errors["base"] = "invalid_path"
            except OSError:
                errors["base"] = "cannot_access"
            else:
                unique_id = (
                    f"{Path(user_input[CONF_VAULT_PATH]).resolve()}::"
                    f"{user_input[CONF_NOTE_PATH]}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_VAULT_PATH): str,
                vol.Required(CONF_NOTE_PATH, default=DEFAULT_NOTE_PATH): str,
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )
