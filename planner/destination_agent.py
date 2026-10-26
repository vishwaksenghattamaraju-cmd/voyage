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
    # India & South Asia
    if any(k in d for k in ["india", "hyderabad", "mumbai", "delhi", "bengaluru", "bangalore", "chennai", "kolkata", "jaipur", "goa", "kerala", "agra"]):
        return "INR"
    # Japan
    if any(k in d for k in ["japan", "tokyo", "kyoto", "osaka", "hokkaido", "fukuoka", "okinawa"]):
        return "JPY"
    # UK
    if any(k in d for k in ["uk", "london", "england", "scotland", "edinburgh", "britain", "manchester", "birmingham"]):
        return "GBP"
    # Switzerland & Alps
    if any(k in d for k in ["switzerland", "swiss", "alps", "zurich", "geneva", "lucerne", "zermatt", "matterhorn", "interlaken"]):
        return "CHF"
    # Eurozone
    if any(k in d for k in [
        "france", "paris", "nice", "lyon", "italy", "rome", "florence", "venice", "milan",
        "germany", "berlin", "munich", "spain", "barcelona", "madrid", "seville",
        "netherlands", "amsterdam", "greece", "athens", "santorini", "portugal", "lisbon", "porto",
        "vienna", "austria", "ireland", "dublin", "czech", "prague", "budapest", "hungary", "belgium", "brussels"
    ]):
        return "EUR"
    # United Arab Emirates / Middle East
    if any(k in d for k in ["dubai", "abu dhabi", "uae", "emirates", "sharjah"]):
        return "AED"
    # Indonesia
    if any(k in d for k in ["bali", "indonesia", "jakarta", "lombok", "ubud"]):
        return "IDR"
    # South Africa
    if any(k in d for k in ["south africa", "cape town", "johannesburg", "kruger", "durban"]):
        return "ZAR"
    # Thailand
    if any(k in d for k in ["thailand", "bangkok", "phuket", "chiang mai", "krabi", "koh samui"]):
        return "THB"
    # Singapore
    if "singapore" in d:
        return "SGD"
    # Malaysia
    if any(k in d for k in ["malaysia", "kuala lumpur", "penang"]):
        return "MYR"
    # Vietnam
    if any(k in d for k in ["vietnam", "hanoi", "da nang", "hoi an", "saigon", "ho chi minh"]):
        return "VND"
    # Egypt
    if any(k in d for k in ["egypt", "cairo", "giza", "luxor", "alexandria"]):
        return "EGP"
    # Turkey
    if any(k in d for k in ["turkey", "istanbul", "cappadocia", "antalya"]):
        return "TRY"
    # Morocco
    if any(k in d for k in ["morocco", "marrakech", "casablanca", "fez"]):
        return "MAD"
    # Mexico
    if any(k in d for k in ["mexico", "cancun", "oaxaca", "tulum", "guadalajara"]):
        return "MXN"
    # Brazil
    if any(k in d for k in ["brazil", "rio", "sao paulo", "salvador"]):
        return "BRL"
    # Canada
    if any(k in d for k in ["canada", "toronto", "vancouver", "banff", "montreal", "quebec", "calgary", "ottawa"]):
        return "CAD"
    # Australia
    if any(k in d for k in ["australia", "sydney", "melbourne", "brisbane", "cairns", "perth"]):
        return "AUD"
    # New Zealand
    if any(k in d for k in ["new zealand", "auckland", "queenstown", "wellington"]):
        return "NZD"
    # Korea
    if any(k in d for k in ["korea", "seoul", "busan", "jeju"]):
        return "KRW"
    # Default to USD
    return "USD"


