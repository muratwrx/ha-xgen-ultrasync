"""Door chime switch for each area."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import XGenError
from .coordinator import XGenConfigEntry, XGenCoordinator
from .entity import XGenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XGenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        XGenChime(coordinator, number) for number in coordinator.data.areas
    )


class XGenChime(XGenEntity, SwitchEntity):
    """Keypad chime when a chime-enabled zone opens."""

    _attr_icon = "mdi:bell-ring"

    def __init__(self, coordinator: XGenCoordinator, number: int) -> None:
        super().__init__(coordinator, f"chime_{number}")
        self._number = number
        area = coordinator.data.areas[number].name
        self._attr_name = "Chime" if len(coordinator.data.areas) == 1 else f"{area} chime"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.areas[self._number].chime

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.client.async_set_chime(self._number, on)
        except XGenError as err:
            raise HomeAssistantError(f"Alarm panel did not accept the command: {err}") from err
        self.coordinator.push()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
