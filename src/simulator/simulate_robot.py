"""
================================================================================
simulate_robot.py — Simulador de hardware para el Brazo Robótico Pick & Place
================================================================================
Autor: Francisco Bevilacqua | Versión: 1.0.0

Responsabilidad única (SRP):
    Actuar como cliente MQTT que habla el MISMO protocolo que el firmware real
    (src/firmware/), sin depender de MicroPython ni de hardware físico. Permite
    validar el sistema completo (GUI → backend → broker → "brazo") sin un ESP32
    conectado — requisito de cátedra a partir de esta entrega.

[IMPORTANTE — FUENTE DE VERDAD DEL PROTOCOLO]
    Este script es una REIMPLEMENTACIÓN del contrato de mensajes documentado en
    la tabla de tópicos/eventos del README (sección "Comunicación bidireccional
    vía MQTT"), NO una copia del firmware MicroPython. Si el protocolo cambia
    (nuevo comando, nuevo evento, nuevo campo), hay que actualizar AMBOS lugares:
    este simulador y src/firmware/commands.py — no hay import compartido entre
    ambos porque MicroPython y CPython no son binariamente compatibles
    (umqtt.simple vs. paho-mqtt).

Modos de simulación de detección de caja (dos formas, para cubrir tanto una
corrida desatendida como una demo dirigida por el evaluador):
    - Automática: cada SIM_BOX_INTERVAL_S segundos (si es > 0).
    - Manual: presionar ENTER en la terminal donde corre el script (modo
      interactivo, ver _stdin_listener). En Docker, correr con `-it` y
      `docker attach` o usar el modo automático (más simple para CI).

Dependencias: paho-mqtt
================================================================================
"""

import json
import os
import random
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

# ------------------------------------------------------------------------
# Configuración — todo por variable de entorno, igual criterio que
# config.py del firmware real (nada de credenciales hardcodeadas acá).
# ------------------------------------------------------------------------
BROKER_HOST = os.environ.get("MQTT_BROKER", "mosquitto")
BROKER_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "esp32")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD")  # sin default: fail-fast si falta
TOPIC_CMD = "robot/cmd"
TOPIC_LOG = "robot/log"
CLIENT_ID = "SIMULATOR_ESP32_" + str(random.randint(1000, 9999))

# Intervalo de detección automática de caja, en segundos. 0 = deshabilitada
# (solo detección manual vía ENTER).
SIM_BOX_INTERVAL_S = int(os.environ.get("SIM_BOX_INTERVAL_S", "25"))

MAX_CAJAS_PALLET = 3

if not MQTT_PASSWORD:
    raise SystemExit(
        "[CRITICAL] Falta MQTT_PASSWORD en el entorno. "
        "Copiar src/simulator/.env.example a .env y completarlo."
    )


