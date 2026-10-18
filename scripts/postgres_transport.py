# SPDX-License-Identifier: Apache-2.0
# Code authors: Vijay and Codex
"""Byte transport to real PostgreSQL inside network-none Docker, not a DB mock."""
from contextlib import contextmanager
import os
import selectors
import socketserver
import subprocess
import threading


@contextmanager
def postgres_transport(container, env):
    """Keep the installed host binary intact; forward only the loopback wire."""
    stats = {"connections": 0, "client_bytes": 0, "server_bytes": 0, "errors": []}

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            stats["connections"] += 1
            process = subprocess.Popen(
                ["docker", "exec", "-i", container, "bash", "-c",
                 'exec 3<>/dev/tcp/127.0.0.1/5432; cat <&3 & reader=$!; cat >&3; '
                 'kill "$reader" 2>/dev/null || :; wait "$reader" 2>/dev/null || :'],
                env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL)
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(self.request, selectors.EVENT_READ, "client")
                    selector.register(process.stdout, selectors.EVENT_READ, "server")
                    while True:
                        events = selector.select(timeout=30)
                        if not events:
                            raise TimeoutError("database transport idle timeout")
                        for key, _ in events:
                            if key.data == "client":
                                data = self.request.recv(65536)
                                if not data:
                                    return
                                process.stdin.write(data)
                                process.stdin.flush()
                                stats["client_bytes"] += len(data)
                            else:
                                data = os.read(process.stdout.fileno(), 65536)
                                if not data:
                                    if process.wait(timeout=5):
                                        raise RuntimeError("database transport process failed")
                                    return
                                self.request.sendall(data)
                                stats["server_bytes"] += len(data)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                stats["errors"].append(type(error).__name__)
            finally:
                process.stdin.close()
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process.stdout.close()

    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server.server_address[1], stats
        finally:
            server.shutdown()
            thread.join()
