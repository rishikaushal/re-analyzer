import requests
from datetime import datetime, timedelta
from models import Permit


class AustinPermits:
    BASE_URL = "https://data.austintexas.gov/resource/3syk-w9eu.json"

    def search_street(self, street_name: str, zip_code: str) -> list[Permit]:
        two_years_ago = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%dT00:00:00')
        where = f"permit_location like '%{street_name.upper()}%' AND permittype='BP' AND work_class='New' AND original_zip='{zip_code}' AND issue_date >= '{two_years_ago}'"
        params = {"$where": where, "$order": "issue_date DESC", "$limit": 100}
        for attempt in range(2):
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=20)
                if resp.status_code != 200:
                    continue
                return self._parse_permits(resp.json())
            except Exception:
                continue
        return []

    def search_street_all_types(self, street_name: str, zip_code: str) -> list[Permit]:
        """Search all permit types (building, electrical, plumbing, mechanical) for a street."""
        two_years_ago = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%dT00:00:00')
        where = f"permit_location like '%{street_name.upper()}%' AND original_zip='{zip_code}' AND issue_date >= '{two_years_ago}'"
        params = {"$where": where, "$order": "issue_date DESC", "$limit": 200}
        for attempt in range(2):
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=20)
                if resp.status_code != 200:
                    continue
                return self._parse_permits(resp.json())
            except Exception:
                continue
        return []

    def search_zip(self, zip_code: str, limit: int = 200) -> list[Permit]:
        two_years_ago = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%dT00:00:00')
        where = f"original_zip='{zip_code}' AND permittype='BP' AND work_class='New' AND issue_date >= '{two_years_ago}'"
        params = {"$where": where, "$order": "issue_date DESC", "$limit": limit}
        for attempt in range(2):
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=20)
                if resp.status_code != 200:
                    continue
                permits = self._parse_permits(resp.json())
                return [p for p in permits if 'Single Family' in p.permit_class
                        or 'Two Family' in p.permit_class
                        or 'Secondary' in p.permit_class]
            except Exception:
                continue
        return []

    def _parse_permits(self, data: list) -> list[Permit]:
        permits = []
        for r in data:
            issue_date = ""
            if r.get("issue_date"):
                try:
                    dt = datetime.fromisoformat(r["issue_date"].replace("T", " ").split(".")[0])
                    issue_date = dt.strftime("%Y-%m-%d")
                except Exception:
                    issue_date = str(r["issue_date"])[:10]
            permits.append(Permit(
                address=r.get("permit_location", ""),
                description=r.get("description", ""),
                sqft=float(r.get("total_new_add_sqft", 0) or 0),
                issue_date=issue_date,
                permit_class=r.get("permit_class", ""),
                work_class=r.get("work_class", ""),
                builder=r.get("contractor_company_name", "Unknown"),
                contractor_name=r.get("contractor_full_name", ""),
                applicant_name=r.get("applicant_full_name", ""),
                applicant_org=r.get("applicant_org", ""),
                housing_units=int(r.get("housing_units", 0) or 0),
                floors=int(r.get("number_of_floors", 0) or 0),
                status=r.get("status_current", ""),
                permit_number=r.get("permit_num", r.get("permitnumber", "")),
                permit_type=r.get("permittype", ""),
                permit_type_desc=r.get("permit_type_desc", ""),
            ))
        return permits
