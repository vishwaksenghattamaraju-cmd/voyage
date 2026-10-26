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
from destinations_service import (
    get_attraction_by_id,
    get_autocomplete_suggestions,
    get_catalog_facets,
    get_destination_autocomplete,
    get_place_details,
    is_google_places_configured,
    load_attractions,
    recommend_attractions_for_trip,
    search_attractions,
)
from planner.destination_agent import recommend_destinations
from storage import (
    StorageCorruptedError,
    StorageError,
    add_trip,
    delete_trip as storage_delete_trip,
    get_default_trips_filepath,
    get_trip_by_id,
    is_supabase_configured,
    load_trips,
    update_trip as storage_update_trip,
    _save_trips_file_unlocked as _save_trips_unlocked,
    _load_trips_file_locked as _load_trips_locked,
    _add_trip_file_locked as _add_trip_locked,
    _delete_trip_file_locked as _delete_trip_locked,
)

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

# Log storage engine status
if is_supabase_configured():
    print("[INFO] Production Storage: Connected to Supabase PostgreSQL Database (Cloud Persistence).", file=sys.stderr)
else:
    print(
        f"[INFO] Local Storage: Using file storage at '{get_default_trips_filepath()}' "
        "(Set SUPABASE_URL and SUPABASE_KEY for permanent cloud storage on Vercel).",
        file=sys.stderr,
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
    static_url_path="/static",
)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["TRIPS_FILE"] = get_default_trips_filepath()

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


# =====================================================================
# Server-Side Input Validation
# =====================================================================

def is_valid_destination_chars(text: str) -> bool:
    """Validate that text only contains letters (any language), digits, spaces, and safe punctuation."""
    allowed_punct = {",", ".", "'", "(", ")", "-", "&", "/", ":"}
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
        elif len(destination) > 160:
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Destination must not exceed 160 characters.",
                "field": "destination",
            }
        elif not is_valid_destination_chars(destination):
            return None, {
                "code": "VALIDATION_ERROR",
                "message": "Destination may only contain letters, numbers, spaces, and punctuation characters.",
                "field": "destination",
            }

    # Optional Google Place ID & Location Context
    raw_place_id = data.get("place_id")
    place_id = str(raw_place_id).strip() if raw_place_id and isinstance(raw_place_id, str) else None

    raw_loc_ctx = data.get("location_context")
    location_context = str(raw_loc_ctx).strip() if raw_loc_ctx and isinstance(raw_loc_ctx, str) else None

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

    # 7. Selected Attractions (Optional)
    raw_selected = data.get("selected_attractions", [])
    cleaned_attractions: List[Any] = []
    if isinstance(raw_selected, list):
        for it in raw_selected[:15]:
            if isinstance(it, str) and it.strip():
                cleaned_attractions.append(it.strip()[:100])
            elif isinstance(it, dict) and it.get("name"):
                cleaned_attractions.append({
                    "name": str(it.get("name"))[:100],
                    "city": str(it.get("city", ""))[:60],
                    "country": str(it.get("country", ""))[:60],
                    "category": str(it.get("category", ""))[:40],
                    "description": str(it.get("description", ""))[:300],
                })

    return {
        "destination": destination,
        "duration_days": raw_days,
        "budget": raw_budget,
        "interests": cleaned_interests,
        "companions": companions,
        "climate": climate,
        "place_id": place_id,
        "location_context": location_context,
        "selected_attractions": cleaned_attractions,
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
        is_cloud_db=is_supabase_configured(),
        has_google_places=is_google_places_configured(),
        cache_bust=int(time.time()),
    )


