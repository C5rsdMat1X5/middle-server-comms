import socket
import threading
import json
from datetime import datetime

HOST = "0.0.0.0"
PORT = 7833

listeners = {}
listener_addrs = {}
listeners_lock = threading.Lock()
listener_counter = 0

controller_conn = None
controller_lock = threading.Lock()

R   = "\033[0m"
G   = "\033[92m"
Y   = "\033[93m"
C   = "\033[96m"
RED = "\033[91m"
B   = "\033[1m"
DIM = "\033[2m"


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(tag, msg):
    print(f"{DIM}[{ts()}]{R} [{tag}] {msg}")


def fmt_listener_msg(lid, msg):
    t     = msg.get("type", "?")
    stage = msg.get("stage", "?")
    body  = msg.get("msg") or ""
    label = f"{B}{lid}{R}"
    if t == "ok":
        return f"  {G}✓{R} {label} [{stage}] {body}"
    elif t == "error":
        return f"  {RED}✗{R} {label} [{stage}] {body}"
    elif t == "warn":
        return f"  {Y}⚠{R} {label} [{stage}] {body}"
    return f"  {C}?{R} {label} {msg}"


def notify_controller(payload):
    with controller_lock:
        ctrl = controller_conn
    if ctrl:
        try:
            ctrl.sendall((json.dumps(payload) + "\n").encode())
        except Exception:
            pass


def recv_line(conn):
    buf = ""
    while "\n" not in buf:
        chunk = conn.recv(1024)
        if not chunk:
            return None
        buf += chunk.decode(errors="ignore")
    return buf.split("\n")[0].strip()


def forward_listener(conn, addr, lid):
    buf = ""
    try:
        while True:
            data = conn.recv(4096)
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
                    print(f"{DIM}[{ts()}]{R} " + fmt_listener_msg(lid, msg))
                    notify_controller({**msg, "from": lid})
                except Exception:
                    log(lid, line)
                    notify_controller({"type": "raw", "from": lid, "msg": line})
    except Exception:
        pass

    log(f"{RED}-{R}", f"Listener {B}{lid}{R} disconnected from {addr}")
    with listeners_lock:
        listeners.pop(lid, None)
        listener_addrs.pop(lid, None)
    notify_controller({"event": "listener_disconnected", "id": lid})


def handle_client(conn, addr):
    global listener_counter, controller_conn

    role_line = recv_line(conn)
    if not role_line:
        conn.close()
        return

    role = role_line.split("role=")[-1] if "role=" in role_line else ""

    if role == "listener":
        with listeners_lock:
            listener_counter += 1
            lid = f"L{listener_counter}"
            listeners[lid] = conn
            listener_addrs[lid] = str(addr[0])

        log(f"{G}+{R}", f"Listener {B}{lid}{R} connected from {addr}")
        notify_controller({"event": "listener_connected", "id": lid, "addr": str(addr[0])})
        forward_listener(conn, addr, lid)

    elif role == "controller":
        log(f"{G}+{R}", f"Controller connected from {addr}")
        with controller_lock:
            controller_conn = conn

        with listeners_lock:
            available = {lid: listener_addrs[lid] for lid in listeners}
        try:
            conn.sendall((json.dumps({"event": "listeners", "available": available}) + "\n").encode())
        except Exception:
            pass

        buf = ""
        try:
            while True:
                data = conn.recv(4096)
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
                        target_id = msg.pop("target", None)

                        with listeners_lock:
                            if target_id:
                                target = listeners.get(target_id)
                            else:
                                target = next(iter(listeners.values()), None)

                        if target:
                            target.sendall((json.dumps(msg) + "\n").encode())
                        else:
                            err = f"listener {target_id} not found" if target_id else "no listener connected"
                            conn.sendall((json.dumps({"type": "error", "stage": "manager", "msg": err}) + "\n").encode())
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        finally:
            with controller_lock:
                if controller_conn is conn:
                    controller_conn = None
            conn.close()
        log(f"{RED}-{R}", f"Controller disconnected from {addr}")

    else:
        conn.sendall(b'{"type":"error","stage":"manager","msg":"unknown role"}\n')
        conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    log("*", f"Listening on {HOST}:{PORT}")

    try:
        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        log("*", "Shutting down")
    finally:
        server.close()


if __name__ == "__main__":
    main()
