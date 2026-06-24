# Raspberry Pi Sensor Setup — PFAS Facility QC

This document covers hardware selection, wiring, software installation, and
configuration for automated temperature and humidity monitoring via Raspberry Pi.
Readings are pushed to SENAITE over the lab LAN and stored in the Facility QC
database (`/data/qc/facility_monitoring.db`).

---

## Hardware

### Recommended sensors

| Location | Sensor | Interface | Accuracy | Notes |
|---|---|---|---|---|
| Refrigerator / Freezer | DS18B20 (waterproof probe) | 1-Wire | ±0.5°C | Thread probe through door gasket; use food-safe silicone sealant |
| Room (temp + humidity) | SHT31-D breakout | I²C | ±0.3°C, ±2% RH | Better long-term stability than DHT22 |
| Eye wash station | DS18B20 (clip probe) | 1-Wire | ±0.5°C | Clip to outflow pipe; optional |

Multiple DS18B20 sensors can share a single GPIO pin (1-Wire supports up to
~10 devices per bus). Each has a unique 64-bit serial address burned in at the
factory.

### Wiring — DS18B20 (1-Wire)

```
DS18B20 (3-wire)          Raspberry Pi
─────────────────         ─────────────
GND (black)     ──────── Pin 6  (GND)
VDD (red)       ──────── Pin 1  (3.3V)
DATA (yellow)   ──────── Pin 7  (GPIO4 / 1-Wire default)
                  ┤4.7kΩ├ (pull-up between DATA and VDD)
```

The 4.7 kΩ pull-up resistor is **required** between DATA and VDD. Omitting it
causes intermittent read failures. Most waterproof probe kits include it.

### Wiring — SHT31-D (I²C)

```
SHT31-D breakout          Raspberry Pi
─────────────────         ─────────────
GND   ──────────────────  Pin 9  (GND)
VIN   ──────────────────  Pin 17 (3.3V)
SDA   ──────────────────  Pin 3  (GPIO2 / I2C SDA)
SCL   ──────────────────  Pin 5  (GPIO3 / I2C SCL)
```

I²C is enabled by default on Raspberry Pi OS. Verify with:
```bash
ls /dev/i2c-*
```
If not present: `sudo raspi-config` → Interface Options → I2C → Enable.

---

## Raspberry Pi OS setup

### Enable 1-Wire (for DS18B20)

Add to `/boot/firmware/config.txt` (or `/boot/config.txt` on older images):
```
dtoverlay=w1-gpio
```
Reboot. Sensors appear as `/sys/bus/w1/devices/28-xxxxxxxxxxxx/w1_slave`.

### Python packages

```bash
sudo apt update
sudo apt install python3-pip python3-smbus i2c-tools -y
pip3 install requests adafruit-circuitpython-sht31d
```

---

## Sensor reader script

Create `/opt/pfas_sensor/sensor_reader.py`:

