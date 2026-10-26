"""tests/test_app.py - Integration and Unit Tests for the Flask Application

Covers:
- Index page loading and HTML checks
- Server-side input validation for all invalid payload scenarios (400 responses)
- Successful plan generation, interest normalization, and atomic persistence
- Retrieval of all trips (newest first) and lookup by ID
- Missing trips.json creation
- Corrupted trips.json preservation, backup creation, and error response
- AgentError mapping to status and code without saving incomplete trips
- Unexpected exception suppression (internal error details hidden)
- Unknown API route handling (JSON 404)
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app import app
from agents import AgentError


class AppTestCase(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory and test trips file
        self.test_dir = tempfile.mkdtemp(prefix="voyage_test_")
        self.test_trips_path = os.path.join(self.test_dir, "test_trips.json")
        app.config["TRIPS_FILE"] = self.test_trips_path
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        # Remove temporary directory and files created during test
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_index_page_loads(self):
        """Test that the index page loads with HTTP 200 and required elements."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Voyage AI", html)
        self.assertIn("Plan smarter. Travel better.", html)
        self.assertIn("Destination &amp; Activity Agent", html)
        self.assertIn("Create New Trip Plan", html)
        self.assertIn("Saved Trips", html)

    def test_validation_empty_and_whitespace_destination(self):
        """Test that missing, empty, or whitespace-only destinations are rejected with 400."""
        # Empty string
        res = self.client.post("/api/plan", json={"destination": "", "duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["field"], "destination")

        # Whitespace only
        res = self.client.post("/api/plan", json={"destination": "   ", "duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["field"], "destination")

        # Missing field
        res = self.client.post("/api/plan", json={"duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["field"], "destination")

    def test_validation_destination_too_long(self):
        """Test destination exceeding 160 characters returns 400."""
        long_dest = "A" * 161
        res = self.client.post("/api/plan", json={"destination": long_dest, "duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["field"], "destination")

    def test_validation_destination_illegal_characters(self):
        """Test destination with illegal characters returns 400."""
        illegal_cases = [
            "Tokyo <script>alert(1)</script>",
            "Paris @#$",
            "London; UK",
            "Berlin_Germany",
            "Rome %20 Italy",
        ]
        for dest in illegal_cases:
            res = self.client.post("/api/plan", json={"destination": dest, "duration_days": 3, "budget": "Moderate"})
            self.assertEqual(res.status_code, 400, f"Expected 400 for '{dest}'")
            data = res.get_json()
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["field"], "destination")

    def test_validation_duration_days_invalid(self):
        """Test invalid duration values: boolean, non-int, zero, negative, > 30."""
        invalid_durations = [
            True,        # Boolean must be rejected
            False,
            "three",     # String
            3.5,         # Float
            0,           # < 1
            -2,          # Negative
            31,          # > 30
            100,
        ]
        for val in invalid_durations:
            res = self.client.post("/api/plan", json={"destination": "Kyoto", "duration_days": val, "budget": "Moderate"})
            self.assertEqual(res.status_code, 400, f"Expected 400 for duration_days={val}")
            data = res.get_json()
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["field"], "duration_days")

    def test_validation_budget_invalid(self):
        """Test invalid budget returns 400."""
        invalid_budgets = ["Cheap", "SuperLuxury", "moderate", "budget", 100, None]
        for val in invalid_budgets:
            res = self.client.post("/api/plan", json={"destination": "Kyoto", "duration_days": 3, "budget": val})
            self.assertEqual(res.status_code, 400, f"Expected 400 for budget={val}")
            data = res.get_json()
            self.assertFalse(data["ok"])
            self.assertEqual(data["error"]["field"], "budget")

    def test_validation_interests_invalid(self):
        """Test invalid interests returns 400."""
        # Non-list
        res = self.client.post("/api/plan", json={"destination": "Kyoto", "duration_days": 3, "budget": "Moderate", "interests": "Food"})
        self.assertEqual(res.status_code, 400)

        # Non-string inside list
        res = self.client.post("/api/plan", json={"destination": "Kyoto", "duration_days": 3, "budget": "Moderate", "interests": [123]})
        self.assertEqual(res.status_code, 400)

        # Disallowed interest
        res = self.client.post("/api/plan", json={"destination": "Kyoto", "duration_days": 3, "budget": "Moderate", "interests": ["Food", "Gambling"]})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("Gambling", data["error"]["message"])

    @patch("app.run_agents")
    def test_successful_plan_saves_and_normalizes_interests(self, mock_run_agents):
        """Test successful plan generation with mocked agent responses, normalized interests, and file save."""
        fake_plan = {
            "destination": "Kyoto, Japan",
            "duration_days": 3,
            "budget": "Moderate",
            "interests": ["Food", "Culture"],
            "summary": "A peaceful 3-day exploration of Kyoto.",
            "experiences": [{"name": "Fushimi Inari", "category": "Culture", "description": "Torii gates.", "practical_tip": "Go early.", "estimated_cost": "Free"}],
            "accommodations": [{"name": "Kyoto Ryokan", "tier": "Moderate", "area": "Gion", "nightly_price": 150.0, "reason": "Traditional", "note": "Indicative"}],
            "logistics": {"overview": "Buses and trains.", "transport_options": [], "daily_transport_estimate": 10.0, "tips": [], "safety": [], "verify": []},
            "itinerary": [{"day": 1, "title": "Arrival", "morning": ["Check in"], "afternoon": ["Temple visit"], "evening": ["Dinner"]}],
            "estimated_budget": {"currency": "JPY", "per_person": True, "flights_excluded": True, "nights": 2, "total": 500.0, "assumptions": []},
            "travel_tips": ["Wear comfortable shoes."],
        }
        mock_run_agents.return_value = fake_plan

        payload = {
            "destination": "Kyoto, Japan",
            "duration_days": 3,
            "budget": "Moderate",
            "interests": ["food", "CULTURE", "Food"], # Testing case insensitivity and deduplication
        }

        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("trip", data)
        trip = data["trip"]
        self.assertIn("trip_id", trip)
        self.assertIn("created_at", trip)

        # Verify run_agents was called with normalized, deduplicated interests
        mock_run_agents.assert_called_once_with(
            destination="Kyoto, Japan",
            duration_days=3,
            budget="Moderate",
            interests=["Food", "Culture"],
        )

        # Verify trip was persisted in trips file
        with open(self.test_trips_path, "r", encoding="utf-8") as f:
            saved_trips = json.load(f)
        self.assertEqual(len(saved_trips), 1)
        self.assertEqual(saved_trips[0]["trip_id"], trip["trip_id"])

    @patch("app.run_agents")
    def test_trips_retrieval_newest_first_and_lookup_by_id(self, mock_run_agents):
        """Test GET /api/trips returns newest first and GET /api/trips/<id> looks up correctly."""
        # Create two trips with slightly different timestamps
        trip1 = {
            "trip_id": "id-1",
            "created_at": "2026-01-01T10:00:00Z",
            "destination": "Paris",
            "duration_days": 2,
            "budget": "Budget",
        }
        trip2 = {
            "trip_id": "id-2",
            "created_at": "2026-01-02T10:00:00Z", # newer
            "destination": "Tokyo",
            "duration_days": 4,
            "budget": "Luxury",
        }

        with open(self.test_trips_path, "w", encoding="utf-8") as f:
            json.dump([trip1, trip2], f)

        res = self.client.get("/api/trips")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        trips = data["trips"]
        self.assertEqual(len(trips), 2)
        # Should be sorted newest first (id-2 first)
        self.assertEqual(trips[0]["trip_id"], "id-2")
        self.assertEqual(trips[1]["trip_id"], "id-1")

        # Lookup by ID: existing
        res_one = self.client.get("/api/trips/id-1")
        self.assertEqual(res_one.status_code, 200)
        self.assertEqual(res_one.get_json()["trip"]["destination"], "Paris")

        # Lookup by ID: non-existent
        res_none = self.client.get("/api/trips/nonexistent-id")
        self.assertEqual(res_none.status_code, 404)
        self.assertFalse(res_none.get_json()["ok"])
        self.assertEqual(res_none.get_json()["error"]["code"], "NOT_FOUND")

        # Update by ID: existing
        up_res = self.client.put("/api/trips/id-2", json={"destination": "Kyoto Updated", "trip_id": "id-2"})
        self.assertEqual(up_res.status_code, 200)
        self.assertTrue(up_res.get_json()["ok"])
        self.assertEqual(self.client.get("/api/trips/id-2").get_json()["trip"]["destination"], "Kyoto Updated")

        # Update by ID: non-existent
        up_none = self.client.put("/api/trips/id-999", json={"destination": "Nowhere", "trip_id": "id-999"})
        self.assertEqual(up_none.status_code, 404)
        self.assertFalse(up_none.get_json()["ok"])

        # Delete by ID: existing
        del_res = self.client.delete("/api/trips/id-1")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.get_json()["ok"])

        # Verify id-1 is deleted
        res_after = self.client.get("/api/trips")
        self.assertEqual(len(res_after.get_json()["trips"]), 1)
        self.assertEqual(res_after.get_json()["trips"][0]["trip_id"], "id-2")

        # Delete by ID: non-existent
        del_none = self.client.delete("/api/trips/id-1")
        self.assertEqual(del_none.status_code, 404)
        self.assertFalse(del_none.get_json()["ok"])

    def test_missing_trips_file_is_created(self):
        """Test that if trips.json does not exist, GET /api/trips creates it as [] and returns empty list."""
        if os.path.exists(self.test_trips_path):
            os.remove(self.test_trips_path)

        res = self.client.get("/api/trips")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["trips"], [])

        # Check that file was created on disk
        self.assertTrue(os.path.exists(self.test_trips_path))
        with open(self.test_trips_path, "r", encoding="utf-8") as f:
            content = json.load(f)
        self.assertEqual(content, [])

    def test_corrupted_trips_file_is_preserved_and_backed_up(self):
        """Test that a corrupt trips.json returns 500, backs up to .corrupt-<timestamp>.json, and preserves original."""
        corrupted_text = "{ this is completely invalid JSON content !!!"
        with open(self.test_trips_path, "w", encoding="utf-8") as f:
            f.write(corrupted_text)

        res = self.client.get("/api/trips")
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "DATA_CORRUPT")

        # Verify original corrupted file was NOT overwritten
        with open(self.test_trips_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), corrupted_text)

        # Verify backup file was created
        files = os.listdir(self.test_dir)
        backup_files = [f for f in files if "corrupt-" in f]
        self.assertEqual(len(backup_files), 1)

        backup_path = os.path.join(self.test_dir, backup_files[0])
        with open(backup_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), corrupted_text)

    @patch("app.run_agents")
    def test_agent_error_maps_to_status_and_saves_nothing(self, mock_run_agents):
        """Test that AgentError maps to its custom status code and message, saving nothing."""
        mock_run_agents.side_effect = AgentError(
            message="OpenAI rate limit reached. Please wait a moment.",
            code="RATE_LIMIT",
            status_code=429,
        )

        with open(self.test_trips_path, "w", encoding="utf-8") as f:
            json.dump([], f)

        res = self.client.post("/api/plan", json={"destination": "Madrid", "duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 429)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "RATE_LIMIT")
        self.assertEqual(data["error"]["message"], "OpenAI rate limit reached. Please wait a moment.")

        # Verify storage remains empty
        with open(self.test_trips_path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved, [])

    @patch("app.run_agents")
    def test_unexpected_error_hides_internal_details(self, mock_run_agents):
        """Test that unexpected exceptions return a safe generic 500 without leaking stack traces or messages."""
        mock_run_agents.side_effect = RuntimeError("SECRET_INTERNAL_DB_PASSWORD_LEAK")

        res = self.client.post("/api/plan", json={"destination": "Madrid", "duration_days": 3, "budget": "Moderate"})
        self.assertEqual(res.status_code, 500)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "INTERNAL_SERVER_ERROR")
        self.assertNotIn("SECRET_INTERNAL_DB_PASSWORD_LEAK", data["error"]["message"])
        self.assertIn("unexpected error", data["error"]["message"].lower())

    def test_unknown_api_route_returns_json_404(self):
        """Test that non-existent API routes return a JSON 404 response."""
        res = self.client.get("/api/unknown_endpoint")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "NOT_FOUND")

    def test_places_autocomplete_endpoint(self):
        """Test GET /api/places/autocomplete returns suggestions."""
        res = self.client.get("/api/places/autocomplete?query=Hyder")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIn("suggestions", data)
        self.assertTrue(len(data["suggestions"]) > 0)
        self.assertTrue(any("Hyderabad" in s["name"] for s in data["suggestions"]))

    def test_places_details_missing_id_returns_400(self):
        """Test GET /api/places/details without place_id returns 400."""
        res = self.client.get("/api/places/details")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
