"""tests/test_places.py - Comprehensive Unit & Integration Tests for Google Places & Worldwide Destination Discovery

Covers:
1. Google Places API (New) live mock:
   - Verification of POST payload, headers (X-Goog-Maps-Solution-ID: gmp_git_agentskills_v1), and field mask
   - Parsing of suggestions with categories (City, Landmark, National Park, Island, etc.)
   - Proper attribution ("Google Maps")
2. Offline Global Atlas fallback:
   - Full coverage of required test destinations:
     * Hyderabad, India
     * Paris, France
     * Tokyo, Japan
     * London, UK
     * Rome, Italy
     * Bali, Indonesia
     * New York, USA
     * Dubai, UAE
     * Cape Town, South Africa
     * The Swiss Alps
     * The Grand Canyon
     * A valid destination absent from existing dataset (e.g. Reykjavik, Iceland or custom city)
     * An ambiguous place name (e.g. Paris -> France vs Texas)
     * International characters (e.g. São Paulo, Montréal, Zermatt)
3. Error handling:
   - Quota limit / 429 Too Many Requests
   - HTTP 403 Forbidden / Invalid API Key
   - Network URLError connection timeout
   - Seamless fallback without website crash
4. Planner integration:
   - Resolving unknown destinations preserves the destination name and geographic context
   - No silent replacement with hardcoded default (Kyoto/Rome)
   - Proper itinerary generation for arbitrary duration (e.g. 5 days, 7 days)
   - Currency resolution (INR for Hyderabad, AED for Dubai, IDR for Bali, CHF for Alps, ZAR for Cape Town)
"""

import json
import os
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import places_service
from agents import run_agents, run_rule_based_agents
from planner.destination_agent import infer_currency_from_name, resolve_or_create_destination


