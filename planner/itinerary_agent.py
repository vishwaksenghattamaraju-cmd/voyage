"""planner/itinerary_agent.py - Itinerary Planning Agent

Synthesizes curated destination experiences, user-selected tourist attractions,
local exploration, dining, and scenic walks into balanced day-by-day itineraries
for exactly duration_days days.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def build_itinerary(
    destination_data: Dict[str, Any],
    duration_days: int,
    interests: Optional[List[str]] = None,
    budget_tier: str = "Moderate",
    companions: str = "Solo",
    selected_attractions: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Construct an engaging, cohesive day-by-day itinerary for exactly duration_days.

    If selected_attractions are provided by the user, weaves them directly into the
    daily schedule as prioritized highlights.
    """
    days = max(1, duration_days)
    dest_name = destination_data.get("name", "Destination")
    experiences = destination_data.get("experiences", [])
    user_interests = [i.strip().capitalize() for i in (interests or [])]
    companion_type = companions.strip().capitalize() if companions else "Solo"

    # Normalize user-selected attractions
    clean_selected: List[Dict[str, str]] = []
    if selected_attractions and isinstance(selected_attractions, list):
        for item in selected_attractions:
            if isinstance(item, str) and item.strip():
                clean_selected.append({"name": item.strip(), "description": ""})
            elif isinstance(item, dict) and item.get("name"):
                clean_selected.append({
                    "name": str(item.get("name")).strip(),
                    "description": str(item.get("description", "")).strip(),
                    "category": str(item.get("category", "")).strip(),
                })

    # Thematic daily templates
    day_themes = [
        ("Arrival & Historic Orientation", "Morning arrival, check in to lodging, and orient to the neighborhood.", "Historic center walking promenade.", "Traditional welcome dinner at local bistro/trattoria."),
        ("Cultural Masterpieces & Heritage", "Visit celebrated national museum or cultural monument.", "Explore scenic plazas and artisan craft shops.", "Atmospheric evening stroll through illuminated heritage streets."),
        ("Culinary Discovery & Local Markets", "Morning specialty coffee and neighborhood bakery tasting.", "Curated market tasting tour exploring street food specialties.", "Casual dinner at neighborhood favorite eatery."),
        ("Scenic Panoramas & Natural Wonders", "Scenic trail hike or visit to celebrated mountain/river vantage point.", "Relaxed park picnic or garden visit.", "Sunset viewpoint cocktails or tea with panoramic vistas."),
        ("Neighborhood Gems & Boutique Living", "Explore bohemian arts district and indie boutiques.", "Gallery visit and leisurely lunch in leafy courtyards.", "Dinner featuring regional seasonal dishes."),
        ("Active Adventure & Outdoor Excursion", "Outdoor activity, coastal walk, or day trip to nearby scenic preserve.", "Al fresco lunch with local provisions.", "Relaxing thermal soak or spa recovery."),
        ("Architectural Wonders & Hidden Courtyards", "Architectural discovery tour exploring hidden courtyards.", "Antiques and flea market browsing.", "Farewell dinner celebrating local culinary traditions."),
        ("Leisure, Souvenirs & Departure Prep", "Last-minute souvenir shopping for local teas, crafts, or treats.", "Scenic lunch overlooking landmarks.", "Departure preparation and airport/rail transit."),
    ]

    # Queue of selected attractions to distribute across days
    attraction_queue = list(clean_selected)

    itinerary: List[Dict[str, Any]] = []

    for i in range(days):
        day_num = i + 1
        theme_idx = i % len(day_themes)
        theme_title, default_morning, default_afternoon, default_evening = day_themes[theme_idx]

        # Use curated experience if available for this day
        exp_for_day = experiences[i % len(experiences)] if experiences else None

        morning_items: List[str] = []
        afternoon_items: List[str] = []
        evening_items: List[str] = []
        day_attractions: List[str] = []

        if day_num == 1:
            morning_items = [
                f"Arrive in {dest_name}, check in to your accommodation, and unpack.",
                "Pick up local transit pass and review city orientation maps.",
            ]
            if attraction_queue:
                chosen = attraction_queue.pop(0)
                day_attractions.append(chosen["name"])
                afternoon_items = [
                    f"Highlight Visit: {chosen['name']}.",
                    f"{chosen['description']}" if chosen["description"] else f"Explore {chosen['name']} and its scenic surrounding neighborhood.",
                    "Stop at a nearby cafe for afternoon refreshments and people-watching.",
                ]
            else:
                afternoon_items = [
                    f"Gentle introductory walking stroll through {dest_name}'s central district.",
                    "Stop at a local cafe for afternoon refreshments and people-watching.",
                ]
            evening_items = [
                f"Enjoy a welcoming dinner at a traditional neighborhood eatery in {dest_name}.",
                "Early evening walk to shake off travel fatigue before a good night's rest.",
            ]
        elif day_num == days and days > 1:
            if attraction_queue:
                chosen = attraction_queue.pop(0)
                day_attractions.append(chosen["name"])
                morning_items = [
                    f"Morning Highlight: Visit {chosen['name']}.",
                    f"Final chance to experience {chosen['name']} before packing.",
                ]
            else:
                morning_items = [
                    "Enjoy a leisurely final breakfast at a nearby bakery or hotel dining room.",
                    f"Visit local market stalls or souvenir boutiques to pick up regional gifts from {dest_name}.",
                ]
            afternoon_items = [
                f"Final stroll past favorite viewpoints or parks in {dest_name}.",
                "Return to accommodation to pack luggage and complete check-out.",
            ]
            evening_items = [
                "Transfer to airport or train station for departure journey.",
                "Safe travels home with memorable highlights from your journey!",
            ]
        else:
            # Days in between
            if attraction_queue:
                chosen = attraction_queue.pop(0)
                day_attractions.append(chosen["name"])
                morning_items = [
                    f"Priority Highlight: Visit {chosen['name']}.",
                    f"{chosen['description']}" if chosen['description'] else f"Take your time discovering the sights and photo spots at {chosen['name']}.",
                ]
            elif exp_for_day:
                exp_name = exp_for_day.get("name", "Local Attraction")
                exp_tip = exp_for_day.get("practical_tip", "")
                morning_items = [
                    f"Visit {exp_name}.",
                    f"Tip: {exp_tip}" if exp_tip else f"Enjoy exploring the sights and surroundings of {exp_name}.",
                ]
            else:
                morning_items = [
                    f"Morning exploration in {dest_name}: {default_morning}",
                    "Breakfast featuring regional specialties.",
                ]

            if attraction_queue and (len(attraction_queue) >= (days - day_num)):
                # If we have more attractions than remaining days, put one in the afternoon
                chosen2 = attraction_queue.pop(0)
                day_attractions.append(chosen2["name"])
                afternoon_items = [
                    f"Afternoon Highlight: {chosen2['name']}.",
                    f"{chosen2['description']}" if chosen2['description'] else f"Explore {chosen2['name']} during peak afternoon atmosphere.",
                    f"Leisure time for coffee and exploring side streets suited to {companion_type.lower()} travel.",
                ]
            else:
                afternoon_items = [
                    f"{default_afternoon}",
                    f"Leisure time for coffee and exploring side streets suited to {companion_type.lower()} travel.",
                ]

            evening_items = [
                f"{default_evening}",
                f"Relaxed evening dinner highlighting regional flavors of {dest_name}.",
            ]

        # Customize based on user interests
        if "Food" in user_interests and day_num == 2 and not any("delicacies" in it for it in afternoon_items):
            afternoon_items.append("Sample local delicacies at renowned neighborhood specialty stalls.")
        if "Nature" in user_interests and day_num == 3 and not any("botanical" in it for it in morning_items):
            morning_items.append("Morning walk through botanical gardens or tranquil riverside trails.")
        if "Technology" in user_interests and day_num == 2 and not any("innovation" in it for it in afternoon_items):
            afternoon_items.append("Visit local innovation exhibits or futuristic transit hubs.")

        day_dict: Dict[str, Any] = {
            "day": day_num,
            "title": f"Day {day_num}: {theme_title}",
            "morning": morning_items,
            "afternoon": afternoon_items,
            "evening": evening_items,
        }
        if day_attractions:
            day_dict["attractions_visited"] = day_attractions

        itinerary.append(day_dict)

    return itinerary