```python
#!/usr/bin/env python3
"""
PFAS Facility QC — Raspberry Pi sensor reader.

Reads DS18B20 (1-Wire) and SHT31-D (I2C) sensors, posts readings to the
SENAITE pfas-sensor-ingest endpoint. Stores failed POSTs locally in a SQLite
buffer and retries on the next run.

Schedule with systemd (see pfas_sensor.service below) or cron:
  */15 * * * * /opt/pfas_sensor/venv/bin/python3 /opt/pfas_sensor/sensor_reader.py
"""

import configparser
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

CONFIG_PATH = os.environ.get("PFAS_SENSOR_CONFIG", "/etc/pfas_sensor.conf")

# ── Config ────────────────────────────────────────────────────────────────────

def load_config():
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    s = cfg["sensor"] if "sensor" in cfg else {}
    return {
        "api_key":     s.get("api_key", ""),
        "endpoint":    s.get("endpoint", "http://senaite.local:8080/senaite/@@pfas-sensor-ingest"),
        "timeout":     int(s.get("timeout_seconds", "10")),
        "buffer_db":   s.get("buffer_db", "/opt/pfas_sensor/buffer.db"),
        "sensors":     _parse_sensors(cfg),
    }

def _parse_sensors(cfg):
    """Parse [sensor.XXX] sections into a list of sensor dicts."""
    sensors = []
    for section in cfg.sections():
        if not section.startswith("sensor."):
            continue
        s = cfg[section]
        sensors.append({
            "sensor_id":   section[len("sensor."):],
            "type":        s.get("type", "ds18b20"),   # ds18b20 | sht31
            "address":     s.get("address", ""),       # 1-Wire id or I2C addr
        })
    return sensors

# ── Sensor reading ────────────────────────────────────────────────────────────

def read_ds18b20(address):
    """Read temperature from a DS18B20 via 1-Wire sysfs interface."""
    path = "/sys/bus/w1/devices/{}/w1_slave".format(address)
    try:
        with open(path, "r") as f:
            lines = f.readlines()
        if "YES" not in lines[0]:
            return None, None
        temp_str = lines[1].split("t=")[1].strip()
        temp_c = float(temp_str) / 1000.0
        return round(temp_c, 3), None   # (temperature, humidity)
    except Exception as e:
        print("DS18B20 read error ({}): {}".format(address, e), file=sys.stderr)
        return None, None

def read_sht31(i2c_address=0x44):
    """Read temperature and humidity from an SHT31-D via I2C."""
    try:
        import board
        import adafruit_sht31d
        i2c = board.I2C()
        sensor = adafruit_sht31d.SHT31D(i2c, address=int(i2c_address, 16)
                                         if isinstance(i2c_address, str) else i2c_address)
        return round(sensor.temperature, 3), round(sensor.relative_humidity, 1)
    except Exception as e:
        print("SHT31 read error: {}".format(e), file=sys.stderr)
        return None, None

def read_sensor(s):
    if s["type"] == "ds18b20":
        return read_ds18b20(s["address"])
    elif s["type"] == "sht31":
        addr = int(s["address"], 16) if s["address"].startswith("0x") else 0x44
        return read_sht31(addr)
    return None, None

# ── Local buffer (survives network outages) ───────────────────────────────────

def _buf_connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            payload    TEXT NOT NULL,
            created_at TEXT NOT NULL,
            attempts   INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn

def buffer_add(db_path, payload):
    with _buf_connect(db_path) as conn:
        conn.execute("INSERT INTO pending (payload, created_at) VALUES (?,?)",
                     (json.dumps(payload), _now()))

def buffer_pending(db_path, limit=50):
    with _buf_connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, payload FROM pending ORDER BY id LIMIT ?", (limit,)
        ).fetchall()
    return [(r[0], json.loads(r[1])) for r in rows]

def buffer_delete(db_path, row_id):
    with _buf_connect(db_path) as conn:
        conn.execute("DELETE FROM pending WHERE id=?", (row_id,))

def buffer_increment(db_path, row_id):
    with _buf_connect(db_path) as conn:
        conn.execute("UPDATE pending SET attempts=attempts+1 WHERE id=?", (row_id,))

# ── HTTP POST ─────────────────────────────────────────────────────────────────

def post_reading(cfg, payload):
    """POST one reading. Returns True on success."""
    try:
        r = requests.post(
            cfg["endpoint"],
            json=payload,
            timeout=cfg["timeout"],
            headers={"Content-Type": "application/json"},
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "ok":
                return True
        print("POST failed: {} {}".format(r.status_code, r.text[:200]), file=sys.stderr)
        return False
    except requests.RequestException as e:
        print("Network error: {}".format(e), file=sys.stderr)
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def main():
    cfg = load_config()
    if not cfg["api_key"]:
        print("ERROR: api_key not set in {}".format(CONFIG_PATH), file=sys.stderr)
        sys.exit(1)

    ts = _now()

    # 1. Read all sensors and add to buffer
    for s in cfg["sensors"]:
        temp, humidity = read_sensor(s)
        if temp is None and humidity is None:
            print("No data from sensor {}".format(s["sensor_id"]), file=sys.stderr)
            continue
        payload = {
            "api_key":    cfg["api_key"],
            "sensor_id":  s["sensor_id"],
            "timestamp":  ts,
            "temperature": temp,
            "humidity":    humidity,
        }
        buffer_add(cfg["buffer_db"], payload)

    # 2. Drain the buffer — retry old failures too
    for row_id, payload in buffer_pending(cfg["buffer_db"]):
        if post_reading(cfg, payload):
            buffer_delete(cfg["buffer_db"], row_id)
        else:
            buffer_increment(cfg["buffer_db"], row_id)

if __name__ == "__main__":
    main()
```

---

