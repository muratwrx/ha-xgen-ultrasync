"""Base entity for xGen Alarm."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import XGenCoordinator


class XGenEntity(CoordinatorEntity[XGenCoordinator]):
    """An entity belonging to the panel device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: XGenCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Alarm",
            manufacturer=MANUFACTURER,
            model=MODEL,
            configuration_url=f"http://{entry.data['host']}/",
        )