def log(msg: str, level: str = "INFO") -> None:
    """Log con el mismo formato que state.log() del firmware real, para que los
    logs del simulador se lean igual que la consola Thonny de un ESP32 real."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] [{level:<8s}] {msg}", flush=True)


class RobotState:
    """
    Espejo simplificado de state.SystemState (firmware real). Mantiene en
    memoria todo lo que publish_status() necesita reportar, para que el
    simulador responda de forma consistente a {"cmd":"status"}.
    """

    def __init__(self):
        self.mode = "MANUAL"
        self.arm_busy = False
        self.semi_pending = False
        self.pallet_count = {1: 0, 2: 0}
        self.pallet_full = {1: False, 2: False}
        self.servo_angle = {1: 90, 2: 90, 3: 90, 4: 90}
        self.cmd_received = 0
        self.last_cmd_id = None


state = RobotState()
client: mqtt.Client


def publish(payload: dict) -> None:
    """Publica un dict como JSON en robot/log — equivalente a mqtt_publish() del firmware."""
    body = json.dumps(payload)
    client.publish(TOPIC_LOG, body, qos=0)
    log(f"-> {body}", "DEBUG")


def publish_status() -> None:
    """Snapshot completo, mismo formato que commands.publish_status() del firmware."""
    publish({
        "event": "status",
        "mode": state.mode,
        "arm_busy": state.arm_busy,
        "semi_pending": state.semi_pending,
        "pallets": {
            "1": {"count": state.pallet_count[1], "full": state.pallet_full[1]},
            "2": {"count": state.pallet_count[2], "full": state.pallet_full[2]},
        },
        "servos": dict(state.servo_angle),
        "sensor": False,
        "mem_free": 45000,          # valor fijo plausible: no hay heap real que reportar
        "loop_count": 0,
        "cmd_received": state.cmd_received,
        "reconnects": 1,
        "wifi_rssi": -50,           # valor fijo plausible: no hay radio WiFi real
        "reset_cause": 1,           # PWRON_RESET — el simulador "arranca en frío" siempre
    })


def _simulate_move(action: str) -> None:
    """Simula una secuencia de movimiento preconfigurado con sleeps cortos en
    vez de mover servos reales. Publica move_start/move_done igual que el
    firmware, para que la GUI reciba el mismo feedback visual."""
    state.arm_busy = True
    publish({"event": "move_start", "action": action})
    time.sleep(0.8)  # simula el tiempo real de movimiento del brazo
    if action == "abrir_pinza":
        state.servo_angle[4] = 90
    elif action == "cerrar_pinza":
        state.servo_angle[4] = 0
    elif action == "home":
        state.servo_angle = {1: 90, 2: 90, 3: 90, 4: 90}
    publish({"event": "move_done", "action": action})
    state.arm_busy = False


def _simulate_pick_and_place(dest_pallet: int) -> bool:
    """Simula el ciclo completo de pick & place — mismo contrato de eventos
    que servos.pick_and_place() del firmware, sin movimiento físico real."""
    if state.pallet_full[dest_pallet]:
        publish({"event": "pallet_full", "pallet": dest_pallet})
        return False

    state.arm_busy = True
    level = state.pallet_count[dest_pallet] + 1
    publish({"event": "pick_start", "dest": f"P{dest_pallet}", "level": level})
    time.sleep(1.5)  # simula el ciclo completo de movimiento (~lo mismo que el brazo real)

    state.pallet_count[dest_pallet] += 1
    if state.pallet_count[dest_pallet] >= MAX_CAJAS_PALLET:
        state.pallet_full[dest_pallet] = True
        publish({"event": "pallet_full", "pallet": dest_pallet})

    publish({
        "event": "box_collected",
        "dest": f"P{dest_pallet}",
        "level": level,
        "count": state.pallet_count[dest_pallet],
        "full": state.pallet_full[dest_pallet],
    })
    state.arm_busy = False
    return True


def _trigger_box_detected() -> None:
    """Simula que el sensor KY-032 confirmó una detección (equivalente a
    sensor.poll_debounced() retornando True tras el debounce)."""
    if state.arm_busy:
        log("Deteccion simulada ignorada: brazo ocupado", "WARNING")
        return

    log("Sensor SIMULADO: caja detectada (confirmado)", "INFO")
    publish({"event": "sensor", "detected": True})

    if state.mode == "SEMI_AUTO":
        if not state.semi_pending:
            state.semi_pending = True
            publish({"event": "box_detected"})
    elif state.mode == "AUTOMATICO":
        dest = 1 if not state.pallet_full[1] else (2 if not state.pallet_full[2] else None)
        if dest is None:
            publish({"event": "all_pallets_full"})
            return
        _simulate_pick_and_place(dest)
    # En MANUAL: se publica el evento "sensor" igual (telemetría), sin disparar acción.


def on_message(_client, _userdata, msg) -> None:
    """Dispatcher de comandos entrantes — mismo contrato que commands.on_message()."""
    state.cmd_received += 1
    try:
        data = json.loads(msg.payload.decode())
    except Exception:
        log(f"JSON invalido: {msg.payload!r}", "ERROR")
        return

    log(f"<- CMD: {data}", "INFO")

    # Deduplicación por msg_id — mismo criterio que el firmware real.
    incoming_id = data.get("msg_id")
    if incoming_id is not None:
        if incoming_id == state.last_cmd_id:
            log(f"CMD duplicado ignorado (msg_id={incoming_id})", "WARNING")
            return
        state.last_cmd_id = incoming_id

    cmd = data.get("cmd", "")

    if cmd == "set_mode":
        new_mode = data.get("mode", "MANUAL").upper()
        if new_mode in ("MANUAL", "SEMI_AUTO", "AUTOMATICO"):
            state.mode = new_mode
            publish({"event": "mode_changed", "mode": state.mode})
        else:
            log(f"Modo desconocido: {new_mode}", "WARNING")

    elif cmd == "servo":
        if state.arm_busy:
            log("Brazo ocupado, comando ignorado", "WARNING")
            return
        sid, angle = int(data.get("id", 1)), int(data.get("angle", 90))
        if 1 <= sid <= 4:
            state.servo_angle[sid] = max(0, min(180, angle))
            publish({"event": "servo_ack", "id": sid, "angle": state.servo_angle[sid]})

    elif cmd == "move":
        if state.arm_busy:
            log("Brazo ocupado, comando ignorado", "WARNING")
            return
        threading.Thread(target=_simulate_move, args=(data.get("action", "home"),), daemon=True).start()

    elif cmd == "semi_decision":
        if not state.semi_pending:
            log("No hay caja pendiente para decision", "WARNING")
            return
        dest = data.get("dest", "ignorar")
        state.semi_pending = False
        if dest == "P1":
            threading.Thread(target=_simulate_pick_and_place, args=(1,), daemon=True).start()
        elif dest == "P2":
            threading.Thread(target=_simulate_pick_and_place, args=(2,), daemon=True).start()
        else:
            publish({"event": "box_ignored"})

    elif cmd == "pallet_clear":
        pid = int(data.get("pallet", 1))
        if pid in (1, 2):
            state.pallet_count[pid] = 0
            state.pallet_full[pid] = False
            publish({"event": "pallet_cleared", "pallet": pid})

    elif cmd == "status":
        publish_status()

    else:
        log(f"Comando desconocido: '{cmd}'", "WARNING")


def on_connect(client_: mqtt.Client, _userdata, _flags, reason_code, _props=None) -> None:
    if reason_code == 0:
        log(f"Conectado a {BROKER_HOST}:{BROKER_PORT} como '{MQTT_USER}'", "INFO")
        client_.subscribe(TOPIC_CMD, qos=1)
        publish({"event": "online", "reset_cause": 1, "mem_free": 45000, "reconnects": 1, "mode": state.mode})
        time.sleep(0.5)
        publish_status()
    else:
        log(f"Fallo de conexion MQTT, reason_code={reason_code}", "ERROR")


def _box_timer_loop() -> None:
    """Hilo de detección automática de caja (si SIM_BOX_INTERVAL_S > 0)."""
    if SIM_BOX_INTERVAL_S <= 0:
        return
    log(f"Deteccion automatica de caja cada {SIM_BOX_INTERVAL_S}s", "INFO")
    while True:
        time.sleep(SIM_BOX_INTERVAL_S)
        _trigger_box_detected()


def _stdin_listener() -> None:
    """Hilo de detección manual: ENTER en la terminal fuerza una detección
    de caja inmediata, sin esperar el timer — útil para pruebas dirigidas
    durante una corrección o demo en vivo."""
    log("Presiona ENTER en cualquier momento para simular una caja detectada.", "INFO")
    while True:
        try:
            input()
        except EOFError:
            return  # stdin no interactivo (ej. corriendo con -d en Docker) — se ignora
        _trigger_box_detected()


def main() -> None:
    global client
    log("=" * 70)
    log("SIMULADOR DE BRAZO ROBOTICO PICK & PLACE — sin hardware fisico")
    log(f"Broker: {BROKER_HOST}:{BROKER_PORT} | Usuario MQTT: {MQTT_USER}")
    log("=" * 70)

    client = mqtt.Client(client_id=CLIENT_ID, callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    threading.Thread(target=_box_timer_loop, daemon=True).start()
    threading.Thread(target=_stdin_listener, daemon=True).start()

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        publish({"event": "offline"})
        log("Simulador detenido (Ctrl+C).", "INFO")


if __name__ == "__main__":
    main()
