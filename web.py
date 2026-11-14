import hashlib
import hmac
import json
import os
import queue
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for, send_file)

load_dotenv()

HOST = "localhost"
PORT = 7833
API_KEY = os.getenv("API_KEY")

# ── Autenticación ──
USERS_FILE = os.getenv("USERS_FILE", "users.json")
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "24"))

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(hours=SESSION_HOURS)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("HTTPS", "0") == "1",
)

# ── Estado global ──
available_listeners = {}
listener_names = {}
listeners_lock = threading.Lock()

current_target = None
target_lock = threading.Lock()

sock = None
sock_lock = threading.Lock()

action_history = []
history_lock = threading.Lock()

saved_items = []
saved_lock = threading.Lock()

manager_connected = False
manager_lock = threading.Lock()

sse_clients = []
sse_lock = threading.Lock()


# ═══════════════ AUTENTICACIÓN ═══════════════
def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        app.logger.warning(f"[auth] No existe '{USERS_FILE}'. Crea el archivo con {{'usuario':'clave'}}.")
        return {}
    except Exception as e:
        app.logger.error(f"[auth] Error leyendo {USERS_FILE}: {e}")
        return {}


def verify_password(stored, provided):
    if not isinstance(stored, str) or not stored:
        return False
    if stored.startswith("sha256:"):
        expected = "sha256:" + hashlib.sha256(provided.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, stored)
    return hmac.compare_digest(stored, provided)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped


