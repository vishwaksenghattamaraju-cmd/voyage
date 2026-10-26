# Start Voyage AI in offline rule-based mode. No LLM API keys or network calls are required.
$ErrorActionPreference = "Stop"
$env:DEMO_MODE = "true"
$env:LLM_PROVIDER = "rule_based"
Write-Host "Starting Voyage AI in offline mode. No paid API will be called." -ForegroundColor Green
python app.py
