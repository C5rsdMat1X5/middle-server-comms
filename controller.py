import socket
import json
import os
import time
import threading
from dotenv import load_dotenv

load_dotenv()

HOST = "190.153.147.14"
PORT = 7833
API_KEY = os.getenv("API_KEY")

R   = "\033[0m"
G   = "\033[92m"
Y   = "\033[93m"
C   = "\033[96m"
RED = "\033[91m"
B   = "\033[1m"
DIM = "\033[2m"

available_listeners = {}
listeners_lock = threading.Lock()
current_target = None
target_lock = threading.Lock()


def handle_event(msg):
    global current_target
    event = msg.get("event")

    if event == "listeners":
        available = msg.get("available", {})
        with listeners_lock:
            available_listeners.clear()
            available_listeners.update(available)
        if available:
            print(f"\n  {C}Connected listeners:{R}")
            for lid, addr in available.items():
                print(f"    {B}{lid}{R}  {DIM}{addr}{R}")
            with target_lock:
                if current_target is None:
                    current_target = next(iter(available))
                    print(f"  {G}Auto-selected {current_target}{R}")
        else:
            print(f"\n  {Y}No listeners connected{R}")

    elif event == "listener_connected":
        lid  = msg.get("id")
        addr = msg.get("addr", "?")
        with listeners_lock:
            available_listeners[lid] = addr
        print(f"\n  {G}[+] Listener {B}{lid}{R}{G} connected from {addr}{R}")
        with target_lock:
            if current_target is None:
                current_target = lid
                print(f"  {G}Auto-selected {lid}{R}")

    elif event == "listener_disconnected":
        lid = msg.get("id")
        with listeners_lock:
            available_listeners.pop(lid, None)
            fallback = next(iter(available_listeners), None)
        print(f"\n  {RED}[-] Listener {B}{lid}{R}{RED} disconnected{R}")
        with target_lock:
            if current_target == lid:
                current_target = fallback
                if fallback:
                    print(f"  {Y}Target switched to {fallback}{R}")
                else:
                    print(f"  {Y}No listeners available{R}")


def recv_loop(s):
    buf = ""
    try:
        while True:
            data = s.recv(4096)
            if not data:
                print(f"\n{RED}[!] Disconnected from manager{R}")
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
                        continue
                    from_id = msg.get("from", "")
                    t       = msg.get("type", "?")
                    stage   = msg.get("stage", "?")
                    body    = msg.get("msg") or ""
                    prefix  = f"{DIM}[{from_id}]{R} " if from_id else ""
                    if t == "ok":
                        print(f"\n  {G}✓{R} {prefix}[{stage}] {body}")
                    elif t == "error":
                        print(f"\n  {RED}✗{R} {prefix}[{stage}] {body}")
                    elif t == "warn":
                        print(f"\n  {Y}⚠{R} {prefix}[{stage}] {body}")
                    else:
                        print(f"\n  {C}?{R} {prefix}{line}")
                except Exception:
                    print(f"\n  {C}raw{R} {line}")
    except Exception:
        pass


def connect():
    global current_target
    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((HOST, PORT))
            s.sendall(b"role=controller\n")
            print(f"{G}[*] Connected to manager{R}")
            return s
        except Exception:
            print(f"{Y}[~] Manager not reachable, retrying in 3s...{R}")
            time.sleep(3)


def send(s, packet):
    with target_lock:
        t = current_target
    if t:
        packet["target"] = t
    s.sendall((json.dumps(packet) + "\n").encode("utf-8"))


def target_label():
    with target_lock:
        t = current_target
    return f"{C}{t}{R}" if t else f"{RED}none{R}"


def print_menu():
    print(f"\n  target → {target_label()}")
    print(f"  {C}[1]{R} Audio URL   {C}[2]{R} TTS   {C}[404]{R} Self-destruct")
    print(f"  {C}[ls]{R} Listeners   {C}[sw]{R} Switch target   {C}[q]{R} Quit")


def main():
    global current_target

    s = connect()
    threading.Thread(target=recv_loop, args=(s,), daemon=True).start()

    print(f"\n{B}{'━' * 32}{R}")
    print(f"{B}  Controller{R}")
    print(f"{B}{'━' * 32}{R}")

    time.sleep(0.3)
    while True:
        try:
            print_menu()
            cmd = input(f"\n{B}>{R} ").strip()

            if cmd == "1":
                url = input("  URL: ").strip()
                if not url:
                    print(f"{Y}  [!] Empty URL{R}")
                    continue
                send(s, {"type": 1, "url": url})

            elif cmd == "2":
                txt = input("  Message: ").strip()
                if not txt:
                    print(f"{Y}  [!] Empty message{R}")
                    continue
                send(s, {"type": 2, "txt": txt, "api_key": API_KEY})

            elif cmd == "404":
                confirm = input(f"  {RED}Self-destruct {target_label()}{RED}? (yes/n): {R}").strip()
                if confirm == "yes":
                    send(s, {"type": 404})
                else:
                    print(f"{Y}  Cancelled{R}")

            elif cmd == "ls":
                with listeners_lock:
                    ls = dict(available_listeners)
                if ls:
                    print(f"\n  {C}Listeners:{R}")
                    for lid, addr in ls.items():
                        marker = f"  {G}← current{R}" if lid == current_target else ""
                        print(f"    {B}{lid}{R}  {DIM}{addr}{R}{marker}")
                else:
                    print(f"\n  {Y}No listeners connected{R}")

            elif cmd == "sw":
                with listeners_lock:
                    ls = dict(available_listeners)
                if not ls:
                    print(f"{Y}  No listeners available{R}")
                    continue
                print(f"  Available: {', '.join(f'{B}{k}{R}' for k in ls)}")
                choice = input("  ID: ").strip()
                if choice in ls:
                    with target_lock:
                        current_target = choice
                    print(f"  {G}Target → {choice}{R}")
                else:
                    print(f"{RED}  Unknown: {choice}{R}")

            elif cmd in ("q", "quit", "exit"):
                print(f"{Y}[*] Bye{R}")
                break

            else:
                print(f"{Y}  [!] Unknown command{R}")

        except KeyboardInterrupt:
            print(f"\n{Y}[*] Bye{R}")
            break
        except BrokenPipeError:
            print(f"{RED}[!] Lost connection, reconnecting...{R}")
            with target_lock:
                current_target = None
            s = connect()
            threading.Thread(target=recv_loop, args=(s,), daemon=True).start()
            time.sleep(0.3)
        except Exception as e:
            print(f"{RED}[!] {e}{R}")


if __name__ == "__main__":
    main()
