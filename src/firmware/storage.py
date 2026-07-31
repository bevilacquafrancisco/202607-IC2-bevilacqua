"""
================================================================================
storage.py — Persistencia de estado crítico en flash (filesystem interno)
================================================================================
Autor: Francisco Bevilacqua | Versión: 5.1

Responsabilidad única (SRP):
    Este módulo es el ÚNICO lugar del firmware que sabe leer/escribir el
    sistema de archivos interno del ESP32. Serializa y restaura el
    SUBCONJUNTO de `state` que debe sobrevivir a un reinicio o corte de
    energía: modo de operación, contadores de pallets, y el último ángulo
    conocido de cada servo.

QUÉ SE PERSISTE Y QUÉ NO (y por qué):
    - mode, pallet_count, pallet_full: es el requisito explícito — sin
      esto, un reset deja los pallets en 0 aunque físicamente sigan llenos,
      desincronizando el conteo de la GUI respecto a la realidad.
    - servo_angle: Es la pieza que
      permite resolver correctamente el homing suave al arranque (ver
      servos.init_servos()). Un SG90 no tiene encoder — el firmware no
      tiene forma de conocer la posición física real salvo por lo último
      que ÉL MISMO comandó. Sin persistir esto, "home suave" al arrancar
      no tendría un punto de partida real desde el cual barrer, y asumir
      90° por defecto es una suposición falsa la mayoría de las veces
      (ver docstring de servos.pick_and_place, paso 9: el ciclo normal
      termina con la base en 180°, no en home).
    - NO se persisten: contadores de diagnóstico (loop_count, cmd_received,
      reconnect_count — son telemetría de sesión, no estado de negocio) ni
      credenciales/config (viven en config.py, no cambian en runtime).

POR QUÉ ESCRITURA DIFERIDA (dirty flag) EN VEZ DE SÍNCRONA:
    Si cada cambio de estado escribiera a flash de inmediato, dos
    problemas: (1) desgaste de flash sin necesidad — un slider de servo
    en modo MANUAL puede generar varios eventos por segundo; (2) latencia
    de I/O metida en el medio de una secuencia de movimiento suave
    (move_sequence/pick_and_place llaman a mark_dirty() al final de cada
    acción, no en cada paso — pero igual conviene no escribir sincrónico).
    En cambio, los callers solo llaman a mark_dirty() (una asignación de
    booleano, costo despreciable) y main.py flushea a flash cada
    TIMING["persist_ms"] SOLO si hay cambios pendientes — mismo patrón ya
    usado en el proyecto para heartbeat y garbage collection periódicos.

ESCRITURA ATÓMICA:
    save_state() escribe a un archivo temporal y recién después lo
    renombra sobre el archivo final. Si el ESP32 pierde alimentación a
    mitad de la escritura, el archivo previo queda intacto (en el peor
    caso se pierde la última actualización, nunca se corrompe el archivo
    completo con un JSON a medio escribir).

FAIL-SAFE, NO FAIL-FAST:
    A diferencia de config.py del backend (donde un secreto faltante debe
    abortar el arranque), acá perder el estado persistido NO es un riesgo
    de seguridad — es, a lo sumo, un conteo de pallets desincronizado que
    el operador corrige manualmente con "pallet_clear". load_state() nunca
    aborta el arranque del sistema: ante archivo ausente (primer boot) o
    corrupto, loguea y continúa con los defaults de SystemState.__init__.

Dependencias:
    ujson  → serialización
    os     → rename() para la escritura atómica
    state  → state.log, y los atributos a persistir
================================================================================
"""

import ujson as json
import os

from state import state, log

STATE_FILE = "/persisted_state.json"
STATE_FILE_TMP = "/persisted_state.tmp"

# Flag de "hay cambios sin guardar". Vive a nivel de módulo (no en state.py)
# porque es un detalle de implementación de ESTE módulo — state.py se
# mantiene sin dependencias, igual que config.py (ver docstring de state.py).
_dirty = False


def mark_dirty():
    """
    Marca que el estado en memoria cambió respecto al último flush a flash.
    Costo despreciable (una asignación) — se puede llamar tan seguido como
    haga falta (cada cambio de modo, cada pallet_clear, al final de cada
    move_sequence/pick_and_place) sin preocuparse por desgaste de flash,
    porque el flush real lo decide flush_if_dirty() con su propio timing.
    """
    global _dirty
    _dirty = True


