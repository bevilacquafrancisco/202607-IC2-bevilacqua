#!/usr/bin/env bash
# ==============================================================================
# arrancar_sistema.sh - v1.0
# Brazo Robotico Pick & Place v5.0 — equivalente Linux/macOS de ARRANCAR_SISTEMA.ps1
# USO: ./arrancar_sistema.sh   (antes de cada sesion de trabajo/demo, sin Docker)
#
# [SEC] Este script no maneja secretos directamente: backend/.env ya debe existir
# (copiado desde .env.example) antes de correrlo. Si no existe, uvicorn fallará con
# el mensaje fail-fast de config.py — comportamiento esperado, no un bug de este script.
#
# Requiere: mosquitto instalado (apt/brew), python3 + venv ya creado en src/backend/venv
# ==============================================================================
set -euo pipefail

# Resolver la ruta del script para que funcione sin importar desde dónde se invoque.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKER_DIR="$SCRIPT_DIR/mosquitto-broker"
BACKEND_DIR="$SCRIPT_DIR/backend"

echo "============================================"
echo " Brazo Robotico Pick & Place - Arranque (Linux/macOS)"
echo "============================================"

# 1. Matar instancias previas de mosquitto (mismo criterio que el .ps1)
if pgrep -x mosquitto >/dev/null 2>&1; then
    echo "-> Deteniendo instancia previa de mosquitto..."
    pkill -x mosquitto || true
    sleep 1
fi

# 2. Arrancar Mosquitto con la config del proyecto, en background
if ! [ -f "$BROKER_DIR/mosquitto.conf" ]; then
    echo "[ERROR] No se encontro $BROKER_DIR/mosquitto.conf"
    exit 1
fi

echo "-> Arrancando Mosquitto..."
mosquitto -c "$BROKER_DIR/mosquitto.conf" -v > "$SCRIPT_DIR/mosquitto.log" 2>&1 &
MQTT_PID=$!
sleep 2

# 3. Verificar que el proceso sigue vivo
if kill -0 "$MQTT_PID" 2>/dev/null; then
    echo "[OK] Mosquitto corriendo (PID $MQTT_PID) — log en mosquitto.log"
else
    echo "[ERROR] Mosquitto no arranco. Ver mosquitto.log para el detalle."
    exit 1
fi

# 4. Verificar puertos (lsof en macOS/Linux; ss como fallback en distros sin lsof)
check_port() {
    local port="$1"
    if command -v lsof >/dev/null 2>&1; then
        lsof -i ":$port" >/dev/null 2>&1
    else
        ss -ltn "( sport = :$port )" 2>/dev/null | grep -q ":$port"
    fi
}
check_port 1883 && echo "[OK] Puerto 1883 activo" || echo "[WARN] Puerto 1883 no detectado"
check_port 9001 && echo "[OK] Puerto 9001 activo" || echo "[WARN] Puerto 9001 no detectado"

# 5. Arrancar Backend FastAPI en una terminal nueva si es posible, si no, en background
if ! [ -d "$BACKEND_DIR/venv" ]; then
    echo "[ERROR] No existe $BACKEND_DIR/venv — crealo con:"
    echo "        cd src/backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo "-> Arrancando Backend FastAPI..."
(
    cd "$BACKEND_DIR"
    source venv/bin/activate
    uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$SCRIPT_DIR/backend.log" 2>&1 &
    echo $! > "$SCRIPT_DIR/.backend.pid"
)
sleep 2

if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    echo "[OK] Backend FastAPI respondiendo en /health"
else
    echo "[WARN] Backend no respondio a /health todavia — revisar backend.log"
fi

echo ""
echo "============================================"
echo " Sistema listo. Abri la GUI en el navegador:"
echo " http://localhost:5500/login.html"
echo " (servir src/gui/ con: python3 -m http.server 5500 --directory src/gui)"
echo "============================================"
echo ""
echo "Para detener: pkill -x mosquitto && kill \$(cat $SCRIPT_DIR/.backend.pid)"
