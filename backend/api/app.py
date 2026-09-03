"""REST and WebSocket API server for TrackShift 2026 Race Intelligence Engine."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from evaluation.backtesting.engine import BacktestEngine
from evaluation.latency.benchmark import LatencyBenchmark
from radio.transcription.service import RadioTranscriptionService
from simulator.scenarios.suite import NAMED_SCENARIOS, ScenarioRunner, create_scenario
from backend.websocket.manager import ConnectionManager

app = FastAPI(
    title="TrackShift 2026 Race Intelligence Engine",
    description="Simulator-independent, real-time F1 race intelligence and strategy REST/WebSocket API.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/dashboard", StaticFiles(directory="frontend", html=True), name="dashboard")

manager = ConnectionManager()
radio_service = RadioTranscriptionService()
scenario_runner = ScenarioRunner()
backtest_engine = BacktestEngine(scenario_runner)
latency_benchmark = LatencyBenchmark()


class RadioIngestRequest(BaseModel):
    car_id: str = "44"
    lap: int = 1
    raw_text: str
    speaker: str = "DRIVER"


@app.get("/")
def read_root():
    return FileResponse("frontend/index.html")


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "engine": "TrackShift 2026 Race Intelligence Engine",
        "version": "1.0.0",
        "scenarios_available": len(NAMED_SCENARIOS),
    }


@app.get("/api/scenarios")
def list_scenarios():
    catalog = []
    for sc_id in NAMED_SCENARIOS:
        sc = create_scenario(sc_id, seed=42)
        catalog.append({
            "scenario_id": sc.scenario_id,
            "name": sc.name,
            "description": sc.description,
            "seed": sc.seed,
            "primary_car_id": sc.primary_car_id,
            "num_cars": len(sc.generator_configs),
        })
    return catalog


@app.post("/api/scenarios/{scenario_id}/run")
def run_scenario(scenario_id: str, seed: int = 42):
    try:
        sc = create_scenario(scenario_id, seed=seed)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    states = scenario_runner.run(sc)

    serialized_states = {}
    for car_id, state in states.items():
        serialized_states[car_id] = {
            "car_id": state.car_id,
            "current_lap": state.current_lap,
            "position": state.position,
            "gap_ahead_s": state.gap_ahead_s,
            "gap_behind_s": state.gap_behind_s,
            "tyre_compound": state.tyre_compound.value if state.tyre_compound else None,
            "tyre_age_laps": state.tyre_age_laps,
            "estimated_degradation_s": state.estimated_degradation_s,
            "tyre_cliff_probability": state.tyre_cliff_probability,
            "weather": state.weather.value if state.weather else "DRY",
            "rain_probability": state.rain_probability,
            "strategy_decision": state.current_strategy.decision.value if state.current_strategy else None,
            "strategy_confidence": state.current_strategy.confidence if state.current_strategy else None,
            "reasons": state.current_strategy.reasons if state.current_strategy else [],
            "disagreements": [
                {
                    "disagreement_type": d.disagreement_type.value,
                    "summary": d.summary,
                    "severity": d.severity,
                }
                for d in state.disagreements
            ],
        }

    return {
        "scenario_id": scenario_id,
        "seed": seed,
        "cars": serialized_states,
    }


@app.post("/api/radio")
async def ingest_radio(request: RadioIngestRequest):
    msg = await radio_service.transcribe_and_extract_async(
        car_id=request.car_id,
        lap=request.lap,
        raw_text=request.raw_text,
        speaker=request.speaker,
    )
    return {
        "message_id": msg.message_id,
        "car_id": msg.car_id,
        "lap": msg.lap,
        "speaker": msg.speaker,
        "raw_text": msg.raw_text,
        "detected_intents": [i.value for i in msg.detected_intents],
        "confidence": msg.confidence,
        "is_demo_mode": msg.is_demo_mode,
    }


@app.get("/api/evaluation")
def get_evaluation_report(seed: int = 42):
    report = backtest_engine.run_full_evaluation(seed=seed)
    return asdict(report)


@app.get("/api/latency")
def get_latency_report(num_cars: int = 2, laps: int = 5):
    report = latency_benchmark.run_benchmark(num_cars=num_cars, laps=laps, tick_hz=5.0)
    return asdict(report)


@app.websocket("/ws/race")
async def race_websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Send initial connection handshake
        await websocket.send_json({"type": "CONNECTED", "engine": "TrackShift 2026"})
        while True:
            # Echo or receive client ping/control messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "PONG"})
    except WebSocketDisconnect:
        manager.disconnect(websocket)
