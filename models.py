from dataclasses import dataclass, field


@dataclass
class Permit:
    address: str = ""
    description: str = ""
    sqft: float = 0
    issue_date: str = ""
    permit_class: str = ""
    work_class: str = ""
    builder: str = ""
    contractor_name: str = ""
    applicant_name: str = ""
    applicant_org: str = ""
    housing_units: int = 0
    floors: int = 0
    status: str = ""
    permit_number: str = ""
    permit_type: str = ""
    permit_type_desc: str = ""

@dataclass
class AnalysisResult:
    street_permits: list = field(default_factory=list)
    street_all_permits: list = field(default_factory=list)
    zip_permits: list = field(default_factory=list)
    redfin_comps: list = field(default_factory=list)
    neighborhood_comps: list = field(default_factory=list)
    active_comps: list = field(default_factory=list)
    rental_comps: list = field(default_factory=list)
    rental_stats: dict = field(default_factory=dict)
    market_stats: dict = field(default_factory=dict)
    neighborhood_stats: dict = field(default_factory=dict)
    active_stats: dict = field(default_factory=dict)
    sources_status: dict = field(default_factory=dict)
    listing_status: dict = field(default_factory=dict)
