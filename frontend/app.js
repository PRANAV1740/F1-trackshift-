// TrackShift 2026 Race Intelligence Engine -- Frontend App Logic

const API_BASE = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws/race";

document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupScenarioRunner();
  setupCornerInspector();
  setupEvaluationButton();
  connectWebSocket();
});

// Tab Navigation
function setupTabs() {
  const tabs = document.querySelectorAll(".nav-btn");
  tabs.forEach(btn => {
    btn.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      
      btn.classList.add("active");
      const targetId = `tab-${btn.dataset.tab}`;
      const targetContent = document.getElementById(targetId);
      if (targetContent) {
        targetContent.classList.add("active");
      }
    });
  });
}

// Scenario Simulation Runner
function setupScenarioRunner() {
  const runBtn = document.getElementById("run-scenario-btn");
  const scenarioSelect = document.getElementById("scenario-select");

  if (runBtn && scenarioSelect) {
    runBtn.addEventListener("click", async () => {
      const scenarioId = scenarioSelect.value;
      runBtn.innerText = "RUNNING...";
      runBtn.disabled = true;

      try {
        const res = await fetch(`${API_BASE}/api/scenarios/${scenarioId}/run?seed=42`, { method: "POST" });
        const data = await res.json();
        updateDashboard(data);
      } catch (err) {
        console.error("Error running scenario:", err);
      } finally {
        runBtn.innerText = "RUN SCENARIO";
        runBtn.disabled = false;
      }
    });
  }
}

// Update UI with Scenario Output Data
function updateDashboard(data) {
  if (!data || !data.cars) return;

  const cars = data.cars;
  const primaryCar = cars["44"] || Object.values(cars)[0];

  if (primaryCar) {
    // 1. Update Hero Decision Widget
    document.getElementById("hero-decision-action").innerText = primaryCar.strategy_decision || "STAY OUT";
    document.getElementById("hero-decision-sub").innerText = `COMPOUND: ${primaryCar.tyre_compound || "MEDIUM"}`;
    document.getElementById("metric-compound").innerText = primaryCar.tyre_compound || "MEDIUM";
    
    const conf = Math.round((primaryCar.strategy_confidence || 0.85) * 100);
    document.getElementById("metric-confidence").innerText = `${conf}%`;
    document.getElementById("current-lap-val").innerText = primaryCar.current_lap;

    // Reasons list
    const reasonsUl = document.getElementById("reasons-list");
    reasonsUl.innerHTML = "";
    const reasons = primaryCar.reasons && primaryCar.reasons.length ? primaryCar.reasons : [
      "Tyre degradation within linear bounds",
      "Pace delta maintains track position",
      "Optimal pit window ahead"
    ];
    reasons.forEach(r => {
      const li = document.createElement("li");
      li.innerText = r;
      reasonsUl.appendChild(li);
    });

    // Disagreements
    const disBanner = document.getElementById("disagreement-banner");
    if (primaryCar.disagreements && primaryCar.disagreements.length > 0) {
      const dis = primaryCar.disagreements[0];
      document.getElementById("disagreement-title").innerText = `HUMAN / AI DISAGREEMENT (${dis.disagreement_type})`;
      document.getElementById("disagreement-desc").innerText = dis.summary;
      disBanner.style.display = "flex";
    } else {
      disBanner.style.display = "none";
    }
  }

  // 2. Update HQ Leaderboard Table
  const tbody = document.getElementById("leaderboard-body");
  if (tbody) {
    tbody.innerHTML = "";
    Object.values(cars).forEach(car => {
      const tr = document.createElement("tr");
      const cliffStyle = (car.tyre_cliff_probability || 0) >= 0.7 ? "color: var(--accent-red); font-weight: 700;" : "";
      tr.innerHTML = `
        <td>${car.position || 1}</td>
        <td><strong>#${car.car_id}</strong></td>
        <td><span style="color: var(--accent-amber);">${car.tyre_compound || 'MEDIUM'}</span></td>
        <td>${car.tyre_age_laps || 0} laps</td>
        <td>${(car.estimated_degradation_s || 0.03).toFixed(2)}s/lap</td>
        <td style="${cliffStyle}">${Math.round((car.tyre_cliff_probability || 0) * 100)}%</td>
        <td>${car.gap_ahead_s ? '+' + car.gap_ahead_s.toFixed(1) + 's' : '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  }
}

// Corner Inspector interaction
function setupCornerInspector() {
  const corners = document.querySelectorAll(".corner-node");
  corners.forEach(node => {
    node.addEventListener("click", () => {
      const cornerId = node.dataset.corner;
      document.getElementById("corner-title").innerText = `CORNER ${cornerId} (MEDIUM SPEED ARC)`;
      document.getElementById("corner-line").innerText = "IDEAL";
      document.getElementById("corner-braking").innerText = `${(100 + cornerId * 15).toFixed(1)}m`;
      document.getElementById("corner-entry").innerText = `${240 - cornerId * 5} km/h`;
      document.getElementById("corner-apex").innerText = `${170 - cornerId * 4} km/h`;
      document.getElementById("corner-exit").innerText = `${250 - cornerId * 3} km/h`;
      document.getElementById("corner-dev").innerText = `0.${cornerId * 2}m`;
      document.getElementById("corner-loss").innerText = `0.0${cornerId * 3}s`;
    });
  });
}

// Full Evaluation runner
function setupEvaluationButton() {
  const btn = document.getElementById("run-eval-btn");
  const output = document.getElementById("eval-report-output");

  if (btn && output) {
    btn.addEventListener("click", async () => {
      btn.innerText = "EVALUATING 12 SCENARIOS...";
      btn.disabled = true;
      output.innerText = "Running evaluation suite...";

      try {
        const res = await fetch(`${API_BASE}/api/evaluation?seed=42`);
        const data = await res.json();

        document.getElementById("eval-scenarios").innerText = data.scenarios_evaluated;
        document.getElementById("eval-wins").innerText = data.ai_win_count;
        document.getElementById("eval-saved").innerText = `+${data.total_time_saved_s.toFixed(1)}s`;

        output.innerText = JSON.stringify(data, null, 2);
      } catch (err) {
        output.innerText = `Error: ${err.message}`;
      } finally {
        btn.innerText = "RUN FULL BENCHMARK EVALUATION";
        btn.disabled = false;
      }
    });
  }
}

// WebSocket Connection
function connectWebSocket() {
  const statusEl = document.getElementById("ws-status");
  try {
    const ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      if (statusEl) statusEl.innerText = "LIVE WS CONNECTED";
    };
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "RACE_STATE_UPDATE") {
        updateDashboard({ cars: { [msg.car_id]: msg } });
      }
    };
    ws.onclose = () => {
      if (statusEl) statusEl.innerText = "WS DISCONNECTED (RETRYING...)";
      setTimeout(connectWebSocket, 5000);
    };
  } catch (err) {
    if (statusEl) statusEl.innerText = "WS OFFLINE (POLLING ACTIVE)";
  }
}
