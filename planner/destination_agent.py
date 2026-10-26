"""planner/destination_agent.py - Destination Recommendation and Resolution Agent

Evaluates traveler parameters (budget, duration, interests, companions, climate)
against the local knowledge base to rank destination matches, or resolves custom
user-entered destinations into structured travel profiles.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from planner.dataset import find_destination_by_query, get_all_destinations

logger = logging.getLogger(__name__)


def recommend_destinations(
    budget: str = "Moderate",
    duration_days: int = 3,
    interests: Optional[List[str]] = None,
    companions: str = "Solo",
    climate: str = "Any",
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    """Rank and recommend destinations based on budget, duration, interests, companions, and climate.

    Returns:
        List of ranked destination recommendations with match scores and rationales.
    """
    destinations = get_all_destinations()
    if not destinations:
        return []

    user_interests = set(i.strip().lower() for i in (interests or []))
    target_budget = budget.strip().capitalize() if budget else "Moderate"
    target_companions = companions.strip().capitalize() if companions else "Solo"
    target_climate = climate.strip() if climate else "Any"

    scored_results = []

    for dest in destinations:
        score = 0.0
        reasons = []

        # 1. Budget Compatibility (max 30 pts)
        supported_budgets = dest.get("budget_tiers", [])
        if target_budget in supported_budgets:
            score += 30.0
            reasons.append(f"Supports {target_budget} budget tier with great lodging and dining value.")
        elif "Moderate" in supported_budgets:
            score += 15.0
            reasons.append("Adaptable to your budget preferences with selective choices.")
        else:
            score += 5.0

        # 2. Interests Alignment (max 30 pts)
        dest_interests = [i.lower() for i in dest.get("interests", [])]
        if user_interests:
            matched_interests = [i for i in dest_interests if i in user_interests]
            if matched_interests:
                ratio = len(matched_interests) / len(user_interests)
                points = min(30.0, ratio * 30.0 + len(matched_interests) * 5.0)
                score += points
                matched_names = [i.capitalize() for i in matched_interests]
                reasons.append(f"Excellent for your interests in {', '.join(matched_names)}.")
            else:
                score += 5.0
        else:
            # Neutral interest score
            score += 20.0
            reasons.append("Offers rich, balanced sightseeing and cultural diversity.")

        # 3. Climate Match (max 20 pts)
        dest_climate = dest.get("climate", "")
        if target_climate in ("Any", "", None):
            score += 20.0
        elif target_climate.lower() in dest_climate.lower() or dest_climate.lower() in target_climate.lower():
            score += 20.0
            reasons.append(f"Matches your preference for {dest_climate} climate.")
        else:
            score += 5.0

        # 4. Travel Companions Suitability (max 10 pts)
        dest_companions = dest.get("companions", [])
        if target_companions in dest_companions or target_companions == "Solo":
            score += 10.0
            reasons.append(f"Well-suited for {target_companions.lower()} travelers.")
        else:
            score += 5.0

        # 5. Trip Duration Fit (max 10 pts)
        min_d = dest.get("min_days", 2)
        max_d = dest.get("max_days", 14)
        if min_d <= duration_days <= max_d:
            score += 10.0
            reasons.append(f"Ideal for a {duration_days}-day itinerary.")
        elif duration_days < min_d:
            score += 4.0
            reasons.append(f"Can be enjoyed as a fast-paced {duration_days}-day express visit.")
        else:
            score += 7.0
            reasons.append(f"Provides ample depth for an extended {duration_days}-day exploration.")

        # Cap match score between 0 and 100
        final_score = int(min(100.0, max(10.0, score)))

        scored_results.append({
            "id": dest.get("id"),
            "destination": dest.get("name"),
            "country": dest.get("country"),
            "region": dest.get("region"),
            "currency": dest.get("currency", "USD"),
            "climate": dest_climate,
            "match_score": final_score,
            "reasons": reasons[:3],
            "overview": dest.get("overview", ""),
        })

    # Sort descending by match score
    scored_results.sort(key=lambda r: r["match_score"], reverse=True)
    return scored_results[:top_k]


def filter_accommodations_for_budget(accommodations: List[Dict[str, Any]], target_tier: str) -> List[Dict[str, Any]]:
    """Return exactly 2 accommodation options matching or nearest to the target budget tier."""
    if len(accommodations) <= 2:
        return accommodations

    match = next((a for a in accommodations if a.get("tier", "").lower() == target_tier.lower()), None)
    others = [a for a in accommodations if a != match]

    if match and others:
        return [match, others[0]]
    return accommodations[:2]


def infer_currency_from_name(destination_name: str) -> str:
    """Infer common ISO currency code from destination name or text."""
    d = destination_name.lower()
    if any(k in d for k in ["japan", "tokyo", "kyoto", "osaka", "hokkaido"]):
        return "JPY"
    if any(k in d for k in ["uk", "london", "england", "scotland", "edinburgh", "britain"]):
        return "GBP"
    if any(k in d for k in ["france", "paris", "italy", "rome", "germany", "berlin", "spain", "madrid", "amsterdam", "greece", "portugal", "vienna", "austria", "ireland", "dublin", "czech", "prague"]):
        return "EUR"
    if any(k in d for k in ["switzerland", "zurich", "geneva", "lucerne"]):
        return "CHF"
    if any(k in d for k in ["canada", "toronto", "vancouver", "banff", "montreal"]):
        return "CAD"
    if any(k in d for k in ["australia", "sydney", "melbourne"]):
        return "AUD"
    if any(k in d for k in ["korea", "seoul", "busan"]):
        return "KRW"
    return "USD"


def resolve_or_create_destination(
    destination_name: str,
    budget: str = "Moderate",
    interests: Optional[List[str]] = None,
    companions: str = "Solo",
    climate: str = "Any",
) -> Dict[str, Any]:
    """Retrieve an existing curated destination profile or construct a rule-based synthetic profile."""
    clean_name = destination_name.strip()
    match = find_destination_by_query(clean_name)

    if match:
        logger.info("Found curated profile for '%s' -> %s", clean_name, match.get("name"))
        return match

    # Custom Destination Synthesis
    logger.info("Destination '%s' not in knowledge base; synthesizing rule-based profile.", clean_name)
    currency = infer_currency_from_name(clean_name)

    curr_mult = 1.0
    if currency == "JPY":
        curr_mult = 150.0
    elif currency == "KRW":
        curr_mult = 1350.0
    elif currency == "GBP":
        curr_mult = 0.8
    elif currency == "CAD":
        curr_mult = 1.35

    tier_mult = 1.0
    if budget == "Budget":
        tier_mult = 0.65
    elif budget == "Luxury":
        tier_mult = 2.4

    base_hotel = round(110.0 * curr_mult * tier_mult)
    alt_hotel = round(base_hotel * 1.3)

    experiences = [
        {
            "name": f"Historic Old Town & Architectural Landmarks in {clean_name}",
            "category": "Culture",
            "description": f"Walk through iconic historic districts, heritage monuments, and central plazas in {clean_name}.",
            "practical_tip": "Visit early in the morning before tourist crowds gather for peaceful photography.",
            "estimated_cost": "Free admission",
        },
        {
            "name": f"{clean_name} Culinary Market & Local Food Tour",
            "category": "Food",
            "description": "Sample authentic regional delicacies and fresh seasonal products at renowned market stalls and cafes.",
            "practical_tip": "Carry small cash denominations for independent family-run street stalls.",
            "estimated_cost": f"Approx. {round(25 * curr_mult * tier_mult)} {currency} per person",
        },
        {
            "name": f"{clean_name} Panoramic Scenic Vista & Gardens",
            "category": "Nature",
            "description": f"Enjoy elevated vistas and landscaped urban parks overlooking {clean_name}.",
            "practical_tip": "Time your visit for the golden hour right before dusk for sunset views.",
            "estimated_cost": "Free admission",
        },
        {
            "name": f"Museum of Art & Cultural Heritage in {clean_name}",
            "category": "History",
            "description": "Explore world-class exhibitions, historical artifacts, and works celebrating regional identity.",
            "practical_tip": "Check for online advance bookings to bypass ticket queues.",
            "estimated_cost": f"Approx. {round(15 * curr_mult)} {currency} entry",
        },
    ]

    accommodations = [
        {
          "name": f"Central Boutique Stay {clean_name}",
          "tier": budget,
          "area": "City Center / Downtown",
          "nightly_price": base_hotel,
          "reason": f"Walking distance to primary attractions, public transit, and vibrant cafes in {clean_name}.",
          "note": "Indicative seasonal estimate for solo/couple travel.",
        },
        {
          "name": f"Heritage Guesthouse & Suites {clean_name}",
          "tier": budget,
          "area": "Historic Cultural Quarter",
          "nightly_price": alt_hotel,
          "reason": "Charming local atmosphere with convenient metro/bus connectivity.",
          "note": "Advance booking recommended for peak holiday dates.",
        },
    ]

    logistics = {
        "overview": f"{clean_name} features practical transportation including urban trains, local buses, and pedestrian-friendly zones.",
        "transport_options": [
            {
                "mode": "Public Metro & Bus Network",
                "description": f"Reliable municipal transport serving central {clean_name} and outlying sights.",
                "approx_cost_per_trip": round(2.5 * curr_mult, 2),
                "notes": "Purchase multi-ride transit passes or use contactless tap payment.",
            },
            {
                "mode": "Licensed City Taxis & Rideshare",
                "description": "Available from major stations and city squares for point-to-point transit.",
                "approx_cost_per_trip": round(15.0 * curr_mult, 2),
                "notes": "Verify metered rates or confirm approximate fare beforehand.",
            },
        ],
        "daily_transport_estimate": round(12.0 * curr_mult, 2),
        "tips": [
            f"Download offline transit and street maps for {clean_name} before departure.",
            "Utilize multi-day transit passes if planning several daily trips.",
        ],
        "safety": [
            "Keep valuables in secure zippered pockets in bustling transit hubs.",
            "Use official marked taxi stands at airport and rail arrival halls.",
        ],
        "verify": [
            "Confirm operating hours for return trains or buses in the late evening.",
            "Verify whether transport tickets require physical stamp validation prior to boarding.",
        ],
    }

    return {
        "id": re.sub(r"[^\w]+", "_", clean_name.lower()),
        "name": clean_name,
        "country": "International",
        "currency": currency,
        "climate": climate if climate != "Any" else "Temperate/Mild",
        "overview": f"A vibrant travel destination offering diverse cultural experiences, historical landmarks, and regional dining in {clean_name}.",
        "experiences": experiences,
        "accommodations": accommodations,
        "logistics": logistics,
        "cost_defaults": {
            "accommodation_per_night": base_hotel,
            "food_per_day": round(45.0 * curr_mult * tier_mult),
            "transport_per_day": round(12.0 * curr_mult),
            "activities_total": round(50.0 * curr_mult * tier_mult),
        },
        "travel_tips": [
            "Keep digital backups of your passport and reservations saved offline.",
            f"Check local weather forecasts before packing for your stay in {clean_name}.",
            "Carry a small portable power bank for mobile map navigation.",
        ],
    }
