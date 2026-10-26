"""planner/travel_tips_agent.py - Travel Logistics, Safety, and Tips Agent

Compiles transit advice, safety recommendations, actionable verification checklists,
and climate/companion-adapted practical travel tips.
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def generate_logistics_and_tips(
    destination_data: Dict[str, Any],
    companions: str = "Solo",
    climate: str = "Any",
) -> Tuple[Dict[str, Any], List[str]]:
    """Compile ground logistics, safety warnings, verify checklist, and travel tips."""
    raw_logistics = destination_data.get("logistics", {})
    dest_name = destination_data.get("name", "Destination")
    companion_type = companions.strip().capitalize() if companions else "Solo"
    climate_pref = climate.strip() if climate else "Any"

    # Base transport options
    options = raw_logistics.get("transport_options", [])
    if not options:
        options = [{
            "mode": "Public Transit & Taxis",
            "description": f"Standard urban transit network serving {dest_name}.",
            "approx_cost_per_trip": 3.0,
            "notes": "Use contactless payment cards or reloadable transit passes.",
        }]

    # Base tips & safety
    base_tips = list(raw_logistics.get("tips", []))
    base_safety = list(raw_logistics.get("safety", []))
    base_verify = list(raw_logistics.get("verify", []))

    # Companion-specific additions
    if companion_type == "Family":
        base_tips.append("Look for family passes or discounted youth transit tickets at station kiosks.")
        base_safety.append("Establish a designated meeting point in busy transit terminals in case group members get separated.")
    elif companion_type == "Couple":
        base_tips.append("Reserve dinner tables a few days in advance for popular romantic bistros.")
    elif companion_type == "Solo":
        base_tips.append("Keep emergency contacts and lodging address cards written in the local language in your wallet.")

    # Climate-specific tips
    general_tips = list(destination_data.get("travel_tips", []))
    if "cool" in climate_pref.lower() or "alpine" in climate_pref.lower():
        general_tips.append("Pack thermal base layers, a windproof outer shell, and warm wool socks.")
    elif "warm" in climate_pref.lower() or "tropical" in climate_pref.lower():
        general_tips.append("Carry biodegradable reef-safe sunscreen, polarized sunglasses, and a refillable hydration bottle.")
    else:
        general_tips.append("Pack versatile layering pieces to easily adjust between cool mornings and warmer afternoons.")

    general_tips.append("Save digital offline copies of your travel itinerary, tickets, and passports.")

    compiled_logistics = {
        "overview": raw_logistics.get(
            "overview",
            f"{dest_name} features practical transportation including urban trains, local buses, and pedestrian-friendly zones.",
        ),
        "transport_options": options,
        "daily_transport_estimate": raw_logistics.get("daily_transport_estimate", 12.0),
        "tips": base_tips,
        "safety": base_safety,
        "verify": base_verify,
    }

    return compiled_logistics, general_tips
