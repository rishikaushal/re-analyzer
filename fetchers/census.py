import requests


def fetch_census_rents(zip_code: str) -> dict:
    """Fetch median rent data from Census Bureau ACS 5-year survey (no API key needed)."""
    try:
        url = 'https://api.census.gov/data/2022/acs/acs5'
        params = {
            'get': 'B25064_001E,B25031_002E,B25031_003E,B25031_004E,B25031_005E,B25031_006E',
            'for': f'zip code tabulation area:{zip_code}'
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if len(data) < 2:
            return {}
        values = data[1]
        def _int(v):
            try:
                return int(v) if v and int(v) > 0 else None
            except (ValueError, TypeError):
                return None
        return {
            'median_rent': _int(values[0]),
            'rent_0br': _int(values[1]),
            'rent_1br': _int(values[2]),
            'rent_2br': _int(values[3]),
            'rent_3br': _int(values[4]),
            'rent_4br_plus': _int(values[5]),
            'source': 'Census ACS 5-Year (2022)',
        }
    except Exception:
        return {}


def fetch_census_home_value(zip_code: str) -> dict:
    """Fetch median home value from Census Bureau ACS (no API key needed)."""
    try:
        url = 'https://api.census.gov/data/2022/acs/acs5'
        params = {
            'get': 'B25077_001E',
            'for': f'zip code tabulation area:{zip_code}'
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if len(data) < 2:
            return {}
        val = data[1][0]
        return {'median_value': int(val) if val else 0}
    except Exception:
        return {}
