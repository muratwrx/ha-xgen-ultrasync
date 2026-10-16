"""The panel's most recent event, e.g. who last armed or disarmed it."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import XGenConfigEntry, XGenCoordinator
from .entity import XGenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XGenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([XGenLastEvent(entry.runtime_data)])


class XGenLastEvent(XGenEntity, SensorEntity):
    """Text of the newest event-log entry, skipping web logins."""

    _attr_name = "Last event"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: XGenCoordinator) -> None:
        super().__init__(coordinator, "last_event")

    @property
    def native_value(self) -> str | None:
        event = self.coordinator.data.last_event
        return event.text[:255] if event else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        event = self.coordinator.data.last_event
        if event is None:
            return {}
        return {"time": event.time.isoformat(), "user_number": event.user}
