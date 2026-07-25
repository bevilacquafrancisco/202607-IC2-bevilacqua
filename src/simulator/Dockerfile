# ==============================================================================
# Dockerfile — Simulador de hardware ESP32 (sin brazo físico)
# ==============================================================================
FROM python:3.11-slim

RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY simulate_robot.py .

RUN chown -R appuser:appuser /app
USER appuser

# Se ejecuta con `docker compose --profile simulate up` — ver docker-compose.yml.
CMD ["python", "simulate_robot.py"]
