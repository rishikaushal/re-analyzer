import requests
import csv
import io
import re
import time
from typing import Optional


class RedfinComps:
    REGION_CACHE = {}

    def _get_region_id(self, zip_code: str) -> Optional[str]:
        if zip_code in self.REGION_CACHE:
            return self.REGION_CACHE[zip_code]
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        }
        try:
            resp = requests.get(f'https://www.redfin.com/zipcode/{zip_code}', headers=headers, timeout=15)
            if resp.status_code == 200:
                matches = re.findall(r'region_id=(\d+)', resp.text)
                for rid in matches:
                    if rid != zip_code and len(rid) >= 4:
                        self.REGION_CACHE[zip_code] = rid
                        return rid
                match2 = re.search(r'"regionId"\s*:\s*(\d+)', resp.text)
                if match2 and match2.group(1) != zip_code:
                    rid = match2.group(1)
                    self.REGION_CACHE[zip_code] = rid
                    return rid
        except Exception:
            pass
        return None

    def get_sold_comps(self, zip_code: str, lat: float = 0, lon: float = 0, radius_miles: float = 0) -> list[dict]:
        """Get sold comps in ZIP via region_id. If lat/lon/radius provided, compute distance and filter."""
        region_id = self._get_region_id(zip_code)
        if not region_id:
            return []
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        ]
        url = (
            f'https://www.redfin.com/stingray/api/gis-csv?al=1&num_homes=200'
            f'&ord=redfin-recommended-asc&page_number=1'
            f'&region_id={region_id}&region_type=2'
            f'&sold_within_days=730&status=9&uipt=1&v=8&min_year_built=2020'
        )
        for ua in user_agents:
            try:
                headers = {'User-Agent': ua}
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                lines = resp.text.strip().split('\n')
                header_idx = None
                for i, line in enumerate(lines):
                    if line.startswith('SALE TYPE') or line.startswith('"SALE TYPE'):
                        header_idx = i
                        break
                if header_idx is None:
                    continue
                reader = csv.DictReader(io.StringIO('\n'.join(lines[header_idx:])))
                comps = []
                for row in reader:
                    try:
                        price_str = (row.get('PRICE') or '0').replace(',', '').replace('$', '')
                        price = int(float(price_str)) if price_str else 0
                        sqft_str = (row.get('SQUARE FEET') or '0').replace(',', '')
                        sqft = int(float(sqft_str)) if sqft_str else 0
                        year_str = row.get('YEAR BUILT') or '0'
                        year = int(float(year_str)) if year_str else 0
                        psf = round(price / sqft) if sqft > 0 else 0
                        if price > 0 and year >= 2020:
                            redfin_url = ''
                            for key in row.keys():
                                if key and 'URL' in key.upper():
                                    redfin_url = row[key] or ''
                                    break
                            raw_addr = (row.get('ADDRESS') or '').strip()
                            city = (row.get('CITY') or '').strip()
                            state = (row.get('STATE OR PROVINCE') or 'TX').strip()
                            zipcode = (row.get('ZIP OR POSTAL CODE') or '').strip()
                            zillow_query = f"{raw_addr} {city} {state} {zipcode}".replace(' ', '-')
                            dist = 0
                            comp_lat = float(row.get('LATITUDE') or 0)
                            comp_lon = float(row.get('LONGITUDE') or 0)
                            if comp_lat and comp_lon and lat and lon:
                                dist = ((comp_lat - lat) * 69) ** 2 + ((comp_lon - lon) * 60) ** 2
                                dist = dist ** 0.5
                            comps.append({
                                'address': f"{raw_addr}, {city}",
                                'price': price, 'sqft': sqft, 'psf': psf,
                                'year_built': year,
                                'sold_date': row.get('SOLD DATE') or '',
                                'beds': row.get('BEDS') or '',
                                'baths': row.get('BATHS') or '',
                                'redfin_url': redfin_url,
                                'zillow_url': f"https://www.zillow.com/homes/{zillow_query}_rb/",
                                'distance_mi': round(dist, 2),
                            })
                    except (ValueError, ZeroDivisionError):
                        continue
                if radius_miles > 0 and lat and lon:
                    comps = [c for c in comps if c.get('distance_mi', 99) <= radius_miles]
                return sorted(comps, key=lambda x: x.get('distance_mi', 99))
            except Exception:
                time.sleep(2)
                continue
        return []

    def get_active_listings(self, zip_code: str, lat: float = 0, lon: float = 0, radius_miles: float = 1.0) -> list[dict]:
        """Get currently active (for sale) listings in ZIP, filtered by distance if lat/lon provided."""
        region_id = self._get_region_id(zip_code)
        if not region_id:
            return []
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        ]
        url = (
            f'https://www.redfin.com/stingray/api/gis-csv?al=1&num_homes=200'
            f'&ord=redfin-recommended-asc&page_number=1'
            f'&region_id={region_id}&region_type=2'
            f'&status=1&uipt=1&v=8'
        )
        for ua in user_agents:
            try:
                headers = {'User-Agent': ua}
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                lines = resp.text.strip().split('\n')
                header_idx = None
                for i, line in enumerate(lines):
                    if line.startswith('SALE TYPE') or line.startswith('"SALE TYPE'):
                        header_idx = i
                        break
                if header_idx is None:
                    continue
                reader = csv.DictReader(io.StringIO('\n'.join(lines[header_idx:])))
                comps = []
                for row in reader:
                    try:
                        price_str = (row.get('PRICE') or '0').replace(',', '').replace('$', '')
                        price = int(float(price_str)) if price_str else 0
                        sqft_str = (row.get('SQUARE FEET') or '0').replace(',', '')
                        sqft = int(float(sqft_str)) if sqft_str else 0
                        psf = round(price / sqft) if sqft > 0 else 0
                        if price > 0:
                            redfin_url = ''
                            for key in row.keys():
                                if key and 'URL' in key.upper():
                                    redfin_url = row[key] or ''
                                    break
                            raw_addr = (row.get('ADDRESS') or '').strip()
                            city = (row.get('CITY') or '').strip()
                            state = (row.get('STATE OR PROVINCE') or 'TX').strip()
                            zipcode = (row.get('ZIP OR POSTAL CODE') or '').strip()
                            zillow_query = f"{raw_addr} {city} {state} {zipcode}".replace(' ', '-')
                            comp_lat = float(row.get('LATITUDE') or 0)
                            comp_lon = float(row.get('LONGITUDE') or 0)
                            dist = 0
                            if comp_lat and comp_lon:
                                dist = ((comp_lat - lat) * 69) ** 2 + ((comp_lon - lon) * 60) ** 2
                                dist = dist ** 0.5
                            comps.append({
                                'address': f"{raw_addr}, {city}",
                                'price': price, 'sqft': sqft, 'psf': psf,
                                'year_built': int(float(row.get('YEAR BUILT') or 0)),
                                'beds': row.get('BEDS') or '',
                                'baths': row.get('BATHS') or '',
                                'days_on_market': row.get('DAYS ON MARKET') or '',
                                'redfin_url': redfin_url,
                                'zillow_url': f"https://www.zillow.com/homes/{zillow_query}_rb/",
                                'distance_mi': round(dist, 2),
                            })
                    except (ValueError, ZeroDivisionError):
                        continue
                # Filter to within radius if lat/lon provided
                if lat and lon:
                    comps = [c for c in comps if c.get('distance_mi', 99) <= radius_miles]
                return sorted(comps, key=lambda x: x.get('distance_mi', 99))
            except Exception:
                time.sleep(2)
                continue
        return []

    def get_rental_listings(self, zip_code: str, lat: float = 0, lon: float = 0, radius_miles: float = 2.0) -> list[dict]:
        """Get active rental listings in ZIP from Redfin, filtered by distance if lat/lon provided."""
        region_id = self._get_region_id(zip_code)
        if not region_id:
            return []
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        ]
        # Redfin rental CSV: status=1 (active), is_rentals=true
        url = (
            f'https://www.redfin.com/stingray/api/gis-csv?al=1&num_homes=200'
            f'&ord=redfin-recommended-asc&page_number=1'
            f'&region_id={region_id}&region_type=2'
            f'&status=1&uipt=1,2,3&v=8&is_rentals=true'
        )
        for ua in user_agents:
            try:
                headers = {'User-Agent': ua}
                resp = requests.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    time.sleep(2)
                    continue
                lines = resp.text.strip().split('\n')
                header_idx = None
                for i, line in enumerate(lines):
                    if line.startswith('SALE TYPE') or line.startswith('"SALE TYPE') or 'PRICE' in line.upper()[:50]:
                        header_idx = i
                        break
                if header_idx is None:
                    continue
                reader = csv.DictReader(io.StringIO('\n'.join(lines[header_idx:])))
                rentals = []
                for row in reader:
                    try:
                        # For rentals, PRICE is monthly rent
                        price_str = (row.get('PRICE') or row.get('PRICE/SQ.FT.') or '0').replace(',', '').replace('$', '').replace('/mo', '')
                        rent = int(float(price_str)) if price_str else 0
                        sqft_str = (row.get('SQUARE FEET') or '0').replace(',', '')
                        sqft = int(float(sqft_str)) if sqft_str else 0
                        rent_psf = round(rent / sqft, 2) if sqft > 0 else 0
                        if rent > 0:
                            redfin_url = ''
                            for key in row.keys():
                                if key and 'URL' in key.upper():
                                    redfin_url = row[key] or ''
                                    break
                            raw_addr = (row.get('ADDRESS') or '').strip()
                            city = (row.get('CITY') or '').strip()
                            comp_lat = float(row.get('LATITUDE') or 0)
                            comp_lon = float(row.get('LONGITUDE') or 0)
                            dist = 0
                            if comp_lat and comp_lon and lat and lon:
                                dist = ((comp_lat - lat) * 69) ** 2 + ((comp_lon - lon) * 60) ** 2
                                dist = dist ** 0.5
                            rentals.append({
                                'address': f"{raw_addr}, {city}",
                                'rent': rent, 'sqft': sqft, 'rent_psf': rent_psf,
                                'beds': row.get('BEDS') or '',
                                'baths': row.get('BATHS') or '',
                                'property_type': row.get('PROPERTY TYPE') or row.get('HOME TYPE') or '',
                                'redfin_url': redfin_url,
                                'distance_mi': round(dist, 2),
                            })
                    except (ValueError, ZeroDivisionError):
                        continue
                if lat and lon:
                    rentals = [r for r in rentals if r.get('distance_mi', 99) <= radius_miles]
                return sorted(rentals, key=lambda x: x.get('distance_mi', 99))
            except Exception:
                time.sleep(2)
                continue
        return []

    def check_listing_status(self, address: str, zip_code: str) -> dict:
        """Check if property is active, pending, or sold on Redfin."""
        region_id = self._get_region_id(zip_code)
        if not region_id:
            return {'status': 'Unknown', 'url': ''}
        user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        ]
        # Extract street number + name for matching
        addr_parts = address.upper().replace(',', '').split()
        addr_num = addr_parts[0] if addr_parts else ''
        addr_street = addr_parts[1] if len(addr_parts) > 1 else ''

        # Check: 1=Active, 130=Pending/Under Contract, 9=Sold
        for status_code, label in [(1, 'Active'), (130, 'Pending'), (9, 'Sold')]:
            for ua in user_agents:
                try:
                    url = (
                        f'https://www.redfin.com/stingray/api/gis-csv?al=1&num_homes=100'
                        f'&region_id={region_id}&region_type=2'
                        f'&status={status_code}&uipt=1&v=8'
                    )
                    headers = {'User-Agent': ua}
                    resp = requests.get(url, headers=headers, timeout=20)
                    if resp.status_code != 200:
                        continue
                    lines = resp.text.strip().split('\n')
                    for i, line in enumerate(lines):
                        if 'SALE TYPE' in line:
                            reader = csv.DictReader(io.StringIO('\n'.join(lines[i:])))
                            for row in reader:
                                row_addr = (row.get('ADDRESS') or '').upper()
                                if addr_num in row_addr and addr_street in row_addr:
                                    redfin_url = ''
                                    for key in row.keys():
                                        if key and 'URL' in key.upper():
                                            redfin_url = row[key] or ''
                                            break
                                    return {
                                        'status': label,
                                        'price': row.get('PRICE', ''),
                                        'url': redfin_url,
                                    }
                            break
                except Exception:
                    continue
        return {'status': 'Not Found', 'url': ''}
