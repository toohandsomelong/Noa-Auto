from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import win32api
import win32event
import winerror

from bot_controller import BotController

MUTEX_NAME = "Global\\NoaAutoSingleInstance"
STATIC_DIR = Path(__file__).parent / "static"
PREFERRED_PORTS = [6969, 6767, 6967]

_controller: BotController | None = None
_ws_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def acquire_mutex() -> bool:
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return False
    return True


def broadcast_log(line: str) -> None:
    _schedule_broadcast({"type": "log", "line": line})


def broadcast_state(data: dict) -> None:
    _schedule_broadcast(data)


def _schedule_broadcast(data: dict) -> None:
    if _loop is None:
        return
    clients = _ws_clients.copy()
    for ws in clients:
        asyncio.run_coroutine_threadsafe(_safe_send(ws, data), _loop)


async def _safe_send(ws: WebSocket, data: dict) -> None:
    try:
        await ws.send_json(data)
    except Exception:
        _ws_clients.discard(ws)


def create_app(controller: BotController) -> FastAPI:
    global _controller
    _controller = controller

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        global _loop
        _loop = asyncio.get_running_loop()
        yield

    app = FastAPI(title="Noa Auto", lifespan=_lifespan)

    controller.on_log_event(broadcast_log)
    controller.on_state_event(broadcast_state)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def get_state() -> JSONResponse:
        return JSONResponse(content=controller.get_state())

    @app.post("/api/start")
    async def start_bot() -> JSONResponse:
        body = controller.get_config()
        path = body.get("game_path", "")
        controller.start(path)
        return JSONResponse(content={"ok": True})

    @app.post("/api/stop")
    async def stop_bot() -> JSONResponse:
        controller.stop()
        return JSONResponse(content={"ok": True})

    @app.get("/api/config")
    async def get_config() -> JSONResponse:
        return JSONResponse(content=controller.get_config())

    @app.put("/api/config")
    async def set_config(body: dict) -> JSONResponse:
        path = body.get("game_path", "")
        controller.set_config(path)
        return JSONResponse(content={"ok": True})

    @app.get("/api/browse")
    async def browse_path(path: str = "") -> JSONResponse:
        result = controller.browse(path)
        return JSONResponse(content=result)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        _ws_clients.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            _ws_clients.discard(ws)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app



def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def find_available_port(preferred: list[int]) -> int | None:
    for port in preferred:
        if _port_is_free(port):
            return port
    return None


def run_server(controller: BotController) -> None:
    global _ws_clients

    if not acquire_mutex():
        print("Another instance is already running. Exiting.")
        sys.exit(0)

    app = create_app(controller)
    controller.start_flush()

    result = find_available_port(PREFERRED_PORTS)
    if result is None:
        print(f"No available port in {PREFERRED_PORTS}. Exiting.")
        sys.exit(1)

    port = result
    url = f"http://127.0.0.1:{port}"
    print(f"Starting Noa Auto at {url}")
    webbrowser.open(url)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    server.run()

    controller.shutdown()
