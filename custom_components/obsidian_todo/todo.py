"""Native Home Assistant to-do entity backed by an Obsidian Markdown note."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.todo import TodoItem, TodoListEntity
from homeassistant.components.todo.const import TodoItemStatus, TodoListEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_NOTE_PATH, CONF_VAULT_PATH, SCAN_INTERVAL_SECONDS
from .markdown_store import MarkdownStoreError, MarkdownTask, MarkdownTodoStore

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SECONDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Obsidian-backed to-do entity."""
    store = MarkdownTodoStore(
        vault_path=entry.data[CONF_VAULT_PATH],
        note_path=entry.data[CONF_NOTE_PATH],
        title=entry.data[CONF_NAME],
    )
    async_add_entities(
        [ObsidianTodoEntity(entry, store)], update_before_add=True
    )


class ObsidianTodoEntity(TodoListEntity):
    """Represent one Markdown note as a Home Assistant to-do list."""

    _attr_icon = "mdi:notebook-check-outline"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self,
        entry: ConfigEntry,
        store: MarkdownTodoStore,
    ) -> None:
        self._store = store
        self._attr_name = entry.data[CONF_NAME]
        self._attr_unique_id = entry.unique_id or entry.entry_id

    async def async_update(self) -> None:
        """Refresh tasks from the Markdown note."""
        try:
            tasks = await self.hass.async_add_executor_job(self._store.load)
        except OSError as err:
            raise HomeAssistantError(
                translation_domain="obsidian_todo",
                translation_key="read_failed",
            ) from err
        self._attr_todo_items = self._to_ha_items(tasks)

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Append a task to the Markdown note."""
        if item.summary is None:
            raise HomeAssistantError("A task summary is required")
        await self._run_mutation(self._store.add, item.summary)

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Rename or check/uncheck a Markdown task."""
        if item.uid is None:
            raise HomeAssistantError("A task UID is required")
        completed = (
            None
            if item.status is None
            else item.status == TodoItemStatus.COMPLETED
        )
        await self._run_mutation(
            self._store.update,
            item.uid,
            summary=item.summary,
            completed=completed,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete Markdown tasks."""
        await self._run_mutation(self._store.delete, uids)

    async def _run_mutation(self, func, *args, **kwargs) -> None:
        """Run blocking storage work and publish the resulting task list."""
        try:
            tasks = await self.hass.async_add_executor_job(
                lambda: func(*args, **kwargs)
            )
        except (MarkdownStoreError, OSError) as err:
            _LOGGER.error("Unable to update Obsidian to-do note: %s", err)
            raise HomeAssistantError(str(err)) from err
        self._attr_todo_items = self._to_ha_items(tasks)
        self.async_write_ha_state()

    @staticmethod
    def _to_ha_items(tasks: list[MarkdownTask]) -> list[TodoItem]:
        return [
            TodoItem(
                uid=task.uid,
                summary=task.summary,
                status=(
                    TodoItemStatus.COMPLETED
                    if task.completed
                    else TodoItemStatus.NEEDS_ACTION
                ),
            )
            for task in tasks
        ]
