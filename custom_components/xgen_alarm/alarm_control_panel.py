"""Alarm control panel for each area of the panel."""

from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import Area, XGenError
from .coordinator import XGenConfigEntry, XGenCoordinator
from .entity import XGenEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: XGenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        XGenAlarmPanel(coordinator, number)
        for number in coordinator.data.areas
    )


class XGenAlarmPanel(XGenEntity, AlarmControlPanelEntity):
    """One area, armed and disarmed with the panel user's own PIN."""

    _attr_code_arm_required = False
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
    )

    def __init__(self, coordinator: XGenCoordinator, number: int) -> None:
        super().__init__(coordinator, f"area_{number}")
        self._number = number
        self._attr_name = coordinator.data.areas[number].name

    @property
    def _area(self) -> Area:
        return self.coordinator.data.areas[self._number]

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        area = self._area
        if area.triggered:
            return AlarmControlPanelState.TRIGGERED
        if area.entry_delay:
            return AlarmControlPanelState.PENDING
        if area.exit_delay:
            return AlarmControlPanelState.ARMING
        # Stay arming may also set the armed bit, so check it first
        if area.armed_stay:
            return AlarmControlPanelState.ARMED_HOME
        if area.armed_away:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        area = self._area
        return {
            "ready": area.ready,
            "chime": area.chime,
            "zones_bypassed": area.bypass,
            "trouble": area.trouble,
            "tamper": area.tamper,
            "low_battery": area.low_battery,
            "fire": area.fire,
            "panic": area.panic,
        }

    async def _send(self, command) -> None:
        try:
            await command(self._number)
        except XGenError as err:
            raise HomeAssistantError(f"Alarm panel did not accept the command: {err}") from err
        self.coordinator.push()

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        await self._send(self.coordinator.client.async_disarm)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        await self._send(self.coordinator.client.async_arm_stay)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        await self._send(self.coordinator.client.async_arm_away)
