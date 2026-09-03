"""Tests for REST and WebSocket API layer (`backend/api/app.py`)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app

client = TestClient(app)


def test_health_check_endpoint():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["scenarios_available"] == 12


def test_list_scenarios_endpoint():
    response = client.get("/api/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 12
    assert data[0]["scenario_id"] == "normal_race"


def test_run_scenario_endpoint():
    response = client.post("/api/scenarios/normal_race/run?seed=42")
    assert response.status_code == 200
    data = response.json()
    assert data["scenario_id"] == "normal_race"
    assert "44" in data["cars"]
    car = data["cars"]["44"]
    assert car["car_id"] == "44"
    assert car["current_lap"] == 20


def test_ingest_radio_endpoint():
    response = client.post(
        "/api/radio",
        json={"car_id": "44", "lap": 10, "raw_text": "Front tyres are graining", "speaker": "DRIVER"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["car_id"] == "44"
    assert "TYRE_GRAINING" in data["detected_intents"]
    assert data["is_demo_mode"] is True


def test_evaluation_endpoint():
    response = client.get("/api/evaluation?seed=42")
    assert response.status_code == 200
    data = response.json()
    assert data["scenarios_evaluated"] == 12
    assert data["ai_win_count"] >= 6


def test_websocket_connection():
    with client.websocket_connect("/ws/race") as websocket:
        data = websocket.receive_json()
        assert data["type"] == "CONNECTED"
        websocket.send_text("ping")
        pong = websocket.receive_json()
        assert pong["type"] == "PONG"
