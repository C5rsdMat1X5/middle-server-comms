from ast import dump
import socket,json, os
from dotenv import load_dotenv

s = socket.socket()
s.connect(("localhost", 9000))
s.sendall(b"role=controller\n")
load_dotenv()
api_key = os.getenv("API_KEY")
print("[*] Connected as controller, sending data...")
while True:
    msg = input("Send audio (1), Send message (2), Auto-Destruct (404): ")
    if msg == "2":
        tts = input("Message: ")
        packet = {"type": 2, "txt": tts, "api_key": api_key}
    elif msg == "1":
        url = input("URL: ")
        packet = {"type": 1, "url": url}

    elif msg == "404":
        answ = input("Sure> (yes/n): ")
        if answ == "yes":
            packet = {"type": 404}
    texto = json.dumps(packet)
    s.sendall((texto + "\n").encode("utf-8"))