def resolve_or_create_destination(
    destination_name: str,
    budget: str = "Moderate",
    interests: Optional[List[str]] = None,
    companions: str = "Solo",
    climate: str = "Any",
    place_id: Optional[str] = None,
    location_context: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve an existing curated destination profile or construct a rule-based synthetic profile."""
    clean_name = destination_name.strip()
    match = find_destination_by_query(clean_name)

    if match:
        logger.info("Found curated profile for '%s' -> %s", clean_name, match.get("name"))
        return match

    # Custom Worldwide Destination Synthesis
    logger.info("Destination '%s' not in knowledge base; synthesizing rule-based profile.", clean_name)
    currency = infer_currency_from_name(clean_name)
    d_lower = clean_name.lower()

    # Currency exchange multipliers relative to USD base
    curr_rates = {
        "INR": 83.0,
        "AED": 3.67,
        "IDR": 15500.0,
        "ZAR": 18.0,
        "CHF": 0.9,
        "EUR": 0.92,
        "GBP": 0.8,
        "JPY": 150.0,
        "KRW": 1350.0,
        "CAD": 1.35,
        "AUD": 1.5,
        "NZD": 1.65,
        "SGD": 1.35,
        "THB": 35.0,
        "MYR": 4.7,
        "VND": 24500.0,
        "TRY": 32.0,
        "EGP": 48.0,
        "MAD": 10.0,
        "MXN": 17.5,
        "BRL": 5.2,
        "USD": 1.0,
    }
    curr_mult = curr_rates.get(currency, 1.0)

    tier_mult = 1.0
    if budget == "Budget":
        tier_mult = 0.65
    elif budget == "Luxury":
        tier_mult = 2.4

    base_hotel = round(110.0 * curr_mult * tier_mult)
    alt_hotel = round(base_hotel * 1.3)

    # Detect destination type for domain-specific itineraries
    is_nature_park = any(k in d_lower for k in [
        "alps", "mountain", "canyon", "park", "lake", "valley", "falls", "wilderness",
        "grand canyon", "matterhorn", "banff", "yellowstone", "yosemite", "kruger", "serengeti", "everest"
    ])
    is_island_beach = any(k in d_lower for k in [
        "island", "beach", "bali", "phuket", "hawaii", "maui", "santorini", "maldives",
        "cancun", "fiji", "zanzibar", "caribbean", "coast", "coastline", "bahamas", "tulum"
    ])
    is_heritage = any(k in d_lower for k in [
        "hyderabad", "rome", "kyoto", "cairo", "giza", "athens", "florence", "jaipur",
        "agra", "petra", "machu picchu", "heritage", "historic", "temple", "palace", "fort", "delhi"
    ])

    if is_nature_park:
        inferred_climate = "Cool/Alpine" if ("alps" in d_lower or "mountain" in d_lower) else "Temperate/Mild"
        overview_text = (
            f"An awe-inspiring natural destination in {clean_name}, renowned for protected landscapes, "
            "dramatic scenic vistas, wildlife observation, and outdoor exploration."
        )
        experiences = [
            {
                "name": f"Iconic Scenic Trails & Overlooks in {clean_name}",
                "category": "Nature",
                "description": f"Hike celebrated park trails with panoramic vantage points overlooking {clean_name}.",
                "practical_tip": "Wear sturdy hiking boots and carry layers for changing alpine/wilderness weather.",
                "estimated_cost": "Free park access / Visitor pass required",
            },
            {
                "name": f"{clean_name} Wildlife & Geology Discovery Center",
                "category": "Adventure",
                "description": "Engage with expert ranger talks, interactive geological exhibits, and fauna preservation programs.",
                "practical_tip": "Check visitor center schedules upon arrival for guided ranger walks.",
                "estimated_cost": f"Approx. {round(15 * curr_mult)} {currency} pass",
            },
            {
                "name": f"Sunrise & Sunset Golden Hour Photography at {clean_name}",
                "category": "Nature",
                "description": "Capture magnificent light filtering across dramatic geological formations and natural peaks.",
                "practical_tip": "Arrive at primary viewing points 30 minutes before sunrise for optimal parking.",
                "estimated_cost": "Free admission",
            },
            {
                "name": f"Local Countryside Dining & Farm-to-Table Tasting in {clean_name}",
                "category": "Food",
                "description": "Sample hearty regional dishes, artisan cheeses, and warm bakery goods in neighboring lodges.",
                "practical_tip": "Book dinner tables in advance during high season at park lodges.",
                "estimated_cost": f"Approx. {round(30 * curr_mult * tier_mult)} {currency} per person",
            },
        ]
        accommodations = [
            {
                "name": f"{clean_name} Wilderness Eco-Lodge & Suites",
                "tier": budget,
                "area": "National Park / Scenic Gateway",
                "nightly_price": base_hotel,
                "reason": "Direct access to primary trailheads and scenic vistas.",
                "note": "Includes trail map orientation and morning breakfast.",
            },
            {
                "name": f"{clean_name} Alpine Valley Chalet",
                "tier": budget,
                "area": "Valley Village Center",
                "nightly_price": alt_hotel,
                "reason": "Charming lodge ambiance with heated lounge and mountain views.",
                "note": "Advance booking recommended for summer and winter peaks.",
            },
        ]
        transit_mode = "Park Shuttle System & Rental Vehicle"
    elif is_island_beach:
        inferred_climate = "Warm/Tropical"
        overview_text = (
            f"A sun-drenched island and coastal retreat in {clean_name}, celebrated for turquoise waters, "
            "vibrant seaside culture, relaxation, and fresh local culinary traditions."
        )
        experiences = [
            {
                "name": f"Pristine Beaches & Coastal Promenade in {clean_name}",
                "category": "Nature",
                "description": f"Relax on celebrated shores, stroll scenic beach paths, and swim in calm waters around {clean_name}.",
                "practical_tip": "Apply reef-safe sunscreen and visit early for tranquil beachfront spaces.",
                "estimated_cost": "Free beach access",
            },
            {
                "name": f"{clean_name} Marine Snorkeling & Coastal Boat Excursion",
                "category": "Adventure",
                "description": "Explore vibrant coral reefs, sea life, and hidden sea coves on a guided local boat trip.",
                "practical_tip": "Confirm equipment rental is included with your boat charter.",
                "estimated_cost": f"Approx. {round(45 * curr_mult * tier_mult)} {currency} per person",
            },
            {
                "name": f"Sunset Oceanfront Dining & Fresh Seafood Market in {clean_name}",
                "category": "Food",
                "description": "Dine on grilled local seafood, tropical fruits, and chilled refreshments right on the beach.",
                "practical_tip": "Reserve a seaside table 45 minutes before sunset for prime views.",
                "estimated_cost": f"Approx. {round(35 * curr_mult * tier_mult)} {currency} per person",
            },
            {
                "name": f"{clean_name} Island Artisan Village & Craft Market",
                "category": "Culture",
                "description": "Browse handcrafted textiles, local woodwork, and organic spices from regional artisans.",
                "practical_tip": "Bring local currency cash for independent beach market stalls.",
                "estimated_cost": "Free browsing",
            },
        ]
        accommodations = [
            {
                "name": f"{clean_name} Oceanfront Beach Resort",
                "tier": budget,
                "area": "Beachfront Promenade",
                "nightly_price": base_hotel,
                "reason": "Direct beach access with sea breezes and coastal views.",
                "note": "Complimentary beach towels and kayak rentals available.",
            },
            {
                "name": f"{clean_name} Tropical Garden Villas",
                "tier": budget,
                "area": "Quiet Coastal Village",
                "nightly_price": alt_hotel,
                "reason": "Peaceful tropical garden setting with pool and authentic hospitality.",
                "note": "Short stroll to seaside dining and village markets.",
            },
        ]
        transit_mode = "Island Taxis, Scooters & Beach Shuttles"
    elif is_heritage:
        inferred_climate = "Temperate/Mild"
        overview_text = (
            f"A deeply historic cultural destination in {clean_name}, rich in architectural wonders, "
            "ancient palaces, heritage quarters, and timeless culinary legacies."
        )
        experiences = [
            {
                "name": f"Historic Forts & Architectural Monuments in {clean_name}",
                "category": "History",
                "description": f"Explore legendary fortresses, royal residences, and monumental architecture in {clean_name}.",
                "practical_tip": "Hire an authorized monument guide at the entry gate for authentic historical context.",
                "estimated_cost": f"Approx. {round(15 * curr_mult)} {currency} admission",
            },
            {
                "name": f"{clean_name} Old City Heritage Walk & Artisan Bazaars",
                "category": "Culture",
                "description": "Wander through centuries-old alleys, fragrant spice bazaars, and traditional craft quarters.",
                "practical_tip": "Modest attire covering shoulders and knees is recommended at heritage sites.",
                "estimated_cost": "Free walking tour",
            },
            {
                "name": f"Legendary Culinary Specialties & Local Feasts in {clean_name}",
                "category": "Food",
                "description": "Savor world-renowned regional delicacies and secret family-recipe dishes perfected over generations.",
                "practical_tip": "Dine at reputable heritage restaurants known for authentic preparation.",
                "estimated_cost": f"Approx. {round(20 * curr_mult * tier_mult)} {currency} per person",
            },
            {
                "name": f"Museum of Ancient Art & Regional Antiquities in {clean_name}",
                "category": "Culture",
                "description": "Discover illuminated manuscripts, royal jewels, decorative arms, and archaeological collections.",
                "practical_tip": "Audio guides provide informative descriptions of key collection artifacts.",
                "estimated_cost": f"Approx. {round(10 * curr_mult)} {currency} ticket",
            },
        ]
        accommodations = [
            {
                "name": f"Heritage Palace Stay {clean_name}",
                "tier": budget,
                "area": "Historic Cultural Quarter",
                "nightly_price": base_hotel,
                "reason": "Authentic period architecture within walking distance of prime heritage monuments.",
                "note": "Includes traditional breakfast and cultural courtyard evening music.",
            },
            {
                "name": f"{clean_name} Grand City Center Suites",
                "tier": budget,
                "area": "Downtown Central District",
                "nightly_price": alt_hotel,
                "reason": "Modern comforts with quick transit links to historic sights and airport.",
                "note": "24-hour concierge and travel desk available.",
            },
        ]
        transit_mode = "Licensed Auto-Rickshaws, City Cabs & Metro"
    else:
        # General Worldwide Cosmopolitan City / Destination
        inferred_climate = "Temperate/Mild"
        overview_text = (
            f"A vibrant worldwide destination in {clean_name}, offering dynamic urban culture, "
            "celebrated landmarks, distinct neighborhood character, and diverse gastronomy."
        )
        experiences = [
            {
                "name": f"Historic Old Town & Central Plaza in {clean_name}",
                "category": "Culture",
                "description": f"Walk through iconic central districts, grand avenues, and heritage plazas in {clean_name}.",
                "practical_tip": "Visit early in the morning before crowds gather for peaceful sightseeing.",
                "estimated_cost": "Free admission",
            },
            {
                "name": f"{clean_name} Culinary Market & Local Food Promenade",
                "category": "Food",
                "description": "Sample authentic regional delicacies and fresh seasonal specialties at renowned food halls.",
                "practical_tip": "Carry small cash denominations for independent family-run market stalls.",
                "estimated_cost": f"Approx. {round(25 * curr_mult * tier_mult)} {currency} per person",
            },
            {
                "name": f"{clean_name} Panoramic Skyline Vista & Gardens",
                "category": "Nature",
                "description": f"Enjoy elevated views and landscaped urban parks overlooking {clean_name}.",
                "practical_tip": "Time your visit right before dusk for sunset panoramas.",
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
                "area": "Cultural Quarter",
                "nightly_price": alt_hotel,
                "reason": "Charming local atmosphere with convenient metro/bus connectivity.",
                "note": "Advance booking recommended for peak holiday dates.",
            },
        ]
        transit_mode = "Public Metro & Municipal Bus Network"

    logistics = {
        "overview": f"{clean_name} features practical transportation including {transit_mode.lower()}.",
        "transport_options": [
            {
                "mode": transit_mode,
                "description": f"Reliable transportation serving central {clean_name} and outlying sights.",
                "approx_cost_per_trip": round(2.5 * curr_mult, 2),
                "notes": "Purchase multi-ride passes or use contactless electronic payments.",
            },
            {
                "mode": "Licensed Taxis & Rideshare",
                "description": "Available from major transport terminals, stations, and central avenues.",
                "approx_cost_per_trip": round(15.0 * curr_mult, 2),
                "notes": "Verify metered rates or confirm approximate fare prior to departure.",
            },
        ],
        "daily_transport_estimate": round(12.0 * curr_mult, 2),
        "tips": [
            f"Download offline street and transit maps for {clean_name} before departure.",
            "Utilize multi-day transit passes if planning several daily trips.",
        ],
        "safety": [
            "Keep valuables in secure zippered bags in bustling transit terminals.",
            "Use official marked taxi stands at airport and rail arrival halls.",
        ],
        "verify": [
            "Confirm operating hours for return transit in the late evening.",
            "Verify whether tickets require validation prior to boarding.",
        ],
    }

    return {
        "id": re.sub(r"[^\w]+", "_", clean_name.lower()),
        "name": clean_name,
        "country": location_context or "Worldwide",
        "place_id": place_id,
        "currency": currency,
        "climate": climate if climate != "Any" else inferred_climate,
        "overview": overview_text,
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
