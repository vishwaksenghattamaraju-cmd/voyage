"""destinations_service.py - Worldwide Tourist Destination Database & Fast Local Search

Provides offline, zero-cost, lightning-fast search, autocomplete, faceted filtering,
and recommendations across global tourist attractions and destinations.
No external network requests, subscriptions, or paid APIs required.
"""

import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ATTRACTIONS_FILE = os.path.join(BASE_DIR, "data", "attractions.json")
SAMPLE_DESTINATIONS_FILE = os.path.join(BASE_DIR, "data", "sample_destinations.json")

# In-memory thread-safe cache
_cache_lock = threading.Lock()
_cached_attractions: Optional[List[Dict[str, Any]]] = None
_cached_metadata: Optional[Dict[str, Any]] = None


def normalize_str(s: Any) -> str:
    """Normalize string for safe, case-insensitive comparison."""
    if s is None:
        return ""
    return str(s).strip().lower()


def load_attractions(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Load attractions from data/attractions.json with thread-safe caching."""
    global _cached_attractions, _cached_metadata
    with _cache_lock:
        if _cached_attractions is not None and not force_reload:
            return _cached_attractions

        if not os.path.isfile(ATTRACTIONS_FILE):
            logger.warning("Attractions file not found at %s. Returning empty list.", ATTRACTIONS_FILE)
            _cached_attractions = []
            _cached_metadata = {}
            return _cached_attractions

        try:
            with open(ATTRACTIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                _cached_metadata = data.get("catalog_metadata", {})
                attractions_list = data.get("attractions", [])
            elif isinstance(data, list):
                _cached_metadata = {}
                attractions_list = data
            else:
                attractions_list = []

            # Ensure every item has an id, coordinates, traveler_types, tags
            sanitized: List[Dict[str, Any]] = []
            for item in attractions_list:
                if not isinstance(item, dict):
                    continue
                clean_item = dict(item)
                if not clean_item.get("id"):
                    raw_name = clean_item.get("name", "attraction")
                    clean_item["id"] = re.sub(r"[^a-zA-Z0-9_]+", "_", raw_name.lower()).strip("_")
                if "tags" not in clean_item or not isinstance(clean_item["tags"], list):
                    clean_item["tags"] = []
                if "traveler_types" not in clean_item or not isinstance(clean_item["traveler_types"], list):
                    clean_item["traveler_types"] = ["Solo", "Couple", "Family", "Friends"]
                if "coordinates" not in clean_item or not isinstance(clean_item["coordinates"], dict):
                    clean_item["coordinates"] = {"lat": 0.0, "lng": 0.0}
                sanitized.append(clean_item)

            _cached_attractions = sanitized
            logger.info("Successfully loaded %d attractions from %s", len(_cached_attractions), ATTRACTIONS_FILE)
            return _cached_attractions
        except Exception as exc:
            logger.exception("Failed to load attractions from %s: %s", ATTRACTIONS_FILE, exc)
            _cached_attractions = []
            _cached_metadata = {}
            return _cached_attractions


def get_attraction_by_id(attraction_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve an attraction record by its unique ID."""
    if not attraction_id:
        return None
    target_id = normalize_str(attraction_id)
    attractions = load_attractions()
    for item in attractions:
        if normalize_str(item.get("id")) == target_id:
            return dict(item)
    return None


def get_catalog_facets() -> Dict[str, Any]:
    """Return distinct filter facets with item counts."""
    attractions = load_attractions()
    continents: Dict[str, int] = {}
    countries: Dict[str, int] = {}
    categories: Dict[str, int] = {}
    budget_tiers: Dict[str, int] = {}
    traveler_types: Dict[str, int] = {}

    for a in attractions:
        cont = a.get("continent")
        if cont:
            continents[cont] = continents.get(cont, 0) + 1

        country = a.get("country")
        if country:
            countries[country] = countries.get(country, 0) + 1

        cat = a.get("category")
        if cat:
            categories[cat] = categories.get(cat, 0) + 1

        tier = a.get("budget_tier")
        if tier:
            budget_tiers[tier] = budget_tiers.get(tier, 0) + 1

        for tt in a.get("traveler_types", []):
            if tt:
                traveler_types[tt] = traveler_types.get(tt, 0) + 1

    return {
        "continents": sorted([{"name": k, "count": v} for k, v in continents.items()], key=lambda x: x["name"]),
        "countries": sorted([{"name": k, "count": v} for k, v in countries.items()], key=lambda x: x["name"]),
        "categories": sorted([{"name": k, "count": v} for k, v in categories.items()], key=lambda x: x["name"]),
        "budget_tiers": sorted([{"name": k, "count": v} for k, v in budget_tiers.items()], key=lambda x: x["name"]),
        "traveler_types": sorted([{"name": k, "count": v} for k, v in traveler_types.items()], key=lambda x: x["name"]),
        "total_attractions": len(attractions),
    }


def search_attractions(
    query: str = "",
    continent: str = "",
    country: str = "",
    category: str = "",
    budget: str = "",
    traveler_type: str = "",
    tag: str = "",
    sort_by: str = "name",
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Perform faceted search across the local destination and attraction database.

    Filters are combined conjunctively (AND).
    Zero network calls or external dependencies.
    """
    attractions = load_attractions()
    q_norm = normalize_str(query)
    cont_norm = normalize_str(continent)
    country_norm = normalize_str(country)
    cat_norm = normalize_str(category)
    budget_norm = normalize_str(budget)
    tt_norm = normalize_str(traveler_type)
    tag_norm = normalize_str(tag)

    results: List[Dict[str, Any]] = []

    for item in attractions:
        # 1. Continent filter
        if cont_norm and normalize_str(item.get("continent")) != cont_norm:
            continue

        # 2. Country filter (exact or substring)
        if country_norm:
            item_country = normalize_str(item.get("country"))
            if country_norm != item_country and country_norm not in item_country:
                continue

        # 3. Category filter
        if cat_norm and normalize_str(item.get("category")) != cat_norm:
            continue

        # 4. Budget filter
        if budget_norm and normalize_str(item.get("budget_tier")) != budget_norm:
            continue

        # 5. Traveler type filter
        if tt_norm:
            item_tts = [normalize_str(t) for t in item.get("traveler_types", [])]
            if tt_norm not in item_tts:
                continue

        # 6. Tag filter
        if tag_norm:
            item_tags = [normalize_str(t) for t in item.get("tags", [])]
            if not any(tag_norm in t for t in item_tags):
                continue

        # 7. Text Query search (matches name, city, country, region, description, tags)
        if q_norm:
            searchable_fields = [
                item.get("name", ""),
                item.get("city", ""),
                item.get("country", ""),
                item.get("region", ""),
                item.get("category", ""),
                item.get("description", ""),
                " ".join(item.get("tags", [])),
            ]
            combined = " ".join(searchable_fields).lower()
            # Tokenized query: each word must match
            query_tokens = q_norm.split()
            if not all(tok in combined for tok in query_tokens):
                continue

        results.append(item)

    # Sorting
    if sort_by == "name":
        results.sort(key=lambda x: x.get("name", "").lower())
    elif sort_by == "country":
        results.sort(key=lambda x: (x.get("country", "").lower(), x.get("name", "").lower()))
    elif sort_by == "category":
        results.sort(key=lambda x: (x.get("category", "").lower(), x.get("name", "").lower()))

    total = len(results)
    paged = results[offset : offset + limit] if limit > 0 else results

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "attractions": paged,
        "facets": get_catalog_facets(),
    }


def get_destination_autocomplete(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Instant typeahead autocomplete by destination name, city, country, or tag.

    Returns structured suggestions suitable for search bars and dropdown pickers.
    Zero external network requests.
    """
    clean_q = normalize_str(query)
    if not clean_q:
        # Default popular suggestions
        attractions = load_attractions()
        sample = attractions[:limit]
        return [
            {
                "id": a.get("id"),
                "name": a.get("name"),
                "city": a.get("city"),
                "country": a.get("country"),
                "continent": a.get("continent"),
                "category": a.get("category"),
                "display": f"{a.get('name')}, {a.get('city')}, {a.get('country')}",
                "type": "attraction",
                "tags": a.get("tags", [])[:4],
                "image_url": a.get("image_url", ""),
            }
            for a in sample
        ]

    attractions = load_attractions()
    matches: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()

    # Track unique cities/countries that match to offer destination-level suggestions
    matching_places: Dict[str, Dict[str, str]] = {}

    for a in attractions:
        a_id = a.get("id", "")
        name = a.get("name", "")
        city = a.get("city", "")
        country = a.get("country", "")
        cont = a.get("continent", "")
        tags = a.get("tags", [])

        name_lower = name.lower()
        city_lower = city.lower()
        country_lower = country.lower()
        tags_lower = [t.lower() for t in tags]

        # Check city or country level match
        if clean_q in city_lower or clean_q in country_lower:
            place_key = f"{city}, {country}".lower()
            if place_key not in matching_places:
                matching_places[place_key] = {
                    "city": city,
                    "country": country,
                    "continent": cont,
                }

        # Match attraction
        matched = False
        priority = 0
        if name_lower.startswith(clean_q):
            matched = True
            priority = 10
        elif clean_q in name_lower:
            matched = True
            priority = 8
        elif city_lower.startswith(clean_q) or country_lower.startswith(clean_q):
            matched = True
            priority = 6
        elif clean_q in city_lower or clean_q in country_lower:
            matched = True
            priority = 4
        elif any(clean_q in t for t in tags_lower):
            matched = True
            priority = 2

        if matched and a_id not in seen_ids:
            seen_ids.add(a_id)
            matches.append({
                "id": a_id,
                "name": name,
                "city": city,
                "country": country,
                "continent": cont,
                "category": a.get("category", "General"),
                "display": f"{name}, {city}, {country}",
                "type": "attraction",
                "tags": tags[:4],
                "image_url": a.get("image_url", ""),
                "_priority": priority,
            })

    # Sort matches by match quality priority, then alphabetically
    matches.sort(key=lambda x: (-x["_priority"], x["name"].lower()))

    # Build final list: place matches first if strong, followed by attraction matches
    final_suggestions: List[Dict[str, Any]] = []

    for place_info in list(matching_places.values())[:2]:
        final_suggestions.append({
            "id": f"dest_{normalize_str(place_info['city'])}_{normalize_str(place_info['country'])}",
            "name": f"{place_info['city']}, {place_info['country']}",
            "city": place_info["city"],
            "country": place_info["country"],
            "continent": place_info["continent"],
            "category": "Destination",
            "display": f"{place_info['city']}, {place_info['country']}",
            "type": "destination",
            "tags": ["city", "destination"],
            "image_url": "",
        })

    for m in matches:
        clean_item = dict(m)
        clean_item.pop("_priority", None)
        final_suggestions.append(clean_item)
        if len(final_suggestions) >= limit:
            break

    return final_suggestions[:limit]


def recommend_attractions_for_trip(
    destination: str = "",
    budget: str = "",
    duration_days: int = 3,
    interests: Optional[List[str]] = None,
    companions: str = "",
    climate: str = "",
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Recommend attractions from the catalog matching trip parameters.

    Scores by destination name match, interests, budget tier, and traveler type.
    Zero external network calls or paid APIs.
    """
    attractions = load_attractions()
    dest_norm = normalize_str(destination)
    clean_interests = [normalize_str(i) for i in (interests or [])]
    budget_norm = normalize_str(budget)
    comp_norm = normalize_str(companions)

    interest_keyword_map = {
        "culture": ["culture", "cultural", "art", "museum", "temple", "shrine", "heritage", "monument"],
        "history": ["history", "historical", "ancient", "castle", "fort", "unesco", "palace", "ruins"],
        "nature": ["nature", "park", "wildlife", "safari", "mountain", "lake", "scenic", "fjord", "garden", "reef"],
        "adventure": ["adventure", "hiking", "trekking", "safari", "outdoor", "walk", "climb"],
        "food": ["food", "culinary", "market", "tasting", "street food", "local"],
        "shopping": ["shopping", "bazaar", "souk", "boutique", "market"],
        "technology": ["technology", "modern", "futuristic", "skyline", "architecture", "tower", "innovation"],
    }

    scored: List[Tuple[float, Dict[str, Any]]] = []

    for a in attractions:
        score = 0.0
        a_city = normalize_str(a.get("city"))
        a_country = normalize_str(a.get("country"))
        a_name = normalize_str(a.get("name"))
        a_cat = normalize_str(a.get("category"))
        a_tags = [normalize_str(t) for t in a.get("tags", [])]
        a_budget = normalize_str(a.get("budget_tier"))
        a_travelers = [normalize_str(t) for t in a.get("traveler_types", [])]

        # 1. Geographic match
        if dest_norm:
            if dest_norm in a_city or a_city in dest_norm:
                score += 50.0
            elif dest_norm in a_country or a_country in dest_norm:
                score += 30.0
            elif dest_norm in a_name or a_name in dest_norm:
                score += 40.0

        # 2. Interests match
        for user_int in clean_interests:
            keywords = interest_keyword_map.get(user_int, [user_int])
            matched_interest = False
            if any(kw in a_cat for kw in keywords):
                score += 15.0
                matched_interest = True
            for tag in a_tags:
                if any(kw in tag for kw in keywords):
                    score += 10.0
                    matched_interest = True
                    break
            if matched_interest:
                score += 5.0

        # 3. Budget match
        if budget_norm and a_budget == budget_norm:
            score += 10.0

        # 4. Companion match
        if comp_norm and comp_norm in a_travelers:
            score += 10.0

        scored.append((score, a))

    # Sort descending by score, then name
    scored.sort(key=lambda x: (-x[0], x[1].get("name", "").lower()))
    return [item for _, item in scored[:limit]]


# =====================================================================
# Backward Compatibility Shim for Google Places
# =====================================================================

def is_google_places_configured() -> bool:
    """Return False always: Google Maps is completely replaced with offline local catalog."""
    return False


def get_autocomplete_suggestions(query: str, session_token: Optional[str] = None) -> Dict[str, Any]:
    """Shim returning autocomplete suggestions formatted for frontend consumers."""
    items = get_destination_autocomplete(query=query, limit=8)
    predictions = []
    for it in items:
        predictions.append({
            "place_id": it.get("id"),
            "description": it.get("display"),
            "main_text": it.get("name"),
            "secondary_text": f"{it.get('city', '')}, {it.get('country', '')}".strip(", "),
            "category": it.get("category", "General"),
            "type": it.get("type", "attraction"),
            "continent": it.get("continent", ""),
        })
    return {
        "ok": True,
        "provider": "worldwide_atlas",
        "predictions": predictions,
        "suggestions": items,
    }


def get_place_details(place_id: str, session_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Shim returning attraction details formatted as place details."""
    attraction = get_attraction_by_id(place_id)
    if not attraction:
        return None
    coords = attraction.get("coordinates", {})
    return {
        "place_id": attraction.get("id"),
        "name": attraction.get("name"),
        "formatted_address": f"{attraction.get('name')}, {attraction.get('city')}, {attraction.get('country')}",
        "city": attraction.get("city"),
        "country": attraction.get("country"),
        "continent": attraction.get("continent"),
        "latitude": coords.get("lat", 0.0),
        "longitude": coords.get("lng", 0.0),
        "category": attraction.get("category"),
        "description": attraction.get("description"),
        "duration_hours": attraction.get("duration_hours"),
        "estimated_cost": attraction.get("estimated_cost"),
        "budget_tier": attraction.get("budget_tier"),
        "best_season": attraction.get("best_season"),
        "traveler_types": attraction.get("traveler_types", []),
        "tags": attraction.get("tags", []),
        "image_url": attraction.get("image_url", ""),
    }
