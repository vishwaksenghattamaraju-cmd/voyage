"""storage.py - Unified storage layer for Voyage AI.

Supports two storage backends:
1. Supabase (PostgreSQL via PostgREST) - Persistent cloud database for production on Vercel ($0 free tier).
2. Local File (trips.json) - Thread-safe atomic file storage for local dev, testing, and fallback.
"""

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("voyage_ai.storage")

# Re-entrant thread lock for local file operations
_file_storage_lock = threading.RLock()


class StorageError(Exception):
    """Base storage error."""
    pass


class StorageCorruptedError(StorageError):
    """Raised when trips storage contains malformed or unparseable data."""
    pass


def is_serverless_environment() -> bool:
    """Detect if running in Vercel, AWS Lambda, or a serverless container."""
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("VERCEL_URL")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        or os.environ.get("LAMBDA_TASK_ROOT")
    )


def is_supabase_configured() -> bool:
    """Check if Supabase database environment variables are configured.

    Returns True only if both SUPABASE_URL and a key are set and are not placeholder strings.
    """
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    if not url or not key:
        return False
    # Avoid placeholder values from example files
    if "your_" in url or "your_" in key or "placeholder" in url.lower() or "placeholder" in key.lower():
        return False
    return True


def get_default_trips_filepath() -> str:
    """Determine the default local trips.json path based on environment."""
    explicit = os.environ.get("TRIPS_FILE")
    if explicit:
        return explicit

    # On Vercel / serverless runtimes, root directory is read-only.
    # Default to /tmp/trips.json so local fallback never raises [Errno 30] Read-only file system.
    if is_serverless_environment():
        return "/tmp/trips.json"

    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "trips.json")


# =====================================================================
# Supabase PostgREST Client
# =====================================================================

def _get_supabase_config() -> Tuple[str, str]:
    """Retrieve and validate Supabase URL and key."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        or os.environ.get("SUPABASE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
    )
    if not url or not key:
        raise StorageError("Supabase is not configured (SUPABASE_URL or SUPABASE_KEY missing).")
    return url, key


def _supabase_request(
    endpoint: str,
    method: str = "GET",
    body: Optional[Any] = None,
    headers_extra: Optional[Dict[str, str]] = None,
    timeout: int = 12,
) -> Tuple[int, Any]:
    """Execute a request against the Supabase PostgREST API using urllib.request."""
    url_base, key = _get_supabase_config()
    full_url = f"{url_base}/rest/v1/{endpoint}"

    req_headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if headers_extra:
        req_headers.update(headers_extra)

    data_bytes = None
    if body is not None:
        data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url=full_url,
        data=data_bytes,
        headers=req_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            resp_bytes = response.read()
            if not resp_bytes:
                return status, None
            try:
                return status, json.loads(resp_bytes.decode("utf-8"))
            except Exception:
                return status, resp_bytes.decode("utf-8")
    except urllib.error.HTTPError as http_err:
        err_body = ""
        try:
            err_body = http_err.read().decode("utf-8")
        except Exception:
            pass
        logger.error("Supabase PostgREST %s error on %s %s: %s", http_err.code, method, full_url, err_body)
        if "relation \"public.trips\" does not exist" in err_body or "does not exist" in err_body:
            raise StorageError(
                "Database table 'trips' does not exist in your Supabase project. "
                "Please run the table creation SQL provided in the documentation."
            )
        if http_err.code == 401 or http_err.code == 403:
            raise StorageError("Supabase authentication failed. Please verify your SUPABASE_KEY in Vercel settings.")
        raise StorageError(f"Database error ({http_err.code}): {http_err.reason}")
    except urllib.error.URLError as url_err:
        logger.error("Supabase connection failed on %s %s: %s", method, full_url, url_err.reason)
        raise StorageError("Could not connect to database. Please check your SUPABASE_URL.")
    except Exception as exc:
        logger.error("Unexpected database error on %s %s: %s", method, full_url, exc)
        raise StorageError("An unexpected database error occurred.")


def _supabase_load_trips() -> List[Dict[str, Any]]:
    """Fetch all saved trips from Supabase, sorted newest first."""
    _, rows = _supabase_request("trips?select=*&order=created_at.desc")
    if not isinstance(rows, list):
        return []

    trips: List[Dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            # If stored as jsonb column trip_data
            if isinstance(row.get("trip_data"), dict):
                trip = dict(row["trip_data"])
                if "trip_id" not in trip and "trip_id" in row:
                    trip["trip_id"] = row["trip_id"]
                if "created_at" not in trip and "created_at" in row:
                    trip["created_at"] = row["created_at"]
                trips.append(trip)
            else:
                trips.append(row)
    return trips


def _supabase_add_trip(trip_data: Dict[str, Any]) -> None:
    """Insert a trip record into Supabase."""
    trip_id = trip_data.get("trip_id")
    created_at = trip_data.get("created_at")
    payload = {
        "trip_id": trip_id,
        "created_at": created_at,
        "destination": trip_data.get("destination", ""),
        "duration_days": trip_data.get("duration_days", 1),
        "budget": trip_data.get("budget", ""),
        "companions": trip_data.get("companions", ""),
        "climate": trip_data.get("climate", ""),
        "llm_provider": trip_data.get("llm_provider", ""),
        "trip_data": trip_data,
    }
    _supabase_request("trips", method="POST", body=payload, headers_extra={"Prefer": "return=minimal"})


def _supabase_update_trip(trip_id: str, updated_data: Dict[str, Any]) -> bool:
    """Update an existing trip record in Supabase."""
    clean_id = urllib.parse.quote(trip_id.strip())
    endpoint = f"trips?trip_id=eq.{clean_id}"
    payload = {
        "destination": updated_data.get("destination", ""),
        "trip_data": updated_data,
    }
    _, res = _supabase_request(endpoint, method="PATCH", body=payload, headers_extra={"Prefer": "return=representation"})
    if isinstance(res, list) and len(res) > 0:
        return True
    return False


def _supabase_delete_trip(trip_id: str) -> bool:
    """Delete a trip record from Supabase by trip_id."""
    clean_id = urllib.parse.quote(trip_id.strip())
    endpoint = f"trips?trip_id=eq.{clean_id}"
    _, res = _supabase_request(endpoint, method="DELETE", headers_extra={"Prefer": "return=representation"})
    if isinstance(res, list) and len(res) > 0:
        return True
    return False


def _supabase_get_trip(trip_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single trip from Supabase by trip_id."""
    clean_id = urllib.parse.quote(trip_id.strip())
    endpoint = f"trips?trip_id=eq.{clean_id}&select=*"
    _, rows = _supabase_request(endpoint, method="GET")
    if isinstance(rows, list) and len(rows) > 0:
        row = rows[0]
        if isinstance(row.get("trip_data"), dict):
            trip = dict(row["trip_data"])
            if "trip_id" not in trip and "trip_id" in row:
                trip["trip_id"] = row["trip_id"]
            if "created_at" not in trip and "created_at" in row:
                trip["created_at"] = row["created_at"]
            return trip
        return row
    return None


