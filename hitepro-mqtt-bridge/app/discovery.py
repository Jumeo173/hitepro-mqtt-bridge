"""Генерация MQTT Discovery конфигов для Home Assistant."""
import json
import logging

_LOGGER = logging.getLogger(__name__)

DEVICE_INFO = {
    "identifiers": ["hitepro_gateway"],
    "name": "",
    "manufacturer": "HiTE-PRO",
    "model": "HitePro Gateway",
}


def build_discovery(device: dict, base_topic: str, discovery_prefix: str):
    """
    Возвращает (topic, payload_str) для публикации discovery,
    либо None, если тип не поддержан.
    """
    control_id = device["control_id"]
    title = device["title"]
    dev_type = device["type"]

    state_topic = f"{base_topic}/state/{control_id}"
    command_topic = f"{base_topic}/cmd/{control_id}"
    unique_id = f"hitepro_{control_id}"

    payload = {
        "name": title,
        "unique_id": unique_id,
        "device": DEVICE_INFO,
        "availability_topic": f"{base_topic}/status",
        "payload_available": "online",
        "payload_not_available": "offline",
    }

    if dev_type == "switch":
        payload.update({
            "state_topic": state_topic,
            "command_topic": command_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
            "state_on": "ON",
            "state_off": "OFF",
            "optimistic": False,
        })
        topic = f"{discovery_prefix}/switch/{unique_id}/config"

    elif dev_type in ("pushbutton", "alarm"):
        payload.update({
            "state_topic": state_topic,
            "payload_on": "ON",
            "payload_off": "OFF",
        })
        if dev_type == "alarm":
            payload["device_class"] = "motion"
        if dev_type == "pushbutton":
            payload["device_class"] = "running"
        topic = f"{discovery_prefix}/binary_sensor/{unique_id}/config"

    elif dev_type == "text":
        payload.update({
            "state_topic": state_topic,
            "unit_of_measurement": "%",
            "value_template": "{{ value | replace('%', '') | float(0) }}",
        })
        topic = f"{discovery_prefix}/sensor/{unique_id}/config"

    elif dev_type == "cover":
        payload.update({
            "state_topic": state_topic,
            "command_topic": command_topic,
            "payload_open": "OPEN",
            "payload_close": "CLOSE",
            "payload_stop": "STOP",
            "state_open": "open",
            "state_opening": "opening",
            "state_closed": "closed",
            "state_closing": "closing",
            "state_stopped": "stopped",
            "device_class": "window",
        })
        topic = f"{discovery_prefix}/cover/{unique_id}/config"

    else:
        _LOGGER.debug("Пропускаем тип %s для %s", dev_type, control_id)
        return None

    return topic, json.dumps(payload, ensure_ascii=False)
