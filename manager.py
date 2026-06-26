import socket
import threading
import json

HOST = "0.0.0.0"
PORT = 9000

listener_conn = None
listener_lock = threading.Lock()


def handle_client(conn, addr):
    global listener_conn
    try:
        data = conn.recv(1024).decode().strip()
        role = data.split("role=")[-1] if "role=" in data else ""

        if role == "listener":
            print(f"[+] Listener connected from {addr}")
            with listener_lock:
                listener_conn = conn
            buffer = ""
            try:
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break

                    buffer += data.decode(errors="ignore")

                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue

                        try:
                            msg = json.loads(line)
                            print(f"[listener] {msg}")
                        except Exception:
                            print(f"[listener] {line}")
            except Exception:
                pass
            print(f"[-] Listener disconnected from {addr}")
            with listener_lock:
                listener_conn = None

        elif role == "controller":
            print(f"[+] Controller connected from {addr}")
            with listener_lock:
                target = listener_conn
            if target is None:
                conn.sendall(b"no listener connected\n")
                conn.close()
                return
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    target.sendall(chunk)
            except Exception:
                pass
            finally:
                conn.close()
            print(f"[-] Controller disconnected from {addr}")

        else:
            conn.sendall(b"unknown role\n")
            conn.close()

    except Exception as e:
        print(f"[!] Error with {addr}: {e}")
        conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"[*] Listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    main()
