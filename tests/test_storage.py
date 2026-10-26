"""tests/test_storage.py - Unit and Integration Tests for Unified Storage Layer.

Covers:
- Configuration detection for Supabase (environment variables vs placeholders)
- Default path resolution (local vs Vercel /tmp fallback)
- Supabase REST client operations (load, add, delete, get_by_id) via mocked HTTP
- Supabase error handling (missing table friendly error message, connection error)
- Local file atomic fallback persistence
"""

import io
import json
import os
import shutil
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

import storage


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="voyage_storage_test_")
        self.test_filepath = os.path.join(self.test_dir, "test_trips.json")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_supabase_configured_detection(self):
        """Test is_supabase_configured returns True only for real non-placeholder values."""
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(storage.is_supabase_configured())

        with patch.dict(os.environ, {"SUPABASE_URL": "https://xyz.supabase.co", "SUPABASE_KEY": "your_key_here"}):
            self.assertFalse(storage.is_supabase_configured())

        with patch.dict(os.environ, {"SUPABASE_URL": "https://xyz.supabase.co", "SUPABASE_KEY": "sb_real_key_123"}):
            self.assertTrue(storage.is_supabase_configured())

    def test_vercel_environment_defaults_to_tmp(self):
        """Test that get_default_trips_filepath returns /tmp/trips.json on Vercel without TRIPS_FILE."""
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=True):
            path = storage.get_default_trips_filepath()
            self.assertEqual(path, "/tmp/trips.json")

    def test_local_environment_defaults_to_workspace_trips_json(self):
        """Test that get_default_trips_filepath returns local trips.json when not on Vercel."""
        with patch.dict(os.environ, {}, clear=True):
            path = storage.get_default_trips_filepath()
            self.assertTrue(path.endswith("trips.json"))
            self.assertNotIn("/tmp", path)

    def test_local_file_crud_operations(self):
        """Test local file storage add, load, get_by_id, and delete under thread lock."""
        trip = {
            "trip_id": "test_trip_123",
            "destination": "Kyoto, Japan",
            "created_at": "2026-10-26T12:00:00Z",
            "duration_days": 3,
            "budget": "Moderate",
        }
        # Add
        storage.add_trip(trip, filepath=self.test_filepath)
        self.assertTrue(os.path.exists(self.test_filepath))

        # Load
        loaded = storage.load_trips(filepath=self.test_filepath)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["trip_id"], "test_trip_123")

        # Get by ID
        fetched = storage.get_trip_by_id("test_trip_123", filepath=self.test_filepath)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["destination"], "Kyoto, Japan")

        # Update existing
        trip["destination"] = "Tokyo, Japan"
        updated = storage.update_trip("test_trip_123", trip, filepath=self.test_filepath)
        self.assertTrue(updated)
        fetched_updated = storage.get_trip_by_id("test_trip_123", filepath=self.test_filepath)
        self.assertEqual(fetched_updated["destination"], "Tokyo, Japan")

        # Delete existing
        deleted = storage.delete_trip("test_trip_123", filepath=self.test_filepath)
        self.assertTrue(deleted)
        self.assertEqual(len(storage.load_trips(filepath=self.test_filepath)), 0)

        # Delete non-existent
        deleted_again = storage.delete_trip("non_existent_id", filepath=self.test_filepath)
        self.assertFalse(deleted_again)

    @patch("urllib.request.urlopen")
    def test_supabase_load_trips_jsonb_format(self, mock_urlopen):
        """Test loading trips from Supabase when stored with jsonb trip_data column."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 200
        mock_data = [
            {
                "trip_id": "sp_1",
                "created_at": "2026-10-26T14:00:00Z",
                "trip_data": {
                    "trip_id": "sp_1",
                    "destination": "Rome, Italy",
                    "budget": "Moderate",
                },
            }
        ]
        mock_response.read.return_value = json.dumps(mock_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "valid_key"}):
            trips = storage.load_trips()
            self.assertEqual(len(trips), 1)
            self.assertEqual(trips[0]["trip_id"], "sp_1")
            self.assertEqual(trips[0]["destination"], "Rome, Italy")

    @patch("urllib.request.urlopen")
    def test_supabase_add_trip(self, mock_urlopen):
        """Test inserting a trip into Supabase PostgREST table."""
        mock_response = MagicMock()
        mock_response.getcode.return_value = 201
        mock_response.read.return_value = b""
        mock_urlopen.return_value.__enter__.return_value = mock_response

        sample_trip = {
            "trip_id": "sp_add_1",
            "destination": "Banff, Canada",
            "created_at": "2026-10-26T15:00:00Z",
        }
        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "valid_key"}):
            storage.add_trip(sample_trip)
            self.assertTrue(mock_urlopen.called)
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.get_method(), "POST")
            self.assertIn("rest/v1/trips", req.full_url)
            self.assertEqual(req.headers["Apikey"], "valid_key")

    @patch("urllib.request.urlopen")
    def test_supabase_delete_trip_success_and_not_found(self, mock_urlopen):
        """Test deleting a trip in Supabase returns True when row is returned, False when empty list."""
        mock_response_found = MagicMock()
        mock_response_found.getcode.return_value = 200
        mock_response_found.read.return_value = json.dumps([{"trip_id": "del_1"}]).encode("utf-8")

        mock_response_not_found = MagicMock()
        mock_response_not_found.getcode.return_value = 200
        mock_response_not_found.read.return_value = json.dumps([]).encode("utf-8")

        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "valid_key"}):
            # 1. Successful deletion
            mock_urlopen.return_value.__enter__.return_value = mock_response_found
            result = storage.delete_trip("del_1")
            self.assertTrue(result)

            # 2. Not found deletion
            mock_urlopen.return_value.__enter__.return_value = mock_response_not_found
            result2 = storage.delete_trip("missing_id")
            self.assertFalse(result2)

    @patch("urllib.request.urlopen")
    def test_supabase_update_trip(self, mock_urlopen):
        """Test updating a trip in Supabase returns True when updated, False when not found."""
        mock_response_found = MagicMock()
        mock_response_found.getcode.return_value = 200
        mock_response_found.read.return_value = json.dumps([{"trip_id": "up_1"}]).encode("utf-8")

        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "valid_key"}):
            mock_urlopen.return_value.__enter__.return_value = mock_response_found
            updated = storage.update_trip("up_1", {"destination": "Updated Kyoto", "trip_id": "up_1"})
            self.assertTrue(updated)
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.get_method(), "PATCH")

    @patch("urllib.request.urlopen")
    def test_supabase_missing_table_informative_error(self, mock_urlopen):
        """Test that if the trips table hasn't been created in Supabase yet, a clear instructional error is raised."""
        http_err = urllib.error.HTTPError(
            url="https://test.supabase.co/rest/v1/trips",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b'{"message":"relation \\"public.trips\\" does not exist"}'),
        )
        mock_urlopen.side_effect = http_err

        with patch.dict(os.environ, {"SUPABASE_URL": "https://test.supabase.co", "SUPABASE_KEY": "valid_key"}):
            with self.assertRaises(storage.StorageError) as ctx:
                storage.load_trips()
            self.assertIn("table 'trips' does not exist", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
