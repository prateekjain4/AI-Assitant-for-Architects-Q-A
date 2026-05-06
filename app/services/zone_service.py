import requests
import json
import os
from functools import lru_cache
from shapely.geometry import Point, shape

# ── Load BDA zone GeoJSON polygons ────────────────────────────────
ZONES = []
GEOJSON_PATH = "bangalore_zones.geojson"

if os.path.exists(GEOJSON_PATH):
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)
    ZONES = [
        {"shape": shape(feat["geometry"]), "properties": feat["properties"]}
        for feat in geojson["features"]
    ]

# ── Load BBMP ward GeoJSON polygons ───────────────────────────────
BBMP_WARDS: list[dict] = []
BBMP_WARDS_PATH = "bbmp_wards.geojson"

if os.path.exists(BBMP_WARDS_PATH):
    with open(BBMP_WARDS_PATH) as f:
        _bbmp_gj = json.load(f)
    BBMP_WARDS = [
        {"shape": shape(feat["geometry"]), "properties": feat["properties"]}
        for feat in _bbmp_gj["features"]
    ]

# ── Load Bengaluru ORR polygon (BDA Zone A / Zone B boundary) ─────
_ORR_POLYGON = None
_ORR_PATH = "bengaluru_orr.geojson"

if os.path.exists(_ORR_PATH):
    with open(_ORR_PATH) as f:
        _orr_gj = json.load(f)
    _ORR_POLYGON = shape(_orr_gj["features"][0]["geometry"])


def _detect_planning_zone(lat: float, lng: float) -> str:
    """Return 'zone_A' if inside Bengaluru ORR, else 'zone_B' (BDA RMP 2031)."""
    if _ORR_POLYGON is None:
        return "zone_A"          # safe default when GeoJSON not loaded
    return "zone_A" if _ORR_POLYGON.contains(Point(lng, lat)) else "zone_B"

# ── BBMP zone by ward number (approximate, 8 zones) ───────────────
# Ranges based on geographic clustering; some wards near zone borders
# may be one zone off — ward name (from GIS) is always precise.
_BBMP_ZONE_RANGES: list[tuple[range, str, str]] = [
    (range(1,   28), "Yelahanka Zone",    "BBMP Yelahanka Zone Office, New BEL Road, Yelahanka, Bengaluru 560064"),
    (range(28,  56), "Dasarahalli Zone",  "BBMP Dasarahalli Zone Office, Peenya Industrial Estate, Bengaluru 560058"),
    (range(56,  80), "West Zone",         "BBMP West Zone Office, Rajajinagar, Bengaluru 560010"),
    (range(80,  120),"Mahadevapura Zone", "BBMP Mahadevapura Zone Office, ITPL Main Road, Bengaluru 560048"),
    (range(120, 156),"East Zone",         "BBMP East Zone Office, Domlur, Bengaluru 560071"),
    (range(156, 200),"South Zone",        "BBMP South Zone Office, BSK II Stage, Bengaluru 560070"),
    (range(200, 226),"RR Nagar Zone",     "BBMP RR Nagar Zone Office, Rajarajeshwari Nagar, Bengaluru 560098"),
    (range(226, 244),"Bommanahalli Zone", "BBMP Bommanahalli Zone Office, Hongasandra, Bengaluru 560068"),
]
_WARD_BBMP_ZONE: dict[int, tuple[str, str]] = {}
for _rng, _zone, _office in _BBMP_ZONE_RANGES:
    for _w in _rng:
        _WARD_BBMP_ZONE[_w] = (_zone, _office)


def _lookup_bbmp_ward(lat: float, lng: float) -> dict:
    """Point-in-polygon lookup against BBMP ward boundaries."""
    if not BBMP_WARDS:
        return {}
    point = Point(lng, lat)
    for ward in BBMP_WARDS:
        if ward["shape"].contains(point):
            p = ward["properties"]
            ward_no = int(p.get("KGISWardNo", 0))
            zone, office = _WARD_BBMP_ZONE.get(ward_no, ("BBMP", "BBMP Head Office, N R Square, Bengaluru 560002"))
            return {
                "in_bbmp":         True,
                "bbmp_ward_name":  p.get("KGISWardName", ""),
                "bbmp_ward_no":    str(ward_no),
                "bbmp_zone":       zone,
                "bbmp_zone_office": office,
            }
    return {"in_bbmp": False}

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
    3-layer BDA zone detection + BBMP ward overlay:
    1. Precise GeoJSON polygon (BDA zones)
    2. KSRSAC K-GIS API (cached)
    3. Not found fallback
    BBMP ward detection runs in parallel and is merged into every response.
    """
    bbmp          = _lookup_bbmp_ward(lat, lng)
    planning_zone = _detect_planning_zone(lat, lng)

    # ── Layer 1: GeoJSON polygon ───────────────────────────────────
    point = Point(lng, lat)
    for zone in ZONES:
        if zone["shape"].contains(point):
            p = zone["properties"]
            return {
                "found":         True,
                "source":        "geojson",
                "confidence":    "precise",
                "zone_code":     p["zone_code"],
                "zone_name":     p["zone_name"],
                "locality":      p["locality"],
                "ward":          p["ward"],
                "planning_zone": planning_zone,
                **bbmp,
            }

    # ── Layer 2: KSRSAC API (single cached call) ───────────────────
    try:
        ksrsac = _get_ksrsac(lat, lng)
    except Exception:
        ksrsac = {}

    if ksrsac.get("message") == "200":
        zone_code, zone_name, match_type = _resolve_bda_zone(ksrsac)
        return {
            "found":         True,
            "source":        "ksrsac",
            "confidence":    "approximate",
            "zone_code":     zone_code,
            "zone_name":     zone_name,
            "locality":      ksrsac.get("wardName",     ""),
            "ward":          ksrsac.get("zoneName",     ""),
            "ward_code":     ksrsac.get("wardCode",     ""),
            "district":      ksrsac.get("districtName", ""),
            "ksrsac_zone":   ksrsac.get("zoneName",     ""),
            "ksrsac_ward":   ksrsac.get("wardName",     ""),
            "match_type":    match_type,
            "planning_zone": planning_zone,
            **bbmp,
        }

    # ── Layer 3: Not found (still return BBMP ward if available) ───
    if bbmp.get("in_bbmp"):
        return {
            "found":         True,
            "source":        "bbmp_ward_only",
            "confidence":    "approximate",
            "zone_code":     "R",
            "zone_name":     "Residential Zone (default — verify BDA zone manually)",
            "locality":      bbmp.get("bbmp_ward_name", ""),
            "ward":          bbmp.get("bbmp_zone", ""),
            "planning_zone": planning_zone,
            **bbmp,
        }

    return {
        "found":   False,
        "message": "Location not within Bangalore municipal limits or API unavailable."
    }