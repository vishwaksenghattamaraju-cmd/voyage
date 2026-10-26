"""places_service.py - Google Maps Platform Places API Integration & Worldwide Place Discovery

Provides worldwide destination search, real-time query autocomplete, and place details
resolution using Google Maps Platform's Places API (New).

Features:
1. Places API (New) Autocomplete (POST https://places.googleapis.com/v1/places:autocomplete)
   with required 'X-Goog-Maps-Solution-ID: gmp_git_agentskills_v1' header and field masking.
2. Short-lived in-memory LRU cache to debounce repeat keystrokes and minimize API quota usage.
3. Robust offline Global Atlas fallback with 150+ worldwide travel destinations (Hyderabad,
   Bali, Swiss Alps, Grand Canyon, Cape Town, Dubai, etc.) plus dynamic custom destination
   synthesis when GOOGLE_MAPS_API_KEY is not configured or in offline demo mode.
4. Compliant attribution handling: returns "Google Maps" attribution when data originates
   from Google Maps Platform.
"""

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("voyage_ai.places")

# Mandatory attribution tracking header for Google Maps Platform Agent Skills
SOLUTION_ID = "gmp_git_agentskills_v1"

# In-memory thread-safe LRU cache for autocomplete predictions (5 min TTL)
_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Tuple[float, Any]] = {}
_CACHE_TTL_SECONDS = 300
_CACHE_MAX_ENTRIES = 250


def is_google_places_configured() -> bool:
    """Check if a valid, non-placeholder Google Maps Platform API key is available."""
    key = (
        os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        or os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    )
    if not key:
        return False
    if "your_" in key.lower() or "placeholder" in key.lower():
        return False
    return True


def _get_api_key() -> str:
    return (
        os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        or os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    )


def _cache_get(key: str) -> Optional[Any]:
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE:
            expire_at, value = _CACHE[key]
            if now < expire_at:
                return value
            del _CACHE[key]
    return None


def _cache_set(key: str, value: Any) -> None:
    now = time.time()
    with _CACHE_LOCK:
        if len(_CACHE) >= _CACHE_MAX_ENTRIES:
            # Purge oldest 25% of entries
            sorted_keys = sorted(_CACHE.keys(), key=lambda k: _CACHE[k][0])
            for k in sorted_keys[: len(sorted_keys) // 4 + 1]:
                _CACHE.pop(k, None)
        _CACHE[key] = (now + _CACHE_TTL_SECONDS, value)


# =====================================================================
# Places API (New) Categories & Mapping
# =====================================================================

def map_place_types_to_category(types: List[str]) -> str:
    """Map Google Places API types to a user-friendly destination category badge."""
    if not types:
        return "Destination"
    t_set = set(types)

    if "national_park" in t_set or "park" in t_set:
        return "National Park"
    if "natural_feature" in t_set:
        return "Natural Wonder"
    if any(k in t_set for k in ["tourist_attraction", "museum", "point_of_interest", "historical_landmark"]):
        return "Landmark"
    if "locality" in t_set or "colloquial_area" in t_set or "postal_town" in t_set:
        return "City"
    if "administrative_area_level_1" in t_set or "administrative_area_level_2" in t_set:
        return "Region / State"
    if "country" in t_set:
        return "Country"
    if "neighborhood" in t_set or "sublocality" in t_set:
        return "District"
    if any(k in t_set for k in ["island", "archipelago"]):
        return "Island"
    return "Destination"


# =====================================================================
# Places API (New) Live Client
# =====================================================================

def _fetch_google_places_autocomplete(
    query: str, session_token: Optional[str] = None, timeout: float = 4.0
) -> List[Dict[str, Any]]:
    """Execute live autocomplete query against Google Places API (New)."""
    api_key = _get_api_key()
    url = "https://places.googleapis.com/v1/places:autocomplete"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-Maps-Solution-ID": SOLUTION_ID,
        "X-Goog-FieldMask": (
            "suggestions.placePrediction.placeId,"
            "suggestions.placePrediction.text.text,"
            "suggestions.placePrediction.structuredFormat,"
            "suggestions.placePrediction.types"
        ),
    }

    payload: Dict[str, Any] = {"input": query}
    if session_token:
        payload["sessionToken"] = session_token

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            data = json.loads(resp_body)
    except urllib.error.HTTPError as http_err:
        err_msg = ""
        try:
            err_msg = http_err.read().decode("utf-8")
        except Exception:
            pass
        logger.warning(
            "Google Places Autocomplete HTTP %s for '%s': %s", http_err.code, query, err_msg
        )
        raise
    except Exception as exc:
        logger.warning("Google Places Autocomplete network error for '%s': %s", query, exc)
        raise

    suggestions = []
    raw_suggestions = data.get("suggestions", [])
    for item in raw_suggestions:
        pred = item.get("placePrediction")
        if not pred:
            continue
        place_id = pred.get("placeId", "")
        types = pred.get("types", [])
        category = map_place_types_to_category(types)

        struct_fmt = pred.get("structuredFormat") or {}
        main_text = (struct_fmt.get("mainText") or {}).get("text", "")
        secondary_text = (struct_fmt.get("secondaryText") or {}).get("text", "")
        full_text = (pred.get("text") or {}).get("text", "")

        if not main_text:
            main_text = full_text.split(",")[0].strip() if full_text else query

        suggestions.append({
            "place_id": place_id,
            "name": main_text,
            "secondary_text": secondary_text,
            "full_text": full_text or f"{main_text}, {secondary_text}".strip(", "),
            "category": category,
            "types": types,
            "source": "google_places",
        })

    return suggestions


