# HitePro MQTT Bridge — Контекст для LLM

## Проект
Home Assistant addon (Hassio), мост между MQTT-брокером HitePro и Home Assistant.
Управляет шторами (cover) и другими устройствами через MQTT.

## Архитектура
- `app/main.py` — основная логика, MQTT-клиент
- `app/parser.py` — парсинг JS-конфига HitePro
- `app/translator.py` — перевод команд между HA и HitePro
- `app/discovery.py` — MQTT discovery для HA
- `app/cache.py` — сохранение/загрузка состояния
- `app/web.py` — веб-интерфейс
- `config.yaml` — конфигурация addon (версия тут)

## Ключевые глобальные переменные (main.py)
- `STATE: dict` — текущие значения реле HitePro (control_id -> "0"/"1")
- `COVER_DIRECTIONS: dict` — направление шторы: "opening" | "closing" | "stopped"
- `COVER_TIMERS: dict` — таймеры на 180с для auto-open/close
- `COVER_CMD_LOCK: dict` — timestamp отправки команды (3с lock)

## Ключевые функции (main.py)
- `on_message()` (~line 219) — обработка входящих MQTT от HitePro и HA
- `on_ha_command()` — обработка команд от HA (OPEN/CLOSE/STOP)
- `start_cover_timer()` — запуск 180с таймера -> open/closed
- `start_stop_timer()` — запуск 3с таймера -> restored direction
- `publish_cover_state()` — публикация state в HA + обновление COVER_DIRECTIONS

## Проблема HitePro
HitePro — аппаратный контроллер штор. После получения команды (OPEN/CLOSE/STOP)
он возвращает по MQTT stale-эхо — старые значения реле, которые могут прийти
через 1-5 секунд ДВУМЯ волнами (через ~1с и через ~4с).
Это эхо НЕ отражает реальное состояние, но мост раньше принимал
его за реальные статусы и переключал направление шторы.

## Что сделано (v1.2.3) — 4 слоя защиты

### 1. STOP guard — игнорировать STOP на неподвижной шторе

```python
elif cmd == "STOP":
    cur_dir = COVER_DIRECTIONS.get(control_id, "stopped")
    if cur_dir in ("opening", "closing"):
        COVER_CMD_LOCK[control_id] = time.time()
        start_stop_timer(client, control_id)
    else:
        _LOGGER.info("Cover %s: STOP ignored (not moving, state=%s)", control_id, cur_dir)
        return  # НЕ отправлять в HitePro
```

### 2. Command lock — 3с игнорировать входящие статусы HitePro после любой команды
Ловит первую волну stale-эха (~1-2с после команды).

```python
lock_time = COVER_CMD_LOCK.get(device["control_id"], 0)
if time.time() - lock_time < 3.0:
    _LOGGER.info("Cover %s: ignoring HitePro status (command lock, %.1fs)", device["control_id"], time.time() - lock_time)
    return
```

### 3. Direction filter — игнорировать stale по направлению
Ловит вторую волну stale-эха (~4-5с после команды), когда lock уже истёк.
Плюс восстанавливает STATE до ожидаемых значений.

```python
if o == "1" and c == "0":
    if current_dir == "closing":
        # stale OPEN echo от предыдущего OPEN — игнорировать
        _LOGGER.info("Cover %s: ignoring stale OPEN echo (direction=%s)", device["control_id"], current_dir)
        STATE[device["open_id"]] = "0"
        STATE[device["close_id"]] = "1"
        save_state(STATE)
    elif current_dir != "opening":
        publish_cover_state(client, device["control_id"], "opening")
        start_cover_timer(client, device["control_id"], "opening")
elif o == "0" and c == "1":
    if current_dir == "opening":
        # stale CLOSE echo от предыдущего CLOSE — игнорировать
        _LOGGER.info("Cover %s: ignoring stale CLOSE echo (direction=%s)", device["control_id"], current_dir)
        STATE[device["open_id"]] = "1"
        STATE[device["close_id"]] = "0"
        save_state(STATE)
    elif current_dir != "closing":
        publish_cover_state(client, device["control_id"], "closing")
        start_cover_timer(client, device["control_id"], "closing")
```

### 4. Stop only on active timer
`o=0, c=0` без активного таймера движения — просто эхо реле, не триггерит STOP.

```python
elif o == "0" and c == "0":
    if device["control_id"] in COVER_TIMERS:
        start_stop_timer(client, device["control_id"])
```

### 5. STATE обновляется только после lock (stale не попадает в STATE)
STATE = payload выполняется ПОСЛЕ проверок lock и direction.
Stale-значения не записываются в STATE и не портят картину.

### 6. Оптимистичное обновление STATE при отправке команды
После CLOSE: STATE сразу open=0, close=1. Даже если HitePro ещё не ответил.

```python
for suffix, val in actions:
    if device["type"] == "cover":
        target = f"{prefix}/{suffix}/on"
        STATE[suffix] = str(val)  # сразу пишем ожидаемое значение
```

## Логика stop timer
1. STOP на движущейся шторе -> direction = "stopped" -> 3с таймер
2. В течение 3с все статусы HitePro игнорируются ("during stop")
3. Через 3с -> restored direction (opening/closing) -> state = open/closed
4. Если stop timer истёк и direction = "closing" -> stale close=1 игнорируется

## Протестированные сценарии (всё работает)
1. OPEN -> 5с -> STOP -> stopped -> 3с -> open OK
2. CLOSE -> 5с -> STOP -> stopped -> 3с -> open (direction=closing) OK
3. CLOSE до конца (180с) -> closed OK
4. STOP на closed/open/stopped -> ignored OK
5. CLOSE -> stale open=1 (lock) -> stale open=1 (dir filter) -> real close=1 OK
6. Двойной STOP подряд -> второй ignored OK

## Возможные доработки
- Если HitePro меняет состояние реле позже 5с (обе волны прошли),
  а STATE уже оптимистично обновлён — может быть рассинхрон.
  Решение: после истечения lock принимать только те статусы, которые
  совпадают с ожидаемым направлением.
- Если пользователь нажимает OPEN/CLOSE очень быстро (быстрее 3с),
  lock продлевается, но direction может не успеть обновиться.
- Cover timer (180с) может истечь во время stop — проверить поведение.

## Версии
- v1.1.8 — STOP guard (ignore STOP on idle)
- v1.1.9 — early return on ignored STOP
- v1.2.0 — 3s command lock
- v1.2.1 — STATE after lock + optimistic STATE on send
- v1.2.2 — direction filter + STATE revert for stale echo
- v1.2.3 — stop only triggers when cover timer active

## Текущая версия: 1.2.3
