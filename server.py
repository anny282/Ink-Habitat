"""Start the Creature World server: python server.py (the code lives in backend/)."""
import os
import socket

import uvicorn

import backend  # loads .env


def lan_address():
    """This laptop's address on the local network (no traffic is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return None


if __name__ == "__main__":
    # HOST=0.0.0.0 in .env lets other laptops on the same Wi-Fi open this server (for live battles).
    host = os.environ.get("HOST", "127.0.0.1")
    if host == "0.0.0.0" and lan_address():
        print(f"\n  Others on your Wi-Fi can open http://{lan_address()}:8000\n")
    uvicorn.run("backend.app:asgi", host=host, port=8000, reload=True)
