"""agents.py - Multi-Agent Travel Planner Engine

This module coordinates both autonomous LLM agents and pure-Python rule-based agents:
1. Destination & Activity Agent: recommends local attractions, dining, and culture.
2. Stay & Accommodation Agent: recommends lodging options and establishes currency.
3. Logistics & Transit Agent: analyzes ground transport, daily costs, and safety.
4. Coordinator & Itinerary Synthesizer: constructs a balanced day-by-day plan.

Reliability & Offline Mode:
- Works 100% offline without any external LLM keys or network access via pure-Python rule-based planning.
- If an LLM provider (OpenAI, Gemini, Groq) is configured but fails or times out, the engine
  gracefully switches to the rule-based planner without crashing or returning an error to the user.
- Cost calculations are strictly computed in Python to guarantee mathematical accuracy.
"""

import json
import logging
import math
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from planner.budget_agent import estimate_budget
from planner.destination_agent import (
    filter_accommodations_for_budget,
    recommend_destinations,
    resolve_or_create_destination,
)
from planner.itinerary_agent import build_itinerary
from planner.travel_tips_agent import generate_logistics_and_tips

logger = logging.getLogger(__name__)

# Shared lazy client instances
_client = None
_active_provider = None


class AgentError(Exception):
    """Custom exception raised when an agent encounters an error or validation failure."""

    def __init__(self, message: str, code: str = "AGENT_ERROR", status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# =====================================================================
# Provider Resolution & Client Management
# =====================================================================

def get_active_provider() -> str:
    """Determine the active LLM provider based on environment variables.

    Returns one of: 'rule_based', 'gemini', 'groq', 'openai', or 'mock'.
    """
    if os.environ.get("DEMO_MODE", "").strip().lower() in ("true", "1", "yes"):
        return "rule_based"

    explicit = os.environ.get("LLM_PROVIDER", "auto").strip().lower()
    if explicit in ("rule_based", "gemini", "groq", "openai", "mock"):
        return explicit

    # Auto-detection: check keys in priority order
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
    if gemini_key and gemini_key not in ("your_gemini_api_key_here", "your_actual_gemini_api_key"):
        return "gemini"

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and groq_key not in ("your_groq_api_key_here", "your_actual_groq_api_key"):
        return "groq"

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key and openai_key not in ("your_openai_api_key_here", "your_actual_openai_api_key"):
        return "openai"

    # Default fallback when no valid API keys are configured: pure-Python rule-based
    return "rule_based"


def get_llm_client():
    """Lazily initialize and return the client for the active LLM provider.

    Raises:
        AgentError: If an explicit provider is selected but its API key is missing.
    """
    global _client, _active_provider
    provider = get_active_provider()

    if provider in ("rule_based", "mock"):
        _active_provider = "rule_based"
        return {"provider": "rule_based"}

    if provider == "gemini":
        gemini_key = os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
        if not gemini_key or gemini_key in ("your_gemini_api_key_here", "your_actual_gemini_api_key"):
            raise AgentError(
                "Google Gemini API key is missing. Set GEMINI_API_KEY in your .env file or set LLM_PROVIDER=rule_based for offline demo mode.",
                code="API_KEY_MISSING",
                status_code=500,
            )
        if _client is None or _active_provider != "gemini":
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                _client = genai
                _active_provider = "gemini"
            except Exception as err:
                raise AgentError(
                    f"Failed to initialize Google Gemini client: {err}",
                    code="CLIENT_INIT_ERROR",
                    status_code=500,
                )
        return _client

    if provider == "groq":
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key or groq_key in ("your_groq_api_key_here", "your_actual_groq_api_key"):
            raise AgentError(
                "Groq API key is missing. Set GROQ_API_KEY in your .env file or set LLM_PROVIDER=rule_based for offline demo mode.",
                code="API_KEY_MISSING",
                status_code=500,
            )
        if _client is None or _active_provider != "groq":
            try:
                from groq import Groq
                _client = Groq(api_key=groq_key)
                _active_provider = "groq"
            except Exception as err:
                raise AgentError(
                    f"Failed to initialize Groq client: {err}",
                    code="CLIENT_INIT_ERROR",
                    status_code=500,
                )
        return _client

    if provider == "openai":
        openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not openai_key or openai_key in ("your_openai_api_key_here", "your_actual_openai_api_key"):
            raise AgentError(
                "OpenAI API key is missing or not configured. Set OPENAI_API_KEY in your .env file or switch LLM_PROVIDER to rule_based for free offline mode.",
                code="API_KEY_MISSING",
                status_code=500,
            )
        if _client is None or _active_provider != "openai":
            try:
                from openai import OpenAI
                _client = OpenAI(api_key=openai_key)
                _active_provider = "openai"
            except Exception as err:
                raise AgentError(
                    f"Failed to initialize OpenAI client: {err}",
                    code="CLIENT_INIT_ERROR",
                    status_code=500,
                )
        return _client

    return {"provider": "rule_based"}


def get_openai_client():
    """Return the OpenAI client, raising AgentError if OPENAI_API_KEY is not configured.

    Maintains backwards compatibility with unit tests expecting get_openai_client.
    """
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not openai_key or openai_key in ("your_openai_api_key_here", "your_actual_openai_api_key"):
        raise AgentError(
            "OpenAI API key is missing or not configured. Please set OPENAI_API_KEY in your .env file.",
            code="API_KEY_MISSING",
            status_code=500,
        )
    return get_llm_client()


# =====================================================================
# Pure Python Rule-Based Planning Pipeline
# =====================================================================

def run_rule_based_agents(
    destination: str,
    duration_days: int,
    budget: str,
    interests: Optional[List[str]] = None,
    companions: str = "Solo",
    climate: str = "Any",
    fallback_note: Optional[str] = None,
    place_id: Optional[str] = None,
    location_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the multi-agent travel plan using pure-Python rule-based agents and local data.

    Never requires external API keys or network connectivity.
    """
    clean_dest = destination.strip()
    clean_interests = interests or []
    budget_tier = budget.capitalize() if budget else "Moderate"
    companion_type = companions.strip().capitalize() if companions else "Solo"
    climate_pref = climate.strip() if climate else "Any"

    # Step 1: Destination Agent
    dest_data = resolve_or_create_destination(
        destination_name=clean_dest,
        budget=budget_tier,
        interests=clean_interests,
        companions=companion_type,
        climate=climate_pref,
        place_id=place_id,
        location_context=location_context,
    )
    final_dest_name = dest_data.get("name", clean_dest)
    experiences = dest_data.get("experiences", [])
    raw_accommodations = dest_data.get("accommodations", [])
    accommodations = filter_accommodations_for_budget(raw_accommodations, budget_tier)

    # Step 2: Logistics & Tips Agent
    logistics, travel_tips = generate_logistics_and_tips(
        destination_data=dest_data,
        companions=companion_type,
        climate=climate_pref,
    )

    # Step 3: Itinerary Planning Agent
    itinerary = build_itinerary(
        destination_data=dest_data,
        duration_days=duration_days,
        interests=clean_interests,
        budget_tier=budget_tier,
        companions=companion_type,
    )

    # Step 4: Budget Estimation Agent
    estimated_budget = estimate_budget(
        destination_data=dest_data,
        duration_days=duration_days,
        budget_tier=budget_tier,
        companions=companion_type,
    )

    # Summary narrative
    mode_label = "Rule-Based Offline Planner"
    if fallback_note:
        summary_intro = f"[{mode_label}] {fallback_note} "
    else:
        summary_intro = f"[{mode_label}] "

    summary = (
        f"{summary_intro}An expertly crafted {duration_days}-day itinerary for {final_dest_name}, "
        f"tailored for {companion_type.lower()} travel in the {budget_tier.lower()} budget tier. "
        f"{dest_data.get('overview', '')}"
    )

    # Append rule-based notice in budget assumptions
    assumptions = list(estimated_budget.get("assumptions", []))
    assumptions.insert(
        0,
        "[Offline Demo Mode] Generated using Voyage AI's pure-Python rule-based planning engine and local knowledge base ($0 API cost).",
    )
    estimated_budget["assumptions"] = assumptions

    return {
        "destination": final_dest_name,
        "duration_days": duration_days,
        "budget": budget_tier,
        "interests": clean_interests,
        "companions": companion_type,
        "climate": climate_pref,
        "llm_provider": "rule_based",
        "summary": summary,
        "experiences": experiences,
        "accommodations": accommodations,
        "logistics": logistics,
        "itinerary": itinerary,
        "estimated_budget": estimated_budget,
        "travel_tips": travel_tips,
        "fallback_used": bool(fallback_note),
        "place_id": place_id or dest_data.get("place_id"),
        "location_context": location_context or dest_data.get("country"),
    }


# =====================================================================
# LLM Completion Dispatcher with 1 Retry & Fallback
# =====================================================================

def _request_completion(client, system_prompt: str, user_prompt: str) -> str:
    """Execute a completion request against the active LLM provider.

    Stand-alone helper so unit tests can patch it directly.
    """
    provider = get_active_provider()

    # Rule-Based / Mock fallback
    if provider in ("rule_based", "mock"):
        time.sleep(0.15)
        # Delegate to rule-based destination synthesizer for mock responses
        from planner.destination_agent import resolve_or_create_destination
        dest_match = re.search(r"Destination:\s*(.+)", user_prompt)
        dest = dest_match.group(1).strip() if dest_match else "Kyoto, Japan"
        data = resolve_or_create_destination(dest)

        if "Destination and Activity Travel Specialist" in system_prompt:
            return json.dumps({"experiences": data.get("experiences", [])})
        if "Accommodation and Lodging Specialist" in system_prompt:
            return json.dumps({"currency": data.get("currency", "USD"), "accommodations": data.get("accommodations", [])})
        if "Transit and Ground Logistics Specialist" in system_prompt:
            return json.dumps(data.get("logistics", {}))
        if "Lead Travel Coordinator and Master Itinerary Synthesizer" in system_prompt:
            days_match = re.search(r"(\d+)\s*days", user_prompt, re.IGNORECASE)
            d = int(days_match.group(1)) if days_match else 3
            itin = build_itinerary(data, d)
            c_def = data.get("cost_defaults", {})
            return json.dumps({
                "summary": data.get("overview", "A wonderful travel plan."),
                "itinerary": itin,
                "cost_inputs": c_def,
                "assumptions": ["Solo traveler"],
                "travel_tips": data.get("travel_tips", []),
            })
        return "{}"

    # Google Gemini
    if provider == "gemini":
        try:
            import google.generativeai as genai
            model = genai.GenerativeModel(
                model_name="gemini-1.5-flash",
                generation_config={"response_mime_type": "application/json"},
            )
            full_prompt = f"System Instructions:\n{system_prompt}\n\nTask:\n{user_prompt}"
            response = model.generate_content(full_prompt)
            return response.text or "{}"
        except Exception as err:
            err_msg = str(err)
            if "API_KEY" in err_msg.upper():
                raise AgentError("Invalid Google Gemini API key.", "AUTH_ERROR", 401)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                raise AgentError("Google Gemini rate limit exceeded.", "RATE_LIMIT", 429)
            raise AgentError(f"Google Gemini error: {err_msg}", "GEMINI_ERROR", 502)

    # Groq
    if provider == "groq":
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                timeout=60.0,
            )
            return response.choices[0].message.content or "{}"
        except Exception as err:
            err_msg = str(err)
            if "401" in err_msg:
                raise AgentError("Invalid Groq API key.", "AUTH_ERROR", 401)
            if "429" in err_msg:
                raise AgentError("Groq rate limit exceeded.", "RATE_LIMIT", 429)
            raise AgentError(f"Groq service error: {err_msg}", "GROQ_ERROR", 502)

    # OpenAI
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            timeout=60.0,
        )
        return response.choices[0].message.content or ""
    except Exception as err:
        err_type = type(err).__name__
        err_msg = str(err)
        if "AuthenticationError" in err_type:
            raise AgentError("Invalid OpenAI API key.", "AUTH_ERROR", 401)
        if "RateLimitError" in err_type:
            raise AgentError("OpenAI rate limit or quota exceeded.", "RATE_LIMIT", 429)
        if "APITimeoutError" in err_type:
            raise AgentError("Request timed out after 60 seconds.", "TIMEOUT", 504)
        if "APIConnectionError" in err_type:
            raise AgentError("Could not connect to OpenAI services.", "CONNECTION_ERROR", 503)
        raise AgentError(f"OpenAI service error: {err_msg}", "OPENAI_ERROR", 502)


def extract_json_block(text: str) -> str:
    """Extract outer {...} JSON block from text."""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


# =====================================================================
# Sanitation Helpers
# =====================================================================

def clean_string(val: Any, max_len: int = 1000, default: str = "") -> str:
    if val is None or isinstance(val, (bool, dict, list)):
        return default
    s = str(val).strip()
    return s[:max_len]


def parse_number(val: Any, default: float = 0.0, min_val: float = 0.0, max_val: float = 1_000_000.0) -> float:
    if isinstance(val, bool) or val is None:
        return default

    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return default
        return round(max(min_val, min(max_val, float(val))), 2)

    val_str = str(val).strip()
    match = re.search(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", val_str)
    if not match:
        return default

    clean_num_str = match.group(0).replace(",", "")
    try:
        num = float(clean_num_str)
        if math.isnan(num) or math.isinf(num):
            return default
        return round(max(min_val, min(max_val, num)), 2)
    except (ValueError, OverflowError):
        return default


def normalize_tier(val: Any) -> str:
    s = str(val or "").strip().lower()
    if "budget" in s:
        return "Budget"
    if "lux" in s:
        return "Luxury"
    return "Moderate"


def normalize_currency(val: Any) -> str:
    s = str(val or "").strip().upper()
    if re.match(r"^[A-Z]{3}$", s):
        return s
    return "USD"


def clean_string_list(val: Any, max_items: int = 20, max_len: int = 500) -> List[str]:
    if not isinstance(val, list):
        if isinstance(val, str) and val.strip():
            return [clean_string(val, max_len=max_len)]
        return []
    result = []
    for item in val:
        cleaned = clean_string(item, max_len=max_len)
        if cleaned:
            result.append(cleaned)
        if len(result) >= max_items:
            break
    return result


def execute_agent_call(
    client,
    system_prompt: str,
    user_prompt: str,
    validator_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    agent_name: str,
) -> Dict[str, Any]:
    last_error_msg = ""
    for attempt in range(2):
        try:
            raw_text = _request_completion(client, system_prompt, user_prompt)
            parsed = None
            try:
                parsed = json.loads(raw_text)
            except json.JSONDecodeError:
                fallback_text = extract_json_block(raw_text)
                try:
                    parsed = json.loads(fallback_text)
                except json.JSONDecodeError as json_err:
                    raise ValueError(f"Model response was not valid JSON: {json_err}")

            if not isinstance(parsed, dict):
                raise ValueError("Model response must be a JSON object.")

            return validator_fn(parsed)

        except AgentError:
            raise
        except Exception as err:
            last_error_msg = str(err)
            logger.warning("Agent '%s' attempt %d failed: %s", agent_name, attempt + 1, last_error_msg)
            if attempt == 1:
                raise AgentError(
                    f"The {agent_name} failed to return valid plan data. Reason: {last_error_msg}",
                    code="AGENT_VALIDATION_ERROR",
                    status_code=502,
                )

    raise AgentError(
        f"The {agent_name} failed unexpectedly: {last_error_msg}",
        code="AGENT_EXECUTION_ERROR",
        status_code=502,
    )


# =====================================================================
# LLM Agent Prompts & Validators
# =====================================================================

DESTINATION_ACTIVITY_SYSTEM_PROMPT = """You are an expert Destination and Activity Travel Specialist.
Return 3-4 attractions/activities/dining/local experiences tailored to the destination, duration, budget tier, and interests.
Output strictly JSON: {"experiences": [{"name": "string", "category": "string", "description": "string", "practical_tip": "string", "estimated_cost": "string"}]}
"""

def validate_destination_activity_output(data: Dict[str, Any]) -> Dict[str, Any]:
    raw_exp = data.get("experiences")
    if not isinstance(raw_exp, list) or len(raw_exp) < 1:
        raise ValueError("Field 'experiences' must be a non-empty list.")

    experiences = []
    for item in raw_exp[:4]:
        if not isinstance(item, dict):
            continue
        name = clean_string(item.get("name"), max_len=120)
        if not name:
            continue
        experiences.append({
            "name": name,
            "category": clean_string(item.get("category"), max_len=60, default="Sightseeing"),
            "description": clean_string(item.get("description"), max_len=500),
            "practical_tip": clean_string(item.get("practical_tip"), max_len=300),
            "estimated_cost": clean_string(item.get("estimated_cost"), max_len=100, default="Varies"),
        })

    if not experiences:
        raise ValueError("No valid experiences returned.")
    return {"experiences": experiences}


def destination_activity_agent(
    client, destination: str, duration_days: int, budget: str, interests: List[str]
) -> Dict[str, Any]:
    user_prompt = (
        f"Destination: {destination}\nDuration: {duration_days} days\nBudget: {budget}\n"
        f"Interests: {', '.join(interests) if interests else 'General'}"
    )
    return execute_agent_call(
        client,
        DESTINATION_ACTIVITY_SYSTEM_PROMPT,
        user_prompt,
        validate_destination_activity_output,
        "Destination & Activity Agent",
    )


STAY_ACCOMMODATION_SYSTEM_PROMPT = """You are an expert Accommodation Specialist.
Recommend exactly 2 lodging options and destination ISO 4217 currency code. Never claim real-time prices or availability.
Output strictly JSON: {"currency": "USD", "accommodations": [{"name": "string", "tier": "Budget|Moderate|Luxury", "area": "string", "nightly_price": 120, "reason": "string", "note": "string"}]}
"""

def validate_stay_accommodation_output(data: Dict[str, Any]) -> Dict[str, Any]:
    currency = normalize_currency(data.get("currency"))
    raw_acc = data.get("accommodations")
    if not isinstance(raw_acc, list) or len(raw_acc) == 0:
        raise ValueError("Field 'accommodations' must be a list.")

    accommodations = []
    for item in raw_acc:
        if not isinstance(item, dict):
            continue
        name = clean_string(item.get("name"), max_len=120)
        if not name:
            continue
        accommodations.append({
            "name": name,
            "tier": normalize_tier(item.get("tier")),
            "area": clean_string(item.get("area"), max_len=100, default="City Center"),
            "nightly_price": parse_number(item.get("nightly_price"), default=100.0),
            "reason": clean_string(item.get("reason"), max_len=300),
            "note": clean_string(item.get("note"), max_len=300, default="Indicative seasonal rate."),
        })

    if len(accommodations) < 2:
        if len(accommodations) == 1:
            first = accommodations[0]
            accommodations.append({
                "name": f"Alternative Guesthouse near {first['area']}",
                "tier": first["tier"],
                "area": first["area"],
                "nightly_price": round(first["nightly_price"] * 0.85, 2),
                "reason": "Alternative option offering great value.",
                "note": "Indicative seasonal rate.",
            })
        else:
            raise ValueError("No valid accommodations found.")

    return {"currency": currency, "accommodations": accommodations[:2]}


def stay_accommodation_agent(
    client, destination: str, duration_days: int, budget: str, interests: List[str], experiences: List[Dict[str, Any]]
) -> Dict[str, Any]:
    exp_summary = "; ".join([e.get("name", "") for e in experiences if e.get("name")])
    user_prompt = f"Destination: {destination}\nDuration: {duration_days} days\nBudget: {budget}\nPlanned Experiences: {exp_summary}"
    return execute_agent_call(
        client,
        STAY_ACCOMMODATION_SYSTEM_PROMPT,
        user_prompt,
        validate_stay_accommodation_output,
        "Stay & Accommodation Agent",
    )


LOGISTICS_TRANSIT_SYSTEM_PROMPT = """You are an expert Transit and Ground Logistics Specialist.
Provide ground transportation analysis using the specified local currency.
Output strictly JSON: {"overview": "string", "transport_options": [{"mode": "string", "description": "string", "approx_cost_per_trip": 3.5, "notes": "string"}], "daily_transport_estimate": 15.0, "tips": ["string"], "safety": ["string"], "verify": ["string"]}
"""

def validate_logistics_transit_output(data: Dict[str, Any]) -> Dict[str, Any]:
    overview = clean_string(data.get("overview"), max_len=600, default="Standard urban transportation available.")
    daily_est = parse_number(data.get("daily_transport_estimate"), default=15.0)

    options = []
    for opt in data.get("transport_options", []):
        if not isinstance(opt, dict):
            continue
        mode = clean_string(opt.get("mode"), max_len=60)
        if not mode:
            continue
        options.append({
            "mode": mode,
            "description": clean_string(opt.get("description"), max_len=300),
            "approx_cost_per_trip": parse_number(opt.get("approx_cost_per_trip"), default=2.5),
            "notes": clean_string(opt.get("notes"), max_len=200),
        })

    if not options:
        options = [{
            "mode": "Public Transit",
            "description": "Metro and bus network.",
            "approx_cost_per_trip": 3.0,
            "notes": "Use contactless tap or refillable transit card.",
        }]

    return {
        "overview": overview,
        "transport_options": options,
        "daily_transport_estimate": daily_est,
        "tips": clean_string_list(data.get("tips"), max_items=6, max_len=250) or ["Download offline maps."],
        "safety": clean_string_list(data.get("safety"), max_items=6, max_len=250) or ["Keep valuables secure in transit."],
        "verify": clean_string_list(data.get("verify"), max_items=6, max_len=250) or ["Confirm airport train schedule."],
    }


def logistics_transit_agent(
    client, destination: str, duration_days: int, budget: str, currency: str
) -> Dict[str, Any]:
    user_prompt = f"Destination: {destination}\nDuration: {duration_days} days\nBudget: {budget}\nCurrency: {currency}"
    return execute_agent_call(
        client,
        LOGISTICS_TRANSIT_SYSTEM_PROMPT,
        user_prompt,
        validate_logistics_transit_output,
        "Logistics & Transit Agent",
    )


COORDINATOR_SYNTHESIZER_SYSTEM_PROMPT = """You are the Lead Travel Coordinator and Master Itinerary Synthesizer.
Synthesize experiences, lodging, and transport into a cohesive day-by-day itinerary for EXACTLY duration_days days.
Output strictly JSON: {"summary": "string", "itinerary": [{"day": 1, "title": "string", "morning": ["string"], "afternoon": ["string"], "evening": ["string"]}], "cost_inputs": {"accommodation_per_night": 120.0, "food_per_day": 45.0, "transport_per_day": 15.0, "activities_total": 75.0}, "assumptions": ["string"], "travel_tips": ["string"]}
"""

def validate_coordinator_output(data: Dict[str, Any], duration_days: int) -> Dict[str, Any]:
    summary = clean_string(data.get("summary"), max_len=800, default="An expertly planned itinerary.")
    raw_itinerary = data.get("itinerary", [])
    if not isinstance(raw_itinerary, list):
        raw_itinerary = []

    itinerary_days = []
    for i in range(duration_days):
        day_num = i + 1
        day_data = raw_itinerary[i] if i < len(raw_itinerary) and isinstance(raw_itinerary[i], dict) else {}
        itinerary_days.append({
            "day": day_num,
            "title": clean_string(day_data.get("title"), max_len=120, default=f"Day {day_num} Exploration"),
            "morning": clean_string_list(day_data.get("morning"), max_items=4) or ["Morning exploration in city."],
            "afternoon": clean_string_list(day_data.get("afternoon"), max_items=4) or ["Afternoon sightseeing."],
            "evening": clean_string_list(day_data.get("evening"), max_items=4) or ["Evening dinner and relaxation."],
        })

    cost_inputs_raw = data.get("cost_inputs", {}) if isinstance(data.get("cost_inputs"), dict) else {}
    cost_inputs = {
        "accommodation_per_night": parse_number(cost_inputs_raw.get("accommodation_per_night"), default=100.0),
        "food_per_day": parse_number(cost_inputs_raw.get("food_per_day"), default=40.0),
        "transport_per_day": parse_number(cost_inputs_raw.get("transport_per_day"), default=15.0),
        "activities_total": parse_number(cost_inputs_raw.get("activities_total"), default=50.0),
    }

    return {
        "summary": summary,
        "itinerary": itinerary_days,
        "cost_inputs": cost_inputs,
        "assumptions": clean_string_list(data.get("assumptions"), max_items=6),
        "travel_tips": clean_string_list(data.get("travel_tips"), max_items=6) or ["Pack versatile layers."],
    }


def coordinator_itinerary_agent(
    client,
    destination: str,
    duration_days: int,
    budget: str,
    interests: List[str],
    experiences: List[Dict[str, Any]],
    accommodations: List[Dict[str, Any]],
    logistics: Dict[str, Any],
    currency: str,
) -> Dict[str, Any]:
    user_prompt = (
        f"Destination: {destination}\nDuration: {duration_days} days (EXACTLY {duration_days} days)\n"
        f"Budget: {budget}\nCurrency: {currency}\n"
        f"Experiences: {json.dumps(experiences)}\nLodging: {json.dumps(accommodations)}\nLogistics: {json.dumps(logistics)}"
    )
    return execute_agent_call(
        client,
        COORDINATOR_SYNTHESIZER_SYSTEM_PROMPT,
        user_prompt,
        lambda d: validate_coordinator_output(d, duration_days),
        "Coordinator & Itinerary Synthesizer",
    )


# =====================================================================
# Cost Arithmetic (Python Precision)
# =====================================================================

def calculate_budget(
    duration_days: int,
    cost_inputs: Dict[str, Any],
    currency: str,
    model_assumptions: List[str],
) -> Dict[str, Any]:
    days = max(1, duration_days)
    nights = max(days - 1, 0)

    acc_per_night = parse_number(cost_inputs.get("accommodation_per_night"), default=0.0)
    acc_total = round(acc_per_night * nights, 2)

    food_per_day = parse_number(cost_inputs.get("food_per_day"), default=0.0)
    food_total = round(food_per_day * days, 2)

    trans_per_day = parse_number(cost_inputs.get("transport_per_day"), default=0.0)
    trans_total = round(trans_per_day * days, 2)

    act_total = round(parse_number(cost_inputs.get("activities_total"), default=0.0), 2)
    total_sum = round(acc_total + food_total + trans_total + act_total, 2)

    standard_assumptions = [
        "All cost estimates are AI-generated and unverified; actual prices will vary based on season, availability, and booking time.",
        "Estimates are per person for a solo traveler.",
        "International and domestic flights are excluded from this budget.",
    ]

    cleaned_assumptions = [clean_string(item, max_len=250) for item in model_assumptions if clean_string(item, max_len=250)]
    for std in standard_assumptions:
        if std not in cleaned_assumptions:
            cleaned_assumptions.append(std)

    return {
        "currency": currency,
        "per_person": True,
        "flights_excluded": True,
        "nights": nights,
        "accommodation_per_night": acc_per_night,
        "accommodation": acc_total,
        "food_per_day": food_per_day,
        "food": food_total,
        "transport_per_day": trans_per_day,
        "transport": trans_total,
        "activities": act_total,
        "total": total_sum,
        "assumptions": cleaned_assumptions,
    }


# =====================================================================
# Master Orchestration Pipeline with Automatic Fallback
# =====================================================================

def run_agents(
    destination: str,
    duration_days: int,
    budget: str,
    interests: Optional[List[str]] = None,
    companions: str = "Solo",
    climate: str = "Any",
    place_id: Optional[str] = None,
    location_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute the multi-agent travel planning pipeline with automatic fallback.

    If an external LLM fails, is unconfigured, or has invalid keys, it automatically
    switches to the pure-Python rule-based planning engine without crashing.
    """
    clean_dest = clean_string(destination, max_len=160)
    clean_interests = interests or []
    provider = get_active_provider()

    # If destination was not specified or requested a recommendation, choose best match
    if not clean_dest or clean_dest.lower() in ("recommend", "surprise me", "auto", "any", "suggest"):
        recs = recommend_destinations(budget, duration_days, clean_interests, companions, climate, top_k=1)
        if recs:
            clean_dest = recs[0]["destination"]
            logger.info("Destination recommendation selected: '%s'", clean_dest)
        else:
            clean_dest = "Kyoto, Japan"

    # Direct rule-based / demo execution
    if provider in ("rule_based", "mock"):
        logger.info("Running pure-Python rule-based planner for '%s' (provider: %s)", clean_dest, provider)
        plan = run_rule_based_agents(
            destination=clean_dest,
            duration_days=duration_days,
            budget=budget,
            interests=clean_interests,
            companions=companions,
            climate=climate,
            place_id=place_id,
            location_context=location_context,
        )
        plan["llm_provider"] = provider
        return plan

    # Attempt LLM execution with graceful fallback
    try:
        client = get_llm_client()
        logger.info("Running LLM pipeline with provider '%s' for '%s'", provider, clean_dest)

        agent1_out = destination_activity_agent(client, clean_dest, duration_days, budget, clean_interests)
        experiences = agent1_out["experiences"]

        agent2_out = stay_accommodation_agent(client, clean_dest, duration_days, budget, clean_interests, experiences)
        accommodations = agent2_out["accommodations"]
        currency = agent2_out["currency"]

        agent3_out = logistics_transit_agent(client, clean_dest, duration_days, budget, currency)

        agent4_out = coordinator_itinerary_agent(
            client=client,
            destination=clean_dest,
            duration_days=duration_days,
            budget=budget,
            interests=clean_interests,
            experiences=experiences,
            accommodations=accommodations,
            logistics=agent3_out,
            currency=currency,
        )

        estimated_budget = calculate_budget(
            duration_days=duration_days,
            cost_inputs=agent4_out["cost_inputs"],
            currency=currency,
            model_assumptions=agent4_out.get("assumptions", []),
        )

        return {
            "destination": clean_dest,
            "duration_days": duration_days,
            "budget": budget,
            "interests": clean_interests,
            "companions": companions,
            "climate": climate,
            "place_id": place_id,
            "location_context": location_context,
            "llm_provider": provider,
            "summary": agent4_out["summary"],
            "experiences": experiences,
            "accommodations": accommodations,
            "logistics": agent3_out,
            "itinerary": agent4_out["itinerary"],
            "estimated_budget": estimated_budget,
            "travel_tips": agent4_out.get("travel_tips", []),
            "fallback_used": False,
        }

    except Exception as llm_err:
        # Graceful fallback: Never crash, never expose API keys, never return blank page!
        logger.warning(
            "LLM provider '%s' failed (%s). Gracefully switching to rule-based planner for '%s'.",
            provider,
            type(llm_err).__name__,
            clean_dest,
        )
        return run_rule_based_agents(
            destination=clean_dest,
            duration_days=duration_days,
            budget=budget,
            interests=clean_interests,
            companions=companions,
            climate=climate,
            place_id=place_id,
            location_context=location_context,
            fallback_note=f"Plan generated via rule-based engine (LLM {provider} unavailable).",
        )
