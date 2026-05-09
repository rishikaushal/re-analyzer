import streamlit as st
from models import AnalysisResult
from fetchers.permits import AustinPermits
from fetchers.redfin import RedfinComps
from fetchers.census import fetch_census_home_value
from fetchers.geocode import geocode_address


def extract_street_name(address: str) -> str:
    parts = address.upper().replace(",", "").split()
    suffixes = {"ST", "STREET", "AVE", "AVENUE", "DR", "DRIVE", "LN", "LANE",
                "BLVD", "BOULEVARD", "CT", "COURT", "WAY", "RD", "ROAD",
                "CIR", "CIRCLE", "PL", "PLACE", "TRL", "TRAIL", "PKWY", "PARKWAY"}
    street_parts = [p for p in parts[1:] if p not in suffixes]
    return " ".join(street_parts) if street_parts else (parts[1] if len(parts) > 1 else parts[0])


@st.cache_data(ttl=3600, show_spinner=False)
def run_analysis(address: str, zip_code: str, street_name: str):
    """Run permits + Redfin analysis (cached for 1 hour)."""
    result = AnalysisResult()
    permits_api = AustinPermits()
    redfin_api = RedfinComps()

    # Permits
    result.street_permits = permits_api.search_street(street_name, zip_code)
    result.street_all_permits = permits_api.search_street_all_types(street_name, zip_code)
    result.zip_permits = permits_api.search_zip(zip_code)
    result.sources_status['permits'] = '✅' if result.street_permits or result.zip_permits else '⚠'

    # Geocode for radius-based queries
    lat, lon = geocode_address(address, zip_code)

    # Redfin — Sold comps (1 mile radius, fallback to ZIP-wide)
    comps_radius = True
    if lat and lon:
        result.redfin_comps = redfin_api.get_sold_comps(zip_code, lat, lon, radius_miles=1.0)
    if not result.redfin_comps:
        result.redfin_comps = redfin_api.get_sold_comps(zip_code, lat, lon, radius_miles=0)
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
        # Fallback: use Census Bureau median home value to estimate $/sf
        try:
            census = fetch_census_home_value(zip_code)
            if census.get('median_value') and census['median_value'] > 0:
                # Estimate $/sf from Census median value / typical new construction size
                typical_sf = 1800  # typical new construction in Austin
                est_psf = round(census['median_value'] / typical_sf)
                result.market_stats = {
                    "median_psf": est_psf,
                    "avg_psf": est_psf,
                    "min_psf": est_psf,
                    "max_psf": est_psf,
                    "count": 0,
                    "source": "Census Bureau (estimated)",
                }
                result.sources_status['redfin'] = '⚠ Census fallback'
        except Exception:
            pass

    # Listing status (active/pending/sold)
    result.listing_status = redfin_api.check_listing_status(address, zip_code)

    # Neighborhood comps are now the same as sold comps (both 1 mile)
    if lat and lon:
        result.neighborhood_comps = result.redfin_comps
        result.neighborhood_stats = result.market_stats

        # Active listings (1 mile radius)
        result.active_comps = redfin_api.get_active_listings(zip_code, lat, lon, radius_miles=1.0)
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

        # Rental listings — Redfin CSV doesn't support rentals, so skip
        # Users can research rentals via the links in the Rental Comps tab

    return result
