"""planner/budget_agent.py - Budget Estimation and Arithmetic Agent

Performs deterministic Python calculations for travel expenses.
Calculates costs strictly in Python to guarantee arithmetic precision and eliminate
AI mathematical hallucinations.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def estimate_budget(
    destination_data: Dict[str, Any],
    duration_days: int,
    budget_tier: str = "Moderate",
    companions: str = "Solo",
    cost_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Calculate the comprehensive estimated budget breakdown strictly in Python.

    Formula:
    nights = max(duration_days - 1, 0)
    accommodation = accommodation_per_night * nights
    food = food_per_day * duration_days
    transport = transport_per_day * duration_days
    activities = activities_total
    total = accommodation + food + transport + activities
    """
    days = max(1, duration_days)
    nights = max(days - 1, 0)
    currency = destination_data.get("currency", "USD")

    # Get defaults from destination data
    cost_defaults = destination_data.get("cost_defaults", {})
    overrides = cost_overrides or {}

    # Multipliers for budget tiers
    tier = budget_tier.capitalize() if budget_tier else "Moderate"
    tier_factor = 1.0
    if tier == "Budget":
        tier_factor = 0.7
    elif tier == "Luxury":
        tier_factor = 2.2

    # Extract base figures
    acc_per_night = overrides.get("accommodation_per_night")
    if acc_per_night is None:
        # Check first accommodation matching tier if available
        accs = destination_data.get("accommodations", [])
        matched = next((a for a in accs if a.get("tier", "").lower() == tier.lower()), None)
        if matched and "nightly_price" in matched:
            acc_per_night = float(matched["nightly_price"])
        else:
            acc_per_night = float(cost_defaults.get("accommodation_per_night", 120.0)) * tier_factor

    food_per_day = overrides.get("food_per_day")
    if food_per_day is None:
        food_per_day = float(cost_defaults.get("food_per_day", 45.0)) * (0.8 if tier == "Budget" else (1.8 if tier == "Luxury" else 1.0))

    trans_per_day = overrides.get("transport_per_day")
    if trans_per_day is None:
        trans_per_day = float(cost_defaults.get("transport_per_day", 12.0))

    activities_total = overrides.get("activities_total")
    if activities_total is None:
        activities_total = float(cost_defaults.get("activities_total", 50.0)) * (0.75 if tier == "Budget" else (1.75 if tier == "Luxury" else 1.0))

    # Companion adjustments
    companion_type = companions.strip().capitalize() if companions else "Solo"
    companion_note = "Estimates are per person for a solo traveler."
    if companion_type == "Couple":
        companion_note = "Estimated per person based on two travelers sharing double accommodation."
    elif companion_type == "Family":
        companion_note = "Estimated per person based on family travel sharing accommodation."
    elif companion_type == "Friends":
        companion_note = "Estimated per person based on friends sharing lodging."

    # Compute exact sums
    acc_total = round(float(acc_per_night) * nights, 2)
    food_total = round(float(food_per_day) * days, 2)
    trans_total = round(float(trans_per_day) * days, 2)
    act_total = round(float(activities_total), 2)
    grand_total = round(acc_total + food_total + trans_total + act_total, 2)

    # Standard mandatory assumptions
    assumptions = [
        "All cost estimates are for planning reference and unverified; actual rates vary with season and availability.",
        companion_note,
        "Domestic and international flights are excluded from this estimated ground budget.",
        f"Calculated in {currency} for a {days}-day ({nights}-night) stay at the {tier} budget tier.",
    ]

    return {
        "currency": currency,
        "per_person": True,
        "flights_excluded": True,
        "nights": nights,
        "accommodation_per_night": round(float(acc_per_night), 2),
        "accommodation": acc_total,
        "food_per_day": round(float(food_per_day), 2),
        "food": food_total,
        "transport_per_day": round(float(trans_per_day), 2),
        "transport": trans_total,
        "activities": act_total,
        "total": grand_total,
        "assumptions": assumptions,
    }
