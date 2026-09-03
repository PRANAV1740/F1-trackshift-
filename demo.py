"""TrackShift 2026 Race Intelligence Engine -- Interactive Demo Mode Launcher.

Launches the packaged scenario runner with preset race profiles, live playback,
fast-forward multipliers, and embedded REST API & Pit Wall/HQ web dashboard.

Usage:
    python demo.py [--scenario SCENARIO_ID] [--speed MULTIPLIER] [--port PORT]
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
import uvicorn

from backend.api.app import app
from simulator.scenarios.suite import NAMED_SCENARIOS, ScenarioRunner, create_scenario


def run_terminal_demo(scenario_id: str = "tyre_cliff", speed: float = 1.0) -> None:
    print("\n" + "=" * 80)
    print("  🏎️  TRACKSHIFT 2026 RACE INTELLIGENCE ENGINE -- LIVE DEMO MODE")
    print("=" * 80)
    print(f"  Scenario: {scenario_id}")
    print(f"  Speed Multiplier: {speed}x")
    print("=" * 80 + "\n")

    scenario = create_scenario(scenario_id, seed=42)
    runner = ScenarioRunner()
    states = runner.run(scenario)

    for car_id, state in states.items():
        strat = state.current_strategy
        dec = strat.decision.value if strat else "STAY_OUT"
        conf = round(strat.confidence * 100) if strat else 85
        print(f"  Car #{car_id} | Lap {state.current_lap} | Pos: P{state.position} | Tyre: {state.tyre_compound.value if state.tyre_compound else 'MEDIUM'} ({state.tyre_age_laps} Laps)")
        print(f"  └─► OPTIMAL DECISION: [{dec}] (Confidence: {conf}%)")
        if strat and strat.reasons:
            print(f"      Reasons: {', '.join(strat.reasons[:2])}")
        print("-" * 80)
        time.sleep(0.5 / speed)

    print("\n  Demo completed successfully!")


def main() -> None:
    parser = argparse.ArgumentParser(description="TrackShift 2026 Demo Mode Launcher")
    parser.add_argument("--scenario", default="tyre_cliff", choices=list(NAMED_SCENARIOS.keys()), help="Preset scenario ID")
    parser.add_argument("--speed", type=float, default=2.0, help="Playback speed multiplier")
    parser.add_argument("--port", type=int, default=8000, help="Web server port")
    parser.add_argument("--cli-only", action="store_true", help="Run terminal demo without web server")

    args = parser.parse_args()

    if args.cli-only or "--cli-only" in sys.argv:
        run_terminal_demo(scenario_id=args.scenario, speed=args.speed)
    else:
        print(f"\n🚀 Launching TrackShift REST & WebSocket server on http://localhost:{args.port}")
        print(f"📊 Opening Pit Wall & HQ Web Dashboard on http://localhost:{args.port}/dashboard ...\n")
        webbrowser.open(f"http://localhost:{args.port}/dashboard")
        uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
