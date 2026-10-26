"""planner/dataset.py - Local Destination Knowledge Base Loader

Loads and provides access to curated sample destination profiles for rule-based planning.
Guarantees that the application functions fully without external network calls or paid APIs.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DATASET_CACHE: Optional[Dict[str, Any]] = None
_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "sample_destinations.json",
)


def load_dataset(filepath: Optional[str] = None) -> Dict[str, Any]:
    """Load the local JSON destination dataset into memory with caching."""
    global _DATASET_CACHE
    path = filepath or _DEFAULT_DATA_PATH

    if _DATASET_CACHE is not None and filepath is None:
        return _DATASET_CACHE

    if not os.path.exists(path):
        logger.warning("Sample destinations file not found at %s. Returning empty catalog.", path)
        return {"destinations": []}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if filepath is None:
            _DATASET_CACHE = data
        return data
    except Exception as err:
        logger.error("Failed to parse sample destinations dataset: %s", err)
        return {"destinations": []}


def get_all_destinations(filepath: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve all destination records from the knowledge base."""
    data = load_dataset(filepath)
    return data.get("destinations", [])


def find_destination_by_query(query: str, filepath: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Search for a destination matching the query by city name, country, or keyword."""
    if not query:
        return None

    destinations = get_all_destinations(filepath)
    q = query.strip().lower()

    # 1. Exact match on ID or name
    for dest in destinations:
        if q == dest.get("id", "").lower() or q == dest.get("name", "").lower():
            return dest

    # 2. Match city or country name substring
    for dest in destinations:
        dest_name = dest.get("name", "").lower()
        country_name = dest.get("country", "").lower()
        if q in dest_name or dest_name in q or q in country_name or country_name in q:
            return dest

    # 3. Keyword matching (token split)
    tokens = [t.strip(",.()'-") for t in q.split() if len(t) > 2]
    for dest in destinations:
        dest_name = dest.get("name", "").lower()
        if any(token in dest_name for token in tokens):
            return dest

    return None
