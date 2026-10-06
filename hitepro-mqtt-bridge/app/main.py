"""Точка входа аддона HitePro MQTT Bridge."""
import json
import logging
import os
import sys
import threading

import paho.mqtt.client as mqtt
import requests

from parser import parse_hite_pro_js
from translator import to_ha, to_hitepro, cover_state_from_parts
from discovery import build_discovery
from cache import (
    load_state, save_state,
    load_names,
    load_published, save_published,
)
from web import start_web

LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger("main")


def load_options() -> dict:
    options_path = "/data/options.json"
    if os.path.exists(options_path):
        with open(options_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "hitepro_json_url": os.environ.get("HITEPRO_JSON_URL", ""),
        "mqtt_host": os.environ.get("MQTT_HOST", "localhost"),
        "mqtt_port": int(os.environ.get("MQTT_PORT", "1883")),
        "mqtt_user": os.environ.get("MQTT_USER", ""),
        "mqtt_password": os.environ.get("MQTT_PASSWORD", ""),
        "base_topic": os.environ.get("BASE_TOPIC", "hitepro"),
        "discovery_prefix": os.environ.get("DISCOVERY_PREFIX", "homeassistant"),
        "hitepro_device_prefix": os.environ.get(
            "HITEPRO_DEVICE_PREFIX", "/devices/hite-pro/controls"
        ),
        "log_level": os.environ.get("LOG_LEVEL", "info"),
    }


CONFIG = load_options()
DEVICES: dict = {}
STATE: dict = load_state()
NAMES: dict = load_names()
PUBLISHED: dict = load_published()
MQTT_CLIENT = None


def fetch_devices() -> list:
    url = CONFIG["hitepro_json_url"]
    if not url:
        _LOGGER.error("URL до hite-pro.js не задан")
        return []
    _LOGGER.info("Скачиваем %s", url)
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return parse_hite_pro_js(r.text)
    except Exception as e:
        _LOGGER.error("Не удалось загрузить/распарсить hite-pro.js: %s", e)
        return []


def apply_names(devices: list) -> list:
    for d in devices:
        custom = NAMES.get(d["control_id"])
        if custom:
            d["title"] = custom
    return devices


def publish_discovery(client: mqtt.Client):
    current_ids = set()
    for d in DEVICES.values():
        result = build_discovery(
            d,
            base_topic=CONFIG["base_topic"],
            discovery_prefix=CONFIG["discovery_prefix"],
        )
        if not result:
            continue
        topic, payload = result
        client.publish(topic, payload, retain=True)
        PUBLISHED[d["control_id"]] = topic
        current_ids.add(d["control_id"])
        _LOGGER.info("Discovery: %s", topic)

    for control_id, topic in list(PUBLISHED.items()):
        if control_id not in current_ids:
            client.publish(topic, "", retain=True)
            _LOGGER.info("Удалено discovery: %s", topic)
            del PUBLISHED[control_id]

    save_published(PUBLISHED)


def publish_initial_states(client: mqtt.Client):
    for d in DEVICES.values():
        control_id = d["control_id"]
        if d["type"] == "cover":
            open_id = d["open_id"]
            close_id = d["close_id"]
            open_val = STATE.get(open_id, "0")
            close_val = STATE.get(close_id, "0")
            state = cover_state_from_parts(open_val, close_val)
            client.publish(
                f"{CONFIG['base_topic']}/state/{control_id}",
                state, retain=True,
            )
            continue

        if control_id in STATE:
            val = STATE[control_id]
        elif d.get("initial_value") is not None:
            val = d["initial_value"]
            STATE[control_id] = val
        else:
            continue

        ha_val = to_ha(d, str(val))
        client.publish(
            f"{CONFIG['base_topic']}/state/{control_id}",
            ha_val, retain=True,
        )

    save_state(STATE)


def on_connect(client, userdata, flags, reason_code, properties=None):
    _LOGGER.info("MQTT подключён, rc=%s", reason_code)
    client.subscribe(f"{CONFIG['hitepro_device_prefix']}/#")
    client.subscribe(f"{CONFIG['base_topic']}/cmd/#")
    client.publish(f"{CONFIG['base_topic']}/status", "online", retain=True)

    threading.Thread(
        target=lambda: (publish_discovery(client),
                        publish_initial_states(client)),
        daemon=True,
    ).start()


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = msg.payload.decode("utf-8", errors="replace")
    except Exception:
        return

    prefix = CONFIG["hitepro_device_prefix"]
    base = CONFIG["base_topic"]

    if topic.startswith(prefix + "/"):
        rest = topic[len(prefix) + 1:]
        if rest.endswith("/on"):
            return
        control_id = rest

        device = DEVICES.get(control_id)
        if device is None:
            for d in DEVICES.values():
                if d["type"] == "cover" and control_id in (d["open_id"], d["close_id"]):
                    device = d
                    break
        if device is None:
            return

        STATE[control_id] = payload

        if device["type"] == "cover":
            open_val = STATE.get(device["open_id"], "0")
            close_val = STATE.get(device["close_id"], "0")
            ha_state = cover_state_from_parts(open_val, close_val)
            client.publish(
                f"{base}/state/{device['control_id']}",
                ha_state, retain=True,
            )
        else:
            ha_val = to_ha(device, payload)
            client.publish(
                f"{base}/state/{control_id}",
                ha_val, retain=True,
            )
        save_state(STATE)
        return

    if topic.startswith(base + "/cmd/"):
        control_id = topic[len(base) + 5:]
        device = DEVICES.get(control_id)
        if device is None:
            _LOGGER.warning("Команда для неизвестного устройства: %s", control_id)
            return

        actions = to_hitepro(device, payload)
        for suffix, val in actions:
            if device["type"] == "cover":
                target = f"{prefix}/{suffix}/on"
            else:
                target = f"{prefix}/{control_id}/on"
            client.publish(target, val)
            _LOGGER.info("-> HitePro: %s = %s", target, val)
        return


def reload_devices(client: mqtt.Client):
    global DEVICES
    devices = apply_names(fetch_devices())
    DEVICES = {d["control_id"]: d for d in devices}
    _LOGGER.info("Загружено устройств: %d", len(DEVICES))
    publish_discovery(client)
    publish_initial_states(client)


def main():
    global MQTT_CLIENT

    _LOGGER.info("Запуск HitePro MQTT Bridge")

    devices = apply_names(fetch_devices())
    DEVICES.update({d["control_id"]: d for d in devices})
    _LOGGER.info("Загружено устройств: %d", len(DEVICES))

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="hitepro_bridge",
        protocol=mqtt.MQTTv311,
    )
    if CONFIG.get("mqtt_user"):
        client.username_pw_set(CONFIG["mqtt_user"], CONFIG.get("mqtt_password", ""))

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(CONFIG["mqtt_host"], CONFIG["mqtt_port"], keepalive=60)
    MQTT_CLIENT = client

    start_web(CONFIG, on_reload=lambda: reload_devices(client))

    client.loop_forever()


if __name__ == "__main__":
    main()