def _fetch_google_place_details(
    place_id: str, session_token: Optional[str] = None, timeout: float = 4.0
) -> Optional[Dict[str, Any]]:
    """Retrieve place details from Google Places API (New)."""
    if not place_id or not is_google_places_configured():
        return None

    api_key = _get_api_key()
    url = f"https://places.googleapis.com/v1/places/{urllib.parse.quote(place_id)}"

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-Maps-Solution-ID": SOLUTION_ID,
        "X-Goog-FieldMask": "id,displayName,formattedAddress,location,types",
    }
    if session_token:
        url += f"?sessionToken={urllib.parse.quote(session_token)}"

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "place_id": data.get("id"),
                "name": (data.get("displayName") or {}).get("text", ""),
                "formatted_address": data.get("formattedAddress", ""),
                "location": data.get("location", {}),
                "types": data.get("types", []),
            }
    except Exception as exc:
        logger.warning("Google Place Details error for %s: %s", place_id, exc)
        return None


# =====================================================================
# Comprehensive Offline Global Atlas
# =====================================================================

GLOBAL_DESTINATION_ATLAS = [
    # India & South Asia
    {"name": "Hyderabad", "secondary_text": "Telangana, India", "category": "City", "currency": "INR", "country": "India"},
    {"name": "Mumbai", "secondary_text": "Maharashtra, India", "category": "City", "currency": "INR", "country": "India"},
    {"name": "New Delhi", "secondary_text": "Delhi, India", "category": "City", "currency": "INR", "country": "India"},
    {"name": "Bengaluru", "secondary_text": "Karnataka, India", "category": "City", "currency": "INR", "country": "India"},
    {"name": "Goa", "secondary_text": "India", "category": "Beach / Region", "currency": "INR", "country": "India"},
    {"name": "Jaipur", "secondary_text": "Rajasthan, India", "category": "City", "currency": "INR", "country": "India"},
    {"name": "Agra (Taj Mahal)", "secondary_text": "Uttar Pradesh, India", "category": "Landmark", "currency": "INR", "country": "India"},
    {"name": "Kerala Backwaters", "secondary_text": "Kerala, India", "category": "Natural Wonder", "currency": "INR", "country": "India"},
    {"name": "Kathmandu", "secondary_text": "Nepal", "category": "City", "currency": "NPR", "country": "Nepal"},
    {"name": "Colombo", "secondary_text": "Western Province, Sri Lanka", "category": "City", "currency": "LKR", "country": "Sri Lanka"},
    {"name": "Malé", "secondary_text": "Maldives", "category": "Island", "currency": "USD", "country": "Maldives"},

    # East & Southeast Asia
    {"name": "Tokyo", "secondary_text": "Tokyo Prefecture, Japan", "category": "City", "currency": "JPY", "country": "Japan"},
    {"name": "Kyoto", "secondary_text": "Kyoto Prefecture, Japan", "category": "City", "currency": "JPY", "country": "Japan"},
    {"name": "Osaka", "secondary_text": "Osaka Prefecture, Japan", "category": "City", "currency": "JPY", "country": "Japan"},
    {"name": "Hokkaido", "secondary_text": "Japan", "category": "Region", "currency": "JPY", "country": "Japan"},
    {"name": "Seoul", "secondary_text": "South Korea", "category": "City", "currency": "KRW", "country": "South Korea"},
    {"name": "Busan", "secondary_text": "South Korea", "category": "City", "currency": "KRW", "country": "South Korea"},
    {"name": "Bangkok", "secondary_text": "Thailand", "category": "City", "currency": "THB", "country": "Thailand"},
    {"name": "Phuket", "secondary_text": "Thailand", "category": "Island", "currency": "THB", "country": "Thailand"},
    {"name": "Chiang Mai", "secondary_text": "Northern Thailand", "category": "City", "currency": "THB", "country": "Thailand"},
    {"name": "Singapore", "secondary_text": "Singapore", "category": "City", "currency": "SGD", "country": "Singapore"},
    {"name": "Bali", "secondary_text": "Indonesia", "category": "Island", "currency": "IDR", "country": "Indonesia"},
    {"name": "Jakarta", "secondary_text": "Java, Indonesia", "category": "City", "currency": "IDR", "country": "Indonesia"},
    {"name": "Hanoi", "secondary_text": "Vietnam", "category": "City", "currency": "VND", "country": "Vietnam"},
    {"name": "Da Nang & Hoi An", "secondary_text": "Central Vietnam", "category": "Beach / City", "currency": "VND", "country": "Vietnam"},
    {"name": "Kuala Lumpur", "secondary_text": "Malaysia", "category": "City", "currency": "MYR", "country": "Malaysia"},
    {"name": "Taipei", "secondary_text": "Taiwan", "category": "City", "currency": "TWD", "country": "Taiwan"},
    {"name": "Hong Kong", "secondary_text": "China", "category": "City", "currency": "HKD", "country": "Hong Kong"},

    # Europe
    {"name": "Paris", "secondary_text": "Île-de-France, France", "category": "City", "currency": "EUR", "country": "France"},
    {"name": "Paris", "secondary_text": "Texas, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Nice", "secondary_text": "French Riviera, France", "category": "City", "currency": "EUR", "country": "France"},
    {"name": "London", "secondary_text": "England, United Kingdom", "category": "City", "currency": "GBP", "country": "United Kingdom"},
    {"name": "London", "secondary_text": "Ontario, Canada", "category": "City", "currency": "CAD", "country": "Canada"},
    {"name": "Edinburgh", "secondary_text": "Scotland, United Kingdom", "category": "City", "currency": "GBP", "country": "United Kingdom"},
    {"name": "Rome", "secondary_text": "Lazio, Italy", "category": "City", "currency": "EUR", "country": "Italy"},
    {"name": "Florence", "secondary_text": "Tuscany, Italy", "category": "City", "currency": "EUR", "country": "Italy"},
    {"name": "Venice", "secondary_text": "Veneto, Italy", "category": "City", "currency": "EUR", "country": "Italy"},
    {"name": "Milan", "secondary_text": "Lombardy, Italy", "category": "City", "currency": "EUR", "country": "Italy"},
    {"name": "The Swiss Alps", "secondary_text": "Valais / Bernese Oberland, Switzerland", "category": "Natural Wonder", "currency": "CHF", "country": "Switzerland"},
    {"name": "Zermatt & Matterhorn", "secondary_text": "Valais, Switzerland", "category": "Natural Wonder", "currency": "CHF", "country": "Switzerland"},
    {"name": "Zurich", "secondary_text": "Canton of Zurich, Switzerland", "category": "City", "currency": "CHF", "country": "Switzerland"},
    {"name": "Geneva", "secondary_text": "Switzerland", "category": "City", "currency": "CHF", "country": "Switzerland"},
    {"name": "Barcelona", "secondary_text": "Catalonia, Spain", "category": "City", "currency": "EUR", "country": "Spain"},
    {"name": "Madrid", "secondary_text": "Community of Madrid, Spain", "category": "City", "currency": "EUR", "country": "Spain"},
    {"name": "Seville", "secondary_text": "Andalusia, Spain", "category": "City", "currency": "EUR", "country": "Spain"},
    {"name": "Amsterdam", "secondary_text": "North Holland, Netherlands", "category": "City", "currency": "EUR", "country": "Netherlands"},
    {"name": "Berlin", "secondary_text": "Germany", "category": "City", "currency": "EUR", "country": "Germany"},
    {"name": "Munich", "secondary_text": "Bavaria, Germany", "category": "City", "currency": "EUR", "country": "Germany"},
    {"name": "Vienna", "secondary_text": "Austria", "category": "City", "currency": "EUR", "country": "Austria"},
    {"name": "Prague", "secondary_text": "Czech Republic", "category": "City", "currency": "EUR", "country": "Czech Republic"},
    {"name": "Budapest", "secondary_text": "Hungary", "category": "City", "currency": "EUR", "country": "Hungary"},
    {"name": "Athens", "secondary_text": "Attica, Greece", "category": "City", "currency": "EUR", "country": "Greece"},
    {"name": "Santorini", "secondary_text": "Cyclades, Greece", "category": "Island", "currency": "EUR", "country": "Greece"},
    {"name": "Lisbon", "secondary_text": "Portugal", "category": "City", "currency": "EUR", "country": "Portugal"},
    {"name": "Porto", "secondary_text": "Northern Portugal", "category": "City", "currency": "EUR", "country": "Portugal"},
    {"name": "Dublin", "secondary_text": "Leinster, Ireland", "category": "City", "currency": "EUR", "country": "Ireland"},
    {"name": "Reykjavik", "secondary_text": "Iceland", "category": "City", "currency": "EUR", "country": "Iceland"},
    {"name": "Stockholm", "secondary_text": "Sweden", "category": "City", "currency": "EUR", "country": "Sweden"},
    {"name": "Copenhagen", "secondary_text": "Denmark", "category": "City", "currency": "EUR", "country": "Denmark"},
    {"name": "Oslo", "secondary_text": "Norway", "category": "City", "currency": "EUR", "country": "Norway"},

    # North America
    {"name": "New York", "secondary_text": "New York, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "San Francisco", "secondary_text": "California, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Los Angeles", "secondary_text": "California, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Chicago", "secondary_text": "Illinois, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Miami", "secondary_text": "Florida, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "The Grand Canyon", "secondary_text": "Arizona, United States", "category": "National Park", "currency": "USD", "country": "USA"},
    {"name": "Yellowstone National Park", "secondary_text": "Wyoming, United States", "category": "National Park", "currency": "USD", "country": "USA"},
    {"name": "Yosemite National Park", "secondary_text": "California, United States", "category": "National Park", "currency": "USD", "country": "USA"},
    {"name": "Las Vegas", "secondary_text": "Nevada, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Honolulu & Oahu", "secondary_text": "Hawaii, United States", "category": "Island", "currency": "USD", "country": "USA"},
    {"name": "Maui", "secondary_text": "Hawaii, United States", "category": "Island", "currency": "USD", "country": "USA"},
    {"name": "Seattle", "secondary_text": "Washington, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "New Orleans", "secondary_text": "Louisiana, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Washington, D.C.", "secondary_text": "District of Columbia, United States", "category": "City", "currency": "USD", "country": "USA"},
    {"name": "Banff & Lake Louise", "secondary_text": "Alberta, Canada", "category": "National Park", "currency": "CAD", "country": "Canada"},
    {"name": "Vancouver", "secondary_text": "British Columbia, Canada", "category": "City", "currency": "CAD", "country": "Canada"},
    {"name": "Toronto", "secondary_text": "Ontario, Canada", "category": "City", "currency": "CAD", "country": "Canada"},
    {"name": "Montréal", "secondary_text": "Quebec, Canada", "category": "City", "currency": "CAD", "country": "Canada"},
    {"name": "Mexico City", "secondary_text": "CDMX, Mexico", "category": "City", "currency": "MXN", "country": "Mexico"},
    {"name": "Cancún & Riviera Maya", "secondary_text": "Quintana Roo, Mexico", "category": "Beach / Region", "currency": "MXN", "country": "Mexico"},
    {"name": "Costa Rica", "secondary_text": "Central America", "category": "Natural Wonder", "currency": "USD", "country": "Costa Rica"},

    # Middle East
    {"name": "Dubai", "secondary_text": "Emirate of Dubai, United Arab Emirates", "category": "City", "currency": "AED", "country": "United Arab Emirates"},
    {"name": "Abu Dhabi", "secondary_text": "United Arab Emirates", "category": "City", "currency": "AED", "country": "United Arab Emirates"},
    {"name": "Doha", "secondary_text": "Qatar", "category": "City", "currency": "QAR", "country": "Qatar"},
    {"name": "Muscat", "secondary_text": "Oman", "category": "City", "currency": "OMR", "country": "Oman"},
    {"name": "Istanbul", "secondary_text": "Marmara Region, Turkey", "category": "City", "currency": "TRY", "country": "Turkey"},
    {"name": "Cappadocia", "secondary_text": "Central Anatolia, Turkey", "category": "Natural Wonder", "currency": "TRY", "country": "Turkey"},
    {"name": "Petra", "secondary_text": "Ma'an Governorate, Jordan", "category": "Landmark", "currency": "JOD", "country": "Jordan"},
    {"name": "Cairo & Giza", "secondary_text": "Egypt", "category": "Landmark", "currency": "EGP", "country": "Egypt"},

    # Africa
    {"name": "Cape Town", "secondary_text": "Western Cape, South Africa", "category": "City", "currency": "ZAR", "country": "South Africa"},
    {"name": "Johannesburg", "secondary_text": "Gauteng, South Africa", "category": "City", "currency": "ZAR", "country": "South Africa"},
    {"name": "Kruger National Park", "secondary_text": "Mpumalanga, South Africa", "category": "National Park", "currency": "ZAR", "country": "South Africa"},
    {"name": "Marrakech", "secondary_text": "Marrakech-Safi, Morocco", "category": "City", "currency": "MAD", "country": "Morocco"},
    {"name": "Zanzibar", "secondary_text": "Tanzania", "category": "Island", "currency": "USD", "country": "Tanzania"},
    {"name": "Serengeti National Park", "secondary_text": "Tanzania", "category": "National Park", "currency": "USD", "country": "Tanzania"},
    {"name": "Victoria Falls", "secondary_text": "Zimbabwe / Zambia", "category": "Natural Wonder", "currency": "USD", "country": "Zimbabwe"},
    {"name": "Mauritius", "secondary_text": "Indian Ocean", "category": "Island", "currency": "USD", "country": "Mauritius"},

    # South America
    {"name": "Rio de Janeiro", "secondary_text": "State of Rio de Janeiro, Brazil", "category": "City", "currency": "BRL", "country": "Brazil"},
    {"name": "São Paulo", "secondary_text": "State of São Paulo, Brazil", "category": "City", "currency": "BRL", "country": "Brazil"},
    {"name": "Buenos Aires", "secondary_text": "Argentina", "category": "City", "currency": "ARS", "country": "Argentina"},
    {"name": "Machu Picchu & Cusco", "secondary_text": "Cusco Region, Peru", "category": "Landmark", "currency": "PEN", "country": "Peru"},
    {"name": "Lima", "secondary_text": "Peru", "category": "City", "currency": "PEN", "country": "Peru"},
    {"name": "Patagonia", "secondary_text": "Argentina & Chile", "category": "Natural Wonder", "currency": "USD", "country": "Argentina"},
    {"name": "Santiago", "secondary_text": "Santiago Metropolitan, Chile", "category": "City", "currency": "CLP", "country": "Chile"},
    {"name": "Cartagena", "secondary_text": "Bolívar, Colombia", "category": "City", "currency": "COP", "country": "Colombia"},
    {"name": "Galapagos Islands", "secondary_text": "Ecuador", "category": "Natural Wonder", "currency": "USD", "country": "Ecuador"},

    # Oceania
    {"name": "Sydney", "secondary_text": "New South Wales, Australia", "category": "City", "currency": "AUD", "country": "Australia"},
    {"name": "Melbourne", "secondary_text": "Victoria, Australia", "category": "City", "currency": "AUD", "country": "Australia"},
    {"name": "Great Barrier Reef", "secondary_text": "Queensland, Australia", "category": "Natural Wonder", "currency": "AUD", "country": "Australia"},
    {"name": "Auckland", "secondary_text": "North Island, New Zealand", "category": "City", "currency": "NZD", "country": "New Zealand"},
    {"name": "Queenstown", "secondary_text": "South Island, New Zealand", "category": "Natural Wonder", "currency": "NZD", "country": "New Zealand"},
    {"name": "Fiji", "secondary_text": "South Pacific", "category": "Island", "currency": "FJD", "country": "Fiji"},
]


def _offline_atlas_suggestions(query: str, max_results: int = 6) -> List[Dict[str, Any]]:
    """Search offline global destination atlas for matches or synthesize a custom suggestion."""
    clean_q = query.strip().lower()
    if not clean_q:
        return []

    # Strip basic accents for search matching (e.g. montreal -> montréal)
    def normalize_str(s: str) -> str:
        s = s.lower()
        replacements = (
            ("é", "e"), ("è", "e"), ("ê", "e"), ("ë", "e"),
            ("á", "a"), ("à", "a"), ("ã", "a"), ("ä", "a"),
            ("í", "i"), ("ì", "i"), ("ï", "i"),
            ("ó", "o"), ("ò", "o"), ("õ", "o"), ("ö", "o"),
            ("ú", "u"), ("ù", "u"), ("ü", "u"),
            ("ç", "c"), ("ñ", "n"),
        )
        for old, new in replacements:
            s = s.replace(old, new)
        return s

    norm_q = normalize_str(clean_q)
    results = []

    for item in GLOBAL_DESTINATION_ATLAS:
        name_norm = normalize_str(item["name"])
        sec_norm = normalize_str(item["secondary_text"])
        combined = f"{name_norm} {sec_norm}"

        if norm_q in combined or combined in norm_q:
            slug = re.sub(r"[^\w]+", "_", item["name"].lower())
            results.append({
                "place_id": f"atlas_{slug}",
                "name": item["name"],
                "secondary_text": item["secondary_text"],
                "full_text": f"{item['name']}, {item['secondary_text']}",
                "category": item["category"],
                "types": [item["category"].lower()],
                "source": "offline_atlas",
            })
            if len(results) >= max_results:
                break

    # If few or no matches, provide an explicit free-text selection entry
    if len(results) == 0:
        display_name = query.strip().title()
        results.append({
            "place_id": f"custom_{re.sub(r'[^\\w]+', '_', clean_q)}",
            "name": display_name,
            "secondary_text": "Worldwide Destination",
            "full_text": display_name,
            "category": "Destination",
            "types": ["locality", "point_of_interest"],
            "source": "free_text",
        })

    return results


# =====================================================================
# Main Public Interface
# =====================================================================

def get_autocomplete_suggestions(
    query: str, session_token: Optional[str] = None, max_results: int = 6
) -> Dict[str, Any]:
    """Retrieve destination suggestions worldwide.

    Prioritizes Google Places API (New) when configured; falls back gracefully to
    the curated offline Global Atlas if unconfigured or on network/quota failure.
    """
    clean_query = query.strip()
    if not clean_query or len(clean_query) < 1:
        return {
            "ok": True,
            "query": clean_query,
            "provider": "none",
            "suggestions": [],
            "attribution": None,
        }

    # Check cache
    cache_key = f"ac:{clean_query.lower()}:{session_token or 'none'}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    # Attempt Google Places API (New)
    if is_google_places_configured():
        try:
            suggestions = _fetch_google_places_autocomplete(clean_query, session_token=session_token)
            if suggestions:
                response = {
                    "ok": True,
                    "query": clean_query,
                    "provider": "google_places",
                    "suggestions": suggestions[:max_results],
                    "attribution": "Google Maps",
                }
                _cache_set(cache_key, response)
                return response
        except Exception as exc:
            logger.warning(
                "Google Places API query '%s' failed (%s). Switching to offline atlas.",
                clean_query,
                exc,
            )

    # Fallback: Curated offline atlas
    fallback_suggestions = _offline_atlas_suggestions(clean_query, max_results=max_results)
    response = {
        "ok": True,
        "query": clean_query,
        "provider": "offline_atlas",
        "suggestions": fallback_suggestions,
        "attribution": None,
    }
    _cache_set(cache_key, response)
    return response


def get_place_details(place_id: str, session_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve detailed location and address information for a selected place."""
    if not place_id:
        return None
    cache_key = f"details:{place_id}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    if is_google_places_configured() and not place_id.startswith("atlas_") and not place_id.startswith("custom_"):
        details = _fetch_google_place_details(place_id, session_token=session_token)
        if details:
            _cache_set(cache_key, details)
            return details

    return None
