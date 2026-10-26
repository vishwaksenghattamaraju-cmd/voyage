"""app.py - Voyage AI Multi-Agent Travel Planner Flask Application

Provides web routes and REST API endpoints:
- GET / : Renders main application page
- POST /api/plan : Validates input, executes the 4 agents (with rule-based fallback), saves and returns plan
- POST /api/recommend-destination : Returns ranked destination suggestions based on preferences
- GET /api/trips : Returns all saved trips (newest first)
- GET /api/trips/<trip_id> : Returns details of a specific saved trip
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

# Load environment variables from .env
load_dotenv()

from agents import AgentError, get_active_provider, run_agents
from planner.destination_agent import recommend_destinations

# Configure application logging (never log API keys or secrets)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voyage_ai")

# Active provider detection notice
_active_provider = get_active_provider()
if _active_provider in ("rule_based", "mock"):
    print(
        "[INFO] Voyage AI is running in Rule-Based Offline Mode ($0 cost, no API keys needed). "
        "Complete travel plans will be generated using the local knowledge base.",
        file=sys.stderr,
    )
elif _active_provider == "gemini":
    print("[INFO] Active LLM Provider: Google Gemini (with automatic rule-based fallback).", file=sys.stderr)
elif _active_provider == "groq":
    print("[INFO] Active LLM Provider: Groq Cloud (with automatic rule-based fallback).", file=sys.stderr)
elif _active_provider == "openai":
    print("[INFO] Active LLM Provider: OpenAI (with automatic rule-based fallback).", file=sys.stderr)

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Default trips file location (overridable by tests or environment)
app.config["TRIPS_FILE"] = os.environ.get(
    "TRIPS_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "trips.json")
)

# Concurrency lock for safe file operations
_storage_lock = threading.Lock()

ALLOWED_INTERESTS = [
    "Food",
    "Culture",
    "Nature",
    "Adventure",
    "Shopping",
    "History",
    "Technology",
]
ALLOWED_BUDGETS = {"Budget", "Moderate", "Luxury"}
ALLOWED_COMPANIONS = ["Solo", "Couple", "Family", "Friends"]
ALLOWED_CLIMATES = ["Any", "Warm/Tropical", "Temperate/Mild", "Cool/Alpine"]
MAX_DAYS = 30


class StorageCorruptedError(Exception):
    """Raised when trips.json exists but contains invalid JSON or structure."""
    pass


# =====================================================================
# Atomic Storage Helpers
# =====================================================================

def _save_trips_unlocked(filepath: str, trips: List[Dict[str, Any]]) -> None:
    """Write trips list atomically to disk using a temporary file and os.replace."""
    dir_name = os.path.dirname(os.path.abspath(filepath)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix="trips_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(trips, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, filepath)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _load_trips_locked(filepath: str) -> List[Dict[str, Any]]:
    """Load trips from the JSON file with thread safety, auto-creation, and corruption backup."""
    with _storage_lock:
        if not os.path.exists(filepath):
            _save_trips_unlocked(filepath, [])
            return []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
            if not isinstance(data, list):
                raise ValueError("Trips content root is not a list")
            return data
        except (json.JSONDecodeError, ValueError) as err:
            timestamp = int(time.time())
            corrupt_path = f"{filepath}.corrupt-{timestamp}.json"
            try:
                shutil.copyfile(filepath, corrupt_path)
                logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
            except Exception as copy_err:
                logger.error("Failed to create backup of corrupted trips file: %s", copy_err)
            raise StorageCorruptedError(
                f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
            )


def _add_trip_locked(filepath: str, trip_data: Dict[str, Any]) -> None:
    """Prepend a newly generated trip to trips.json atomically under lock."""
    with _storage_lock:
        trips = []
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    trips = json.loads(content) if content else []
                if not isinstance(trips, list):
                    raise ValueError("Trips file is not a list")
            except (json.JSONDecodeError, ValueError) as err:
                timestamp = int(time.time())
                corrupt_path = f"{filepath}.corrupt-{timestamp}.json"
                try:
                    shutil.copyfile(filepath, corrupt_path)
                    logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
                except Exception:
                    pass
                raise StorageCorruptedError(
                    f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
                )

        trips.insert(0, trip_data)
        _save_trips_unlocked(filepath, trips)


def _delete_trip_locked(filepath: str, trip_id: str) -> bool:
    """Delete a trip by trip_id from trips.json under lock. Returns True if deleted, False if not found."""
    with _storage_lock:
        if not os.path.exists(filepath):
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                trips = json.loads(content) if content else []
            if not isinstance(trips, list):
                raise ValueError("Trips file is not a list")
        except (json.JSONDecodeError, ValueError) as err:
            timestamp = int(time.time())
            corrupt_path = f"{filepath}.corrupt-{timestamp}.json"
            try:
                shutil.copyfile(filepath, corrupt_path)
                logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
            except Exception:
                pass
            raise StorageCorruptedError(
                f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
            )

        clean_id = trip_id.strip().lower()
        original_len = len(trips)
        trips = [t for t in trips if str(t.get("trip_id", "")).strip().lower() != clean_id]
        if len(trips) == original_len:
            return False

        _save_trips_unlocked(filepath, trips)
        return True


# =====================================================================
# Server-Side Input Validation
# =====================================================================

def is_valid_destination_chars(text: str) -> bool:
    """Validate that text only contains letters (any language), digits, spaces, and , . ' ( ) -"""
    allowed_punct = {",", ".", "'", "(", ")", "-"}
    for ch in text:
        if ch.isalnum() or ch.isspace() or ch in allowed_punct:
            continue
        return False
    return True


