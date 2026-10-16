# xGen UltraSync Alarm for Home Assistant

A Home Assistant integration for **Interlogix xGen / xGenLite** alarm panels. It talks to the panel's built-in web interface (the one UltraSync uses) over your local network. There's no cloud and there are no extra Python packages.

It's a replacement for the template-and-automation setups people build around other UltraSync integrations. It gives you a real alarm control panel entity, which HomeKit Bridge exposes to Apple Home as a Security System.

> Not affiliated with or endorsed by Interlogix, Carrier or UltraSync, and not related to the `ha-ultrasync` integration. Use at your own risk: this arms and disarms a security system.

## Features

| Entity | What it does |
|---|---|
| `alarm_control_panel.<area>` | One per area: Arm Away, Arm Stay (Home) and Disarm. States: disarmed, arming (exit delay), armed home, armed away, pending (entry delay) and triggered. |
| `binary_sensor.<zone>` | One per zone, on while the zone is open or detecting motion. The device class comes from the zone name: *door* gives door, *window* gives window, *smoke* gives smoke, *box*/*tamper* gives tamper, and anything else is motion. Attributes: `bypassed`, `tamper`, `trouble`, `alarm`, `low_battery`, `supervision_fault`. |
| `switch.<…>_chime` | Keypad door chime on/off. |
| `sensor.<…>_last_event` | The newest panel event (e.g. "Turn On Away Home Jane"). Web logins and the automatic Stay-mode bypass entries are skipped. |
| Action `xgen_alarm.set_bypass` | Bypass or un-bypass a zone (target a zone binary sensor). |

Reliability:

- It polls the panel's tiny change-counter endpoint every 2 s and only fetches area or zone details when something has changed.
- It keeps one login session and logs in again automatically if the panel drops it. It doesn't log in again on every poll.
- After an arm or disarm command, the state updates from the panel's reply straight away.

## Requirements

- An xGen or xGenLite panel with its web interface enabled, reachable from Home Assistant (e.g. `http://192.168.1.x/`).
- A panel user with arm/disarm rights. A dedicated user for Home Assistant is a good idea, so its actions show up separately in the panel's event log.
- Home Assistant 2025.2 or newer.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/muratwrx/ha-xgen-ultrasync`, category **Integration**.
2. Search for **xGen UltraSync Alarm** → **Download**.
3. Restart Home Assistant.

### Manual

Copy `custom_components/xgen_alarm` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

**Settings → Devices & services → Add integration → xGen UltraSync Alarm**, then enter:

- **Host**: the panel's IP address or host name
- **User name** and **PIN**: the panel user, exactly as named on the panel

To change these later, open the integration and choose **⋮ → Reconfigure**.

## Apple Home (HomeKit)

Add a **HomeKit Bridge** (Settings → Devices & services → Add integration → HomeKit Bridge) in *include* mode, and select the alarm control panel and the zone sensors. The alarm shows up as a Security System that Siri and Home automations can use.

HomeKit has no tamper sensor type, so tamper zones would show up as "occupancy" sensors. It's usually best to leave them out.

## Dashboard example

```yaml
type: vertical-stack
cards:
  - type: alarm-panel
    entity: alarm_control_panel.alarm_home
    states: [arm_home, arm_away]
  - type: entities
    title: Alarm sensors
    state_color: true
    entities:
      - binary_sensor.alarm_front_door
      - switch.alarm_chime
      - sensor.alarm_last_event
```

## Troubleshooting

- **The panel's event log shows many "Remote Access" entries.** Each one is a login. One appears when Home Assistant starts and another whenever the panel drops the session. If you see one every few seconds, check that nothing else (another integration, an open browser tab) is logged in as the same user.
- **Entities go unavailable.** Check **Settings → System → Logs** for `xgen_alarm`. Turn on debug logging to see each login and request:
  ```yaml
  logger:
    logs:
      custom_components.xgen_alarm: debug
  ```
- **"The panel rejected the user name or PIN".** The user name must match the panel exactly, including capitals and spaces.

## How it works (panel protocol)

The panel has no official API. These are the endpoints its own web UI uses. All of them are `POST`, all take `sess=<session id>`, and an invalid session gets a `302` redirect to the login page.

| Endpoint | Parameters | Returns |
|---|---|---|
| `/login.cgi` | `lgname`, `lgpin` | HTML containing `getSession(){return "<id>"}` and `areaNames` |
| `/user/seq.json` | – | `{"area":[seq…], "zone":[seq per zone state type…]}` change counters |
| `/user/status.json` | `arsel=<bank>` | `{"abank", "aseq", "bankstates": "<hex>"}` for 8 areas |
| `/user/zstate.json` | `state=<type>` | `{"zbank": <type>, "bankstates": "<hex>"}`: one bitmask of zones per state type |
| `/user/zones.htm` | – | HTML with `zoneNames` |
| `/user/keyfunction.cgi` | `fnum`, `start=<bank>`, `mask=<area bit>` | new area status; `fnum` 15 = away, 1 = stay, 0 = disarm, 10/11 = chime on/off |
| `/user/zonefunction.cgi` | `cmd`, `opt`, `zone=<0-based>` | new zone status; `cmd` 5 = bypass (`opt` 1/0), 6 = chime |
| `/user/api/events.cgi` | `count`, `type=0` | event log as JSON (URL-encoded text) |

**Area `bankstates`** is a hex string of bytes, and each byte holds one bit per area in the bank. Byte offsets (in hex characters): 0 ready, 4 armed stay, 6 armed away, 8/10 exit delay, 12 entry delay, 16 fire, 18 burglary, 20 panic, 22 auxiliary alarm, 36 chime, 52 night, 64 bypass, 66 trouble, 68 tamper, 70 low battery.

**Zone state types** (the `state=` index): 0 not ready (open), 1 tamper, 2 trouble, 3 bypassed, 4 inhibited, 5 alarm, 6 low battery, 7 supervision fault, 9 chime-enabled. Zone *n* (0-based) is bit `n % 8` of byte `n // 8`.

## License

MIT
