# RateSift Agent Training Playground (Isolated IDE Sandbox)

This directory is a self-contained, isolated environment designed to test and iterate on **RateSift Agent training ideas, prompt variations, and rule adherence** directly within the IDE without launching the website or modifying production files.

---

## 🛡️ Safety & Non-Interference Guarantee

- **Zero Website Changes:** Does NOT modify `main.py`, `templates/`, `static/`, `services/`, or `shipflow.db`.
- **Zero Server Execution:** Does NOT run `uvicorn`, FastAPI, or open external web ports.
- **Embedded Tariffs:** Uses confirmed tariff matrices (Day & Ross Canadian LTL Guide #1, Purolator Parcel, and Intermodal Rail) packaged inside the playground.

---

## 🚀 How to Use the HTML Simulator in the IDE

Open [`standalone_quote_view.html`](file:///c:/Users/Dylan/Documents/antigravity/quick-hertz/agent_playground/standalone_quote_view.html) directly in your IDE preview or default browser:

1. **Exact "New Quote" Page Layout:**
   - Vertical **From** and **To** location sections with horizontal fields for City Name, Province/State, Postal Code/Zip, and Country.
   - Cargo dimensions, weight (lbs), and shipment date.
   - 8 conditional accessorial checkboxes.
2. **Instant Client-Side Calculation:**
   - Embedded JavaScript engine calculates CWT rates, DIM divisor (139), minimum charge floors, and itemized surcharges dynamically upon clicking **"Run Agent & Calculate Rates"**.
3. **Training Ideas & Experimentation Panel:**
   - Toggle between 4 Agent Training Variants:
     - **Strict 32 Rules:** Baseline production behavior.
     - **Flexible Broker:** Auto-resolves missing origin to Company HQ and bypasses non-critical business metadata.
     - **Deep Auditor:** Forensically audits buried footnotes, minimum surcharges, and cell coordinates.
     - **Speed Priority:** Evaluates express logistics ranking by transit days.
   - 1-click test scenarios to instantly inspect edge cases.
   - Real-time **Agent Reasoning & Rule Trace** drawer showing which of the 32 RateSift Rules fired.
   - **JSON Import / Export:** Bridge results between Python scripts and the visual simulator.

---

## 🐍 Python Training Benchmark Runner

Run the benchmark CLI directly in your IDE terminal:

```powershell
# Run baseline strict 32 rules agent
python agent_playground/run_agent_training.py

# Test the flexible broker assistant (non-critical info bypass)
python agent_playground/run_agent_training.py --variant variant_2_flexible_broker

# Compare all 4 training variants side-by-side
python agent_playground/run_agent_training.py --compare-all

# Export run to JSON for the HTML simulator
python agent_playground/run_agent_training.py --compare-all --export-json agent_playground/benchmark_results.json
```

---

## 📁 Package Structure

```
c:\Users\Dylan\Documents\antigravity\quick-hertz\agent_playground\
├── README.md                               # This documentation
├── standalone_quote_view.html               # Zero-server interactive HTML simulator mimicking New Quote page
├── run_agent_training.py                    # Python benchmark CLI to test training variants
└── agent/                                   # Copied RateSift Agent module
    ├── __init__.py
    ├── rate_agent.py                       # Master agent controller & reasoning pipeline
    ├── agent_prompts.py                    # Prompt variants, few-shot templates & scenarios
    ├── rules_spec.py                       # Programmatic definitions of all 32 RateSift Rules
    ├── tariffs_data.py                     # Embedded Day & Ross Guide #1, Purolator, and Rail tariffs
    └── engine_copy.py                      # Copied deterministic rating math (DIM, CWT, min floors)
```
