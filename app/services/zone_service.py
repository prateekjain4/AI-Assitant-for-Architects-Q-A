import requests
import json
import os
from functools import lru_cache
from shapely.geometry import Point, shape

# ── Load GeoJSON polygons if available ────────────────────────────
ZONES = []
GEOJSON_PATH = "bangalore_zones.geojson"

if os.path.exists(GEOJSON_PATH):
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)
    ZONES = [
        {"shape": shape(feat["geometry"]), "properties": feat["properties"]}
        for feat in geojson["features"]
    ]

# ── BBMP administrative zone → BDA land use zone mapping ──────────
BBMP_TO_BDA_ZONE = {
    "YELAHANKA":       ("R",  "Residential Zone",       "North Bangalore — primarily residential"),
    "DASARAHALLI":     ("R",  "Residential Zone",       "West Bangalore — residential/industrial mix"),
    "RAJARAJESHWARI":  ("R",  "Residential Zone",       "West Bangalore — residential"),
    "BOMMANAHALLI":    ("RM", "Residential Mixed Zone", "South Bangalore — residential mixed"),
    "MAHADEVAPURA":    ("RM", "Residential Mixed Zone", "East Bangalore — IT corridor"),
    "EAST":            ("RM", "Residential Mixed Zone", "Central East — residential mixed"),
    "WEST":            ("R",  "Residential Zone",       "Central West — residential"),
    "SOUTH":           ("R",  "Residential Zone",       "South Bangalore — residential"),
    "BBMP":            ("R",  "Residential Zone",       "Bangalore — verify with BDA"),
}

# ── Ward-level overrides ───────────────────────────────────────────
WARD_ZONE_OVERRIDES = {
    "MG Road":           ("C3", "Commercial Zone C3"),
    "Shivajinagar":      ("C2", "Commercial Zone C2"),
    "Commercial Street": ("C3", "Commercial Zone C3"),
    "Brigade Road":      ("C3", "Commercial Zone C3"),
    "Whitefield":        ("IT", "IT / ITES Zone"),
    "Doddathoguru":      ("IT", "IT / ITES Zone"),
    "Marathahalli":      ("IT", "IT / ITES Zone"),
    "Bellandur":         ("IT", "IT / ITES Zone"),
    "Electronic City":   ("IT", "IT / ITES Zone"),
    "Koramangala":       ("RM", "Residential Mixed Zone"),
    "Indiranagar":       ("RM", "Residential Mixed Zone"),
    "Jayanagar":         ("R",  "Residential Zone"),
    "BTM Layout":        ("R",  "Residential Zone"),
    "HSR Layout":        ("R",  "Residential Zone"),
    "Malleshwaram":      ("R",  "Residential Zone"),
    "Rajajinagar":       ("R",  "Residential Zone"),
    "Basavanagudi":      ("R",  "Residential Zone"),
    "Banashankari":      ("R",  "Residential Zone"),
    "JP Nagar":          ("R",  "Residential Zone"),
    "Yelahanka":         ("R",  "Residential Zone"),
    "Hebbal":            ("RM", "Residential Mixed Zone"),
    "Nagawara":          ("RM", "Residential Mixed Zone"),
    "RT Nagar":          ("R",  "Residential Zone"),
    "Peenya":            ("I",  "Industrial Zone"),
    "Yeshwantpur":       ("RM", "Residential Mixed Zone"),
}


# ── Step 1: Raw API call (no cache) ───────────────────────────────
# Must be defined BEFORE _call_ksrsac_cached
def _call_ksrsac(lat: float, lng: float) -> dict:
    """
    Call KSRSAC K-GIS API with lat/lng in decimal degrees.
    Returns the full response dict or empty dict on failure.
    """
    try:
        url = (
            f"https://kgis.ksrsac.in:9000/genericwebservices/ws/"
            f"getlocationdetails?coordinates={lat},{lng}&type=dd"
        )
        res = requests.get(
            url,
            headers={"User-Agent": "BangaloreZoningTool/1.0"},
            timeout=6
        )
        data = res.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return {}
    except Exception as e:
        print(f"KSRSAC API error: {e}")
        return {}


# ── Step 2: Cached wrapper ────────────────────────────────────────
# Must be defined AFTER _call_ksrsac
@lru_cache(maxsize=512)
def _call_ksrsac_cached(lat_rounded: float, lng_rounded: float) -> str:
    """
    lru_cache requires hashable args and return types.
    Floats are hashable. Dict is not — so we return JSON string.
    """
    data = _call_ksrsac(lat_rounded, lng_rounded)
    return json.dumps(data)


# ── Step 3: Public wrapper ────────────────────────────────────────
def _get_ksrsac(lat: float, lng: float) -> dict:
    """
    Rounds coordinates to 3 decimal places (~111m grid),
    calls cache, returns dict.
    """
    lat_r = round(lat, 3)
    lng_r = round(lng, 3)
    cached_str = _call_ksrsac_cached(lat_r, lng_r)
    return json.loads(cached_str)


# ── Zone resolver ─────────────────────────────────────────────────
def _resolve_bda_zone(ksrsac_data: dict) -> tuple:
    """
    Map KSRSAC administrative zone + ward → BDA land use zone.
    Returns (zone_code, zone_name, match_type)
    """
    ward_name = ksrsac_data.get("wardName", "").strip()
    zone_name = ksrsac_data.get("zoneName", "").strip().upper()

    # Ward override — most specific, check first
    for ward_key, (code, name) in WARD_ZONE_OVERRIDES.items():
        if ward_key.lower() in ward_name.lower():
            return code, name, "ward_match"

    # BBMP zone fallback
    for bbmp_zone, (code, name, _) in BBMP_TO_BDA_ZONE.items():
        if bbmp_zone in zone_name:
            return code, name, "bbmp_zone"

    # Final fallback
    return "R", "Residential Zone", "default"


# ── Main detection function ───────────────────────────────────────
def detect_zone_from_coordinate(lat: float, lng: float) -> dict:
    """
    3-layer zone detection:
    1. Precise GeoJSON polygon
    2. KSRSAC K-GIS API (cached)
    3. Not found fallback
    """

    # ── Layer 1: GeoJSON polygon ───────────────────────────────────
    point = Point(lng, lat)
    for zone in ZONES:
        if zone["shape"].contains(point):
            p = zone["properties"]
            return {
                "found":      True,
                "source":     "geojson",
                "confidence": "precise",
                "zone_code":  p["zone_code"],
                "zone_name":  p["zone_name"],
                "locality":   p["locality"],
                "ward":       p["ward"],
            }

    # ── Layer 2: KSRSAC API (single cached call) ───────────────────
    try:
        ksrsac = _get_ksrsac(lat, lng)
    except Exception:
        ksrsac = {}

    if ksrsac.get("message") == "200":
        zone_code, zone_name, match_type = _resolve_bda_zone(ksrsac)
        return {
            "found":       True,
            "source":      "ksrsac",
            "confidence":  "approximate",
            "zone_code":   zone_code,
            "zone_name":   zone_name,
            "locality":    ksrsac.get("wardName",     ""),
            "ward":        ksrsac.get("zoneName",     ""),
            "ward_code":   ksrsac.get("wardCode",     ""),
            "district":    ksrsac.get("districtName", ""),
            "ksrsac_zone": ksrsac.get("zoneName",     ""),
            "ksrsac_ward": ksrsac.get("wardName",     ""),
            "match_type":  match_type,
        }

    # ── Layer 3: Not found ─────────────────────────────────────────
    return {
        "found":   False,
        "message": "Location not within Bangalore municipal limits or API unavailable."
    }