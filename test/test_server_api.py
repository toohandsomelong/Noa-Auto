from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from web.server import create_app


def _valid_plan(name: str = "apiplan") -> dict:
    return {
        "name": name,
        "steps": [{"type": "click", "targets": [{"template": "templates/x/A.png"}]}],
    }


@pytest.fixture
def client(controller, tmp_config, tmp_plans) -> TestClient:
    with TestClient(create_app(controller)) as test_client:
        yield test_client


def test_index_served(client):
    response = client.get("/")
    assert response.status_code == 200


def test_get_state(client):
    response = client.get("/api/state")
    assert response.status_code == 200
    assert response.json() == {"state": "IDLE", "active_target": None}


def test_config_get_and_put(client):
    response = client.put("/api/config", json={"repeat": 5, "check_interval": 1.0})
    assert response.status_code == 200
    assert response.json()["ok"] is True

    config = client.get("/api/config").json()
    assert config["repeat"] == 5
    assert config["check_interval"] == 1.0


def test_preview_get_and_enable(client):
    assert client.get("/api/preview").json() == {"enabled": False, "mode": "snapshot"}
    response = client.post("/api/preview", json={"enabled": True, "mode": "live"})
    assert response.status_code == 200
    assert response.json() == {"enabled": True, "mode": "live"}


def test_preview_503_without_screen_bot(
    tmp_config, tmp_plans, fake_logger, fake_game_launcher, fake_focus_watcher
):
    from core.state_manager import StateManager
    from web.bot_controller import BotController

    controller = BotController(
        fake_logger, StateManager(), fake_game_launcher, fake_focus_watcher, None
    )
    with TestClient(create_app(controller)) as client:
        assert client.post("/api/preview", json={"enabled": True}).status_code == 503


def test_list_windows(client):
    assert client.get("/api/windows").json() == {"windows": []}


def test_list_routines(client):
    response = client.get("/api/routines")
    assert response.status_code == 200
    assert "routines" in response.json()


def test_plan_crud_roundtrip(client):
    assert client.post("/api/plan", json=_valid_plan()).status_code == 200

    fetched = client.get("/api/plan/apiplan")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "apiplan"

    updated = _valid_plan()
    updated["steps"].append(
        {"type": "click", "targets": [{"template": "templates/x/B.png"}]}
    )
    assert client.put("/api/plan/apiplan", json=updated).status_code == 200
    assert len(client.get("/api/plan/apiplan").json()["steps"]) == 2

    assert client.delete("/api/plan/apiplan").status_code == 200
    assert client.get("/api/plan/apiplan").status_code == 404


def test_plan_post_invalid_returns_400(client):
    assert client.post("/api/plan", json={"name": "bad", "steps": []}).status_code == 400


def test_plan_update_missing_returns_404(client):
    assert client.put("/api/plan/ghost", json=_valid_plan("ghost")).status_code == 404


def test_plan_delete_missing_returns_404(client):
    assert client.delete("/api/plan/ghost").status_code == 404


def test_image_traversal_forbidden(client):
    response = client.get("/api/image", params={"path": "../secret.txt"})
    assert response.status_code == 403


def test_image_missing_returns_404(client):
    response = client.get("/api/image", params={"path": "does-not-exist.png"})
    assert response.status_code == 404


def test_image_valid_file_served(client):
    response = client.get("/api/image", params={"path": "static/index.html"})
    assert response.status_code == 200


def test_browse_endpoint(client):
    response = client.get("/api/browse", params={"path": ""})
    assert response.status_code == 200
    assert set(response.json()) == {"dirs", "exes", "images", "parent"}