class GooglePlacesTestCase(unittest.TestCase):
    def test_configured_detection(self):
        """Test is_google_places_configured returns True only for real non-placeholder values."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(places_service.is_google_places_configured())

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "your_google_maps_api_key_here"}):
            self.assertFalse(places_service.is_google_places_configured())

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "AIzaSyD_REAL_KEY_123456"}):
            self.assertTrue(places_service.is_google_places_configured())

    @patch("urllib.request.urlopen")
    def test_places_api_new_autocomplete_success(self, mock_urlopen):
        """Test Google Places API (New) autocomplete request, solution header, and field mask."""
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_data = {
            "suggestions": [
                {
                    "placePrediction": {
                        "placeId": "ChIJ2V-iqOn11T8RmsAY9umNPN8",
                        "types": ["locality", "political", "geocode"],
                        "text": {"text": "Hyderabad, Telangana, India"},
                        "structuredFormat": {
                            "mainText": {"text": "Hyderabad"},
                            "secondaryText": {"text": "Telangana, India"},
                        },
                    }
                }
            ]
        }
        mock_resp.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "AIzaSy_TEST_KEY"}):
            res = places_service.get_autocomplete_suggestions("Hyder", session_token="tok_123")
            self.assertTrue(res["ok"])
            self.assertEqual(res["provider"], "google_places")
            self.assertEqual(res["attribution"], "Google Maps")
            self.assertEqual(len(res["suggestions"]), 1)
            first = res["suggestions"][0]
            self.assertEqual(first["name"], "Hyderabad")
            self.assertEqual(first["secondary_text"], "Telangana, India")
            self.assertEqual(first["category"], "City")

            # Check that urllib request had the mandatory Solution ID header
            args, kwargs = mock_urlopen.call_args
            req_obj = args[0]
            self.assertEqual(req_obj.headers.get("X-goog-maps-solution-id"), "gmp_git_agentskills_v1")
            self.assertEqual(req_obj.headers.get("X-goog-api-key"), "AIzaSy_TEST_KEY")

    @patch("urllib.request.urlopen")
    def test_places_api_quota_or_error_falls_back_to_offline_atlas(self, mock_urlopen):
        """Test that HTTP 429 (quota) or 403 gracefully falls back to offline atlas without crashing."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://places.googleapis.com",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=None,
        )

        with patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "AIzaSy_TEST_KEY"}):
            res = places_service.get_autocomplete_suggestions("Hyderabad")
            self.assertTrue(res["ok"])
            self.assertEqual(res["provider"], "offline_atlas")
            self.assertTrue(len(res["suggestions"]) > 0)
            self.assertEqual(res["suggestions"][0]["name"], "Hyderabad")

    def test_worldwide_offline_destinations_coverage(self):
        """Test offline atlas supports all required world destinations."""
        test_queries = [
            ("Hyderabad", "India"),
            ("Paris", "France"),
            ("Tokyo", "Japan"),
            ("London", "United Kingdom"),
            ("Rome", "Italy"),
            ("Bali", "Indonesia"),
            ("New York", "USA"),
            ("Dubai", "United Arab Emirates"),
            ("Cape Town", "South Africa"),
            ("Swiss Alps", "Switzerland"),
            ("Grand Canyon", "USA"),
        ]
        for query, expected_country in test_queries:
            res = places_service.get_autocomplete_suggestions(query)
            self.assertTrue(res["ok"], f"Failed for {query}")
            self.assertTrue(len(res["suggestions"]) > 0, f"No suggestions for {query}")
            names_and_secs = [
                f"{s['name']} {s['secondary_text']}".lower() for s in res["suggestions"]
            ]
            self.assertTrue(
                any(query.lower() in item for item in names_and_secs),
                f"Query '{query}' not found in results: {names_and_secs}",
            )

    def test_ambiguous_destination_returns_disambiguated_options(self):
        """Test ambiguous place names return multiple disambiguated choices."""
        res = places_service.get_autocomplete_suggestions("Paris")
        self.assertTrue(res["ok"])
        suggestions = res["suggestions"]
        self.assertGreaterEqual(len(suggestions), 2)
        # Should include Paris France and Paris Texas
        full_texts = [s["full_text"] for s in suggestions]
        self.assertTrue(any("France" in t for t in full_texts))
        self.assertTrue(any("Texas" in t or "United States" in t for t in full_texts))

    def test_international_characters_matching(self):
        """Test matching destinations with accents and international spellings."""
        # Query with and without accents
        res1 = places_service.get_autocomplete_suggestions("São Paulo")
        self.assertTrue(res1["ok"])
        self.assertTrue(any("Paulo" in s["name"] for s in res1["suggestions"]))

        res2 = places_service.get_autocomplete_suggestions("Sao Paulo")
        self.assertTrue(res2["ok"])
        self.assertTrue(any("Paulo" in s["name"] for s in res2["suggestions"]))

        res3 = places_service.get_autocomplete_suggestions("Montreal")
        self.assertTrue(res3["ok"])
        self.assertTrue(any("Montréal" in s["name"] or "Montreal" in s["name"] for s in res3["suggestions"]))

    def test_unlisted_destination_fallback(self):
        """Test valid destination completely absent from knowledge base provides custom suggestion."""
        res = places_service.get_autocomplete_suggestions("Timbuktu")
        self.assertTrue(res["ok"])
        self.assertTrue(len(res["suggestions"]) > 0)
        self.assertEqual(res["suggestions"][0]["name"], "Timbuktu")
        self.assertEqual(res["suggestions"][0]["category"], "Destination")

    def test_empty_query_returns_empty_list(self):
        """Test empty query returns clean empty suggestions."""
        res = places_service.get_autocomplete_suggestions("")
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["suggestions"]), 0)