def validate_plan_request(data: Any) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Validate POST /api/plan payload strictly before invoking agents.

    Returns:
        (cleaned_data, error_dict)
    """
    if not isinstance(data, dict):
        return None, {
            "code": "VALIDATION_ERROR",
            "message": "Request body must be a valid JSON object.",
        }

    # 1. Destination
    raw_dest = data.get("destination")
    recommend_flag = bool(data.get("recommend_destination", False))

    if raw_dest is None or not isinstance(raw_dest, str):
        if not recommend_flag:
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Destination is required.",
                "field": "destination",
            }
        destination = "Recommend"
    else:
        destination = raw_dest.strip()
        if not destination:
            if not recommend_flag:
                return None, {
                    "code": "VALIDATION_ERROR",
                    "message": "Destination cannot be empty.",
                    "field": "destination",
                }
            destination = "Recommend"
        elif len(destination) > 80:
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Destination must not exceed 80 characters.",
                "field": "destination",
            }
        elif not is_valid_destination_chars(destination):
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Destination may only contain letters, numbers, spaces, and , . ' ( ) - characters.",
                "field": "destination",
            }

    # 2. Duration Days
    raw_days = data.get("duration_days")
    if isinstance(raw_days, bool) or not isinstance(raw_days, int):
        return None, {
            "code": "VALIDATION_ERROR",
            "message": "Duration must be an integer whole number between 1 and 30.",
            "field": "duration_days",
        }
    if raw_days < 1 or raw_days > MAX_DAYS:
        return None, {
            "code": "VALIDATION_ERROR",
            "message": f"Duration must be between 1 and {MAX_DAYS} days.",
            "field": "duration_days",
        }

    # 3. Budget
    raw_budget = data.get("budget")
    if raw_budget not in ALLOWED_BUDGETS:
        return None, {
            "code": "VALIDATION_ERROR",
            "message": "Budget must be exactly 'Budget', 'Moderate', or 'Luxury'.",
            "field": "budget",
        }

    # 4. Interests (Optional)
    raw_interests = data.get("interests", [])
    if raw_interests is None:
        raw_interests = []
    if not isinstance(raw_interests, list):
        return None, {
            "code": "VALIDATION_ERROR",
            "message": "Interests must be an array of strings.",
            "field": "interests",
        }

    allowed_map = {item.lower(): item for item in ALLOWED_INTERESTS}
    cleaned_interests: List[str] = []
    seen = set()

    for item in raw_interests:
        if not isinstance(item, str):
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Each interest item must be a string.",
                "field": "interests",
            }
        key = item.strip().lower()
        if not key:
            continue
        if key not in allowed_map:
            return None, {
                "code": "VALIDATION_ERROR",
                "message": f"Invalid interest '{item}'. Allowed interests: {', '.join(ALLOWED_INTERESTS)}.",
                "field": "interests",
            }
        canonical = allowed_map[key]
        if canonical not in seen:
            seen.add(canonical)
            cleaned_interests.append(canonical)

    # 5. Travel Companions (Optional)
    raw_comp = data.get("companions", "Solo")
    companions = "Solo"
    if isinstance(raw_comp, str) and raw_comp.strip():
        c_title = raw_comp.strip().capitalize()
        if c_title in ALLOWED_COMPANIONS:
            companions = c_title

    # 6. Preferred Climate (Optional)
    raw_climate = data.get("climate", "Any")
    climate = "Any"
    if isinstance(raw_climate, str) and raw_climate.strip():
        for ac in ALLOWED_CLIMATES:
            if raw_climate.strip().lower() == ac.lower():
                climate = ac
                break

    return {
        "destination": destination,
        "duration_days": raw_days,
        "budget": raw_budget,
        "interests": cleaned_interests,
        "companions": companions,
        "climate": climate,
    }, None


# =====================================================================
# Routes
# =====================================================================

@app.after_request
def add_no_cache_headers(response):
    """Ensure static files and HTML templates reload immediately during development."""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.route("/")
def index():
    """Render the main single-page travel planner interface."""
    current_provider = get_active_provider()
    return render_template(
        "index.html",
        allowed_interests=ALLOWED_INTERESTS,
        allowed_companions=ALLOWED_COMPANIONS,
        allowed_climates=ALLOWED_CLIMATES,
        max_days=MAX_DAYS,
        active_provider=current_provider,
        cache_bust=int(time.time()),
    )


@app.route("/api/recommend-destination", methods=["POST"])
def get_destination_recommendations():
    """Recommend destinations based on budget, duration, interests, companions, and climate."""
    payload = request.get_json(silent=True) or {}
    budget = payload.get("budget", "Moderate")
    raw_days = payload.get("duration_days", 3)
    duration_days = raw_days if isinstance(raw_days, int) and 1 <= raw_days <= MAX_DAYS else 3
    interests = payload.get("interests", [])
    companions = payload.get("companions", "Solo")
    climate = payload.get("climate", "Any")

    recs = recommend_destinations(
        budget=budget,
        duration_days=duration_days,
        interests=interests,
        companions=companions,
        climate=climate,
        top_k=3,
    )
    return jsonify({"ok": True, "recommendations": recs}), 200


@app.route("/api/plan", methods=["POST"])
def create_plan():
    """Generate a new travel plan using multi-agent pipeline with automatic rule-based fallback."""
    payload = request.get_json(silent=True)
    cleaned, err = validate_plan_request(payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    assert cleaned is not None
    try:
        agent_kwargs = {
            "destination": cleaned["destination"],
            "duration_days": cleaned["duration_days"],
            "budget": cleaned["budget"],
            "interests": cleaned["interests"],
        }
        if payload and "companions" in payload:
            agent_kwargs["companions"] = cleaned["companions"]
        if payload and "climate" in payload:
            agent_kwargs["climate"] = cleaned["climate"]

        plan = run_agents(**agent_kwargs)
    except AgentError as agent_err:
        logger.warning("AgentError during plan generation: [%s] %s", agent_err.code, agent_err.message)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": agent_err.code,
                    "message": agent_err.message,
                },
            }),
            agent_err.status_code,
        )
    except Exception as exc:
        logger.exception("Unexpected internal exception in /api/plan: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred while generating your plan. Please try again later.",
                },
            }),
            500,
        )

    # Attach identifiers and timestamp
    trip_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    trip_data = {
        "trip_id": trip_id,
        "created_at": created_at,
        **plan,
    }

    try:
        _add_trip_locked(app.config["TRIPS_FILE"], trip_data)
    except StorageCorruptedError as storage_err:
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "DATA_CORRUPT",
                    "message": str(storage_err),
                },
            }),
            500,
        )
    except Exception as exc:
        logger.exception("Failed to save trip to disk: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Failed to persist trip to disk.",
                },
            }),
            500,
        )

    return jsonify({"ok": True, "trip": trip_data}), 201


@app.route("/api/trips", methods=["GET"])
def get_trips():
    """Return all saved trips, newest first."""
    try:
        trips = _load_trips_locked(app.config["TRIPS_FILE"])
        sorted_trips = sorted(
            trips,
            key=lambda t: t.get("created_at", ""),
            reverse=True,
        )
        return jsonify({"ok": True, "trips": sorted_trips}), 200
    except StorageCorruptedError as corrupt_err:
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "DATA_CORRUPT",
                    "message": str(corrupt_err),
                },
            }),
            500,
        )
    except Exception as exc:
        logger.exception("Failed to read trips: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Failed to load saved trips.",
                },
            }),
            500,
        )


@app.route("/api/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id: str):
    """Retrieve a single saved trip by trip_id."""
    clean_id = trip_id.strip().lower()
    try:
        trips = _load_trips_locked(app.config["TRIPS_FILE"])
    except StorageCorruptedError as corrupt_err:
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "DATA_CORRUPT",
                    "message": str(corrupt_err),
                },
            }),
            500,
        )
    except Exception as exc:
        logger.exception("Failed to read trips: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Failed to load saved trips.",
                },
            }),
            500,
        )

    for trip in trips:
        if str(trip.get("trip_id", "")).strip().lower() == clean_id:
            return jsonify({"ok": True, "trip": trip}), 200

    return (
        jsonify({
            "ok": False,
            "error": {
                "code": "NOT_FOUND",
                "message": f"Trip with ID '{trip_id}' was not found.",
            },
        }),
        404,
    )


@app.route("/api/trips/<trip_id>", methods=["DELETE"])
def delete_trip(trip_id: str):
    """Delete a single saved trip by trip_id."""
    clean_id = trip_id.strip()
    try:
        deleted = _delete_trip_locked(app.config["TRIPS_FILE"], clean_id)
        if not deleted:
            return (
                jsonify({
                    "ok": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Trip with ID '{trip_id}' was not found.",
                    },
                }),
                404,
            )
        return jsonify({"ok": True, "message": "Trip deleted successfully."}), 200
    except StorageCorruptedError as corrupt_err:
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "DATA_CORRUPT",
                    "message": str(corrupt_err),
                },
            }),
            500,
        )
    except Exception as exc:
        logger.exception("Failed to delete trip: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Failed to delete trip.",
                },
            }),
            500,
        )


# =====================================================================
# Error Handlers
# =====================================================================

@app.errorhandler(404)
def handle_not_found(e):
    if request.path.startswith("/api/"):
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "NOT_FOUND",
                    "message": "The requested API endpoint was not found.",
                },
            }),
            404,
        )
    return "Page Not Found", 404


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return (
        jsonify({
            "ok": False,
            "error": {
                "code": "METHOD_NOT_ALLOWED",
                "message": f"Method {request.method} is not allowed for this route.",
            },
        }),
        405,
    )


@app.errorhandler(500)
def handle_internal_server_error(e):
    logger.exception("Flask 500 handler triggered: %s", e)
    return (
        jsonify({
            "ok": False,
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred.",
            },
        }),
        500,
    )


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0").strip() == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)
