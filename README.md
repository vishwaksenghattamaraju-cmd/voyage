# Voyage AI - Multi-Agent Travel Planner

Voyage AI is an autonomous, multi-agent travel planning web application built with Python and Flask. It designs detailed, balanced, day-by-day travel itineraries with customized activity recommendations, accommodation options, ground transit analysis, and cost calculations computed strictly in Python.

Voyage AI supports multiple LLM providers, including **100% free options** and an **offline demonstration mode** that requires no API keys whatsoever!

---

## Supported LLM Providers

| Provider | Model / Engine | Cost / Tier | API Key Setup |
| :--- | :--- | :--- | :--- |
| **Rule-Based Engine** | Pure-Python Multi-Agent Engine | **Free ($0.00)** | **None needed** (Default fallback when no key is set) |
| **Google Gemini** | `gemini-1.5-flash` | **Free Tier** | Free key from [Google AI Studio](https://aistudio.google.com/app/apikey) |
| **Groq Cloud** | `llama-3.3-70b-versatile` | **Free Tier** | Free key from [Groq Console](https://console.groq.com/keys) |
| **OpenAI** | `gpt-4o-mini` | Paid Tier | Key from [OpenAI Platform](https://platform.openai.com/api-keys) |

> [!TIP]
> **No API Key? No Problem!**  
> If you do not have an API key, the app runs in **Pure-Python Rule-Based / Demo Mode** out of the box. It uses a curated local destination knowledge base and rule-based agent modules (`planner/`) to generate complete, realistic day-by-day itineraries, lodging options, transit guidance, and budget breakdowns locally without paying anything or sending network requests!

---

## Architecture & Autonomous Agent Pipeline

Voyage AI coordinates four specialized agents in strict sequence:

1. **Destination & Activity Agent:** Curates 3–4 tailored local attractions, cultural landmarks, dining spots, and hidden gems based on destination, duration, budget tier, and traveler interests.
2. **Stay & Accommodation Agent:** Recommends exactly two lodging options (e.g. primary recommendation and alternative) and establishes the destination's ISO 4217 currency code. Never claims real-time availability or reservations.
3. **Logistics & Transit Agent:** Receives the currency chosen by Agent 2, providing local transit infrastructure overviews, specific transit modes, daily cost estimates, safety advice, and a checklist of items to verify before departure.
4. **Coordinator & Itinerary Synthesizer:** Integrates findings from Agents 1–3 into a cohesive day-by-day schedule (`1..duration_days`), calculates cost input figures, lists key planning assumptions, and provides practical advice.

### Mathematical Accuracy (Python Arithmetic)
To eliminate AI hallucination in math, budget totals are computed deterministically in Python:
- $\text{nights} = \max(\text{days} - 1, 0)$
- $\text{accommodation} = \text{accommodation\_per\_night} \times \text{nights}$
- $\text{food} = \text{food\_per\_day} \times \text{days}$
- $\text{transport} = \text{transport\_per\_day} \times \text{days}$
- $\text{activities} = \text{activities\_total}$
- $\text{total} = \text{accommodation} + \text{food} + \text{transport} + \text{activities}$

---

## Recommended: Run Offline Without Any API Keys

The project includes a Python rule-based planning engine and local destination data. You do **not** need OpenAI, Gemini, Groq, or any other LLM API to generate a trip. To avoid accidental cloud API calls, use the included PowerShell launcher:

```powershell
.\run_offline.ps1
```

This sets `DEMO_MODE=true` and `LLM_PROVIDER=rule_based` for that process before starting Flask. It takes precedence over API keys in an existing `.env` file. The plan is generated from local rules and sample data; costs and availability are estimates, not live quotes.

If you prefer to launch manually in PowerShell:

```powershell
$env:DEMO_MODE = "true"
$env:LLM_PROVIDER = "rule_based"
python app.py
```

For a clean install, create a virtual environment and install the dependencies listed in `requirements.txt`. The optional Gemini, Groq, and OpenAI packages are only needed if you explicitly choose those cloud providers.

---

## Step-by-Step Setup Guide (Windows & VS Code)

### Prerequisites: Python Installation
1. If you don't have Python installed, download Python 3.10+ from [python.org](https://www.python.org/downloads/).
2. **CRITICAL:** During installation on Windows, ensure you check the box:  
   **"Add python.exe to PATH"** before clicking "Install Now".

---

### Step 1: Open the Project in VS Code
1. Launch **Visual Studio Code**.
2. Go to **File** &gt; **Open Folder...** and select this directory:  
   `multi agent travel management`
3. Open a PowerShell terminal in VS Code:  
   Press <kbd>Ctrl</kbd> + <kbd>`</kbd> (backtick) or select **Terminal** &gt; **New Terminal**.

---

### Step 2: Activate the Virtual Environment
Activate the environment in PowerShell:
```powershell
.venv\Scripts\Activate.ps1
```
*(You will see `(.venv)` appear at the beginning of your terminal prompt).*

> [!NOTE]
> **PowerShell Script Execution Error?**  
> If Windows blocks activating scripts with an execution policy error, run:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```
> Then run `.venv\Scripts\Activate.ps1` again.

---

### Step 3: Configure Environment Variables (Optional)

1. Create your `.env` file from `.env.example`:
   ```powershell
   Copy-Item .env.example .env
   ```
2. Open `.env` in VS Code and choose your provider:

#### Option A: 100% Free - Google Gemini (Recommended)
1. Get a free API key at [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Set in `.env`:
   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=AIzaSy...your_gemini_key_here
   ```

#### Option B: 100% Free - Groq Cloud (Ultra-Fast Llama 3.3)
1. Get a free API key at [Groq Console](https://console.groq.com/keys).
2. Set in `.env`:
   ```env
   LLM_PROVIDER=groq
   GROQ_API_KEY=gsk_...your_groq_key_here
   ```

#### Option C: Offline Demonstration Mode (Zero Setup, No Key)
Leave `.env` empty or set:
```env
LLM_PROVIDER=mock
```
The app will generate realistic, complete itineraries locally with zero external network dependencies!

#### Option D: Paid OpenAI API
```env
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...your_key_here
```

---

### Step 4: Start the Application
Run the Flask server:
```powershell
python app.py
```

You will see output indicating the active provider:
```text
[INFO] Active LLM Provider: GEMINI (or MOCK)
 * Serving Flask app 'app'
 * Running on http://127.0.0.1:5000
```

---

### Step 5: Open the App in Your Browser
Open your web browser and navigate to:
```
http://127.0.0.1:5000
```

---

### Deactivating the Virtual Environment
When you are done testing, you can exit the virtual environment by typing:
```powershell
deactivate
```

---

## API Routes Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Renders the single-page travel planner frontend with active provider indicator. |
| `POST` | `/api/recommend-destination` | Accepts travel preferences (`budget`, `duration_days`, `interests`, `companions`, `climate`) and returns ranked destination suggestions (`200 OK`). |
| `POST` | `/api/plan` | Accepts `destination`, `duration_days`, `budget`, optional `interests`, `companions`, `climate`. Runs the multi-agent pipeline with automatic fallback, computes budget, stores, and returns trip JSON (`201 Created`). |
| `GET` | `/api/trips` | Returns an array of all saved trips sorted newest-first (`200 OK`). |
| `GET` | `/api/trips/<trip_id>` | Returns details for a specific saved trip (`200 OK` or `404 Not Found`). |

---

## Running the Automated Test Suite

All external AI requests are mocked in unit tests, and rule-based tests run entirely offline, so **no API key or internet access is required to run tests**.

To execute all 38 unit and integration tests:
```powershell
.venv\Scripts\python -m unittest discover tests -v
```

---

## Troubleshooting

### 1. "OpenAI API key is missing or not configured"
**Solution:** Either:
- Switch to Google Gemini by adding your free `GEMINI_API_KEY` in `.env`.
- Switch to Groq by adding your free `GROQ_API_KEY` in `.env`.
- Or set `LLM_PROVIDER=mock` in `.env` (or delete the keys) to run in offline demonstration mode.

### 2. PowerShell Script Execution Policy Error
**Error:** `File ... Activate.ps1 cannot be loaded because running scripts is disabled on this system.`  
**Fix:** Run:
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

### 3. Port 5000 Already in Use
**Error:** `Address already in use`  
**Fix:** Close any other running terminal window, or run Flask on port 5001:
```powershell
python -c "from app import app; app.run(port=5001)"
```
Then visit `http://127.0.0.1:5001`.
