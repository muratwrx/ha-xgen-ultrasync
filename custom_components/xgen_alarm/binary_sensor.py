"""A binary sensor for each zone of the panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import XGenError, Zone
from .const import ATTR_BYPASS, SERVICE_SET_BYPASS
from .coordinator import XGenConfigEntry, XGenCoordinator
from .entity import XGenEntity


def _device_class(name: str) -> BinarySensorDeviceClass:
    """Guess the sensor type from the zone name the installer gave it."""
    lower = name.lower()
    if "door" in lower:
        return BinarySensorDeviceClass.DOOR
    if "window" in lower:
        return BinarySensorDeviceClass.WINDOW
    if "smoke" in lower:
        return BinarySensorDeviceClass.SMOKE
    if "box" in lower or "tamper" in lower:
        return BinarySensorDeviceClass.TAMPER
    return BinarySensorDeviceClass.MOTION


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XGenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        XGenZoneSensor(coordinator, number) for number in coordinator.data.zones
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_BYPASS,
        {vol.Required(ATTR_BYPASS): cv.boolean},
        "async_set_bypass",
    )


class XGenZoneSensor(XGenEntity, BinarySensorEntity):
    """On while the zone is open or detecting motion."""

    def __init__(self, coordinator: XGenCoordinator, number: int) -> None:
        super().__init__(coordinator, f"zone_{number}")
        self._number = number
        name = coordinator.data.zones[number].name
        self._attr_name = name
        self._attr_device_class = _device_class(name)

    @property
    def _zone(self) -> Zone:
        return self.coordinator.data.zones[self._number]

    @property
    def is_on(self) -> bool:
        return self._zone.open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        return {
            "zone": zone.number,
            "bypassed": zone.bypassed,
            "tamper": zone.tamper,
            "trouble": zone.trouble,
            "alarm": zone.alarm,
            "low_battery": zone.low_battery,
            "supervision_fault": zone.supervision,
        }

    async def async_set_bypass(self, bypass: bool) -> None:
        try:
            await self.coordinator.client.async_set_bypass(self._number, bypass)
        except XGenError as err:
            raise HomeAssistantError(f"Alarm panel did not accept the bypass: {err}") from err
        self.coordinator.push()