# =====================================================================
# Local File (trips.json) Atomic Implementation
# =====================================================================

def _resolve_safe_filepath(filepath: str) -> str:
    """Ensure filepath directory is writable, falling back to /tmp if read-only."""
    dir_name = os.path.dirname(os.path.abspath(filepath)) or "."
    try:
        os.makedirs(dir_name, exist_ok=True)
        # Test writability by touching a probe file
        probe_fd, probe_path = tempfile.mkstemp(dir=dir_name, prefix=".probe_")
        os.close(probe_fd)
        os.remove(probe_path)
        return filepath
    except (OSError, PermissionError):
        fallback_dir = tempfile.gettempdir()
        return os.path.join(fallback_dir, os.path.basename(filepath))


def _save_trips_file_unlocked(filepath: str, trips: List[Dict[str, Any]]) -> None:
    """Write trips list atomically to disk using a temporary file and os.replace."""
    safe_path = _resolve_safe_filepath(filepath)
    dir_name = os.path.dirname(os.path.abspath(safe_path)) or "."
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix="trips_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(trips, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, safe_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _load_trips_file_locked(filepath: str) -> List[Dict[str, Any]]:
    """Load trips from the JSON file with thread safety, auto-creation, and corruption backup."""
    safe_path = _resolve_safe_filepath(filepath)
    with _file_storage_lock:
        if not os.path.exists(safe_path):
            _save_trips_file_unlocked(safe_path, [])
            return []

        try:
            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
            if not isinstance(data, list):
                raise ValueError("Trips content root is not a list")
            return data
        except (json.JSONDecodeError, ValueError) as err:
            timestamp = int(time.time())
            corrupt_path = f"{safe_path}.corrupt-{timestamp}.json"
            try:
                shutil.copyfile(safe_path, corrupt_path)
                logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
            except Exception as copy_err:
                logger.error("Failed to create backup of corrupted trips file: %s", copy_err)
            raise StorageCorruptedError(
                f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
            )


