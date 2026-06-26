import socket
import json
import requests
import subprocess
import time
import os
import sys

HOST = "localhost"
PORT = 9000
RECONNECT_DELAY = 3

def self_destruct():
    script_path = os.path.abspath(__file__)

    if not os.path.exists(script_path):
        return
    try:
        if os.name == "nt":
            cmd_command = f'cmd /c "timeout /t 5 /nobreak > nul 2>&1 && del /f /q "{script_path}" 2>nul"'
            subprocess.Popen(
                cmd_command,
                shell=True,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.DETACHED_PROCESS,
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
        send_manager(s, {
            "type": "error",
            "stage": "self-destruct",
            "msg": f"failed {e}"
        })
    send_manager(s, {
        "type": "ok",
        "stage": "self-destruct",
        "msg": "success, bye.."
    })
    sys.exit(0)


def send_manager(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode())
    except Exception:
        pass


def connect_socket():
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            s.sendall(b"role=listener\n")
            send_manager(s, {
                "type": "ok",
                "stage": "socket",
                "msg": "connected"
            })
            return s
        except Exception as e:
            time.sleep(RECONNECT_DELAY)


def play_audio(content: bytes):
    try:
        p = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
            stdin=subprocess.PIPE,
        )
        if p.stdin:
            p.stdin.write(content)
            p.stdin.close()
        p.wait()
        send_manager(s, {
            "type": "ok",
            "stage": "audio",
            "msg": "played"
        })
    except Exception as e:
        try:
            send_manager(s, {
                "type": "error",
                "stage": "audio",
                "error": str(e)
            })
        except Exception:
            pass


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
                send_manager(s, {
                    "type": "ok",
                    "stage": "json",
                    "msg": "received"
                })
            except json.JSONDecodeError:
                send_manager(s, {
                    "type": "warn",
                    "stage": "json",
                    "msg": "invalid_json"
                })
                continue

            r = None

            try:
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
                    send_manager(s, {
                        "type": "ok",
                        "stage": "request",
                        "msg": "ok"
                    })
                    play_audio(r.content)

            except requests.RequestException as e:
                send_manager(s, {
                    "type": "error",
                    "stage": "request",
                    "error": str(e)
                })
            except Exception as e:
                send_manager(s, {
                    "type": "error",
                    "stage": "processing",
                    "error": str(e)
                })

    except (ConnectionError, OSError) as e:
        try:
            send_manager(s, {
                "type": "error",
                "stage": "socket",
                "error": str(e)
            })
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        s = connect_socket()
        buffer = ""
    except Exception as e:
        send_manager(s, {
            "type": "error",
            "stage": "processing",
            "error": str(e)
        })
        time.sleep(1)
