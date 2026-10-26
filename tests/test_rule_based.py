"""tests/test_rule_based.py - Comprehensive Unit Tests for the Rule-Based Planning Engine

Covers:
- Destination selection and ranking by budget, duration, interests, companions, and climate
- Precise budget calculation formulas and companion adjustments
- Exact itinerary generation across 1, 3, 7, and 10 days
- Execution when API keys are completely missing (offline demo mode)
- Automatic graceful fallback when an LLM provider fails (no 500 error or blank page)
- /api/recommend-destination endpoint verification
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agents import AgentError, run_agents
from app import app
from planner.budget_agent import estimate_budget
from planner.dataset import get_all_destinations
from planner.destination_agent import recommend_destinations, resolve_or_create_destination
from planner.itinerary_agent import build_itinerary
from planner.travel_tips_agent import generate_logistics_and_tips


class RuleBasedEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="voyage_rb_test_")
        self.test_trips_path = os.path.join(self.test_dir, "test_trips.json")
        with open(self.test_trips_path, "w", encoding="utf-8") as f:
            f.write("[]")
        app.config["TRIPS_FILE"] = self.test_trips_path
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # =================================================================
    # 1. Destination Selection & Recommendation Tests
    # =================================================================

    def test_destination_dataset_loaded(self):
        """Test that the local dataset loads curated destinations."""
        destinations = get_all_destinations()
        self.assertGreaterEqual(len(destinations), 5)
        names = [d["name"] for d in destinations]
        self.assertTrue(any("Kyoto" in n for n in names))
        self.assertTrue(any("Rome" in n for n in names))
        self.assertTrue(any("Banff" in n for n in names))

    def test_recommendation_by_nature_and_adventure_interests(self):
        """Test that nature/adventure interests prioritize outdoor destinations like Banff or Costa Rica."""
        recs = recommend_destinations(
            budget="Moderate",
            duration_days=5,
            interests=["Nature", "Adventure"],
            companions="Friends",
            climate="Any",
            top_k=3,
        )
        self.assertGreater(len(recs), 0)
        top_names = [r["destination"] for r in recs]
        # Should include Banff or Costa Rica or Bali in top recommendations
        self.assertTrue(any("Banff" in n or "Costa Rica" in n or "Bali" in n for n in top_names))
        # Ensure match score is high
        self.assertGreaterEqual(recs[0]["match_score"], 70)
        self.assertGreater(len(recs[0]["reasons"]), 0)

    def test_recommendation_by_culture_and_history_interests(self):
        """Test that culture/history interests prioritize heritage destinations like Kyoto or Rome."""
        recs = recommend_destinations(
            budget="Moderate",
            duration_days=4,
            interests=["Culture", "History"],
            companions="Couple",
            climate="Any",
            top_k=3,
        )
        self.assertGreater(len(recs), 0)
        top_names = [r["destination"] for r in recs]
        self.assertTrue(any("Kyoto" in n or "Rome" in n or "Paris" in n for n in top_names))

    def test_recommendation_by_climate_preference(self):
        """Test that cool/alpine climate preference matches alpine destinations."""
        recs = recommend_destinations(
            budget="Moderate",
            duration_days=4,
            interests=["Nature"],
            companions="Solo",
            climate="Cool/Alpine",
            top_k=2,
        )
        self.assertGreater(len(recs), 0)
        self.assertTrue(any("Banff" in r["destination"] for r in recs))

    def test_recommendation_by_budget_tier(self):
        """Test that budget recommendations consider budget tiers."""
        recs = recommend_destinations(
            budget="Budget",
            duration_days=4,
            interests=["Food"],
            companions="Solo",
            climate="Any",
            top_k=3,
        )
        self.assertGreater(len(recs), 0)
        self.assertIn("Budget", recs[0]["reasons"][0])

    def test_resolve_custom_destination_synthesis(self):
        """Test that unlisted custom cities are synthesized gracefully with realistic estimates."""
        custom = resolve_or_create_destination(
            destination_name="Prague, Czech Republic",
            budget="Moderate",
            interests=["History", "Food"],
            companions="Solo",
            climate="Temperate/Mild",
        )
        self.assertEqual(custom["name"], "Prague, Czech Republic")
        self.assertEqual(custom["currency"], "EUR") # Inferred European currency
        self.assertEqual(len(custom["experiences"]), 4)
        self.assertEqual(len(custom["accommodations"]), 2)
        self.assertIn("transport_options", custom["logistics"])

    # =================================================================
    # 2. Budget Calculation Tests
    # =================================================================

    def test_budget_estimation_formula(self):
        """Test strict mathematical accuracy of budget formula: nights = max(days - 1, 0)."""
        sample_dest = {
            "name": "Test City",
            "currency": "EUR",
            "cost_defaults": {
                "accommodation_per_night": 100.0,
                "food_per_day": 40.0,
                "transport_per_day": 10.0,
                "activities_total": 50.0,
            },
        }

        # 4 days -> 3 nights
        # acc = 100 * 3 = 300
        # food = 40 * 4 = 160
        # trans = 10 * 4 = 40
        # act = 50
        # total = 300 + 160 + 40 + 50 = 550
        budget = estimate_budget(sample_dest, duration_days=4, budget_tier="Moderate", companions="Solo")

        self.assertEqual(budget["nights"], 3)
        self.assertEqual(budget["accommodation_per_night"], 100.0)
        self.assertEqual(budget["accommodation"], 300.0)
        self.assertEqual(budget["food_per_day"], 40.0)
        self.assertEqual(budget["food"], 160.0)
        self.assertEqual(budget["transport_per_day"], 10.0)
        self.assertEqual(budget["transport"], 40.0)
        self.assertEqual(budget["activities"], 50.0)
        self.assertEqual(budget["total"], 550.0)
        self.assertEqual(budget["currency"], "EUR")

    def test_budget_single_day_zero_nights(self):
        """Test 1-day trip has exactly 0 nights and 0 accommodation cost."""
        sample_dest = {
            "name": "Day Trip",
            "currency": "USD",
            "cost_defaults": {
                "accommodation_per_night": 150.0,
                "food_per_day": 50.0,
                "transport_per_day": 20.0,
                "activities_total": 30.0,
            },
        }
        budget = estimate_budget(sample_dest, duration_days=1, budget_tier="Moderate", companions="Solo")
        self.assertEqual(budget["nights"], 0)
        self.assertEqual(budget["accommodation"], 0.0)
        self.assertEqual(budget["total"], 100.0) # 50 food + 20 trans + 30 act

    # =================================================================
    # 3. Itinerary Planning Tests
    # =================================================================

    def test_itinerary_generation_exact_days(self):
        """Test itinerary builder generates exactly duration_days with populated morning, afternoon, evening."""
        sample_dest = resolve_or_create_destination("Kyoto, Japan")

        for test_days in [1, 3, 7, 10]:
            itinerary = build_itinerary(sample_dest, duration_days=test_days, interests=["Culture", "Food"])
            self.assertEqual(len(itinerary), test_days, f"Failed for {test_days} days")
            for idx, day in enumerate(itinerary):
                self.assertEqual(day["day"], idx + 1)
                self.assertTrue(len(day["title"]) > 0)
                self.assertTrue(len(day["morning"]) > 0)
                self.assertTrue(len(day["afternoon"]) > 0)
                self.assertTrue(len(day["evening"]) > 0)

    # =================================================================
    # 4. Offline / Missing API Keys Tests
    # =================================================================

    def test_missing_api_keys_generates_complete_trip(self):
        """Test that when all API keys are omitted, the app generates a complete trip via rule-based engine."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
            plan = run_agents(
                destination="Rome, Italy",
                duration_days=3,
                budget="Moderate",
                interests=["History", "Food"],
                companions="Couple",
                climate="Warm/Tropical",
            )

            self.assertEqual(plan["destination"], "Rome, Italy")
            self.assertEqual(plan["duration_days"], 3)
            self.assertEqual(plan["budget"], "Moderate")
            self.assertEqual(plan["companions"], "Couple")
            self.assertEqual(plan["llm_provider"], "rule_based")
            self.assertEqual(len(plan["itinerary"]), 3)
            self.assertGreaterEqual(len(plan["experiences"]), 3)
            self.assertGreater(plan["estimated_budget"]["total"], 0)

    # =================================================================
    # 5. LLM Failure Fallback Tests
    # =================================================================

    @patch("agents.get_llm_client")
    @patch("agents.destination_activity_agent")
    def test_llm_failure_falls_back_gracefully_to_rule_based(self, mock_dest_agent, mock_get_client):
        """Test that if an LLM call crashes or fails with an API error, it seamlessly falls back to rule-based."""
        mock_get_client.return_value = MagicMock()
        mock_dest_agent.side_effect = AgentError("OpenAI quota exceeded", code="RATE_LIMIT", status_code=429)

        with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-proj-testkey"}):
            plan = run_agents(
                destination="Kyoto, Japan",
                duration_days=3,
                budget="Moderate",
                interests=["Culture"],
            )

            # Must succeed with complete plan via fallback
            self.assertIsNotNone(plan)
            self.assertEqual(plan["destination"], "Kyoto, Japan")
            self.assertEqual(plan["llm_provider"], "rule_based")
            self.assertTrue(plan["fallback_used"])
            self.assertEqual(len(plan["itinerary"]), 3)
            self.assertGreater(plan["estimated_budget"]["total"], 0)

    # =================================================================
    # 6. REST API Endpoint Tests
    # =================================================================

    def test_api_recommend_destination_endpoint(self):
        """Test POST /api/recommend-destination returns ranked suggestions."""
        payload = {
            "budget": "Moderate",
            "duration_days": 4,
            "interests": ["Culture", "Food"],
            "companions": "Couple",
            "climate": "Temperate/Mild",
        }
        res = self.client.post("/api/recommend-destination", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        recs = data["recommendations"]
        self.assertGreater(len(recs), 0)
        self.assertIn("destination", recs[0])
        self.assertIn("match_score", recs[0])

    def test_api_plan_with_destination_recommendation(self):
        """Test POST /api/plan when user requests an automatic destination recommendation."""
        payload = {
            "destination": "Recommend",
            "duration_days": 3,
            "budget": "Moderate",
            "interests": ["Nature"],
            "companions": "Solo",
            "climate": "Cool/Alpine",
        }
        res = self.client.post("/api/plan", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["ok"])
        trip = data["trip"]
        self.assertTrue(len(trip["destination"]) > 0)
        self.assertNotEqual(trip["destination"], "Recommend")


if __name__ == "__main__":
    unittest.main()