def _add_trip_file_locked(filepath: str, trip_data: Dict[str, Any]) -> None:
    """Prepend a newly generated trip to trips.json atomically under lock."""
    safe_path = _resolve_safe_filepath(filepath)
    with _file_storage_lock:
        trips = []
        if os.path.exists(safe_path):
            try:
                with open(safe_path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    trips = json.loads(content) if content else []
                if not isinstance(trips, list):
                    raise ValueError("Trips file is not a list")
            except (json.JSONDecodeError, ValueError) as err:
                timestamp = int(time.time())
                corrupt_path = f"{safe_path}.corrupt-{timestamp}.json"
                try:
                    shutil.copyfile(safe_path, corrupt_path)
                    logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
                except Exception:
                    pass
                raise StorageCorruptedError(
                    f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
                )

        trips.insert(0, trip_data)
        _save_trips_file_unlocked(safe_path, trips)


def _update_trip_file_locked(filepath: str, trip_id: str, updated_data: Dict[str, Any]) -> bool:
    """Update an existing trip record in local file storage under lock."""
    safe_path = _resolve_safe_filepath(filepath)
    with _file_storage_lock:
        if not os.path.exists(safe_path):
            return False
        trips = _load_trips_file_locked(safe_path)
        clean_id = trip_id.strip().lower()
        found = False
        for idx, t in enumerate(trips):
            if str(t.get("trip_id", "")).strip().lower() == clean_id:
                trips[idx] = updated_data
                found = True
                break
        if found:
            _save_trips_file_unlocked(safe_path, trips)
        return found


def _delete_trip_file_locked(filepath: str, trip_id: str) -> bool:
    """Delete a trip by trip_id from trips.json under lock. Returns True if deleted, False if not found."""
    safe_path = _resolve_safe_filepath(filepath)
    with _file_storage_lock:
        if not os.path.exists(safe_path):
            return False
        try:
            with open(safe_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                trips = json.loads(content) if content else []
            if not isinstance(trips, list):
                raise ValueError("Trips file is not a list")
        except (json.JSONDecodeError, ValueError) as err:
            timestamp = int(time.time())
            corrupt_path = f"{safe_path}.corrupt-{timestamp}.json"
            try:
                shutil.copyfile(safe_path, corrupt_path)
                logger.error("Corrupted trips file backed up to %s: %s", corrupt_path, err)
            except Exception:
                pass
            raise StorageCorruptedError(
                f"Trips storage file is corrupt and has been backed up to {os.path.basename(corrupt_path)}."
            )

        clean_id = trip_id.strip().lower()
        original_len = len(trips)
        trips = [t for t in trips if str(t.get("trip_id", "")).strip().lower() != clean_id]
        if len(trips) == original_len:
            return False

        _save_trips_file_unlocked(safe_path, trips)
        return True


# =====================================================================
# Unified Public Storage API
# =====================================================================

def load_trips(filepath: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load trips from Supabase if configured, otherwise from the local JSON file."""
    if is_supabase_configured():
        return _supabase_load_trips()
    target_path = filepath or get_default_trips_filepath()
    return _load_trips_file_locked(target_path)


def add_trip(trip_data: Dict[str, Any], filepath: Optional[str] = None) -> None:
    """Save a newly planned trip to Supabase if configured, otherwise to local JSON file."""
    if is_supabase_configured():
        _supabase_add_trip(trip_data)
        return
    if is_serverless_environment():
        logger.warning(
            "Running in serverless environment without Supabase configured. "
            "Trip saved to ephemeral /tmp storage and will not persist across container cold starts."
        )
    target_path = filepath or get_default_trips_filepath()
    _add_trip_file_locked(target_path, trip_data)


def update_trip(trip_id: str, updated_data: Dict[str, Any], filepath: Optional[str] = None) -> bool:
    """Update a trip record by ID in Supabase if configured, otherwise in local JSON file."""
    if is_supabase_configured():
        return _supabase_update_trip(trip_id, updated_data)
    target_path = filepath or get_default_trips_filepath()
    return _update_trip_file_locked(target_path, trip_id, updated_data)


def delete_trip(trip_id: str, filepath: Optional[str] = None) -> bool:
    """Delete a trip by ID from Supabase if configured, otherwise from local JSON file."""
    if is_supabase_configured():
        return _supabase_delete_trip(trip_id)
    target_path = filepath or get_default_trips_filepath()
    return _delete_trip_file_locked(target_path, trip_id)


def get_trip_by_id(trip_id: str, filepath: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single trip by ID from Supabase if configured, otherwise from local JSON file."""
    if is_supabase_configured():
        return _supabase_get_trip(trip_id)

    clean_id = trip_id.strip().lower()
    trips = load_trips(filepath)
    for trip in trips:
        if str(trip.get("trip_id", "")).strip().lower() == clean_id:
            return trip
    return None
