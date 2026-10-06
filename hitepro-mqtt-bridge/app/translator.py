"""Трансляция payload между HitePro и HA."""
import logging

_LOGGER = logging.getLogger(__name__)


def to_ha(device: dict, payload: str) -> str:
    """HitePro -> HA. Возвращает payload для hitepro/state/<id>."""
    payload = str(payload).strip()
    dev_type = device.get("type")

    if dev_type == "switch":
        return "ON" if payload == "1" else "OFF"

    if dev_type in ("pushbutton", "alarm"):
        return "ON" if payload in ("1", "true", "True") else "OFF"

    return payload


def to_hitepro(device: dict, payload: str):
    """
    HA -> HitePro.
    Возвращает список (topic_suffix, payload) для публикации.
    topic_suffix добавляется к /devices/hite-pro/controls/<id>
    """
    payload = str(payload).strip().upper()
    dev_type = device.get("type")

    if dev_type == "switch":
        value = "1" if payload == "ON" else "0"
        return [("", value)]

    if dev_type == "cover":
        open_id = device["open_id"]
        close_id = device["close_id"]
        if payload == "OPEN":
            return [(open_id, "1"), (close_id, "0")]
        if payload == "CLOSE":
            return [(open_id, "0"), (close_id, "1")]
        if payload == "STOP":
            return [(open_id, "0"), (close_id, "0")]

    _LOGGER.warning("Неизвестная команда %s для типа %s", payload, dev_type)
    return []


def cover_state_from_parts(open_val: str, close_val: str) -> str:
    """Определяет состояние cover по двум топикам."""
    o = str(open_val).strip()
    c = str(close_val).strip()
    if o == "1" and c == "0":
        return "open"
    if o == "0" and c == "1":
        return "closed"
    if o == "0" and c == "0":
        return "stopped"
    return "unknown"


def cover_state_from_parts(open_val: str, close_val: str) -> str:
    """Определяет состояние cover по двум топикам реле."""
    o = str(open_val).strip()
    c = str(close_val).strip()
    if o == "1" and c == "0":
        return "opening"
    if o == "0" and c == "1":
        return "closing"
    return "stopped"


def cover_state_on_startup(open_val: str, close_val: str) -> str:
    """Начальное состояние при старте моста.

    HitePro не обнуляет реле после остановки, поэтому если реле
    держит 1 — предполагаем, что движение уже завершилось.
    """
    o = str(open_val).strip()
    c = str(close_val).strip()
    if o == "1" and c == "0":
        return "open"
    if o == "0" and c == "1":
        return "closed"
    return "stopped"
