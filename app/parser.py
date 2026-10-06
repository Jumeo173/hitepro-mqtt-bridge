"""Парсинг hite-pro.js (defineVirtualDevice) в структурированный список устройств."""
import json
import re
import logging

_LOGGER = logging.getLogger(__name__)


def _strip_escapes(text: str) -> str:
    """
    Чистит title от артефактов HitePro:
      ' \/ баня окно'      -> 'баня окно'
      ' / кухня свет'       -> 'кухня свет'
      'Дом \/ котельная'   -> 'Дом / котельная'
      'баня окно'           -> 'баня окно'
    """
    if not text:
        return text

    text = text.replace("\\/", "/")
    text = re.sub(r"^\s*/+\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text


def parse_hite_pro_js(content: str) -> list:
    """
    Принимает содержимое hite-pro.js вида:
        defineVirtualDevice('hite-pro', {"title":"HiTE PRO","cells":{ ... }})
    Возвращает список словарей:
        {control_id, title, type, readonly, initial_value, is_cover, cover_base_id}
    """
    match = re.search(
        r"defineVirtualDevice\s*\(\s*['\"][^'\"]+['\"]\s*,\s*(\{.*\})\s*\)\s*;?\s*$",
        content, re.DOTALL,
    )
    if not match:
        raise ValueError("Не удалось найти defineVirtualDevice в файле")

    data = json.loads(match.group(1))
    cells = data.get("cells", {})

    devices = []
    covers = {}

    for control_id, cell in cells.items():
        if control_id == "Reload":
            continue

        title = _strip_escapes(cell.get("title", control_id))
        dev_type = cell.get("type", "text")
        readonly = bool(cell.get("readonly", False))
        initial_value = cell.get("value", None)

        is_cover = False
        cover_base_id = None
        cover_direction = None
        if control_id.startswith("Relay-Drive_"):
            if control_id.endswith("_open"):
                cover_base_id = control_id[: -len("_open")]
                cover_direction = "open"
                is_cover = True
            elif control_id.endswith("_close"):
                cover_base_id = control_id[: -len("_close")]
                cover_direction = "close"
                is_cover = True

        device = {
            "control_id": control_id,
            "title": title,
            "type": dev_type,
            "readonly": readonly,
            "initial_value": initial_value,
            "is_cover": is_cover,
            "cover_base_id": cover_base_id,
        }
        devices.append(device)

        if is_cover:
            covers.setdefault(cover_base_id, {})[cover_direction] = device

    cover_entities = []
    for base_id, parts in covers.items():
        if "open" in parts and "close" in parts:
            cover_entities.append({
                "control_id": base_id,
                "title": parts["open"]["title"],
                "type": "cover",
                "readonly": False,
                "initial_value": None,
                "open_id": parts["open"]["control_id"],
                "close_id": parts["close"]["control_id"],
                "is_cover": True,
                "cover_base_id": base_id,
            })
        else:
            _LOGGER.warning(
                "Штора %s имеет только один топик (%s), пропускаем",
                base_id, list(parts.keys()),
            )

    plain_devices = [d for d in devices if not d["is_cover"]]

    return plain_devices + cover_entities
