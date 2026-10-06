"""Веб-GUI для настройки аддона (Ingress)."""
import json
import logging
import threading

import requests
from flask import Flask, request, jsonify, render_template_string
from waitress import serve

from cache import load_names, save_names, load_state
from parser import parse_hite_pro_js

_LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
import os
os.environ["FLASK_ENV"] = "production"

CONFIG = {}
ON_RELOAD = None

PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>HitePro MQTT Bridge</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 20px; background: #f5f5f5; }
h1 { color: #333; }
table { border-collapse: collapse; width: 100%; background: #fff; margin-top: 20px; }
th, td { padding: 8px 12px; border-bottom: 1px solid #eee; text-align: left; font-size: 14px; }
th { background: #fafafa; font-weight: 600; }
input[type=text] { width: 100%; padding: 4px 8px; border: 1px solid #ccc; border-radius: 4px; }
button { padding: 10px 20px; background: #03a9f4; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }
button:hover { background: #0288d1; }
.status { padding: 10px; margin: 10px 0; border-radius: 4px; }
.status.ok { background: #e8f5e9; color: #2e7d32; }
.status.err { background: #ffebee; color: #c62828; }
.url-input { width: 100%; padding: 8px; font-size: 14px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
.row { margin: 10px 0; }
label { display: block; font-weight: 600; margin-bottom: 4px; font-size: 13px; color: #666; }
</style>
</head>
<body>
<h1>HitePro MQTT Bridge</h1>
<div class="row">
  <label>URL до hite-pro.js</label>
  <input type="text" id="url" class="url-input" value="{{ url }}">
</div>
<div class="row">
  <button onclick="checkConnection()">Проверить соединение</button>
  <button onclick="loadDevices()">Загрузить устройства</button>
</div>
<div id="status"></div>
<div id="devices"></div>
<script>
const statusEl = document.getElementById('status');
const devicesEl = document.getElementById('devices');
const BASE = window.location.pathname.replace(/\/$/, '');

function showStatus(msg, ok) {
  statusEl.innerHTML = '<div class="status ' + (ok ? 'ok' : 'err') + '">' + msg + '</div>';
}

async function checkConnection() {
  const url = document.getElementById('url').value;
  showStatus('Проверка...', true);
  const r = await fetch(BASE + '/api/check', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url})});
  const d = await r.json();
  if (d.ok) showStatus('Соединение OK. Найдено устройств: ' + d.count, true);
  else showStatus('Ошибка: ' + d.error, false);
}

async function loadDevices() {
  const url = document.getElementById('url').value;
  showStatus('Загрузка...', true);
  const r = await fetch(BASE + '/api/devices', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({url})});
  const d = await r.json();
  if (!d.ok) { showStatus(d.error, false); return; }
  showStatus('Загружено устройств: ' + d.devices.length, true);
  renderDevices(d.devices);
}

function renderDevices(devices) {
  let html = '<table><thead><tr><th>Control ID</th><th>Оригинальное имя</th><th>Новое имя</th><th>Тип</th></tr></thead><tbody>';
  for (const d of devices) {
    html += '<tr>' +
      '<td><code>' + d.control_id + '</code></td>' +
      '<td>' + d.title + '</td>' +
      '<td><input type="text" data-id="' + d.control_id + '" value="' + (d.custom_name || '') + '" placeholder="' + d.title + '"></td>' +
      '<td>' + d.type + '</td>' +
      '</tr>';
  }
  html += '</tbody></table>';
  html += '<div class="row" style="margin-top:20px;"><button onclick="saveNames()">Сохранить и применить</button></div>';
  devicesEl.innerHTML = html;
}

async function saveNames() {
  const inputs = devicesEl.querySelectorAll('input[type=text]');
  const names = {};
  inputs.forEach(i => { if (i.value.trim()) names[i.dataset.id] = i.value.trim(); });
  const r = await fetch(BASE + '/api/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({names})});
  const d = await r.json();
  if (d.ok) showStatus('Сохранено. Discovery перепубликуется.', true);
  else showStatus(d.error, false);
}
</script>
</body>
</html>
"""


def start_web(config: dict, on_reload=None):
    global CONFIG, ON_RELOAD
    CONFIG = config
    ON_RELOAD = on_reload

    @app.route("/")
    def index():
        return render_template_string(PAGE, url=CONFIG.get("hitepro_json_url", ""))

    @app.route("/api/check", methods=["POST"])
    def api_check():
        url = request.json.get("url", "")
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            devices = parse_hite_pro_js(r.text)
            return jsonify({"ok": True, "count": len(devices)})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/devices", methods=["POST"])
    def api_devices():
        url = request.json.get("url", "")
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            devices = parse_hite_pro_js(r.text)
            names = load_names()
            for d in devices:
                d["custom_name"] = names.get(d["control_id"], "")
            return jsonify({"ok": True, "devices": devices})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/save", methods=["POST"])
    def api_save():
        names = request.json.get("names", {})
        try:
            save_names(names)
            if ON_RELOAD:
                threading.Thread(target=ON_RELOAD, daemon=True).start()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    @app.route("/api/state")
    def api_state():
        return jsonify(load_state())

    def run():
        _LOGGER.info("Веб-GUI запущен на порту 8099")
        serve(app, host="0.0.0.0", port=8099, _quiet=True)

    threading.Thread(target=run, daemon=True).start()