def login_required_api(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return jsonify({"error": "No autorizado"}), 401
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if session.get("user"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        users = load_users()
        if username and verify_password(users.get(username), password):
            session.permanent = True
            session["user"] = username
            return redirect(url_for("index"))
        error = "Usuario o contraseña incorrectos"
        time.sleep(0.4)  # mitigar fuerza bruta
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ═══════════════ EVENTOS / SOCKET ═══════════════
def push_event(data):
    with sse_lock:
        for q in list(sse_clients):
            try:
                q.put_nowait(data)
            except Exception:
                pass


def add_history(action_type, params, target, label=None):
    entry = {
        "id": int(time.time() * 1000),
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": action_type,
        "params": params,
        "target": target,
        "label": label or "",
    }
    with history_lock:
        action_history.insert(0, entry)
        if len(action_history) > 200:
            action_history.pop()
    push_event({"event": "history_entry", "entry": entry})


def snapshot_listeners():
    with listeners_lock:
        return {lid: {"addr": a, "name": listener_names.get(lid, "")}
                for lid, a in available_listeners.items()}


def snapshot_saved():
    with saved_lock:
        return list(saved_items)


def add_saved(item_type, params, label=""):
    entry = {
        "id": int(time.time() * 1000),
        "type": item_type,
        "params": params,
        "label": label or "",
        "added": datetime.now().strftime("%H:%M:%S"),
    }
    with saved_lock:
        saved_items.insert(0, entry)
        if len(saved_items) > 200:
            saved_items.pop()
    push_event({"event": "saved_added", "entry": entry})
    return entry


def handle_event(msg):
    global current_target
    event = msg.get("event")
    if event == "listeners":
        available = msg.get("available", {})
        with listeners_lock:
            available_listeners.clear()
            available_listeners.update(available)
            for lid in list(listener_names):
                if lid not in available_listeners:
                    listener_names.pop(lid, None)
        with target_lock:
            if current_target not in available_listeners:
                current_target = next(iter(available_listeners), None)
            t = current_target
        push_event({"event": "listeners_update", "listeners": snapshot_listeners(), "current": t})
    elif event == "listener_connected":
        lid = msg.get("id"); addr = msg.get("addr", "?")
        with listeners_lock:
            available_listeners[lid] = addr
        with target_lock:
            if current_target is None:
                current_target = lid
            t = current_target
        push_event({"event": "listener_connected", "id": lid, "addr": addr,
                    "listeners": snapshot_listeners(), "current": t})
    elif event == "listener_disconnected":
        lid = msg.get("id")
        with listeners_lock:
            available_listeners.pop(lid, None)
            listener_names.pop(lid, None)
            fallback = next(iter(available_listeners), None)
        with target_lock:
            if current_target == lid:
                current_target = fallback
            t = current_target
        push_event({"event": "listener_disconnected", "id": lid,
                    "listeners": snapshot_listeners(), "current": t})


def handle_response(msg):
    push_event({
        "event": "response",
        "from": msg.get("from", ""),
        "rtype": msg.get("type", "?"),
        "stage": msg.get("stage", "?"),
        "msg": msg.get("msg") or "",
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
                    push_event({"event": "raw", "data": line,
                                "time": datetime.now().strftime("%H:%M:%S")})
    except Exception:
        pass
    finally:
        global manager_connected, sock
        with manager_lock:
            manager_connected = False
        with sock_lock:
            if sock is s:
                sock = None
        push_event({"event": "manager_disconnected"})
        time.sleep(3)
        threading.Thread(target=connect_manager, daemon=True).start()


def connect_manager():
    global sock, manager_connected
    push_event({"event": "manager_connecting"})
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            s.sendall(b"role=controller\n")
            with sock_lock:
                old = sock
                sock = s
            if old is not None and old is not s:
                try: old.close()
                except Exception: pass
            with manager_lock:
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
    if s is None:
        return None
    try:
        s.sendall((json.dumps(packet) + "\n").encode("utf-8"))
    except Exception:
        return None
    return t


def send_to_all(packet):
    with listeners_lock:
        ids = list(available_listeners.keys())
    if not ids:
        return []
    ok = []
    with sock_lock:
        s = sock
    if s is None:
        return []
    for lid in ids:
        pkt = dict(packet); pkt["target"] = lid
        try:
            s.sendall((json.dumps(pkt) + "\n").encode("utf-8"))
            ok.append(lid)
        except Exception:
            pass
    return ok


# ═══════════════ RUTAS ═══════════════
@app.route("/")
@login_required
def index():
    return render_template("index.html", session_user=session.get("user"))


@app.route("/api/state")
@login_required_api
def state():
    with target_lock:
        t = current_target
    with history_lock:
        h = list(action_history[:50])
    with manager_lock:
        mc = manager_connected
    return jsonify({
        "listeners": snapshot_listeners(),
        "current_target": t,
        "history": h,
        "manager_connected": mc,
        "saved": snapshot_saved(),
    })


@app.route("/api/audio", methods=["POST"])
@login_required_api
def audio():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL vacía"}), 400
    target = send_packet({"type": 1, "url": url})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("audio", {"url": url}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/tts", methods=["POST"])
@login_required_api
def tts():
    txt = (request.json or {}).get("txt", "").strip()
    if not txt:
        return jsonify({"error": "Mensaje vacío"}), 400
    target = send_packet({"type": 2, "txt": txt, "api_key": API_KEY})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("tts", {"txt": txt}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/vol", methods=["POST"])
@login_required_api
def vol():
    val = (request.json or {}).get("val", "")
    if val == "":
        return jsonify({"error": "Valor vacío"}), 400
    target = send_packet({"type": 3, "vol": val})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("vol", {"val": float(val)}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/stop", methods=["POST"])
@login_required_api
def stop():
    target = send_packet({"type": 4})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("stop", {}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/yt", methods=["POST"])
@login_required_api
def yt():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"error": "URL vacía"}), 400
    target = send_packet({"type": 5, "url": url})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("yt", {"url": url}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/update", methods=["POST"])
@login_required_api
def update():
    target = send_packet({"type": 6})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("update", {}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/wipe", methods=["POST"])
@login_required_api
def wipe():
    target = send_packet({"type": 404})
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history("wipe", {}, target)
    return jsonify({"ok": True, "target": target})


@app.route("/api/switch", methods=["POST"])
@login_required_api
def switch():
    global current_target
    lid = (request.json or {}).get("id", "").strip()
    with listeners_lock:
        ls = set(available_listeners)
    if lid not in ls:
        return jsonify({"error": "Listener desconocido"}), 400
    with target_lock:
        current_target = lid
    push_event({"event": "target_changed", "current": lid})
    return jsonify({"ok": True, "current": lid})


@app.route("/api/rename", methods=["POST"])
@login_required_api
def rename():
    body = request.json or {}
    lid = (body.get("id") or "").strip()
    name = (body.get("name") or "").strip()
    if not lid or not name:
        return jsonify({"error": "Datos incompletos"}), 400
    with listeners_lock:
        if lid not in available_listeners:
            return jsonify({"error": "Listener desconocido"}), 400
        listener_names[lid] = name
    push_event({"event": "zone_renamed", "id": lid, "name": name})
    return jsonify({"ok": True, "id": lid, "name": name})


@app.route("/api/history/rename", methods=["POST"])
@login_required_api
def history_rename():
    body = request.json or {}
    hid = body.get("id")
    label = (body.get("label") or "").strip()
    if hid is None or not label:
        return jsonify({"error": "Datos incompletos"}), 400
    with history_lock:
        entry = next((e for e in action_history if e["id"] == hid), None)
        if entry is None:
            return jsonify({"error": "Entrada no encontrada"}), 404
        entry["label"] = label
    push_event({"event": "history_entry_updated", "id": hid, "label": label})
    return jsonify({"ok": True, "id": hid, "label": label})


@app.route("/api/saved", methods=["GET"])
@login_required_api
def saved_list():
    return jsonify({"items": snapshot_saved()})


@app.route("/api/saved", methods=["POST"])
@login_required_api
def saved_add():
    body = request.json or {}
    item_type = (body.get("type") or "").strip()
    params = body.get("params") or {}
    label = (body.get("label") or "").strip()
    if item_type not in ("audio", "yt", "tts", "vol"):
        return jsonify({"error": "Tipo inválido"}), 400
    if item_type in ("audio", "yt") and not (params.get("url") or "").strip():
        return jsonify({"error": "URL vacía"}), 400
    if item_type == "tts" and not (params.get("txt") or "").strip():
        return jsonify({"error": "Mensaje vacío"}), 400
    if item_type == "vol" and params.get("val") in (None, ""):
        return jsonify({"error": "Volumen vacío"}), 400
    entry = add_saved(item_type, params, label)
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/saved/<int:item_id>", methods=["DELETE"])
@login_required_api
def saved_delete(item_id):
    with saved_lock:
        before = len(saved_items)
        saved_items[:] = [x for x in saved_items if x["id"] != item_id]
        removed = len(saved_items) != before
    if not removed:
        return jsonify({"error": "No encontrado"}), 404
    push_event({"event": "saved_removed", "id": item_id})
    return jsonify({"ok": True, "id": item_id})


@app.route("/api/saved/rename", methods=["POST"])
@login_required_api
def saved_rename():
    body = request.json or {}
    item_id = body.get("id")
    label = (body.get("label") or "").strip()
    if item_id is None or not label:
        return jsonify({"error": "Datos incompletos"}), 400
    with saved_lock:
        entry = next((e for e in saved_items if e["id"] == item_id), None)
        if entry is None:
            return jsonify({"error": "No encontrado"}), 404
        entry["label"] = label
    push_event({"event": "saved_updated", "id": item_id, "label": label})
    return jsonify({"ok": True, "id": item_id, "label": label})


@app.route("/api/saved/send", methods=["POST"])
@login_required_api
def saved_send():
    body = request.json or {}
    item_id = body.get("id")
    target_override = (body.get("target") or "").strip() or None
    with saved_lock:
        entry = next((e for e in saved_items if e["id"] == item_id), None)
    if entry is None:
        return jsonify({"error": "No encontrado"}), 404

    t_type = entry["type"]
    params = entry["params"]
    packet = {"type": {"audio": 1, "tts": 2, "vol": 3, "yt": 5}[t_type]}
    packet.update({k: v for k, v in params.items()})

    global current_target
    if target_override:
        with listeners_lock:
            if target_override not in available_listeners:
                return jsonify({"error": "Listener desconocido"}), 400
        with target_lock:
            current_target = target_override

    target = send_packet(packet)
    if target is None:
        return jsonify({"error": "Manager no conectado"}), 503
    add_history(t_type, params, target, label=entry.get("label") or "")
    return jsonify({"ok": True, "target": target})


@app.route("/api/broadcast", methods=["POST"])
@login_required_api
def broadcast():
    body = request.json or {}
    kind = (body.get("type") or "").strip()
    params = body.get("params") or {}
    if kind not in ("audio", "yt", "tts", "vol", "stop"):
        return jsonify({"error": "Tipo inválido"}), 400
    packet = {"type": {"audio": 1, "tts": 2, "vol": 3, "stop": 4, "yt": 5}[kind]}
    packet.update(params)
    sent = send_to_all(packet)
    if not sent:
        return jsonify({"error": "Sin listeners conectados"}), 503
    add_history(kind, params, "TODOS")
    return jsonify({"ok": True, "sent": sent, "count": len(sent)})

@app.route("/api/exec", methods=["GET"])
def exec_file():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(BASE_DIR, "exces", "listener.exe")
    
    if not os.path.isfile(path):
        return jsonify({"error": "Archivo no encontrado"}), 404

    return send_file(path, as_attachment=True, download_name="listener.exe")

@app.route("/stream")
@login_required
def stream():
    q = queue.Queue(maxsize=100)
    with sse_lock:
        sse_clients.append(q)

    def generate():
        with target_lock:
            t = current_target
        with manager_lock:
            mc = manager_connected
        yield f"data: {json.dumps({'event': 'init', 'listeners': snapshot_listeners(), 'current': t, 'manager_connected': mc})}\n\n"
        try:
            while True:
                try:
                    data = q.get(timeout=25)
                    yield f"data: {json.dumps(data)}\n\n"
                except queue.Empty:
                    yield 'data: {"event":"ping"}\n\n'
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                try: sse_clients.remove(q)
                except ValueError: pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    if not load_users():
        print(f"⚠️  ADVERTENCIA: '{USERS_FILE}' no existe o está vacío. No podrás iniciar sesión.")
        print(f"   Crear '{USERS_FILE}' con: {{\"admin\":\"tu_clave\"}}")
    threading.Thread(target=connect_manager, daemon=True).start()
    app.run(host="0.0.0.0", port=5555, debug=False, threaded=True)