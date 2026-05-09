import requests

ARCGIS_BASE = "https://services.arcgis.com/0L95CJ0VTaxqcmED/ArcGIS/rest/services"

# Austin zoning density rules (approximate max units per lot)
ZONING_INFO = {
    "SF-1": {
        "desc": "Single Family Residence - Large Lot",
        "max_units": 1, "min_lot_sf": 10000,
        "plain": "Only one house allowed. Large lot (¼ acre+). Think suburban estate feel.",
        "can_build": "1 single-family home + 1 ADU (accessory dwelling unit, like a garage apartment)",
        "height": "35 ft (2-3 stories)",
    },
    "SF-2": {
        "desc": "Single Family Residence - Standard Lot",
        "max_units": 1, "min_lot_sf": 5750,
        "plain": "Typical Austin residential neighborhood. One house per lot, standard-sized yard.",
        "can_build": "1 single-family home + 1 ADU. Duplex NOT allowed unless you get a zoning change.",
        "height": "35 ft (2-3 stories)",
    },
    "SF-3": {
        "desc": "Single Family Residence - Standard Lot (more flexible)",
        "max_units": 1, "min_lot_sf": 5750,
        "plain": "Same as SF-2 but slightly more flexible. Most common residential zoning in Austin.",
        "can_build": "1 single-family home + 1 ADU. Duplexes allowed on corner lots in some cases.",
        "height": "35 ft (2-3 stories)",
    },
    "SF-4A": {
        "desc": "Single Family - Small Lot",
        "max_units": 1, "min_lot_sf": 3500,
        "plain": "Smaller lots, urban infill. Great for compact new construction.",
        "can_build": "1 single-family home + 1 ADU on a smaller lot",
        "height": "35 ft (2-3 stories)",
    },
    "SF-5": {
        "desc": "Single Family - Urban",
        "max_units": 1, "min_lot_sf": 2500,
        "plain": "Very small urban lots. Townhome-style development possible.",
        "can_build": "1 single-family home or townhome + 1 ADU",
        "height": "35 ft (2-3 stories)",
    },
    "SF-6": {
        "desc": "Townhouse / Condo",
        "max_units": 8, "min_lot_sf": 2500,
        "plain": "Allows multiple attached units (townhomes, condos). Good for small-scale development.",
        "can_build": "Up to 8 townhome/condo units depending on lot size",
        "height": "35 ft (2-3 stories)",
    },
    "MF-1": {
        "desc": "Multifamily - Low Density",
        "max_units": "18/acre", "min_lot_sf": 8000,
        "plain": "Small apartment buildings, duplexes, fourplexes. Residential feel but multiple units.",
        "can_build": "~18 units per acre. On a 7,000 sf lot ≈ 2-3 units.",
        "height": "40 ft (3 stories)",
    },
    "MF-2": {
        "desc": "Multifamily - Low-Medium Density",
        "max_units": "25/acre", "min_lot_sf": 8000,
        "plain": "Medium apartment buildings. Common along transit corridors.",
        "can_build": "~25 units per acre. On a 7,000 sf lot ≈ 4 units.",
        "height": "40 ft (3 stories)",
    },
    "MF-3": {
        "desc": "Multifamily - Medium Density",
        "max_units": "36/acre", "min_lot_sf": 8000,
        "plain": "Larger apartment complexes. Urban mixed-use areas.",
        "can_build": "~36 units per acre.",
        "height": "40 ft (3 stories)",
    },
    "MF-4": {
        "desc": "Multifamily - Moderate-High Density",
        "max_units": "54/acre", "min_lot_sf": 8000,
        "plain": "Dense apartment buildings. Downtown-adjacent areas.",
        "can_build": "~54 units per acre.",
        "height": "60 ft (5 stories)",
    },
    "MF-5": {
        "desc": "Multifamily - High Density",
        "max_units": "No max", "min_lot_sf": 8000,
        "plain": "High-rise apartments. No unit cap — limited by building size/FAR.",
        "can_build": "No unit maximum. Limited by floor-area ratio and height.",
        "height": "60 ft (5 stories)",
    },
    "MF-6": {
        "desc": "Multifamily - Highest Density",
        "max_units": "No max", "min_lot_sf": 10000,
        "plain": "Tallest residential buildings. Downtown high-rises.",
        "can_build": "No unit maximum. Tallest allowed residential.",
        "height": "No limit",
    },
}

