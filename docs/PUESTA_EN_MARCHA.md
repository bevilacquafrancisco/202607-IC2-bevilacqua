# PUESTA_EN_MARCHA.md — Guía completa de instalación desde cero

**Proyecto:** Sistema Pick & Place — Brazo Robótico Industrial IoT  
**Audiencia de este documento:** alguien que va a clonar el repositorio y ejecutarlo
por primera vez, sin conocimiento previo del proyecto.

Si buscás una vista rápida de arquitectura, stack y comandos mínimos, ver el
[`README.md`](../README.md) principal. Este documento asume que ya lo leíste y ahora
querés efectivamente **correr el sistema**, con cada paso explicado — qué es cada
credencial, por qué existe, cómo se genera, y qué hacer si algo falla.

---

## Índice

1. [Modelo de credenciales del sistema (leer primero)](#1-modelo-de-credenciales-del-sistema-leer-primero)
2. [Prerrequisitos](#2-prerrequisitos)
3. [Vía A — Docker (recomendada)](#3-vía-a--docker-recomendada)
4. [Vía B — Instalación nativa (sin Docker)](#4-vía-b--instalación-nativa-sin-docker)
5. [Cargar el firmware al ESP32 físico](#5-cargar-el-firmware-al-esp32-físico)
6. [Probar sin hardware físico (simulador)](#6-probar-sin-hardware-físico-simulador)
7. [Verificación end-to-end](#7-verificación-end-to-end)
8. [Troubleshooting — errores reales y su causa](#8-troubleshooting--errores-reales-y-su-causa)

---

## 1. Modelo de credenciales del sistema (leer primero)

El sistema tiene **dos planos de autenticación totalmente independientes**, con
credenciales distintas cada uno. Entender esto de entrada evita el 80% de los errores
de configuración:

| Plano | Quién se autentica | Contra qué | Dónde se define | Formato almacenado |
|---|---|---|---|---|
| **Aplicación** | El operador humano (vos) frente a la GUI | El backend FastAPI | `src/backend/.env` → `AUTH_USERS` | hash **bcrypt** |
| **Transporte** | La GUI y el ESP32/simulador, como *clientes*, frente al broker | Mosquitto | `src/mosquitto-broker/passwd` (generado con `mosquitto_passwd`) | hash **sha512** (formato propio de Mosquitto) |

**Regla de oro que vas a repetir varias veces en esta guía:**
En **todo `.env`**, la contraseña que escribís es siempre la de **texto plano**
(la que vos elegiste), nunca el hash que un comando generó a partir de ella. El hash
vive *solo* dentro de `AUTH_USERS` (para bcrypt) o dentro del archivo `passwd` de
Mosquitto (para MQTT) — nunca se copia un hash a otro lado.

### 1.1 Credenciales que vas a crear en esta guía

| Credencial | Para qué sirve | Dónde se genera | Dónde se guarda (hash) | Dónde se usa (texto plano) |
|---|---|---|---|---|
| Usuario/contraseña de un **operador** (ej. `francisco`) | Loguearse en la GUI | `scripts/generar_hash_password.py` | `src/backend/.env` → `AUTH_USERS` | Lo tipeás en el formulario de login |
| `JWT_SECRET_KEY` | Firmar los tokens de sesión emitidos tras el login | `secrets.token_hex(32)` (Python) | `src/backend/.env` | Nunca se "usa" directamente — el backend la usa internamente |
| Usuario MQTT `esp32` | Autenticar al firmware/simulador frente al broker | `mosquitto_passwd` | `src/mosquitto-broker/passwd` | `src/firmware/config.py`, `src/simulator/.env`, `.env` raíz (`MQTT_ESP32_PWD`) |
| Usuario MQTT `gui_operator` | Autenticar a la GUI (como aplicación) frente al broker | `mosquitto_passwd` | `src/mosquitto-broker/passwd` | `src/gui/robot_script.js` (`CFG.mqttPassword`) |

---

## 2. Prerrequisitos

### Vía A (Docker) — lo único que necesitás:
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) instalado y corriendo (Windows, macOS o Linux). Verificar con `docker --version` y `docker compose version`.

### Vía B (nativo, sin Docker):
- **Mosquitto**: [instalador oficial](https://mosquitto.org/download/) (Windows) / `apt install mosquitto` (Linux) / `brew install mosquitto` (macOS). Verificar con `mosquitto -h`.
- **Python 3.11+**: verificar con `python --version` (Windows) o `python3 --version` (Linux/macOS).
- **Git**, para clonar el repo.

### Para cargar el firmware (ambas vías):
- [Thonny](https://thonny.org/) u otro IDE con soporte MicroPython.
- Un ESP32 con MicroPython flasheado, conectado por USB.

---

## 3. Vía A — Docker (recomendada)

> ⚠️ **En Windows: correr los comandos de esta sección desde PowerShell, no desde Git
> Bash.** MSYS/Git Bash traduce (y a veces mal-traduce) las rutas que Docker necesita
> para los *bind mounts* de archivos individuales (como `passwd`) — el síntoma típico es
> `password-file: Error: Unable to open pwfile "/mosquitto/config/passwd"` aunque el
> archivo exista y tenga contenido correcto en el host. Ver
> [Troubleshooting 8.6 y 8.8](#8-troubleshooting--errores-reales-y-su-causa). Git Bash
> sirve para editar archivos o correr `arrancar_sistema.sh` dentro de WSL, pero no para
> `docker compose`.

### 3.1 Clonar y ubicarse en la raíz del repo

```bash
git clone https://github.com/bevilacquafrancisco/202607-IC2-bevilacqua.git
cd 202607-IC2-bevilacqua
```

### 3.2 Generar la contraseña del broker MQTT

Esto crea el archivo `src/mosquitto-broker/passwd` con los dos usuarios de aplicación
(`esp32` y `gui_operator`), cada uno con **su propia contraseña en texto plano** elegida
por vos (podés usar la misma para ambos si es solo para la demo, pero tienen que ser
usuarios separados igual, porque la ACL les da permisos distintos).

> ⚠️ **Generar este archivo con el binario nativo de `mosquitto_passwd`, no con
> Docker.** Si lo generás corriendo `mosquitto_passwd` dentro de un contenedor, el
> archivo queda con permisos/propietario traducidos por la capa de bind mount de
> Docker Desktop de una forma que el propio Mosquitto (corriendo como usuario
> `mosquitto` dentro de su contenedor) no puede leer — el síntoma es
> `password-file: Error: Unable to open pwfile "/mosquitto/config/passwd"` **aunque
> el archivo exista, tenga contenido válido, y vos lo puedas leer sin problema desde
> tu propia terminal**. Ver Troubleshooting 8.8 para el detalle completo.

**Windows — con Mosquitto instalado nativamente** (mismo binario que usa
`ARRANCAR_SISTEMA.ps1`, típicamente en `C:\Program Files\mosquitto\`):
```powershell
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b -c src\mosquitto-broker\passwd esp32 TU_CONTRASEÑA_ESP32
& "C:\Program Files\mosquitto\mosquitto_passwd.exe" -b src\mosquitto-broker\passwd gui_operator TU_CONTRASEÑA_GUI
```

**Linux/macOS — con Mosquitto instalado nativamente:**
```bash
mosquitto_passwd -b -c src/mosquitto-broker/passwd esp32 TU_CONTRASEÑA_ESP32
mosquitto_passwd -b src/mosquitto-broker/passwd gui_operator TU_CONTRASEÑA_GUI
```

**Qué hace cada flag:**
- `-c` crea el archivo desde cero (**solo la primera vez** — si lo usás en el segundo
  comando, borra el usuario que acabás de crear).
- `-b` (*batch*) permite pasar la contraseña como argumento en vez de que el comando la
  pida interactivamente — más cómodo para scriptear, pero significa que la contraseña
  queda un instante en el historial de tu terminal.

#### Alternativa: sin Mosquitto instalado (solo Docker)

Si no tenés Mosquitto nativo y no querés instalarlo solo para este paso, se puede
generar vía Docker — pero hay que forzar los permisos después, o el broker no va a
poder leer el archivo (ver el aviso de arriba):

```powershell
docker run --rm -v "${PWD}\src\mosquitto-broker:/mosquitto/config" eclipse-mosquitto:2 `
  mosquitto_passwd -b -c /mosquitto/config/passwd esp32 TU_CONTRASEÑA_ESP32
docker run --rm -v "${PWD}\src\mosquitto-broker:/mosquitto/config" eclipse-mosquitto:2 `
  mosquitto_passwd -b /mosquitto/config/passwd gui_operator TU_CONTRASEÑA_GUI

# Paso extra OBLIGATORIO con este método: forzar permisos de lectura abiertos
docker run --rm -v "${PWD}\src\mosquitto-broker:/mosquitto/config" --user root eclipse-mosquitto:2 `
  chmod 644 /mosquitto/config/passwd /mosquitto/config/acl.conf
```

Confirmá que el archivo se creó **como archivo, no como carpeta** (ver Troubleshooting
8.7 — es un error silencioso frecuente):
```powershell
Get-Item .\src\mosquitto-broker\passwd | Select-Object Name, PSIsContainer, Length
```
`PSIsContainer` debe decir `False` (si dice `True`, es una carpeta vacía, no el archivo
— borrala y repetí el paso 3.2). `Length` debe ser mayor a 0.

```bash

cat src/mosquitto-broker/passwd    # Linux/macOS
type src\mosquitto-broker\passwd   # Windows PowerShell

```
Deberías ver dos líneas con formato `usuario:$7$101$...` (el hash sha512 propio de
Mosquitto — **no es un hash bcrypt ni sha512_crypt estándar**, es un formato interno de
Mosquitto, no lo generes con otra herramienta).

> **Este archivo `passwd` nunca se sube a Git** (está en `.gitignore`) — cada persona que
> corre el proyecto genera el suyo con sus propias contraseñas.

### 3.3 Completar el `.env` de la raíz (variables de Docker Compose)

```bash
cp .env.example .env
```

Editar `.env` con un editor de texto (no `cp`, no PowerShell `echo >>` — abrilo y
escribilo directo) y completar:

```
MQTT_ESP32_PWD=TU_CONTRASEÑA_ESP32
```

Tiene que ser **exactamente** la misma contraseña en texto plano que usaste en el paso
3.2 para el usuario `esp32`. Esta variable la usa únicamente el *healthcheck* de
Mosquitto en `docker-compose.yml` — no toca la lógica de negocio.

> ⚠️ Si tu contraseña elegida tiene un carácter `$`, hay que escribirlo doble (`$$`) en
> este archivo — Docker Compose interpreta `$algo` como referencia a otra variable. Ver
> [Troubleshooting](#8-troubleshooting--errores-reales-y-su-causa) para el detalle de por
> qué esto rompe las cosas si no se respeta.

### 3.4 Completar el `.env` del backend

```bash
cp src/backend/.env.example src/backend/.env
```

Abrir `src/backend/.env` y completar **tres cosas**:

**a) `JWT_SECRET_KEY`** — una clave aleatoria, no un valor inventado a mano:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Copiar el resultado tal cual a `JWT_SECRET_KEY=<resultado>`.

**b) `AUTH_USERS`** — acá van los operadores que pueden loguearse en la GUI, como
`usuario:hash_bcrypt`. El hash se genera con el script incluido, que pide la contraseña
de forma interactiva (nunca queda en el historial de la terminal):

```bash
cd src/backend
python -m venv venv                 # si todavía no existe
venv\Scripts\activate               # Windows — source venv/bin/activate en Linux/macOS
pip install -r requirements.txt
python scripts/generar_hash_password.py
```

El script pregunta usuario y contraseña, y devuelve una línea lista para pegar, por
ejemplo:
```
francisco:$2b$12$o16U0bJCaQyzME.igwJTzu3gbj5L3nT8IKCYRAO8Jq68ThM8BPore
```

Repetir el script por cada operador, y juntarlos separados por coma en
una sola línea:
```
AUTH_USERS=francisco:$2b$12$o16U0...,evaluador:$2b$12$43RCW...
```

**c) `CORS_ORIGINS`** — el origen desde el que se sirve la GUI. Con Docker (puerto 5500
publicado por el servicio `gui`):
```
CORS_ORIGINS=http://localhost:5500
```

> ⚠️ **Nunca dejar `CORS_ORIGINS=*`** combinado con credenciales — los navegadores
> modernos (Chrome/Edge) rechazan directamente esa combinación por spec, y el login
> falla con un mensaje engañoso ("no se pudo contactar al servidor") que parece un
> problema de red pero es CORS. Ver Troubleshooting, caso 3.

Volver a la raíz del repo: `cd ../..`

### 3.5 Completar el `.env` del simulador (opcional en este momento)

Solo hace falta si vas a usar el [simulador](#6-probar-sin-hardware-físico-simulador)
sin ESP32 físico — se puede hacer ahora o más adelante:

```bash
cp src/simulator/.env.example src/simulator/.env
```

Editar con `MQTT_PASSWORD=TU_CONTRASEÑA_ESP32` (misma del paso 3.2 — el simulador se
autentica ante el broker como si fuera el ESP32, usando el mismo usuario `esp32`).

### 3.6 Configurar la GUI con la contraseña real de `gui_operator`

> ⚠️ **Paso obligatorio, se olvida fácil.** A diferencia del backend (que lee su
> configuración de un `.env` en tiempo de ejecución), la GUI es HTML/JS **estático** —
> sus credenciales quedan escritas literalmente en el código fuente, y ese código se
> "hornea" dentro de la imagen Docker al hacer `docker compose up --build`. Si no
> editás esto ANTES de levantar la imagen, la GUI va a intentar conectarse al broker
> con una contraseña que no coincide con la que generaste en el paso 3.2, y vas a ver
> el badge **MQTT** en rojo sin ningún mensaje de error claro.

Abrir `src/gui/robot_script_vs.js` y buscar el bloque `CFG` cerca del principio del
archivo:

```javascript
const CFG = {
    broker: window.location.hostname,
    port: 9001,
    topicCmd: 'robot/cmd',
    topicLog: 'robot/log',
    // ...
    mqttUser: 'gui_operator',
    mqttPassword: 'password',   // <-- CAMBIAR por la contraseña real que usaste en 3.2
};
```

Reemplazar el valor de `mqttPassword` por la contraseña **en texto plano** que le
diste al usuario `gui_operator` en el paso 3.2 (ojo con mayúsculas/minúsculas — es un
string exacto, no un hash). Guardar el archivo.

Si ya habías levantado el sistema antes de hacer este cambio, hace falta reconstruir
la imagen de la GUI para que tome el nuevo valor:
```bash
docker compose build gui
```
(o simplemente `docker compose up --build`, que reconstruye lo que cambió).

### 3.7 Levantar todo

```bash
docker compose up --build
```

Verificar:
- `docker compose ps` → `robot-mosquitto`, `robot-backend`, `robot-gui` en estado `Up`/`healthy`.
- `http://localhost:8000/health` → `{"status":"ok","service":"robot-auth-api",...}`.
- `http://localhost:5500/login.html` → pantalla de login, con el badge "BACKEND AUTH" en verde ("Disponible").
- Loguearse con el usuario/contraseña que creaste en el paso 3.4.b.
- Una vez dentro del panel, confirmar que el badge **MQTT** pasa a "Conectado" — si
  queda en rojo, revisar el paso 3.6 (contraseña de `gui_operator` en `robot_script.js`).

Para detener: `docker compose down`. Para levantar de nuevo tras un cambio de código:
`docker compose up --build --force-recreate`.

---

## 4. Vía B — Instalación nativa (sin Docker)

### 4.1 Broker MQTT

Instalar Mosquitto según tu sistema operativo (ver [Prerrequisitos](#2-prerrequisitos)).

Generar las credenciales (esta vez con el binario `mosquitto_passwd` instalado
localmente, no vía Docker):

```bash
cd src/mosquitto-broker
mosquitto_passwd -c passwd esp32          # pide la contraseña interactivamente
mosquitto_passwd passwd gui_operator      # sin -c: agrega al archivo existente
```

En Windows, el binario suele ser `mosquitto_passwd.exe` dentro de la carpeta de
instalación de Mosquitto (por defecto `C:\Program Files\mosquitto\`).

### 4.2 Backend

```bash
cd src/backend
python -m venv venv
venv\Scripts\activate            # Windows — source venv/bin/activate en Linux/macOS
pip install -r requirements.txt
cp .env.example .env             # o "copy" en PowerShell
```

Completar `.env` exactamente igual que en el paso 3.4 de la Vía Docker (`JWT_SECRET_KEY`,
`AUTH_USERS`, `CORS_ORIGINS` — para nativo, `CORS_ORIGINS=http://localhost:5500` también
sirve si servís la GUI en ese puerto con un servidor estático simple).

```bash
python scripts/generar_hash_password.py    # generar hash de cada operador
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4.3 Arranque combinado (broker + backend en un solo paso)

Una vez que el `passwd` y el `.env` del backend ya existen (pasos 4.1 y 4.2 hechos al
menos una vez), usar el script combinado en cada sesión de trabajo:

- **Windows**: `src\ARRANCAR_SISTEMA.ps1`
- **Linux/macOS**: `./src/arrancar_sistema.sh` (dar permisos primero: `chmod +x src/arrancar_sistema.sh`)

### 4.4 GUI

> ⚠️ **Antes de servir la GUI**, editar `src/gui/robot_script_vs.js` con la contraseña
> real del usuario `gui_operator` (generado en el paso 4.1) — es el mismo paso 3.6 de
> la Vía Docker, ver el detalle completo ahí. Buscar el bloque `CFG` al inicio del
> archivo y reemplazar `mqttPassword: 'password'` por tu contraseña real. Con la
> instalación nativa el archivo se sirve directo desde disco (no hay build de imagen de
> por medio), así que el cambio se aplica apenas recargués la página — pero igual hay
> que hacerlo, o el badge MQTT de la GUI va a quedar en rojo.

Servir `src/gui/` como contenido estático — cualquiera de estas opciones sirve:

```bash
python -m http.server 5500 --directory src/gui       # Python (cualquier SO)
# o la extensión "Live Server" de VS Code
```

Abrir `http://localhost:5500/login.html`. `auth.js` y `robot_script_vs.js` derivan el host
del backend/broker automáticamente desde `window.location` — no hace falta editar IPs a
mano mientras todo corra en la misma máquina.

> **Nota sobre Live Server**: si usás la extensión de VS Code, asegurate de que la URL
> quede en `http://localhost:5500`, no `http://127.0.0.1:5500` — son *orígenes*
> distintos para CORS aunque apunten a la misma máquina, y el backend solo tiene
> permitido el primero (`CORS_ORIGINS` en `src/backend/.env`). Ver Troubleshooting 8.9.

---

## 5. Cargar el firmware al ESP32 físico

(Igual en ambas vías — Docker no interactúa con el hardware real.)

1. Abrir `src/firmware/` en Thonny.
2. Editar `config.py`:
   - `WIFI["ssid"]` / `WIFI["password"]`: credenciales de tu red WiFi.
   - `MQTT["broker"]`: la IP de la máquina donde corre Mosquitto (si es la misma PC
     donde está Thonny, la IP de esa PC en la red local — **no** `localhost`, porque el
     ESP32 es un dispositivo de red aparte).
   - `MQTT["password"]`: la misma contraseña en texto plano del usuario `esp32` (paso 3.2/4.1).
3. Subir todos los módulos (`main.py`, `config.py`, `wifi.py`, `mqtt.py`, `servos.py`,
   `sensor.py`, `commands.py`, `state.py`) al ESP32 y ejecutar `main.py`.
4. Confirmar en la consola serie de Thonny que WiFi y MQTT conectan (`WiFi OK`, `MQTT
   conectado`).

---

## 6. Probar sin hardware físico (simulador)

Con el broker+backend+GUI ya corriendo (Vía A o B), en una terminal aparte:

```bash
# Si no lo hiciste en el paso 3.5:
cp src/simulator/.env.example src/simulator/.env   # completar MQTT_PASSWORD
```

**Con Docker:**
```bash
docker compose --profile simulate up --build simulator
```

**Sin Docker:**
```bash
cd src/simulator
python -m venv venv
venv\Scripts\activate            # Windows — source venv/bin/activate en Linux/macOS
pip install -r requirements.txt
python simulate_robot.py
```

En ambos casos, el simulador se conecta al broker como si fuera el ESP32 real —
la GUI no distingue uno de otro. Ver el detalle del comportamiento (detección automática
vs. manual con ENTER) en el [README principal](../README.md#probar-el-sistema-sin-hardware-físico-simulador).

---

## 7. Verificación end-to-end

Checklist para confirmar que todo el sistema funciona antes de dar por cerrada la
instalación:

- [ ] `http://localhost:8000/health` responde `200 OK`.
- [ ] Login en `http://localhost:5500/login.html` exitoso con un usuario de `AUTH_USERS`.
- [ ] Badge **MQTT** en el panel pasa a "Conectado".
- [ ] Badge **ESP32** pasa a "Online" (con el firmware real o con el simulador corriendo).
- [ ] Modo MANUAL: mover un slider de servo, confirmar que la GUI recibe el `servo_ack`.
- [ ] Modo SEMI_AUTO: forzar una detección de caja (sensor real, o ENTER en el simulador),
      elegir un pallet, confirmar que se deposita.
- [ ] Modo AUTOMÁTICO: dejar correr un ciclo completo hasta que un pallet se llene,
      vaciarlo desde la GUI, confirmar que se rehabilita.

---

## 8. Troubleshooting — errores reales y su causa

Esta sección documenta problemas que efectivamente aparecieron al poner en marcha este
proyecto en una máquina nueva — no son hipotéticos.

### 8.1 `docker compose up` falla con `required variable MQTT_ESP32_PWD is missing a value`, con warnings tipo `The "XXXXXXXX" variable is not set`

**Causa:** se pegó el **hash** de Mosquitto (formato `$7$101$XXXXXXXX$...`) en vez de la
**contraseña en texto plano** en el `.env` de la raíz. Docker Compose interpreta cada
`$algo` dentro de un `.env` como una referencia a otra variable — el hash tiene varios
`$`, así que se interpola en pedazos y el valor final queda vacío.

**Solución:** en `MQTT_ESP32_PWD` (y en cualquier `.env` de este proyecto) va siempre la
contraseña elegida por vos en texto plano, nunca el resultado de `mosquitto_passwd`.

### 8.2 Login falla con `passlib.exc.UnknownHashError: hash could not be identified`

**Causa:** el mismo mecanismo que 8.1, pero en `src/backend/.env` → `AUTH_USERS`. Si ese
archivo se pasa a Docker vía el atributo `env_file:` de `docker-compose.yml`, Compose
también interpola su contenido — y un hash bcrypt (`$2b$12$...`) tiene varios `$`, así
que llega corrompido al backend.

**Solución aplicada en este proyecto:** `docker-compose.yml` monta `src/backend/.env`
como **volumen** (`volumes: - ./src/backend/.env:/app/.env:ro`), no como `env_file:` —
así Compose nunca toca el contenido, y `pydantic-settings` lo lee directo del disco
dentro del contenedor. Si ves este error, confirmá que tu `docker-compose.yml` tiene esa
sección como `volumes:` y no `env_file:` para el servicio `backend`.

### 8.3 GUI muestra "No se pudo contactar al servidor de autenticación", pero el backend está `healthy`

**Causa más común:** bug de CORS. Si `CORS_ORIGINS=*` en el `.env` del backend **y**
el código de `main.py` tiene `allow_credentials=True`, los navegadores modernos
rechazan la respuesta completa (no es un problema de red real, es un bloqueo del
navegador) — en la consola (F12) vas a ver exactamente:
```
Access to fetch at 'http://localhost:8000/auth/login' from origin 'http://localhost:5500'
has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header is present
```

**Solución:** `CORS_ORIGINS` tiene que ser un origen específico, nunca `*`, cuando el
backend usa `allow_credentials=True` (ver paso 3.4.c / 4.2). Confirmar con:
```bash
curl -i -H "Origin: http://localhost:5500" -H "Access-Control-Request-Method: POST" \
  -X OPTIONS http://localhost:8000/auth/login
```
Si en la respuesta aparece `access-control-allow-origin: http://localhost:5500`, está
bien configurado.

### 8.4 `docker compose --profile simulate up --build simulator` falla con `failed to read dockerfile: open Dockerfile: no such file or directory`

**Causa:** falta alguno de los archivos de `src/simulator/` (`Dockerfile`,
`requirements.txt`, `simulate_robot.py`) — típicamente porque se copió el `.env.example`
pero no el resto de la carpeta.

**Solución:** confirmar que los 4 archivos existen:
```bash
ls src/simulator/     # Linux/macOS
dir src\simulator\    # Windows
```
Deberían aparecer `Dockerfile`, `requirements.txt`, `simulate_robot.py`, `.env.example`
(y `.env` si ya lo creaste).

### 8.5 Mosquitto tira warnings de permisos (`world readable permissions`, `owner is not mosquitto`)

**Causa:** el archivo `passwd`/`acl.conf` montado en el contenedor tiene permisos más
abiertos de lo que Mosquitto 2.x prefiere.

**Impacto:** son **warnings**, no errores — el broker arranca igual. Mosquitto avisa que
en versiones futuras esto podría rechazar la carga del archivo. Para esta entrega
académica no bloquea nada; si querés silenciarlo:
```bash
chmod 600 src/mosquitto-broker/passwd src/mosquitto-broker/acl.conf   # Linux/macOS
```
(En Windows, con Docker Desktop, los permisos del lado del contenedor Linux dependen del
volumen montado y este ajuste no siempre aplica igual — no es crítico para la demo.)

### 8.6 `arrancar_sistema.sh` falla al correrlo desde Git Bash en Windows

**Causa:** Git Bash (MINGW64) sobre Windows **no es** un entorno Linux/macOS real — no
tiene los mismos binarios de gestión de procesos (`pgrep`, `lsof`) actuando sobre
procesos Windows de la misma forma, y el `mosquitto.conf` original usa rutas absolutas
de Windows (`C:/mosquitto-broker/...`) pensadas para `ARRANCAR_SISTEMA.ps1`.

**Solución:** en Windows, usar `ARRANCAR_SISTEMA.ps1` (PowerShell) o la Vía Docker.
`arrancar_sistema.sh` está pensado para Linux/macOS reales o WSL — si necesitás
validarlo en Windows, hacerlo dentro de una distro WSL, no en Git Bash.

### 8.7 El passwd file no existe y Docker no tira un error claro

**Causa:** si `src/mosquitto-broker/passwd` no existe al momento de `docker compose up`,
Docker Desktop en Windows a veces crea automáticamente una **carpeta vacía** en el punto
de montaje en vez de fallar con un mensaje del tipo "archivo no encontrado" — y Mosquitto
arranca sin poder leer ninguna credencial (todo login MQTT falla silenciosamente).

**Solución:** generar el `passwd` **antes** del primer `docker compose up` (paso 3.2) y
confirmar que es un archivo, no una carpeta:
```bash
ls -la src/mosquitto-broker/passwd    # debe decir "-rw-..." (archivo), no "drwx..." (carpeta)
```
Si terminó siendo una carpeta vacía por error, borrarla y volver a correr el paso 3.2.

### 8.8 `password-file: Error: Unable to open pwfile "/mosquitto/config/passwd"`, con el archivo confirmado como válido (existe, tiene contenido, tiene ambos usuarios)

Este es distinto del caso 8.7 — acá el archivo **sí existe y es correcto** (confirmado
con `Get-Item`/`cat`, incluso después de un `docker compose down -v --rmi all` completo
y un rebuild 100% limpio), y aun así Mosquitto no lo puede abrir.

**Causa real:** el archivo `passwd` se generó corriendo `mosquitto_passwd` **dentro de
un contenedor Docker** (vía `docker run -v ...`), en vez de con el binario instalado
nativamente en el sistema operativo. Cuando un contenedor escribe un archivo sobre un
bind mount de Windows, Docker Desktop traduce los permisos/propietario Linux↔Windows de
una forma que deja el archivo sin acceso de lectura para el usuario `mosquitto` con el
que corre el **otro** contenedor (el del broker) — aunque vos, desde tu propia terminal
Windows, lo leas sin ningún problema (por eso `Get-Content`/`cat` no detectan nada raro).
Es una asimetría de permisos entre "quien escribió el archivo" (root, dentro de un
contenedor efímero) y "quien necesita leerlo" (el usuario `mosquitto`, dentro del
contenedor del broker).

**Solución:** regenerar `passwd` con el binario **nativo** de `mosquitto_passwd` (ver
paso 3.2, primera opción) — el archivo resultante tiene permisos Windows normales, sin
la traducción de contenedor de por medio. Después de eso, arranca con los mismos
warnings cosméticos de siempre (`world readable permissions`, `owner is not mosquitto`
— ver caso 8.5), pero **sin el error fatal**.

Si no tenés Mosquitto instalado nativamente y preferís seguir generándolo vía Docker,
hay que forzar los permisos manualmente después (ver la alternativa en el paso 3.2) —
sin ese paso extra, este error se repite siempre con archivos generados así.

### 8.9 CORS bloquea la GUI solo cuando se accede por `http://127.0.0.1:5500`, pero `http://localhost:5500` funciona bien

**Causa:** `127.0.0.1` y `localhost` son *orígenes* distintos para el navegador (CORS
mira `protocolo + host + puerto` exacto), aunque resuelvan a la misma máquina. Si
`CORS_ORIGINS` en `src/backend/.env` solo tiene `http://localhost:5500`, una request
con `Origin: http://127.0.0.1:5500` (por ejemplo, servida por la extensión Live Server
de VS Code con su configuración por defecto) queda bloqueada — sin relación con la ruta
del archivo (`/login.html` vs `/src/gui/login.html`), CORS no mira el path.

**Solución (elegir una):**
1. Usar siempre `http://localhost:5500` en la barra de direcciones.
2. Configurar Live Server para bindear en `localhost`: setting `"liveServer.settings.host": "localhost"` en `settings.json` de VS Code.
3. Permitir ambos orígenes en el backend: `CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500` (`config.py` ya soporta múltiples orígenes separados por coma).

Con Docker esto no aparece — `docker compose up` siempre sirve la GUI en
`http://localhost:5500` de forma consistente.

### 8.10 Badge MQTT queda en rojo en la GUI, aunque el backend y el login funcionen bien

**Causa:** `src/gui/robot_script.js` tiene la contraseña del usuario `gui_operator`
**hardcodeada** en el código (`CFG.mqttPassword`) — a diferencia del backend, la GUI es
estático puro, no lee ningún `.env` en tiempo de ejecución. Si generaste el `passwd` de
Mosquitto con una contraseña distinta a la que quedó escrita en ese archivo (el valor
por defecto del repo es `'FRANCISCO'`), el navegador intenta autenticarse contra el
broker con la contraseña equivocada y la conexión MQTT falla — sin ningún mensaje de
error explícito en la consola de logs de la GUI, solo el badge en rojo.

**Solución:** ver el paso 3.6 (Docker) / 4.4 (nativo) — editar `CFG.mqttPassword` en
`src/gui/robot_script_vs.js` con la contraseña real, y si estás en Docker, reconstruir la
imagen de la GUI (`docker compose build gui`) para que tome el cambio.

---
