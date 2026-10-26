"""tests/test_destinations.py - Comprehensive Unit & Integration Tests for Worldwide Destinations Database

Tests zero-cost offline local search, faceted filtering, typeahead autocomplete,
recommendations, and multi-agent itinerary integration.
"""

import json
import unittest

from app import app
import destinations_service


class TestWorldwideDestinationsDatabase(unittest.TestCase):
    """Test suite for local tourist destination database and search engine."""

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()

    def test_load_attractions_structure(self):
        """Verify attractions are loaded with all mandatory metadata fields."""
        attractions = destinations_service.load_attractions()
        self.assertGreater(len(attractions), 30, "Should have a rich database of attractions")

        required_keys = {
            "id", "name", "country", "city", "continent", "category",
            "description", "duration_hours", "best_season", "budget_tier",
            "coordinates", "traveler_types", "tags"
        }
        for item in attractions:
            for key in required_keys:
                self.assertIn(key, item, f"Attraction '{item.get('name')}' missing required key: {key}")
            self.assertIn("lat", item["coordinates"])
            self.assertIn("lng", item["coordinates"])
            self.assertIsInstance(item["traveler_types"], list)
            self.assertIsInstance(item["tags"], list)

    def test_continents_coverage(self):
        """Verify all six major continents are represented in the database."""
        attractions = destinations_service.load_attractions()
        continents = {a["continent"] for a in attractions}
        expected_continents = {"Asia", "Europe", "North America", "South America", "Africa", "Oceania"}
        for exp in expected_continents:
            self.assertIn(exp, continents, f"Continent {exp} must be covered in the database")

    def test_key_countries_represented(self):
        """Verify key global countries mentioned in requirements are present."""
        attractions = destinations_service.load_attractions()
        countries = {a["country"] for a in attractions}
        sample_countries = [
            "India", "Japan", "China", "France", "Italy", "United Kingdom",
            "United States", "Canada", "Brazil", "Australia", "New Zealand",
            "Egypt", "South Africa", "Kenya", "Morocco", "United Arab Emirates"
        ]
        for country in sample_countries:
            self.assertIn(country, countries, f"Expected {country} to be represented in attractions")

    def test_get_attraction_by_id(self):
        """Test retrieving individual attraction by ID."""
        attraction = destinations_service.get_attraction_by_id("eiffel_tower_paris")
        self.assertIsNotNone(attraction)
        self.assertEqual(attraction["name"], "Eiffel Tower")
        self.assertEqual(attraction["city"], "Paris")

        # Nonexistent ID returns None
        none_res = destinations_service.get_attraction_by_id("non_existent_place_xyz")
        self.assertIsNone(none_res)

    def test_catalog_facets(self):
        """Test facet generation for sidebar/filter controls."""
        facets = destinations_service.get_catalog_facets()
        self.assertIn("continents", facets)
        self.assertIn("countries", facets)
        self.assertIn("categories", facets)
        self.assertIn("budget_tiers", facets)
        self.assertIn("traveler_types", facets)
        self.assertGreater(facets["total_attractions"], 30)

    def test_search_by_continent(self):
        """Test faceted search filtered by continent."""
        res_asia = destinations_service.search_attractions(continent="Asia")
        self.assertGreater(res_asia["total"], 0)
        for item in res_asia["attractions"]:
            self.assertEqual(item["continent"], "Asia")

        res_europe = destinations_service.search_attractions(continent="Europe")
        self.assertGreater(res_europe["total"], 0)
        for item in res_europe["attractions"]:
            self.assertEqual(item["continent"], "Europe")

    def test_search_by_country(self):
        """Test faceted search filtered by country."""
        res_india = destinations_service.search_attractions(country="India")
        self.assertGreater(res_india["total"], 0)
        for item in res_india["attractions"]:
            self.assertEqual(item["country"], "India")

    def test_search_by_category(self):
        """Test faceted search filtered by category."""
        res = destinations_service.search_attractions(category="Historical")
        self.assertGreater(res["total"], 0)
        for item in res["attractions"]:
            self.assertEqual(item["category"], "Historical")

    def test_search_by_text_query(self):
        """Test text search matching names, cities, tags, descriptions."""
        res = destinations_service.search_attractions(query="Taj Mahal")
        self.assertGreater(res["total"], 0)
        self.assertEqual(res["attractions"][0]["name"], "Taj Mahal")

        res_city = destinations_service.search_attractions(query="Tokyo")
        self.assertGreater(res_city["total"], 0)
        for item in res_city["attractions"]:
            self.assertEqual(item["city"], "Tokyo")

    def test_autocomplete_typeahead(self):
        """Test fast typeahead autocomplete suggestions."""
        # Exact prefix match
        res = destinations_service.get_destination_autocomplete("Eiff")
        self.assertGreater(len(res), 0)
        self.assertIn("Eiffel Tower", res[0]["name"])

        # City match
        res_paris = destinations_service.get_destination_autocomplete("Paris")
        self.assertGreater(len(res_paris), 0)
        displays = [item["display"] for item in res_paris]
        self.assertTrue(any("Paris" in d for d in displays))

        # Empty query returns default popular items
        res_empty = destinations_service.get_destination_autocomplete("")
        self.assertEqual(len(res_empty), 8)

    def test_trip_attraction_recommendations(self):
        """Test intelligent attraction recommendations based on trip parameters."""
        recs = destinations_service.recommend_attractions_for_trip(
            destination="Rome",
            interests=["History", "Culture"],
            budget="Moderate",
            limit=4,
        )
        self.assertGreater(len(recs), 0)
        names = [r["name"] for r in recs]
        self.assertTrue(any("Colosseum" in n or "Vatican" in n for n in names))