def save_state():
    """
    Persiste mode, pallet_count, pallet_full y servo_angle a flash de forma
    incondicional (ignora el dirty flag — usado tanto por el flush
    periódico como por el apagado seguro en main._shutdown()).

    Escritura atómica: se escribe primero a STATE_FILE_TMP y recién se
    hace os.rename() sobre STATE_FILE. rename() en la mayoría de los
    filesystems (incluido littlefs, el que usa MicroPython en ESP32) es
    una operación de metadata, no de contenido — no queda un estado
    intermedio corrupto observable.
    """
    global _dirty
    payload = {
        "mode": state.mode,
        "pallet_count": {str(k): v for k, v in state.pallet_count.items()},
        "pallet_full": {str(k): v for k, v in state.pallet_full.items()},
        "servo_angle": {str(k): v for k, v in state.servo_angle.items()},
    }
    try:
        with open(STATE_FILE_TMP, "w") as f:
            json.dump(payload, f)
        os.rename(STATE_FILE_TMP, STATE_FILE)
        _dirty = False
        log("Estado persistido en flash (modo={}, pallets={}/{})".format(
            state.mode, state.pallet_count[1], state.pallet_count[2]), "DEBUG")
    except Exception as exc:
        # [SEC/HW] No se propaga: un fallo de escritura a flash no debe
        # tumbar el sistema de control del brazo. Se reintentará en el
        # próximo flush periódico (_dirty queda en True).
        log("Error persistiendo estado en flash: {}".format(exc), "WARNING")


def flush_if_dirty():
    """
    Debe llamarse periódicamente (cada TIMING["persist_ms"]) desde el loop
    principal. Solo escribe a flash si hubo cambios desde el último flush
    — evita escrituras redundantes cuando el sistema está inactivo.
    """
    if _dirty:
        save_state()


def load_state():
    """
    Restaura mode, pallet_count, pallet_full y servo_angle desde flash, si
    existe un archivo previo válido. Se debe llamar UNA vez, al inicio de
    main(), ANTES de servos.init_servos() — el homing suave al arranque
    depende de que state.servo_angle ya refleje el último ángulo conocido
    real, no el default de fábrica.

    Fail-safe: ante archivo ausente (primer arranque del dispositivo) o
    JSON corrupto (ej. reset justo durante una escritura no atómica de
    una versión anterior del firmware), se loguea y se continúa con los
    valores por defecto de SystemState.__init__ — nunca aborta el boot.
    """
    try:
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
    except OSError:
        log("Sin estado previo en flash (primer arranque)", "INFO")
        return
    except Exception as exc:
        log("Estado en flash corrupto, se descarta: {}".format(exc), "WARNING")
        return

    try:
        if data.get("mode") in ("MANUAL", "SEMI_AUTO", "AUTOMATICO"):
            state.mode = data["mode"]

        pallet_count = data.get("pallet_count", {})
        pallet_full = data.get("pallet_full", {})
        servo_angle = data.get("servo_angle", {})

        for pid in (1, 2):
            key = str(pid)
            if key in pallet_count:
                state.pallet_count[pid] = int(pallet_count[key])
            if key in pallet_full:
                state.pallet_full[pid] = bool(pallet_full[key])

        for sid in (1, 2, 3, 4):
            key = str(sid)
            if key in servo_angle:
                angle = int(servo_angle[key])
                state.servo_angle[sid] = max(0, min(180, angle))

        log("Estado restaurado desde flash: modo={} | Pallet1={}/3 Pallet2={}/3 "
            "| Servos={}".format(
                state.mode, state.pallet_count[1], state.pallet_count[2],
                state.servo_angle), "INFO")
    except Exception as exc:
        # Archivo leído pero con estructura inesperada — se conservan los
        # defaults ya seteados en SystemState.__init__ (no queda a medias:
        # cualquier campo restaurado antes de la excepción se queda como
        # esté, el resto usa el default; es aceptable para este alcance).
        log("Estructura de estado persistido inesperada: {}".format(exc), "WARNING")
