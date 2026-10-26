"""planner - Voyage AI Rule-Based Planning Engine

Provides modular Python planning agents that operate completely offline without
mandatory external LLM dependencies:
- destination_agent: Evaluates traveler parameters and recommends destinations
- budget_agent: Performs accurate Python financial calculations
- itinerary_agent: Generates balanced day-by-day itineraries
- travel_tips_agent: Compiles logistics, safety, and packing advice
- dataset: Loads and searches local curated travel dataset
"""

from planner.budget_agent import estimate_budget
from planner.dataset import get_all_destinations, load_dataset
from planner.destination_agent import recommend_destinations, resolve_or_create_destination
from planner.itinerary_agent import build_itinerary
from planner.travel_tips_agent import generate_logistics_and_tips

__all__ = [
    "recommend_destinations",
    "resolve_or_create_destination",
    "estimate_budget",
    "build_itinerary",
    "generate_logistics_and_tips",
    "load_dataset",
    "get_all_destinations",
]
