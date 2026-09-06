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
from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

import win32api
import win32event
import winerror

from routines import ROUTINES, refresh_routines
from routines.plan_loader import delete_plan, get_plan, save_plan
from web.bot_controller import BotController

MUTEX_NAME = "Global\\NoaAutoSingleInstance"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PREFERRED_PORTS = [6969, 6767, 6967]

_controller: BotController | None = None
_ws_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def acquire_mutex() -> bool:
    mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return False
    return True


class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


def broadcast_log(line: str) -> None:
    _schedule_broadcast({"type": "log", "line": line})


def broadcast_state(data: dict) -> None:
    _schedule_broadcast(data)


def broadcast_frame(data: dict) -> None:
    _schedule_broadcast(data)


def broadcast_config(data: dict) -> None:
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
    app.add_middleware(NoCacheStaticMiddleware)

    controller.on_log_event(broadcast_log)
    controller.on_state_event(broadcast_state)
    controller.on_frame_event(broadcast_frame)
    controller.on_config_event(broadcast_config)

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/state")
    async def get_state() -> JSONResponse:
        return JSONResponse(content=controller.get_state())

    @app.post("/api/start")
    async def start_bot() -> JSONResponse:
        controller.start()
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
        routines = body.get("routines")
        repeat = body.get("repeat")
        check_interval = body.get("check_interval")
        controller.set_config(
            routines=routines, repeat=repeat, check_interval=check_interval
        )
        return JSONResponse(content={"ok": True})

    @app.get("/api/windows")
    async def list_windows() -> JSONResponse:
        result = controller.game_launcher.list_visible_windows()
        return JSONResponse(content={"windows": result})

    @app.get("/api/preview")
    async def get_preview() -> JSONResponse:
        return JSONResponse(content=controller.get_preview())

    @app.post("/api/preview")
    async def set_preview(body: dict) -> JSONResponse:
        enabled = bool(body.get("enabled", False))
        mode = body.get("mode")
        ok = controller.set_preview(enabled)
        if not ok:
            return JSONResponse(status_code=503, content={"error": "Screen bot not available"})
        if isinstance(mode, str):
            controller.set_preview_mode(mode)
        return JSONResponse(content=controller.get_preview())

    @app.get("/api/browse")
    async def browse_path(path: str = "") -> JSONResponse:
        result = controller.browse(path)
        return JSONResponse(content=result)

    @app.get("/api/image")
    async def serve_image(path: str = "") -> Response:
        project_root = STATIC_DIR.parent
        filepath = (project_root / path).resolve()
        if not str(filepath).startswith(str(project_root)):
            return JSONResponse(status_code=403, content={"error": "Access denied"})
        if not filepath.is_file():
            return JSONResponse(status_code=404, content={"error": "Not found"})
        return FileResponse(filepath)

    @app.get("/api/routines")
    async def list_routines() -> JSONResponse:
        refresh_routines()
        return JSONResponse(content=controller.get_routines())

    @app.get("/api/plan/{name}")
    async def get_plan_data(name: str) -> JSONResponse:
        try:
            data = get_plan(name)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if data is None:
            return JSONResponse(status_code=404, content={"error": "Plan not found"})
        return JSONResponse(content=data)

    @app.post("/api/plan")
    async def save_plan_data(body: dict) -> JSONResponse:
        name = body.get("name", "")
        try:
            save_plan(name, body)
            refresh_routines()
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        return JSONResponse(
            content={"ok": True, "name": name, "routines": list(ROUTINES.keys())}
        )

    @app.put("/api/plan/{name}")
    async def update_plan_data(name: str, body: dict) -> JSONResponse:
        try:
            if get_plan(name) is None:
                return JSONResponse(status_code=404, content={"error": "Plan not found"})
            save_plan(name, body)
            refresh_routines()
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        return JSONResponse(
            content={"ok": True, "name": name, "routines": list(ROUTINES.keys())}
        )

    @app.delete("/api/plan/{name}")
    async def delete_plan_data(name: str) -> JSONResponse:
        try:
            deleted = delete_plan(name)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "Plan not found"})
        refresh_routines()
        return JSONResponse(content={"ok": True, "routines": list(ROUTINES.keys())})

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
