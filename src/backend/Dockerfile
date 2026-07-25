# ==============================================================================
# Dockerfile — Backend de autenticación (FastAPI + JWT)
# [SEC] Imagen base con tag fijo (nunca "latest"), usuario no-root, sin secretos
# horneados en la imagen (JWT_SECRET_KEY / AUTH_USERS entran vía env_file en runtime).
# ==============================================================================
FROM python:3.11-slim

# curl: requerido únicamente por el healthcheck de docker-compose.yml (GET /health).
# [SEC] Se limpia apt cache en la misma capa para no dejar metadata innecesaria en la imagen.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# [SEC] Usuario de aplicación sin privilegios — el proceso uvicorn no corre como root.
RUN useradd --create-home --shell /usr/sbin/nologin appuser

WORKDIR /app

# Instalar dependencias primero (aprovecha la cache de capas de Docker: si solo
# cambia el código, no se reinstalan las dependencias en cada build).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY app ./app

# [SEC] Cambiar de root al usuario de aplicación antes de ejecutar el proceso.
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# El healthcheck real vive en docker-compose.yml (usa curl, no disponible en slim
# por defecto); acá solo se documenta el puerto/endpoint esperado.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]