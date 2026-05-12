import streamlit as st
from models import AnalysisResult, Permit
from fetchers.permits import AustinPermits
from fetchers.redfin import RedfinComps
from fetchers.census import fetch_census_home_value
from fetchers.geocode import geocode_address
from firebase_cache import cache_get, cache_set, _make_doc_id


def extract_street_name(address: str) -> str:
    parts = address.upper().replace(",", "").split()
    suffixes = {"ST", "STREET", "AVE", "AVENUE", "DR", "DRIVE", "LN", "LANE",
                "BLVD", "BOULEVARD", "CT", "COURT", "WAY", "RD", "ROAD",
                "CIR", "CIRCLE", "PL", "PLACE", "TRL", "TRAIL", "PKWY", "PARKWAY"}
    street_parts = [p for p in parts[1:] if p not in suffixes]
    return " ".join(street_parts) if street_parts else (parts[1] if len(parts) > 1 else parts[0])


def _cached(collection, doc_id, fetch_fn, hint=""):
    """Cache-through helper. Returns (data, was_cached)."""
    cached = cache_get(collection, doc_id)
    if cached is not None:
        return cached, True
    data = fetch_fn()
    if data is not None:
        cache_set(collection, doc_id, data, hint=hint)
    return data, False


def _permits_to_dicts(permits):
    """Convert Permit dataclass instances to dicts for Firestore."""
    return [vars(p) for p in permits] if permits else []


def _dicts_to_permits(dicts):
    """Convert dicts back to Permit instances."""
    return [Permit(**d) for d in dicts] if dicts else []


@st.cache_data(ttl=3600, show_spinner=False)
def run_analysis(address: str, zip_code: str, street_name: str):
    """Run permits + Redfin analysis with Firestore caching per signal."""
    result = AnalysisResult()
    permits_api = AustinPermits()
    redfin_api = RedfinComps()
    cache_hits = []

    pid = _make_doc_id(street_name, zip_code)

    # Permits — street (new construction)
    data, hit = _cached("permits_street", pid,
                        lambda: _permits_to_dicts(permits_api.search_street(street_name, zip_code)),
                        hint=address)
    if hit: cache_hits.append("permits_street")
    result.street_permits = _dicts_to_permits(data) if data else []

    # Permits — street (all types)
    data, hit = _cached("permits_street_all", pid,
                        lambda: _permits_to_dicts(permits_api.search_street_all_types(street_name, zip_code)),
                        hint=address)
    if hit: cache_hits.append("permits_street_all")
    result.street_all_permits = _dicts_to_permits(data) if data else []

    # Permits — zip
    zpid = _make_doc_id(zip_code)
    data, hit = _cached("permits_zip", zpid,
                        lambda: _permits_to_dicts(permits_api.search_zip(zip_code)),
                        hint=zip_code)
    if hit: cache_hits.append("permits_zip")
    result.zip_permits = _dicts_to_permits(data) if data else []

    result.sources_status['permits'] = '✅' if result.street_permits or result.zip_permits else '⚠'

    # Geocode
    geo_id = _make_doc_id(address, zip_code)
    geo_data, geo_hit = _cached("geocode", geo_id,
                                lambda: list(geocode_address(address, zip_code)),
                                hint=address)
    if geo_hit: cache_hits.append("geocode")
    lat, lon = (geo_data[0], geo_data[1]) if geo_data and len(geo_data) == 2 and geo_data[0] is not None else (None, None)

    # Redfin — Sold comps (1 mile radius, fallback to ZIP-wide)
    comps_radius = True
    lat_r = lon_r = None
    if lat and lon:
        lat_r, lon_r = round(lat, 4), round(lon, 4)
        comps_id = _make_doc_id(zip_code, lat_r, lon_r, 1.0)
        data, hit = _cached("redfin_comps", comps_id,
                            lambda: redfin_api.get_sold_comps(zip_code, lat, lon, radius_miles=1.0),
                            hint=address)
        if hit: cache_hits.append("redfin_comps")
        result.redfin_comps = data or []

    if not result.redfin_comps:
        if lat and lon:
            comps_id_0 = _make_doc_id(zip_code, lat_r, lon_r, 0)
            data, hit = _cached("redfin_comps", comps_id_0,
                                lambda: redfin_api.get_sold_comps(zip_code, lat, lon, radius_miles=0),
                                hint=address)
            result.redfin_comps = data or []
        comps_radius = False

    if result.redfin_comps:
        psf_values = sorted([c["psf"] for c in result.redfin_comps if c.get("psf", 0) > 0])
        if psf_values:
            mid = len(psf_values) // 2
            result.market_stats = {
                "median_psf": psf_values[mid],
                "avg_psf": round(sum(psf_values) / len(psf_values)),
                "min_psf": min(psf_values),
                "max_psf": max(psf_values),
                "count": len(psf_values),
            }
        result.sources_status['redfin'] = '✅'
        result.sources_status['comps_radius'] = comps_radius
    else:
        result.sources_status['redfin'] = '⚠ No data'
        try:
            census_id = _make_doc_id(zip_code)
            census, c_hit = _cached("census_home_value", census_id,
                                    lambda: fetch_census_home_value(zip_code),
                                    hint=zip_code)
            if c_hit: cache_hits.append("census_home_value")
            if census and census.get('median_value') and census['median_value'] > 0:
                typical_sf = 1800
                est_psf = round(census['median_value'] / typical_sf)
                result.market_stats = {
                    "median_psf": est_psf, "avg_psf": est_psf,
                    "min_psf": est_psf, "max_psf": est_psf,
                    "count": 0, "source": "Census Bureau (estimated)",
                }
                result.sources_status['redfin'] = '⚠ Census fallback'
        except Exception:
            pass

    # Listing status
    ls_id = _make_doc_id(address, zip_code)
    data, hit = _cached("listing_status", ls_id,
                        lambda: redfin_api.check_listing_status(address, zip_code),
                        hint=address)
    if hit: cache_hits.append("listing_status")
    result.listing_status = data or {}

    # Neighborhood comps & active listings
    if lat and lon:
        result.neighborhood_comps = result.redfin_comps
        result.neighborhood_stats = result.market_stats

        active_id = _make_doc_id(zip_code, lat_r, lon_r, 1.0)
        data, hit = _cached("redfin_active", active_id,
                            lambda: redfin_api.get_active_listings(zip_code, lat, lon, radius_miles=1.0),
                            hint=address)
        if hit: cache_hits.append("redfin_active")
        result.active_comps = data or []
        if result.active_comps:
            a_psf = sorted([c["psf"] for c in result.active_comps if c.get("psf", 0) > 0])
            if a_psf:
                mid = len(a_psf) // 2
                result.active_stats = {
                    "median_psf": a_psf[mid],
                    "avg_psf": round(sum(a_psf) / len(a_psf)),
                    "min_psf": min(a_psf),
                    "max_psf": max(a_psf),
                    "count": len(a_psf),
                }

    result.sources_status['cache_hits'] = cache_hits
    return result