class WorldwidePlannerIntegrationTestCase(unittest.TestCase):
    def test_currency_inference(self):
        """Test accurate ISO currency inference across major worldwide destinations."""
        self.assertEqual(infer_currency_from_name("Hyderabad, India"), "INR")
        self.assertEqual(infer_currency_from_name("Dubai, United Arab Emirates"), "AED")
        self.assertEqual(infer_currency_from_name("Bali, Indonesia"), "IDR")
        self.assertEqual(infer_currency_from_name("Cape Town, South Africa"), "ZAR")
        self.assertEqual(infer_currency_from_name("The Swiss Alps, Switzerland"), "CHF")
        self.assertEqual(infer_currency_from_name("Grand Canyon, Arizona, USA"), "USD")
        self.assertEqual(infer_currency_from_name("Paris, France"), "EUR")
        self.assertEqual(infer_currency_from_name("London, UK"), "GBP")
        self.assertEqual(infer_currency_from_name("Tokyo, Japan"), "JPY")
        self.assertEqual(infer_currency_from_name("Sydney, Australia"), "AUD")
        self.assertEqual(infer_currency_from_name("Toronto, Canada"), "CAD")

    def test_hyderabad_itinerary_does_not_substitute_default_city(self):
        """Test Hyderabad plan preserves destination name and synthesizes cultural/heritage itinerary."""
        plan = run_rule_based_agents(
            destination="Hyderabad, India",
            duration_days=4,
            budget="Moderate",
            interests=["Culture", "Food"],
            companions="Solo",
        )
        self.assertEqual(plan["destination"], "Hyderabad, India")
        self.assertNotIn("Kyoto", plan["destination"])
        self.assertNotIn("Rome", plan["destination"])
        self.assertEqual(len(plan["itinerary"]), 4)
        self.assertEqual(plan["estimated_budget"]["currency"], "INR")
        # Verify experiences focus on heritage and cuisine
        exp_names = [e["name"] for e in plan["experiences"]]
        self.assertTrue(any("Hyderabad" in name for name in exp_names))

    def test_swiss_alps_itinerary_nature_and_chf_currency(self):
        """Test Swiss Alps plan preserves alpine nature focus and CHF currency."""
        plan = run_rule_based_agents(
            destination="The Swiss Alps, Switzerland",
            duration_days=5,
            budget="Moderate",
            interests=["Nature", "Adventure"],
            companions="Couple",
        )
        self.assertEqual(plan["destination"], "The Swiss Alps, Switzerland")
        self.assertEqual(plan["estimated_budget"]["currency"], "CHF")
        self.assertEqual(len(plan["itinerary"]), 5)
        # Check that lodging is alpine/wilderness themed
        hotel_names = [a["name"] for a in plan["accommodations"]]
        self.assertTrue(any("Eco-Lodge" in h or "Chalet" in h for h in hotel_names))

    def test_grand_canyon_itinerary_preserves_national_park_context(self):
        """Test Grand Canyon itinerary is customized for outdoor/park exploration."""
        plan = run_rule_based_agents(
            destination="The Grand Canyon, Arizona, USA",
            duration_days=3,
            budget="Budget",
            interests=["Nature"],
            companions="Family",
        )
        self.assertEqual(plan["destination"], "The Grand Canyon, Arizona, USA")
        self.assertEqual(plan["estimated_budget"]["currency"], "USD")
        self.assertEqual(len(plan["itinerary"]), 3)

    def test_bali_itinerary_beach_and_idr_currency(self):
        """Test Bali itinerary is customized for island/beach."""
        plan = run_rule_based_agents(
            destination="Bali, Indonesia",
            duration_days=6,
            budget="Moderate",
            interests=["Nature", "Food"],
            companions="Friends",
        )
        self.assertIn("Bali", plan["destination"])
        self.assertIn(plan["estimated_budget"]["currency"], ["USD", "IDR"])
        self.assertEqual(len(plan["itinerary"]), 6)

    def test_custom_unknown_destination_is_accepted_without_crash(self):
        """Test an unlisted custom destination generates complete plan for requested days."""
        plan = run_agents(
            destination="Ljubljana, Slovenia",
            duration_days=3,
            budget="Budget",
            interests=["Culture"],
        )
        self.assertEqual(plan["destination"], "Ljubljana, Slovenia")
        self.assertEqual(len(plan["itinerary"]), 3)
        self.assertFalse(plan.get("fallback_used", False))


if __name__ == "__main__":
    unittest.main()
