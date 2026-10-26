"""planner/itinerary_agent.py - Itinerary Planning Agent

Synthesizes curated destination experiences, local exploration, dining, and scenic
walks into balanced day-by-day itineraries for exactly duration_days days.
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
) -> List[Dict[str, Any]]:
    """Construct an engaging, cohesive day-by-day itinerary for exactly duration_days."""
    days = max(1, duration_days)
    dest_name = destination_data.get("name", "Destination")
    experiences = destination_data.get("experiences", [])
    user_interests = [i.strip().capitalize() for i in (interests or [])]
    companion_type = companions.strip().capitalize() if companions else "Solo"

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

    itinerary: List[Dict[str, Any]] = []

    for i in range(days):
        day_num = i + 1
        theme_idx = i % len(day_themes)
        theme_title, default_morning, default_afternoon, default_evening = day_themes[theme_idx]

        # Use curated experience if available for this day
        exp_for_day = experiences[i % len(experiences)] if experiences else None

        morning_items = []
        afternoon_items = []
        evening_items = []

        if day_num == 1:
            morning_items = [
                f"Arrive in {dest_name}, check in to your accommodation, and unpack.",
                "Pick up local transit pass and review city orientation maps.",
            ]
            afternoon_items = [
                f"Gentle introductory walking stroll through {dest_name}'s central district.",
                "Stop at a local cafe for afternoon refreshments and people-watching.",
            ]
            evening_items = [
                f"Enjoy a welcoming dinner at a traditional neighborhood eatery in {dest_name}.",
                "Early evening walk to shake off travel fatigue before a good night's rest.",
            ]
        elif day_num == days and days > 1:
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
            if exp_for_day:
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

            afternoon_items = [
                f"{default_afternoon}",
                f"Leisure time for coffee and exploring side streets suited to {companion_type.lower()} travel.",
            ]

            evening_items = [
                f"{default_evening}",
                f"Relaxed evening dinner highlighting regional flavors of {dest_name}.",
            ]

        # Customize based on user interests
        if "Food" in user_interests and day_num == 2:
            afternoon_items.append("Sample local delicacies at renowned neighborhood specialty stalls.")
        if "Nature" in user_interests and day_num == 3:
            morning_items.append("Morning walk through botanical gardens or tranquil riverside trails.")
        if "Technology" in user_interests and day_num == 2:
            afternoon_items.append("Visit local innovation exhibits or futuristic transit hubs.")

        itinerary.append({
            "day": day_num,
            "title": f"Day {day_num}: {theme_title}",
            "morning": morning_items,
            "afternoon": afternoon_items,
            "evening": evening_items,
        })

    return itinerary
