"""Firebase Firestore caching layer for market data.

Provides a read-through cache so repeated address searches return
cached data when fresh, falling back to live API calls otherwise.
Each data signal has its own Firestore collection with a per-signal TTL.

Graceful degradation: if Firebase is not configured or unavailable,
all cache operations silently return None / no-op.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

# ── TTL defaults (hours) per signal type ──
TTL_HOURS = {
    "permits_street": 168,      # 7 days
    "permits_street_all": 168,  # 7 days
    "permits_zip": 168,         # 7 days
    "redfin_comps": 24,         # 1 day
    "redfin_active": 12,        # 12 hours
    "census_home_value": 720,   # 30 days
    "census_rents": 720,        # 30 days
    "geocode": 2160,            # 90 days
    "plot_info": 720,           # 30 days
    "listing_status": 6,        # 6 hours
}

# ── Firestore client singleton ──
_db = None
_init_attempted = False


def _get_db():
    """Return Firestore client, initializing once. Returns None if unavailable."""
    global _db, _init_attempted
    if _init_attempted:
        return _db
    _init_attempted = True
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        # Try Streamlit secrets first
        try:
            import streamlit as st
            fb_config = dict(st.secrets["firebase"])
            cred = credentials.Certificate(fb_config)
        except Exception:
            # Fallback: look for local service account JSON
            import glob as _glob
            sa_files = _glob.glob("*-firebase-adminsdk-*.json")
            if not sa_files:
                return None
            cred = credentials.Certificate(sa_files[0])

        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)

        _db = firestore.client()
    except Exception as e:
        import logging
        logging.warning(f"Firebase cache unavailable: {e}")
        _db = None
    return _db


def _make_doc_id(*parts: str) -> str:
    """Create a safe Firestore document ID from parts."""
    raw = "_".join(str(p) for p in parts)
    # Replace characters not safe for Firestore doc IDs
    return re.sub(r'[^a-zA-Z0-9_.\-]', '_', raw)[:500]


def cache_get(collection: str, doc_id: str, ttl_hours: Optional[int] = None) -> Optional[Any]:
    """Read from cache. Returns data if fresh, None otherwise."""
    db = _get_db()
    if db is None:
        return None
    try:
        if ttl_hours is None:
            ttl_hours = TTL_HOURS.get(collection, 24)
        doc = db.collection(collection).document(doc_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        fetched_at = data.get("fetched_at")
        if fetched_at is None:
            return None
        # Check freshness
        if hasattr(fetched_at, 'timestamp'):
            fetched_ts = fetched_at.timestamp()
        else:
            fetched_ts = fetched_at
        age_hours = (datetime.now(timezone.utc).timestamp() - fetched_ts) / 3600
        if age_hours > ttl_hours:
            return None  # stale
        return data.get("data")
    except Exception:
        return None


def cache_set(collection: str, doc_id: str, data: Any,
              ttl_hours: Optional[int] = None, hint: str = "") -> bool:
    """Write data to cache. Returns True on success."""
    db = _get_db()
    if db is None:
        return False
    try:
        if ttl_hours is None:
            ttl_hours = TTL_HOURS.get(collection, 24)
        # Serialize data — convert non-JSON-safe types
        safe_data = _serialize(data)
        doc = {
            "data": safe_data,
            "fetched_at": datetime.now(timezone.utc),
            "ttl_hours": ttl_hours,
            "address_hint": hint,
        }
        db.collection(collection).document(doc_id).set(doc)
        return True
    except Exception as e:
        import logging
        logging.warning(f"Firebase cache write failed [{collection}/{doc_id}]: {e}")
        return False


def cache_delete(collection: str, doc_id: str) -> bool:
    """Delete a specific cached document."""
    db = _get_db()
    if db is None:
        return False
    try:
        db.collection(collection).document(doc_id).delete()
        return True
    except Exception:
        return False


def cache_clear_address(address: str, zip_code: str,
                        lat: float = None, lon: float = None):
    """Clear all cached data for a specific address."""
    db = _get_db()
    if db is None:
        return
    street = _extract_street(address)
    # Delete known document patterns
    keys_to_delete = [
        ("geocode", _make_doc_id(address, zip_code)),
        ("listing_status", _make_doc_id(address, zip_code)),
        ("permits_street", _make_doc_id(street, zip_code)),
        ("permits_street_all", _make_doc_id(street, zip_code)),
        ("permits_zip", _make_doc_id(zip_code)),
        ("census_home_value", _make_doc_id(zip_code)),
        ("census_rents", _make_doc_id(zip_code)),
    ]
    if lat is not None and lon is not None:
        lat_r = round(lat, 4)
        lon_r = round(lon, 4)
        for radius in [0, 1.0]:
            keys_to_delete.append(("redfin_comps", _make_doc_id(zip_code, lat_r, lon_r, radius)))
            keys_to_delete.append(("redfin_active", _make_doc_id(zip_code, lat_r, lon_r, radius)))
        keys_to_delete.append(("plot_info", _make_doc_id(lat_r, lon_r)))

    for coll, did in keys_to_delete:
        try:
            db.collection(coll).document(did).delete()
        except Exception:
            pass


def cache_status(collection: str, doc_id: str) -> Optional[dict]:
    """Return cache metadata (fetched_at, ttl_hours) without returning data."""
    db = _get_db()
    if db is None:
        return None
    try:
        doc = db.collection(collection).document(doc_id).get()
        if not doc.exists:
            return None
        d = doc.to_dict()
        fetched_at = d.get("fetched_at")
        if hasattr(fetched_at, 'timestamp'):
            fetched_ts = fetched_at.timestamp()
        else:
            fetched_ts = fetched_at or 0
        age_hours = (datetime.now(timezone.utc).timestamp() - fetched_ts) / 3600
        ttl = d.get("ttl_hours", TTL_HOURS.get(collection, 24))
        return {
            "fetched_at": fetched_at,
            "age_hours": round(age_hours, 1),
            "ttl_hours": ttl,
            "fresh": age_hours <= ttl,
        }
    except Exception:
        return None


def _extract_street(address: str) -> str:
    """Extract street name from address for permit lookups."""
    parts = address.upper().replace(",", "").split()
    suffixes = {"ST", "STREET", "AVE", "AVENUE", "DR", "DRIVE", "LN", "LANE",
                "BLVD", "BOULEVARD", "CT", "COURT", "WAY", "RD", "ROAD",
                "CIR", "CIRCLE", "PL", "PLACE", "TRL", "TRAIL", "PKWY", "PARKWAY"}
    street_parts = [p for p in parts[1:] if p not in suffixes]
    return " ".join(street_parts) if street_parts else (parts[1] if len(parts) > 1 else parts[0])


def _serialize(obj):
    """Convert Python objects to Firestore-safe types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(item) for item in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    if hasattr(obj, '__dict__'):
        return _serialize(vars(obj))
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)
