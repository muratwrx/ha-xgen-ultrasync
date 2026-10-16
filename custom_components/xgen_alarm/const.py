"""Constants for the xGen Alarm integration."""

from datetime import timedelta

DOMAIN = "xgen_alarm"

MANUFACTURER = "Interlogix"
MODEL = "xGen"

# seq.json is a tiny request, and the panel's own web UI polls it every 5.5 s
SCAN_INTERVAL = timedelta(seconds=2)

SERVICE_SET_BYPASS = "set_bypass"
ATTR_BYPASS = "bypass"
