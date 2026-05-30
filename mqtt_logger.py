"""
mqtt_logger.py
Subscribes to HiveMQ Cloud (TLS) topic hive/esp32 and inserts every reading into Supabase.
Runs as a background service — data is logged even when Streamlit is closed.

  python mqtt_logger.py
"""

import json
import logging
import os
import ssl
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

MQTT_HOST  = os.environ["MQTT_HOST"]
MQTT_PORT  = int(os.environ.get("MQTT_PORT", 8883))
MQTT_USER  = os.environ["MQTT_USER"]
MQTT_PASS  = os.environ["MQTT_PASS"]
MQTT_TOPIC = os.environ.get("MQTT_TOPIC", "hive/esp32")

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("MQTT connected — subscribing to %s", MQTT_TOPIC)
        client.subscribe(MQTT_TOPIC, qos=1)
    else:
        log.error("MQTT connect failed rc=%d", rc)

def on_disconnect(client, userdata, rc):
    log.warning("MQTT disconnected rc=%d — will auto-reconnect", rc)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except json.JSONDecodeError as e:
        log.error("Bad JSON: %s", e)
        return

    row = {
        "created_at":    datetime.now(timezone.utc).isoformat(),
        "switch_status": data.get("switch_status"),
        "alarm":         data.get("alarm"),
        "trip":          data.get("trip"),
        "rated_current": data.get("rated_current"),
        "current":       _f(data.get("current")),
        "voltage":       _f(data.get("voltage")),
        "temperature":   data.get("temperature"),
        "power":         _f(data.get("power")),
        "energy":        _f(data.get("energy")),
        "frequency":     _f(data.get("frequency")),
        "power_factor":  _f(data.get("power_factor")),
    }

    try:
        supabase.table("mcb_readings").insert(row).execute()
        log.info("Saved  %.2fA  %.1fV  %.1fW  %.2fHz  %d°C  sw=%s",
                 row["current"] or 0, row["voltage"] or 0,
                 row["power"] or 0,   row["frequency"] or 0,
                 row["temperature"] or 0,
                 "CLOSED" if row["switch_status"] == 1 else "OPEN")
    except Exception as e:
        log.error("Supabase insert failed: %s", e)

def _f(val):
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

def main():
    client = mqtt.Client(
        client_id=f"py-hongfa-logger-{int(time.time())}",
        clean_session=True,
    )
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set(cert_reqs=ssl.CERT_NONE)          # HiveMQ Cloud TLS
    client.tls_insecure_set(True)

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    log.info("Logger running  broker=%s:%d  topic=%s", MQTT_HOST, MQTT_PORT, MQTT_TOPIC)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        log.info("Logger stopped.")

if __name__ == "__main__":
    main()