@app.route("/api/destinations/search", methods=["GET"])
def destinations_search():
    """Faceted search across worldwide tourist destinations and attractions."""
    query = request.args.get("query", "")
    continent = request.args.get("continent", "")
    country = request.args.get("country", "")
    category = request.args.get("category", "")
    budget = request.args.get("budget", "")
    traveler_type = request.args.get("traveler_type", "")
    tag = request.args.get("tag", "")
    sort_by = request.args.get("sort_by", "name")
    
    try:
        limit = max(1, min(100, int(request.args.get("limit", 50))))
    except (ValueError, TypeError):
        limit = 50

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except (ValueError, TypeError):
        offset = 0

    res = search_attractions(
        query=query,
        continent=continent,
        country=country,
        category=category,
        budget=budget,
        traveler_type=traveler_type,
        tag=tag,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    return jsonify({"ok": True, **res}), 200


@app.route("/api/destinations/autocomplete", methods=["GET"])
def destinations_autocomplete():
    """Fast, local typeahead autocomplete by destination name, city, country, or tag."""
    query = request.args.get("query") or request.args.get("input") or ""
    try:
        limit = max(1, min(20, int(request.args.get("limit", 8))))
    except (ValueError, TypeError):
        limit = 8
    suggestions = get_destination_autocomplete(query=query, limit=limit)
    return jsonify({"ok": True, "suggestions": suggestions}), 200


@app.route("/api/destinations/facets", methods=["GET"])
def destinations_facets():
    """Return filter facets with attraction counts for continents, countries, categories, etc."""
    facets = get_catalog_facets()
    return jsonify({"ok": True, "facets": facets}), 200


@app.route("/api/destinations/<attraction_id>", methods=["GET"])
def destinations_get_by_id(attraction_id: str):
    """Retrieve full details for a single tourist attraction by its ID."""
    attraction = get_attraction_by_id(attraction_id)
    if not attraction:
        return jsonify({"ok": False, "error": {"code": "NOT_FOUND", "message": "Attraction not found"}}), 404
    return jsonify({"ok": True, "attraction": attraction}), 200


@app.route("/api/destinations/recommend", methods=["POST"])
def destinations_recommend():
    """Recommend attractions from the worldwide database matching trip parameters."""
    payload = request.get_json(silent=True) or {}
    dest = payload.get("destination", "")
    budget = payload.get("budget", "Moderate")
    raw_days = payload.get("duration_days", 3)
    duration_days = raw_days if isinstance(raw_days, int) and 1 <= raw_days <= MAX_DAYS else 3
    interests = payload.get("interests", [])
    companions = payload.get("companions", "Solo")
    climate = payload.get("climate", "Any")
    try:
        limit = max(1, min(20, int(payload.get("limit", 6))))
    except (ValueError, TypeError):
        limit = 6

    recs = recommend_attractions_for_trip(
        destination=dest,
        budget=budget,
        duration_days=duration_days,
        interests=interests,
        companions=companions,
        climate=climate,
        limit=limit,
    )
    return jsonify({"ok": True, "recommendations": recs}), 200


@app.route("/api/places/autocomplete", methods=["GET"])
def places_autocomplete():
    """Return worldwide destination autocomplete suggestions via Google Places API (New) or offline atlas."""
    query = request.args.get("query") or request.args.get("input") or ""
    session_token = request.args.get("session_token")
    res = get_autocomplete_suggestions(query=query, session_token=session_token)
    return jsonify(res), 200


@app.route("/api/places/details", methods=["GET"])
def places_details():
    """Retrieve detailed location data for a selected Google Places identifier."""
    place_id = request.args.get("place_id") or ""
    session_token = request.args.get("session_token")
    if not place_id:
        return jsonify({"ok": False, "error": {"code": "VALIDATION_ERROR", "message": "place_id is required"}}), 400
    res = get_place_details(place_id=place_id, session_token=session_token)
    if not res:
        return jsonify({"ok": False, "error": {"code": "NOT_FOUND", "message": "Place details not found"}}), 404
    return jsonify({"ok": True, "place": res}), 200


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
        if cleaned.get("place_id"):
            agent_kwargs["place_id"] = cleaned["place_id"]
        if cleaned.get("location_context"):
            agent_kwargs["location_context"] = cleaned["location_context"]
        if cleaned.get("selected_attractions"):
            agent_kwargs["selected_attractions"] = cleaned["selected_attractions"]

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
        add_trip(trip_data, filepath=app.config.get("TRIPS_FILE"))
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
    except StorageError as storage_err:
        logger.exception("Storage failure saving trip: %s", storage_err)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
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
        trips = load_trips(filepath=app.config.get("TRIPS_FILE"))
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
    except StorageError as storage_err:
        logger.exception("Storage failure reading trips: %s", storage_err)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": str(storage_err),
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
    clean_id = trip_id.strip()
    try:
        trip = get_trip_by_id(clean_id, filepath=app.config.get("TRIPS_FILE"))
        if trip:
            return jsonify({"ok": True, "trip": trip}), 200
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
    except StorageError as storage_err:
        logger.exception("Storage failure reading trip %s: %s", trip_id, storage_err)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": str(storage_err),
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


@app.route("/api/trips/<trip_id>", methods=["PUT"])
def update_trip_endpoint(trip_id: str):
    """Update an existing saved trip by trip_id."""
    clean_id = trip_id.strip()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request body must be a valid JSON object.",
                },
            }),
            400,
        )

    try:
        updated = storage_update_trip(clean_id, payload, filepath=app.config.get("TRIPS_FILE"))
        if not updated:
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
        return jsonify({"ok": True, "message": "Trip updated successfully."}), 200
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
    except StorageError as storage_err:
        logger.exception("Storage failure updating trip %s: %s", trip_id, storage_err)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": str(storage_err),
                },
            }),
            500,
        )
    except Exception as exc:
        logger.exception("Failed to update trip: %s", exc)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": "Failed to update trip.",
                },
            }),
            500,
        )


@app.route("/api/trips/<trip_id>", methods=["DELETE"])
def delete_trip(trip_id: str):
    """Delete a single saved trip by trip_id."""
    clean_id = trip_id.strip()
    try:
        deleted = storage_delete_trip(clean_id, filepath=app.config.get("TRIPS_FILE"))
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
    except StorageError as storage_err:
        logger.exception("Storage failure deleting trip %s: %s", trip_id, storage_err)
        return (
            jsonify({
                "ok": False,
                "error": {
                    "code": "STORAGE_ERROR",
                    "message": str(storage_err),
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