class TestDestinationsAPIEndpoints(unittest.TestCase):
    """Integration test suite for Flask API endpoints."""

    def setUp(self):
        self.client = app.test_client()

    def test_api_destinations_search(self):
        """Test GET /api/destinations/search."""
        res = self.client.get("/api/destinations/search?continent=Asia&limit=5")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("attractions", data)
        self.assertLessEqual(len(data["attractions"]), 5)

    def test_api_destinations_autocomplete(self):
        """Test GET /api/destinations/autocomplete."""
        res = self.client.get("/api/destinations/autocomplete?query=Fuji")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertGreater(len(data.get("suggestions", [])), 0)

    def test_api_destinations_facets(self):
        """Test GET /api/destinations/facets."""
        res = self.client.get("/api/destinations/facets")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("facets", data)
        self.assertIn("continents", data["facets"])

    def test_api_destinations_get_by_id(self):
        """Test GET /api/destinations/<id>."""
        res = self.client.get("/api/destinations/eiffel_tower_paris")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data["attraction"]["name"], "Eiffel Tower")

        # 404 for unknown ID
        res_404 = self.client.get("/api/destinations/unknown_place_12345")
        self.assertEqual(res_404.status_code, 404)

    def test_api_destinations_recommend(self):
        """Test POST /api/destinations/recommend."""
        payload = {
            "destination": "Kyoto",
            "interests": ["Culture", "Nature"],
            "budget": "Moderate",
        }
        res = self.client.post("/api/destinations/recommend", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        self.assertIn("recommendations", data)

    def test_api_plan_with_selected_attractions_integration(self):
        """Test POST /api/plan seamlessly weaves user-selected attractions into the itinerary."""
        payload = {
            "destination": "Paris, France",
            "duration_days": 3,
            "budget": "Moderate",
            "interests": ["Culture", "History"],
            "selected_attractions": [
                {"name": "Eiffel Tower", "category": "Historical", "description": "Iconic lattice tower"},
                {"name": "Louvre Museum", "category": "Cultural", "description": "World-famous art museum"},
            ],
        }
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data.get("ok"))
        trip = data.get("trip", {})

        # Verify selected attractions are recorded in trip data
        self.assertIn("selected_attractions", trip)
        self.assertIn("Eiffel Tower", trip["selected_attractions"])

        # Verify itinerary includes the selected attractions
        itinerary = trip.get("itinerary", [])
        all_itinerary_text = json.dumps(itinerary)
        self.assertIn("Eiffel Tower", all_itinerary_text)
        self.assertIn("Louvre Museum", all_itinerary_text)


if __name__ == "__main__":
    unittest.main()
