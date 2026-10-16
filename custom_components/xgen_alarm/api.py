"""Client for the Interlogix xGen / xGenLite panel's built-in web interface.

The panel has no official API. Its web UI talks to a handful of JSON/CGI
endpoints, all of which take a session id ("sess") obtained from login.cgi:

  POST /login.cgi              lgname, lgpin -> HTML page containing the session id
  POST /user/seq.json          change counters for areas and each zone state bank
  POST /user/status.json       arsel=<bank>  -> area bit fields for 8 areas
  POST /user/zstate.json       state=<type>  -> one zone bitmask per state type
  POST /user/zones.htm         HTML page with the zone names
  POST /user/keyfunction.cgi   fnum, start=<bank>, mask=<area bit>  -> arm/disarm/chime
  POST /user/zonefunction.cgi  cmd, opt, zone  -> bypass/chime per zone
  POST /user/api/events.cgi    count -> event log

An expired or invalid session gets a 302 redirect to the login page, which
the client treats as a signal to log in again.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import re
from typing import Any
from urllib.parse import unquote

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10

# keyfunction.cgi function numbers (from the panel's status.js)
FNUM_DISARM = 0
FNUM_STAY = 1
FNUM_CHIME_ON = 10
FNUM_CHIME_OFF = 11
FNUM_AWAY = 15

# zonefunction.cgi commands
ZONE_CMD_BYPASS = 5
ZONE_CMD_CHIME = 6

# Hex character offsets of each byte in an area bank's "bankstates" string.
# Each byte holds one bit per area in the bank (8 areas per bank).
AREA_READY = 0
AREA_PARTIAL = 4  # armed stay
AREA_ARMED = 6  # armed away
AREA_EXIT1 = 8
AREA_EXIT2 = 10
AREA_ENTRY = 12
AREA_FIRE = 16
AREA_BURGLAR = 18
AREA_PANIC = 20
AREA_AUX = 22
AREA_CHIME = 36
AREA_NIGHT = 52
AREA_BYPASS = 64
AREA_TROUBLE = 66
AREA_TAMPER = 68
AREA_LOW_BATTERY = 70

# Zone state types: the index into the per-type zone bitmasks
ZONE_NOT_READY = 0  # open / active
ZONE_TAMPER = 1
ZONE_TROUBLE = 2
ZONE_BYPASSED = 3
ZONE_INHIBITED = 4
ZONE_ALARM = 5
ZONE_LOW_BATTERY = 6
ZONE_SUPERVISION = 7
ZONE_CHIME = 9

# Event log classes the "last event" skips: 3 = zone bypass/restore, 21 = web login
EVENT_CLASSES_IGNORED = (3, 21)

_SESSION_RE =re.compile(r'getSession\(\)\s*\{\s*return\s*"([0-9A-Fa-f]+)"')
_AREA_NAMES_RE = re.compile(r"var areaNames\s*=\s*\[([^\]]*)\]")
_ZONE_NAMES_RE = re.compile(r"var zoneNames\s*=\s*new Array\(([^)]*)\)")
_QUOTED_RE = re.compile(r'"([^"]*)"')


class XGenError(Exception):
    """The panel could not be reached or returned something unexpected."""


class XGenAuthError(XGenError):
    """The panel rejected the user name or PIN."""


class _SessionExpired(Exception):
    """The panel redirected to its login page."""


def _bit(hexstr: str, offset: int, index: int) -> bool:
    """Return bit `index % 8` of the byte at hex char `offset`."""
    try:
        return bool(int(hexstr[offset : offset + 2], 16) & (1 << (index % 8)))
    except ValueError:
        return False


def _names(raw: str) -> list[str]:
    """Decode the URL-encoded name list the panel embeds in its pages."""
    return [unquote(n) for n in _QUOTED_RE.findall(raw)]


@dataclass
class Area:
    """One area (partition) of the panel."""

    number: int  # 1-based
    name: str
    ready: bool = False
    armed_away: bool = False
    armed_stay: bool = False
    night: bool = False
    exit_delay: bool = False
    entry_delay: bool = False
    fire: bool = False
    burglar: bool = False
    panic: bool = False
    aux: bool = False
    chime: bool = False
    bypass: bool = False
    trouble: bool = False
    tamper: bool = False
    low_battery: bool = False

    @property
    def triggered(self) -> bool:
        return self.fire or self.burglar or self.panic or self.aux

    def update(self, bankstates: str) -> None:
        i = self.number - 1
        self.ready = _bit(bankstates, AREA_READY, i)
        self.armed_away = _bit(bankstates, AREA_ARMED, i)
        self.armed_stay = _bit(bankstates, AREA_PARTIAL, i)
        self.night = _bit(bankstates, AREA_NIGHT, i)
        self.exit_delay = _bit(bankstates, AREA_EXIT1, i) or _bit(
            bankstates, AREA_EXIT2, i
        )
        self.entry_delay = _bit(bankstates, AREA_ENTRY, i)
        self.fire = _bit(bankstates, AREA_FIRE, i)
        self.burglar = _bit(bankstates, AREA_BURGLAR, i)
        self.panic = _bit(bankstates, AREA_PANIC, i)
        self.aux = _bit(bankstates, AREA_AUX, i)
        self.chime = _bit(bankstates, AREA_CHIME, i)
        self.bypass = _bit(bankstates, AREA_BYPASS, i)
        self.trouble = _bit(bankstates, AREA_TROUBLE, i)
        self.tamper = _bit(bankstates, AREA_TAMPER, i)
        self.low_battery = _bit(bankstates, AREA_LOW_BATTERY, i)


@dataclass
class Zone:
    """One zone (sensor) of the panel."""

    number: int  # 1-based
    name: str
    open: bool = False
    tamper: bool = False
    trouble: bool = False
    bypassed: bool = False
    inhibited: bool = False
    alarm: bool = False
    low_battery: bool = False
    supervision: bool = False
    chime: bool = False


@dataclass
class Event:
    """One entry from the panel's event log."""

    id: int
    time: datetime
    text: str
    user: int | None


