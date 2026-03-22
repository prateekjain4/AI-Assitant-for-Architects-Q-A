import json
from shapely.geometry import Point, shape

# Load GeoJSON once at startup — fast for all requests
with open("bangalore_zones.geojson") as f:
    _geojson = json.load(f)

ZONES = [
    {
        "shape": shape(feature["geometry"]),
        "properties": feature["properties"]
    }
    for feature in _geojson["features"]
]

def detect_zone_from_coordinate(lat: float, lng: float):
    """
    Returns zone_code, zone_name, locality, ward for a given coordinate.
    Returns None if coordinate falls outside all mapped zones.
    """
    point = Point(lng, lat)  # Shapely uses (x=lng, y=lat)

    for zone in ZONES:
        if zone["shape"].contains(point):
            p = zone["properties"]
            return {
                "found": True,
                "zone_id":   p["zone_id"],
                "zone_code": p["zone_code"],
                "zone_name": p["zone_name"],
                "locality":  p["locality"],
                "ward":      p["ward"]
            }

    return {"found": False, "zone_code": None}