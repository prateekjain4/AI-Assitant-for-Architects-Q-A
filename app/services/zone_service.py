# zone_service.py — Nominatim-based city-wide zone detection

import requests
import json
import os
from shapely.geometry import Point, shape

# ── Layer 1: precise GeoJSON polygons (load if file exists) ──────
ZONES = []
GEOJSON_PATH = "bangalore_zones.geojson"

if os.path.exists(GEOJSON_PATH):
    with open(GEOJSON_PATH) as f:
        geojson = json.load(f)
    ZONES = [
        {"shape": shape(feat["geometry"]), "properties": feat["properties"]}
        for feat in geojson["features"]
    ]

# ── Layer 2: ward → zone lookup (covers all of Bangalore) ────────
WARD_ZONE_MAP = {
    # Central
    "MG Road":               ("C3", "Commercial Zone C3"),
    "Brigade Road":          ("C3", "Commercial Zone C3"),
    "Commercial Street":     ("C3", "Commercial Zone C3"),
    "Shivajinagar":          ("C2", "Commercial Zone C2"),
    "Frazer Town":           ("RM", "Residential Mixed Zone"),
    "Richmond Town":         ("RM", "Residential Mixed Zone"),
    "Langford Town":         ("R",  "Residential Zone"),
    "Shanthinagar":          ("RM", "Residential Mixed Zone"),

    # South
    "Koramangala":           ("RM", "Residential Mixed Zone"),
    "Indiranagar":           ("RM", "Residential Mixed Zone"),
    "HSR Layout":            ("R",  "Residential Zone"),
    "BTM Layout":            ("R",  "Residential Zone"),
    "Jayanagar":             ("R",  "Residential Zone"),
    "JP Nagar":              ("R",  "Residential Zone"),
    "Banashankari":          ("R",  "Residential Zone"),
    "Basavanagudi":          ("R",  "Residential Zone"),
    "Lakkasandra":           ("R",  "Residential Zone"),
    "Madivala":              ("RM", "Residential Mixed Zone"),
    "Bommanahalli":          ("RM", "Residential Mixed Zone"),
    "Electronic City":       ("IT", "IT / ITES Zone"),
    "Doddathoguru":          ("IT", "IT / ITES Zone"),

    # East
    "Whitefield":            ("IT", "IT / ITES Zone"),
    "Marathahalli":          ("RM", "Residential Mixed Zone"),
    "KR Puram":              ("RM", "Residential Mixed Zone"),
    "Hoodi":                 ("RM", "Residential Mixed Zone"),
    "Doddanekkundi":         ("RM", "Residential Mixed Zone"),
    "Banaswadi":             ("R",  "Residential Zone"),
    "Horamavu":              ("R",  "Residential Zone"),

    # North
    "Hebbal":                ("RM", "Residential Mixed Zone"),
    "Yelahanka":             ("R",  "Residential Zone"),
    "RT Nagar":              ("R",  "Residential Zone"),
    "Thanisandra":           ("R",  "Residential Zone"),
    "Nagawara":              ("RM", "Residential Mixed Zone"),
    "Kogilu":                ("R",  "Residential Zone"),

    # West
    "Malleshwaram":          ("R",  "Residential Zone"),
    "Rajajinagar":           ("R",  "Residential Zone"),
    "Yeshwantpur":           ("RM", "Residential Mixed Zone"),
    "Peenya":                ("I",  "Industrial Zone"),
    "Nagarbhavi":            ("R",  "Residential Zone"),
    "Kengeri":               ("R",  "Residential Zone"),
    "Uttarahalli":           ("R",  "Residential Zone"),
    "Herohalli":             ("I",  "Industrial Zone"),

    # Outer ring / peripheral
    "Sarjapur":              ("R",  "Residential Zone"),
    "Bellandur":             ("RM", "Residential Mixed Zone"),
    "Varthur":               ("RM", "Residential Mixed Zone"),
    "Kadugodi":              ("R",  "Residential Zone"),
    "Begur":                 ("R",  "Residential Zone"),
    "Gottigere":             ("R",  "Residential Zone"),
    "Hulimavu":              ("R",  "Residential Zone"),
    "Bannerghatta":          ("PSP","Public / Semi-Public Zone"),
}

def _reverse_geocode(lat: float, lng: float) -> dict:
    """Call Nominatim to get address components for a coordinate."""
    try:
        url = (
            f"https://nominatim.openstreetmap.org/reverse"
            f"?lat={lat}&lon={lng}&format=json&addressdetails=1"
        )
        res = requests.get(url, headers={"User-Agent": "BangaloreZoningTool/1.0"}, timeout=5)
        return res.json().get("address", {})
    except Exception:
        return {}

def get_land_use_from_osm(lat, lng):
    try:
        query = f"""
        [out:json];
        way(around:50,{lat},{lng})["landuse"];
        out tags;
        """

        response = requests.get(
            "https://overpass-api.de/api/interpreter",
            params={"data": query},
            timeout=5
        )

        data = response.json()

        if data.get("elements"):
            for el in data["elements"]:
                tags = el.get("tags", {})
                if "landuse" in tags:
                    return tags["landuse"]

        return None

    except Exception as e:
        print("OSM Error:", e)
        return None

def map_landuse_to_zone(landuse):

    mapping = {
        "residential": "R",
        "commercial": "C1",
        "industrial": "Industrial",
        "retail": "C1",
        "construction": "R",
        "mixed": "RM"
    }

    return mapping.get(landuse, None)

def _lookup_ward(address: dict) -> tuple:
    """Try each address field against the ward map, most specific first."""
    fields = [
        address.get("suburb"),
        address.get("neighbourhood"),
        address.get("quarter"),
        address.get("city_district"),
        address.get("county"),
    ]
    for field in fields:
        if not field:
            continue
        # exact match
        if field in WARD_ZONE_MAP:
            return field, *WARD_ZONE_MAP[field]
        # partial match — e.g. "Koramangala 5th Block" → "Koramangala"
        for ward, (code, name) in WARD_ZONE_MAP.items():
            if ward.lower() in field.lower():
                return field, code, name
    return None, None, None

def detect_zone_from_coordinate(lat: float, lng: float) -> dict:
    point = Point(lng, lat)

    # ── Layer 1: precise GeoJSON polygon check ────────────────────
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
        
    # ---------------------------
    # 2. OSM LANDUSE (NEW)
    # ---------------------------
    landuse = get_land_use_from_osm(lat, lng)

    if landuse:
        zone = map_landuse_to_zone(landuse)
        if zone:
            return {
                "found": True,
                "source": "osm",
                "confidence": "medium",
                "zone_code": zone,
                "zone_name": f"Derived from OSM ({landuse})",
                "locality": "",
                "ward": ""
            }
        
    # ---------------------------
    # 3. NOMINATIM (LAST)
    # ---------------------------
    address = _reverse_geocode(lat, lng)
    locality, zone_code, zone_name = _lookup_ward(address)

    if zone_code:
        return {
            "found":      True,
            "source":     "ward_lookup",
            "confidence": "approximate",
            "zone_code":  zone_code,
            "zone_name":  zone_name,
            "locality":   locality,
            "ward":       locality,
        }

    return {"found": False, "message": "Location not recognised. Please enter zone manually."}