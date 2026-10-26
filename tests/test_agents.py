"""tests/test_agents.py - Unit Tests for the Multi-Agent Travel Planner Engine

Covers:
- Full 4-agent orchestration pipeline with mocked _request_completion
- Precise Python cost arithmetic verification
- Day renumbering strictly from 1 to duration_days
- Automatic retry on malformed JSON (1 retry)
- Recovery of JSON wrapped inside conversational text (outer {...} extraction)
- Validation failure handling after exhausted retries (AgentError)
- Number and string parsing sanitizers (currency stripping, boolean rejection)
- Missing / placeholder OPENAI_API_KEY detection (AgentError API_KEY_MISSING)
"""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

import agents
from agents import (
    AgentError,
    calculate_budget,
    clean_string,
    destination_activity_agent,
    extract_json_block,
    get_openai_client,
    normalize_currency,
    normalize_tier,
    parse_number,
    run_agents,
)


class AgentsTestCase(unittest.TestCase):
    def setUp(self):
        # Reset cached lazy client before tests
        agents._client = None

    def tearDown(self):
        agents._client = None

    def test_missing_or_placeholder_api_key_raises_error(self):
        """Test that missing or placeholder OPENAI_API_KEY raises AgentError with API_KEY_MISSING."""
        # Case 1: Empty key
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(AgentError) as ctx:
                get_openai_client()
            self.assertEqual(ctx.exception.code, "API_KEY_MISSING")
            self.assertEqual(ctx.exception.status_code, 500)

        # Case 2: Placeholder key from .env.example
        with patch.dict(os.environ, {"OPENAI_API_KEY": "your_actual_openai_api_key"}):
            with self.assertRaises(AgentError) as ctx:
                get_openai_client()
            self.assertEqual(ctx.exception.code, "API_KEY_MISSING")
            self.assertEqual(ctx.exception.status_code, 500)

    def test_number_parser_sanitation(self):
        """Test parse_number handles currency strings, commas, rejects booleans and NaN."""
        # Standard numbers
        self.assertEqual(parse_number(120), 120.0)
        self.assertEqual(parse_number(45.5), 45.5)

        # Strings with symbols and commas
        self.assertEqual(parse_number("1,200 JPY"), 1200.0)
        self.assertEqual(parse_number("$150.50"), 150.50)
        self.assertEqual(parse_number("€ 75"), 75.0)

        # Reject booleans (True is 1 in Python, but must be rejected)
        self.assertEqual(parse_number(True, default=0.0), 0.0)
        self.assertEqual(parse_number(False, default=0.0), 0.0)

        # Non-numeric string and None
        self.assertEqual(parse_number("Free admission", default=0.0), 0.0)
        self.assertEqual(parse_number(None, default=10.0), 10.0)

        # Bounds clamping
        self.assertEqual(parse_number(-50, min_val=0.0), 0.0)
        self.assertEqual(parse_number(2_000_000, max_val=100_000), 100_000.0)

    def test_string_cleaner_and_normalizers(self):
        """Test string cleaners, tier normalization, and currency code normalization."""
        # clean_string
        self.assertEqual(clean_string("  Hello World  "), "Hello World")
        self.assertEqual(clean_string("A" * 1500, max_len=10), "AAAAAAAAAA")
        self.assertEqual(clean_string(None, default="fallback"), "fallback")
        self.assertEqual(clean_string(True, default="fallback"), "fallback")

        # normalize_tier
        self.assertEqual(normalize_tier("budget"), "Budget")
        self.assertEqual(normalize_tier("Luxury Suite"), "Luxury")
        self.assertEqual(normalize_tier("anything else"), "Moderate")

        # normalize_currency
        self.assertEqual(normalize_currency("jpy"), "JPY")
        self.assertEqual(normalize_currency("EUR"), "EUR")
        self.assertEqual(normalize_currency("Dollars"), "USD") # Non-ISO defaults to USD
        self.assertEqual(normalize_currency(None), "USD")

    def test_extract_json_block_fallback(self):
        """Test extract_json_block correctly extracts outer {...} from noisy text."""
        raw = "Here is the response:\n{\"key\": \"value\"}\nHope this helps!"
        extracted = extract_json_block(raw)
        self.assertEqual(extracted, "{\"key\": \"value\"}")
        self.assertEqual(json.loads(extracted), {"key": "value"})

        # No brackets returns raw text
        self.assertEqual(extract_json_block("Plain text"), "Plain text")

    @patch("agents._request_completion")
    def test_malformed_json_retried_once(self, mock_completion):
        """Test that if the first call returns malformed JSON, it is retried once and succeeds."""
        mock_client = MagicMock()
        valid_response = json.dumps({
            "experiences": [
                {
                    "name": "Kiyomizu-dera",
                    "category": "Culture",
                    "description": "Historic wooden temple.",
                    "practical_tip": "Visit at sunrise.",
                    "estimated_cost": "400 JPY",
                }
            ]
        })

        # Call 1: malformed JSON, Call 2: valid JSON
        mock_completion.side_effect = ["{ malformed json without closing", valid_response]

        out = destination_activity_agent(mock_client, "Kyoto", 3, "Moderate", ["Culture"])
        self.assertEqual(len(out["experiences"]), 1)
        self.assertEqual(out["experiences"][0]["name"], "Kiyomizu-dera")
        self.assertEqual(mock_completion.call_count, 2)

    @patch("agents._request_completion")
    def test_malformed_json_fails_after_retries_exhausted(self, mock_completion):
        """Test that if both attempts return malformed JSON, AgentError is raised."""
        mock_client = MagicMock()
        mock_completion.side_effect = ["{ bad json 1", "{ bad json 2"]

        with self.assertRaises(AgentError) as ctx:
            destination_activity_agent(mock_client, "Kyoto", 3, "Moderate", ["Culture"])

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertIn("Destination & Activity Agent", ctx.exception.message)
        self.assertEqual(mock_completion.call_count, 2)

    @patch("agents._request_completion")
    def test_json_wrapped_in_text_is_recovered(self, mock_completion):
        """Test that JSON wrapped in markdown or conversational commentary is recovered by fallback."""
        mock_client = MagicMock()
        wrapped_json = (
            "Certainly! Here is your requested information in JSON format:\n"
            "```json\n"
            "{\n"
            "  \"experiences\": [\n"
            "    {\n"
            "      \"name\": \"Fushimi Inari Taisha\",\n"
            "      \"category\": \"Culture\",\n"
            "      \"description\": \"Iconic thousands of vermilion torii gates.\",\n"
            "      \"practical_tip\": \"Hike early to avoid crowds.\",\n"
            "      \"estimated_cost\": \"Free\"\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "Let me know if you need anything else!"
        )
        mock_completion.return_value = wrapped_json

        out = destination_activity_agent(mock_client, "Kyoto", 3, "Moderate", ["Culture"])
        self.assertEqual(len(out["experiences"]), 1)
        self.assertEqual(out["experiences"][0]["name"], "Fushimi Inari Taisha")
        self.assertEqual(mock_completion.call_count, 1)

    def test_python_cost_arithmetic(self):
        """Test calculate_budget calculates costs strictly using the Python formula."""
        cost_inputs = {
            "accommodation_per_night": 120.0,
            "food_per_day": 40.0,
            "transport_per_day": 15.0,
            "activities_total": 85.0,
        }
        # 4 days -> nights = max(4 - 1, 0) = 3
        # accommodation = 120 * 3 = 360
        # food = 40 * 4 = 160
        # transport = 15 * 4 = 60
        # activities = 85
        # total = 360 + 160 + 60 + 85 = 665
        budget = calculate_budget(
            duration_days=4,
            cost_inputs=cost_inputs,
            currency="EUR",
            model_assumptions=["Solo traveler"],
        )

        self.assertEqual(budget["currency"], "EUR")
        self.assertTrue(budget["per_person"])
        self.assertTrue(budget["flights_excluded"])
        self.assertEqual(budget["nights"], 3)
        self.assertEqual(budget["accommodation_per_night"], 120.0)
        self.assertEqual(budget["accommodation"], 360.0)
        self.assertEqual(budget["food_per_day"], 40.0)
        self.assertEqual(budget["food"], 160.0)
        self.assertEqual(budget["transport_per_day"], 15.0)
        self.assertEqual(budget["transport"], 60.0)
        self.assertEqual(budget["activities"], 85.0)
        self.assertEqual(budget["total"], 665.0)

        # Ensure mandatory disclaimer assumptions are included
        assumptions_str = " ".join(budget["assumptions"])
        self.assertIn("AI-generated and unverified", assumptions_str)
        self.assertIn("flights are excluded", assumptions_str)
        self.assertIn("solo traveler", assumptions_str)

    @patch("agents.get_openai_client")
    @patch("agents._request_completion")
    def test_full_four_agent_pipeline_and_day_renumbering(self, mock_completion, mock_get_client):
        """Test the end-to-end multi-agent orchestration pipeline with all 4 agents."""
        mock_get_client.return_value = MagicMock()

        # Responses for Agent 1, 2, 3, 4
        agent1_resp = json.dumps({
            "experiences": [
                {"name": "Eiffel Tower", "category": "Sightseeing", "description": "Iconic landmark.", "practical_tip": "Book in advance.", "estimated_cost": "28 EUR"},
                {"name": "Louvre Museum", "category": "Culture", "description": "World-famous museum.", "practical_tip": "Enter via Carrousel.", "estimated_cost": "22 EUR"},
                {"name": "Montmartre Walking Tour", "category": "History", "description": "Bohemian district.", "practical_tip": "Wear walking shoes.", "estimated_cost": "Free"},
            ]
        })

        agent2_resp = json.dumps({
            "currency": "EUR",
            "accommodations": [
                {"name": "Hotel Marais", "tier": "Moderate", "area": "Le Marais", "nightly_price": 140.0, "reason": "Central location", "note": "Estimate only"},
                {"name": "Boutique Latin Quarter", "tier": "Moderate", "area": "Latin Quarter", "nightly_price": 160.0, "reason": "Historic charm", "note": "Estimate only"},
            ]
        })

        agent3_resp = json.dumps({
            "overview": "Comprehensive metro and bus network.",
            "transport_options": [
                {"mode": "Metro", "description": "Fast urban subway.", "approx_cost_per_trip": 2.15, "notes": "Navigo Easy card"},
            ],
            "daily_transport_estimate": 10.0,
            "tips": ["Download Citymapper"],
            "safety": ["Beware of pickpockets at major hubs"],
            "verify": ["Check RER airport schedule"],
        })

        # Agent 4 returns unnumbered or misnumbered days to verify renumbering strictly 1..N
        agent4_resp = json.dumps({
            "summary": "An unforgettable 3-day journey through Paris.",
            "itinerary": [
                {"day": 99, "title": "Welcome to Paris", "morning": ["Check in"], "afternoon": ["Eiffel Tower"], "evening": ["Seine stroll"]},
                {"day": 100, "title": "Art and Culture", "morning": ["Louvre Museum"], "afternoon": ["Tuileries Gardens"], "evening": ["Bistro dinner"]},
                {"day": 101, "title": "Historic Charm", "morning": ["Montmartre"], "afternoon": ["Sacre-Coeur"], "evening": ["Departure prep"]},
            ],
            "cost_inputs": {
                "accommodation_per_night": 140.0,
                "food_per_day": 50.0,
                "transport_per_day": 10.0,
                "activities_total": 50.0,
            },
            "assumptions": ["Solo traveler enjoying casual dining"],
            "travel_tips": ["Validate metro tickets before boarding"],
        })

        mock_completion.side_effect = [agent1_resp, agent2_resp, agent3_resp, agent4_resp]

        with patch.dict(os.environ, {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "sk-proj-testkey"}):
            plan = run_agents(
                destination="Paris, France",
                duration_days=3,
                budget="Moderate",
                interests=["Culture", "History"],
            )

        self.assertEqual(plan["destination"], "Paris, France")
        self.assertEqual(plan["duration_days"], 3)
        self.assertEqual(len(plan["experiences"]), 3)
        self.assertEqual(len(plan["accommodations"]), 2)
        self.assertEqual(plan["estimated_budget"]["currency"], "EUR")

        # Verify day renumbering strictly 1..3
        itinerary = plan["itinerary"]
        self.assertEqual(len(itinerary), 3)
        self.assertEqual([d["day"] for d in itinerary], [1, 2, 3])

        # Verify cost calculation:
        # nights = 3 - 1 = 2
        # accommodation = 140 * 2 = 280
        # food = 50 * 3 = 150
        # transport = 10 * 3 = 30
        # activities = 50
        # total = 280 + 150 + 30 + 50 = 510
        budget = plan["estimated_budget"]
        self.assertEqual(budget["nights"], 2)
        self.assertEqual(budget["accommodation"], 280.0)
        self.assertEqual(budget["food"], 150.0)
        self.assertEqual(budget["transport"], 30.0)
        self.assertEqual(budget["activities"], 50.0)
        self.assertEqual(budget["total"], 510.0)

    def test_provider_auto_detection(self):
        """Test provider selection logic for Gemini, Groq, OpenAI, and Mock."""
        from agents import get_active_provider

        # Auto with Gemini key
        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "GEMINI_API_KEY": "AIzaSyFakeKey", "GROQ_API_KEY": "", "OPENAI_API_KEY": ""}):
            self.assertEqual(get_active_provider(), "gemini")

        # Auto with Groq key
        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "GEMINI_API_KEY": "", "GROQ_API_KEY": "gsk_fake_key", "OPENAI_API_KEY": ""}):
            self.assertEqual(get_active_provider(), "groq")

        # Auto with OpenAI key
        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "GEMINI_API_KEY": "", "GROQ_API_KEY": "", "OPENAI_API_KEY": "sk-proj-fake"}):
            self.assertEqual(get_active_provider(), "openai")

        # Auto with no keys falls back to rule_based
        with patch.dict(os.environ, {"LLM_PROVIDER": "auto", "GEMINI_API_KEY": "", "GROQ_API_KEY": "", "OPENAI_API_KEY": ""}):
            self.assertEqual(get_active_provider(), "rule_based")

        # Explicit mock setting
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
            self.assertEqual(get_active_provider(), "mock")

    def test_mock_mode_generates_full_plan_without_keys(self):
        """Test that mock mode generates a complete, valid travel plan with $0 cost and no API keys."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "mock", "OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "GROQ_API_KEY": ""}):
            plan = run_agents(
                destination="Kyoto, Japan",
                duration_days=3,
                budget="Moderate",
                interests=["Culture", "Food"],
            )

            self.assertEqual(plan["destination"], "Kyoto, Japan")
            self.assertEqual(plan["duration_days"], 3)
            self.assertEqual(plan["budget"], "Moderate")
            self.assertEqual(plan["llm_provider"], "mock")
            self.assertGreaterEqual(len(plan["experiences"]), 3)
            self.assertEqual(len(plan["accommodations"]), 2)
            self.assertEqual(plan["estimated_budget"]["currency"], "JPY")
            self.assertEqual(len(plan["itinerary"]), 3)
            self.assertGreater(plan["estimated_budget"]["total"], 0)
            self.assertEqual(plan["estimated_budget"]["nights"], 2)


if __name__ == "__main__":
    unittest.main()
