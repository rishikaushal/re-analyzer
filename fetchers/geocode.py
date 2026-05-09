import requests


def geocode_address(address: str, zip_code: str):
    """Geocode address using Census Bureau geocoder, fallback to Nominatim."""
    # Try Census geocoder first
    try:
        params = {
            'address': f'{address}, Austin, TX {zip_code}',
            'benchmark': 'Public_AR_Current',
            'format': 'json',
        }
        r = requests.get('https://geocoding.geo.census.gov/geocoder/locations/onelineaddress',
                        params=params, timeout=15)
        matches = r.json().get('result', {}).get('addressMatches', [])
        if matches:
            coords = matches[0]['coordinates']
            return coords['y'], coords['x']
    except Exception:
        pass
    # Fallback to Nominatim
    try:
        r = requests.get('https://nominatim.openstreetmap.org/search',
                        params={'q': f'{address}, Austin, TX {zip_code}', 'format': 'json', 'limit': 1},
                        headers={'User-Agent': 'RE-Analyzer/1.0'}, timeout=15)
        data = r.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except Exception:
        pass
    return None, None
