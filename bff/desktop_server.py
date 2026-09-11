"""Authenticated, loopback-only BFF child process owned by Electron."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import socket
import sys
import threading

import uvicorn
from starlette.responses import JSONResponse


class DesktopAuthentication:
    def __init__(self, app, token: str):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            supplied = headers.get(b"authorization", b"")
            if not hmac.compare_digest(
                supplied, ("Bearer " + self.token).encode("ascii")
            ):
                await JSONResponse(
                    {"detail": "Desktop authentication required"}, status_code=401
                )(scope, receive, send)
                return
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)


async def serve() -> None:
    token = os.environ.pop("EV_DESKTOP_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError(
            "EV_DESKTOP_TOKEN must contain at least 32 random characters"
        )
    from bff.main import app

    server = uvicorn.Server(
        uvicorn.Config(
            DesktopAuthentication(app, token),
            host="127.0.0.1",
            port=0,
            access_log=False,
            log_level="warning",
        )
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]

        def watch_parent() -> None:
            # EOF also stops the sidecar after an unexpected Electron exit.
            sys.stdin.readline()
            server.should_exit = True

        threading.Thread(target=watch_parent, daemon=True).start()
        task = asyncio.create_task(server.serve(sockets=[listener]))
        while not server.started:
            if task.done():
                await task
                raise RuntimeError("BFF exited before startup")
            await asyncio.sleep(0.05)
        pid = os.getpid()
        proof = hmac.new(token.encode(), f"{port}:{pid}".encode(), "sha256").hexdigest()
        print(
            "DESKTOP_READY " + json.dumps({"port": port, "pid": pid, "proof": proof}),
            flush=True,
        )
        await task


if __name__ == "__main__":
    asyncio.run(serve())