# Plain-English overlay explanations
OVERLAY_EXPLANATIONS = {
    "-NP": (
        "🏘️ **Neighborhood Plan (NP)**",
        "This property is in a Neighborhood Plan area. The neighborhood has agreed to extra rules about "
        "what can be built — things like building height, setbacks, parking, and design standards. "
        "You may need to attend a neighborhood meeting before getting permits. "
        "Check the specific plan at [Austin Neighborhood Plans](https://www.austintexas.gov/department/neighborhood-plans)."
    ),
    "-CO": (
        "📋 **Conditional Overlay (CO)**",
        "This lot has special conditions attached by the City. These are specific rules that override "
        "the base zoning — for example, limiting hours of operation, requiring extra landscaping, or "
        "restricting certain uses. You MUST check the specific conditions with the City of Austin."
    ),
    "-H": (
        "🏛️ **Historic (H)**",
        "This property is in a historic district. Renovations and new construction must follow strict "
        "design guidelines to preserve neighborhood character. Demolition may be restricted or prohibited."
    ),
    "-V": (
        "🌿 **Vertical Mixed Use (V/VMU)**",
        "Allows ground-floor commercial with residential above. Great for mixed-use development. "
        "May get density bonuses if affordable housing is included."
    ),
}


def fetch_plot_info(lat: float, lon: float, address: str = ""):
    """Fetch zoning, parcel, and flood data from Austin ArcGIS."""
    plot_data = {}
    buf = 0.0003  # ~30 meters buffer for envelope queries

    # Extract address number for parcel matching
    addr_num = ""
    parts = address.split()
    if parts and parts[0].isdigit():
        addr_num = parts[0]

    # Zoning (use envelope/buffer since point can miss on parcel boundaries)
    try:
        url = f'{ARCGIS_BASE}/Current_Zoning_gdb/FeatureServer/0/query'
        buf = 0.0003  # ~30 meters buffer
        params = {
            'geometry': f'{lon-buf},{lat-buf},{lon+buf},{lat+buf}',
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': '4326', 'outFields': '*', 'f': 'json', 'returnGeometry': 'false',
        }
        r = requests.get(url, params=params, timeout=15)
        features = r.json().get('features', [])
        if features:
            attrs = features[0]['attributes']
            plot_data['zoning'] = {
                'zoning_type': attrs.get('ZONING_ZTYPE', ''),
                'base_zone': attrs.get('BASE_ZONE', ''),
                'zone_name': attrs.get('ZONE_NAME', ''),
                'lot_area_sf': round(attrs.get('SHAPE__Area', 0)),
            }
    except Exception:
        pass

    # TCAD Parcel (use envelope since point can miss on boundaries)
    try:
        url = f'{ARCGIS_BASE}/EXTERNAL_tcad_parcel/FeatureServer/0/query'
        params = {
            'geometry': f'{lon-buf},{lat-buf},{lon+buf},{lat+buf}',
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': '4326', 'outFields': '*', 'f': 'json', 'returnGeometry': 'false',
        }
        r = requests.get(url, params=params, timeout=15)
        features = r.json().get('features', [])
        if features:
            # Match by address number if multiple parcels returned
            best = features[0]
            if addr_num and len(features) > 1:
                for f in features:
                    situs = str(f['attributes'].get('SITUS', ''))
                    if situs == addr_num:
                        best = f
                        break
            attrs = best['attributes']
            plot_data['parcel'] = {
                'prop_id': attrs.get('PROP_ID', ''),
                'pid': attrs.get('PID_10', ''),
                'situs': attrs.get('SITUS', ''),
                'lot': attrs.get('LOTS', ''),
                'block': attrs.get('BLOCKS', ''),
                'parcel_area_sf': round(attrs.get('Shape__Area', 0)),
            }
    except Exception:
        pass

    # FEMA Flood (use envelope)
    try:
        url = f'{ARCGIS_BASE}/INLANDWATERS_greater_austin_fema_floodplain/FeatureServer/0/query'
        params = {
            'geometry': f'{lon-buf},{lat-buf},{lon+buf},{lat+buf}',
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': '4326', 'outFields': '*', 'f': 'json', 'returnGeometry': 'false',
        }
        r = requests.get(url, params=params, timeout=15)
        features = r.json().get('features', [])
        plot_data['flood'] = {
            'in_floodplain': len(features) > 0,
            'zone': features[0]['attributes'].get('FLD_ZONE', '') if features else 'None (X - Minimal Risk)',
        }
    except Exception:
        plot_data['flood'] = {'in_floodplain': False, 'zone': 'Unable to determine'}

    return plot_data