@dataclass
class PanelState:
    """Everything the client knows about the panel."""

    areas: dict[int, Area] = field(default_factory=dict)
    zones: dict[int, Zone] = field(default_factory=dict)
    last_event: Event | None = None


class XGenClient:
    """Talks to the panel over its web interface, keeping one session alive."""

    def __init__(
        self, session: aiohttp.ClientSession, host: str, username: str, pin: str
    ) -> None:
        self._http = session
        self._base = f"http://{host}"
        self._username = username
        self._pin = pin
        self._sess: str | None = None
        # The panel's web server handles one request at a time; serialise ours
        self._lock = asyncio.Lock()

        self.state = PanelState()
        self._area_seq: list[int] = []
        self._zone_seq: list[int] = []
        self._zone_banks: dict[int, str] = {}

    # --- low level -------------------------------------------------------

    async def _request(self, path: str, data: dict[str, Any]) -> tuple[int, str]:
        try:
            async with self._http.post(
                self._base + path,
                data=data,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                return resp.status, await resp.text(encoding="latin-1")
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise XGenError(f"Cannot reach panel at {self._base}: {err}") from err

    async def _login(self) -> str:
        """Log in and return the login page (which lists the areas)."""
        self._sess = None
        status, body = await self._request(
            "/login.cgi", {"lgname": self._username, "lgpin": self._pin}
        )
        match = _SESSION_RE.search(body)
        if status != 200 or not match:
            raise XGenAuthError("Panel rejected the user name or PIN")
        self._sess = match.group(1)
        _LOGGER.debug("Logged in to panel")
        return body

    async def _call_once(self, path: str, data: dict[str, Any]) -> str:
        if self._sess is None:
            await self._login()
        status, body = await self._request(path, {"sess": self._sess, **data})
        if status in (301, 302, 303) or "login.cgi" in body[:2000]:
            raise _SessionExpired
        if status != 200:
            raise XGenError(f"Panel returned HTTP {status} for {path}")
        return body

    async def _call(self, path: str, data: dict[str, Any] | None = None) -> str:
        """POST to the panel, logging in again once if the session has expired."""
        data = data or {}
        try:
            return await self._call_once(path, data)
        except _SessionExpired:
            _LOGGER.debug("Panel session expired, logging in again")
            self._sess = None
            try:
                return await self._call_once(path, data)
            except _SessionExpired as err:
                raise XGenError("Panel keeps rejecting the session") from err

    async def _call_json(self, path: str, data: dict[str, Any] | None = None) -> dict:
        body = await self._call(path, data)
        try:
            return json.loads(body)
        except ValueError as err:
            raise XGenError(f"Unexpected response from {path}: {body[:200]!r}") from err

    # --- reading ---------------------------------------------------------

    async def async_setup(self) -> PanelState:
        """Log in, read area and zone names, and load the full state."""
        async with self._lock:
            page = await self._login()
            match = _AREA_NAMES_RE.search(page)
            area_names = _names(match.group(1)) if match else []
            self.state.areas = {
                i + 1: Area(i + 1, name)
                for i, name in enumerate(area_names)
                if name and name != "!"
            }

            page = await self._call("/user/zones.htm")
            match = _ZONE_NAMES_RE.search(page)
            zone_names = _names(match.group(1)) if match else []
            self.state.zones = {
                i + 1: Zone(i + 1, name or f"Zone {i + 1}")
                for i, name in enumerate(zone_names)
                if name != "!"
            }

            # Empty sequence lists make the next poll fetch everything
            self._area_seq = []
            self._zone_seq = []
            await self._poll()
        return self.state

    async def async_update(self) -> PanelState:
        """Fetch whatever changed since the last update."""
        async with self._lock:
            await self._poll()
        return self.state

    async def _poll(self) -> None:
        seq = await self._call_json("/user/seq.json")
        areas_seq: list[int] = seq.get("area", [])
        zones_seq: list[int] = seq.get("zone", [])
        area_changed = False

        for bank, value in enumerate(areas_seq):
            if bank >= len(self._area_seq) or self._area_seq[bank] != value:
                if any((n - 1) // 8 == bank for n in self.state.areas):
                    await self._read_area_bank(bank)
                    area_changed = True
        self._area_seq = list(areas_seq)

        zones_changed = False
        for kind, value in enumerate(zones_seq):
            if kind >= len(self._zone_seq) or self._zone_seq[kind] != value:
                data = await self._call_json("/user/zstate.json", {"state": kind})
                self._zone_banks[data.get("zbank", kind)] = data.get("bankstates", "")
                zones_changed = True
        self._zone_seq = list(zones_seq)
        if zones_changed:
            self._apply_zones()

        if area_changed or self.state.last_event is None:
            await self._read_last_event()

    async def _read_area_bank(self, bank: int) -> None:
        data = await self._call_json("/user/status.json", {"arsel": bank})
        self._apply_area_bank(data)

    def _apply_area_bank(self, data: dict) -> None:
        bank = data.get("abank", 0)
        bankstates = data.get("bankstates", "")
        for area in self.state.areas.values():
            if (area.number - 1) // 8 == bank:
                area.update(bankstates)

    def _apply_zones(self) -> None:
        banks = self._zone_banks

        def flag(kind: int, i: int) -> bool:
            return _bit(banks.get(kind, ""), 2 * (i // 8), i)

        for zone in self.state.zones.values():
            i = zone.number - 1
            zone.open = flag(ZONE_NOT_READY, i)
            zone.tamper = flag(ZONE_TAMPER, i)
            zone.trouble = flag(ZONE_TROUBLE, i)
            zone.bypassed = flag(ZONE_BYPASSED, i)
            zone.inhibited = flag(ZONE_INHIBITED, i)
            zone.alarm = flag(ZONE_ALARM, i)
            zone.low_battery = flag(ZONE_LOW_BATTERY, i)
            zone.supervision = flag(ZONE_SUPERVISION, i)
            zone.chime = flag(ZONE_CHIME, i)

    async def _read_last_event(self) -> None:
        """Remember the newest event that isn't a web login or a bypass."""
        try:
            # Web logins fill the log, so look back far enough to skip them
            data = await self._call_json("/user/api/events.cgi", {"count": 60, "type": 0})
        except XGenError as err:
            _LOGGER.debug("Could not read event log: %s", err)
            return
        for raw in data.get("events", []):
            text = " ".join(unquote(raw.get("text", "")).split())
            # Stay arming bypasses (and later restores) every interior zone,
            # which would bury the arm/disarm event itself
            if raw.get("class") in EVENT_CLASSES_IGNORED or text.startswith("Remote Access"):
                continue
            # Drop the trailing "Time: ... Date: ..." the panel appends
            text = re.sub(r"\s*Time:.*$", "", text).replace("*", "")
            self.state.last_event = Event(
                id=raw.get("id", 0),
                time=datetime.fromtimestamp(raw.get("time", 0), timezone.utc),
                text=text,
                user=raw.get("user"),
            )
            return

    # --- commands --------------------------------------------------------

    async def _area_command(self, area: int, fnum: int) -> None:
        bank, bit = divmod(area - 1, 8)
        async with self._lock:
            data = await self._call_json(
                "/user/keyfunction.cgi",
                {"fnum": fnum, "start": bank, "mask": 1 << bit},
            )
            # The reply is the area bank's new status
            if "bankstates" in data:
                self._apply_area_bank(data)

    async def async_arm_away(self, area: int) -> None:
        await self._area_command(area, FNUM_AWAY)

    async def async_arm_stay(self, area: int) -> None:
        await self._area_command(area, FNUM_STAY)

    async def async_disarm(self, area: int) -> None:
        await self._area_command(area, FNUM_DISARM)

    async def async_set_chime(self, area: int, on: bool) -> None:
        await self._area_command(area, FNUM_CHIME_ON if on else FNUM_CHIME_OFF)

    async def async_set_bypass(self, zone: int, bypass: bool) -> None:
        async with self._lock:
            data = await self._call_json(
                "/user/zonefunction.cgi",
                {"cmd": ZONE_CMD_BYPASS, "opt": int(bypass), "zone": zone - 1},
            )
            if "bankstates" in data:
                self._zone_banks[data.get("zbank", ZONE_BYPASSED)] = data["bankstates"]
                self._apply_zones()