## Configuration file `/etc/pfas_sensor.conf`

```ini
[sensor]
# API key — must match the value set in SENAITE @@pfas-facility-units
api_key  = REPLACE_WITH_YOUR_KEY

# Full URL to the SENAITE ingest endpoint
endpoint = http://192.168.1.100:8080/senaite/@@pfas-sensor-ingest

# HTTP POST timeout in seconds
timeout_seconds = 10

# Local buffer database (stores readings if network is down)
buffer_db = /opt/pfas_sensor/buffer.db

# ── One [sensor.<sensor_id>] section per physical sensor ──────────────────
# The sensor_id here MUST match the "Sensor ID" field in the SENAITE Unit Registry

[sensor.fridge-01]
type    = ds18b20
# Find your device address: ls /sys/bus/w1/devices/ — copy the 28-xxx string
address = 28-00000xxxxxxx

[sensor.freezer-01]
type    = ds18b20
address = 28-00000yyyyyyy

[sensor.room-main]
type    = sht31
# I2C address (default 0x44; ADDR pin high = 0x45)
address = 0x44
```

### Finding DS18B20 device addresses

```bash
ls /sys/bus/w1/devices/
# Output: 28-00000abcdef0  28-00000abcdef1  w1_bus_master1
# Each 28-xxx string is one sensor's address.
```

Label each physical probe with tape at installation time and record which
address maps to which unit. Add this mapping to the Unit Registry in SENAITE
(the `sensor_id` field on each facility unit must match the `[sensor.xxx]`
section name in this config file).

---

## systemd service

Create `/etc/systemd/system/pfas_sensor.service`:

```ini
[Unit]
Description=PFAS Facility QC Sensor Reader
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /opt/pfas_sensor/sensor_reader.py
StandardOutput=journal
StandardError=journal
```

Create `/etc/systemd/system/pfas_sensor.timer`:

```ini
[Unit]
Description=Run PFAS sensor reader every 15 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
AccuracySec=30s

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pfas_sensor.timer
sudo systemctl status pfas_sensor.timer
```

Check logs:
```bash
journalctl -u pfas_sensor.service -n 50
```

---

## SENAITE setup checklist

1. Log in as Lab Manager → Facility QC → Unit Registry
2. Generate a random API key (e.g. `python3 -c "import secrets; print(secrets.token_hex(32))"`) and paste it into the API Key field. Click Save.
3. For each sensor unit:
   - Add a new unit (type: Refrigerator / Freezer / Room Sensor)
   - Set the acceptance range (e.g. Fridge: 2–8 °C)
   - Set the **Sensor ID** to match the `[sensor.xxx]` section name in `/etc/pfas_sensor.conf`
4. Copy the same API key into `/etc/pfas_sensor.conf` on the Pi
5. Test a single POST manually:
   ```bash
   python3 /opt/pfas_sensor/sensor_reader.py
   ```
6. Check the Temperature Log in SENAITE — readings should appear within 15 minutes.

---

## Temperature study (quarterly NIST verification)

**Purpose:** Verify that the installed sensor reads within tolerance (default ±1.0°C)
of a NIST-traceable reference thermometer. Required at unit installation and every
quarter thereafter (or per your ISO 17025 programme).

**Procedure:**

1. Obtain a NIST-traceable reference thermometer (serial number and current cert
   date must be recorded). Do NOT use a consumer thermometer.
2. Place the reference probe at the same height and approximate location as the
   permanent sensor. For larger units, perform a spatial mapping study by
   recording reference readings at multiple locations within the unit.
3. Allow the unit to equilibrate for ≥30 minutes after placing the reference probe.
4. Record **5 paired readings** (sensor + reference) spaced ≥2 hours apart over
   the course of one working day (e.g. 08:00, 10:00, 12:00, 14:00, 16:00).
5. In SENAITE → Temperature Log → select the unit → New Temperature Study.
   Enter the NIST serial, cert date, and your tolerance (default 1.0°C).
6. Enter each time-point's sensor reading and reference reading. The system
   calculates deviation = sensor − reference and marks each point pass/fail.
7. The study passes if all 5 deviations are within the configured tolerance.
8. Print or export the completed study record for your ISO 17025 binder.

**Out-of-tolerance action:** If any point fails, investigate the sensor (check
wiring, recalibrate, or replace). Do not use the unit for critical sample storage
until a passing study is completed.
