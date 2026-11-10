"""Runs INSIDE the runner sandbox: TCP 127.0.0.1:3030 (sandbox netns) -> reviewer Unix socket.

The sandbox's network namespace has only its own loopback, so this bridge can reach nothing
except the reviewer's filter-proxy socket that was bind-mounted into the sandbox.

  python3 -I sandbox_bridge.py SOCKET_PATH [PORT]
"""
import socket
import sys
import threading


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def main():
    path = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3030
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(64)
    print("bridge ready", flush=True)
    while True:
        c, _ = srv.accept()
        u = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            u.connect(path)
        except OSError:
            c.close()  # filter unavailable: fail closed for this connection, keep serving
            u.close()
            continue
        threading.Thread(target=pipe, args=(c, u), daemon=True).start()
        threading.Thread(target=pipe, args=(u, c), daemon=True).start()


if __name__ == "__main__":
    main()
