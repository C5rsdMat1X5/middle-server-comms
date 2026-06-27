import socket
import json
import requests
import subprocess
import time
import os
import sys


HOST = "192.168.4.31"
PORT = 9000
RECONNECT_DELAY = 3


def send_manager(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode())
    except Exception:
        pass


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)


def get_ffplay():
    try:
        subprocess.run(
            ["ffplay", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return "ffplay"
    except Exception:
        pass

    bundled = resource_path("ffplay.exe")
    if os.path.exists(bundled):
        return bundled

    return None


FFPLAY = get_ffplay()


def play_audio(content: bytes):
    try:
        if not FFPLAY:
            raise RuntimeError("ffplay not found (PATH or bundle)")

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        p = subprocess.Popen(
            [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
            stdin=subprocess.PIPE,
            creationflags=creationflags,
        )

        if p.stdin:
            p.stdin.write(content)
            p.stdin.close()

        p.wait()

        send_manager(s, {"type": "ok", "stage": "audio", "msg": f"played {len(content):,} bytes"})

    except Exception as e:
        try:
            send_manager(s, {"type": "error", "stage": "audio", "msg": str(e)})
        except Exception:
            pass


def self_destruct():
    if getattr(sys, "frozen", False):
        script_path = os.path.abspath(sys.executable)
    else:
        script_path = os.path.abspath(__file__)

    if not os.path.exists(script_path):
        send_manager(s, {"type": "error", "stage": "self-destruct", "msg": f"target not found: {script_path}"})
        return

    try:
        if os.name == "nt":
            import tempfile
            vbs_path = os.path.join(tempfile.gettempdir(), f"cleanup_{os.getpid()}.vbs")
            with open(vbs_path, "w") as f:
                f.write(f'WScript.Sleep 5000\n')
                f.write(f'Set fso = CreateObject("Scripting.FileSystemObject")\n')
                f.write(f'On Error Resume Next\n')
                f.write(f'fso.DeleteFile "{script_path}", True\n')
                f.write(f'fso.DeleteFile "{vbs_path}", True\n')

            cmd_command = ["wscript", "//B", "//Nologo", vbs_path]

            subprocess.Popen(
                cmd_command,
                creationflags=(
                    subprocess.DETACHED_PROCESS
                    | subprocess.CREATE_NO_WINDOW
                ),
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        else:
            cmd_command = f"sleep 5 && rm -f '{script_path}'"
            subprocess.Popen(
                ["sh", "-c", cmd_command],
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    except Exception as e:
        send_manager(s, {"type": "error", "stage": "self-destruct", "msg": str(e)})
        return

    send_manager(s, {"type": "ok", "stage": "self-destruct", "msg": f"deleting {os.path.basename(script_path)} in 5s, goodbye"})

    sys.exit(0)


def connect_socket():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            s.sendall(b"role=listener\n")

            send_manager(s, {"type": "ok", "stage": "socket", "msg": f"connected to {HOST}:{PORT}"})

            return s

        except Exception:
            time.sleep(RECONNECT_DELAY)


s = connect_socket()
buffer = ""

while True:
    try:
        data = s.recv(4096)
        if not data:
            raise ConnectionError("Socket disconnected")

        buffer += data.decode(errors="ignore")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)

            if not line.strip():
                continue

            try:
                message = json.loads(line)

                send_manager(s, {"type": "ok", "stage": "dispatch", "msg": f"command type={message.get('type')}"})

            except json.JSONDecodeError:
                send_manager(
                    s, {"type": "warn", "stage": "json", "msg": "invalid_json"}
                )
                continue

            try:
                r = None

                if message.get("type") == 2:
                    r = requests.post(
                        "https://api.fish.audio/v1/tts",
                        headers={
                            "Authorization": f"Bearer {message['api_key']}",
                            "Content-Type": "application/json",
                            "model": "s2.1-pro-free",
                        },
                        json={"text": message.get("txt", "")},
                        timeout=15,
                    )

                elif message.get("type") == 1:
                    r = requests.get(message.get("url", ""), timeout=15)

                elif message.get("type") == 404:
                    self_destruct()

                else:
                    continue

                if r and r.content:
                    send_manager(s, {"type": "ok", "stage": "request", "msg": f"{r.status_code} · {len(r.content):,} bytes"})
                    play_audio(r.content)

            except requests.RequestException as e:
                send_manager(s, {"type": "error", "stage": "request", "msg": str(e)})

            except Exception as e:
                send_manager(s, {"type": "error", "stage": "processing", "msg": str(e)})

    except (ConnectionError, OSError) as e:
        try:
            send_manager(s, {"type": "error", "stage": "socket", "msg": str(e)})
        except Exception:
            pass

        try:
            s.close()
        except Exception:
            pass

        s = connect_socket()
        buffer = ""

    except Exception as e:
        send_manager(s, {"type": "error", "stage": "processing", "msg": str(e)})
        time.sleep(1)
