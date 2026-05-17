import requests
from shapely.geometry import Point, Polygon, LineString
from pyproj import Transformer

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_WGS84_TO_UTM43N = Transformer.from_crs("EPSG:4326", "EPSG:32643", always_xy=True)


def _to_utm(lng: float, lat: float):
    return _WGS84_TO_UTM43N.transform(lng, lat)


def _extract_polygon(el: dict):
    """
    Extract a Shapely Polygon from an OSM way or relation element.
    Relations (multipolygons) store geometry in members with role='outer'.
    """
    el_type = el.get("type")

    if el_type == "way":
        nodes = el.get("geometry", [])
        coords = [_to_utm(n["lon"], n["lat"]) for n in nodes]
        if len(coords) < 3:
            return None
        poly = Polygon(coords)
        return poly.buffer(0) if not poly.is_valid else poly

    if el_type == "relation":
        outer_rings = []
        for member in el.get("members", []):
            if member.get("role") == "outer" and "geometry" in member:
                coords = [_to_utm(n["lon"], n["lat"]) for n in member["geometry"]]
                if len(coords) >= 3:
                    outer_rings.append(coords)
        if not outer_rings:
            return None
        # Use the largest outer ring (main lake boundary)
        coords = max(outer_rings, key=len)
        poly = Polygon(coords)
        return poly.buffer(0) if not poly.is_valid else poly

    return None


def _query_overpass_water(lat: float, lng: float, radius_m: int = 1500) -> list:
    # Use [out:json] with body+geom for relations so member geometry is included
    query = (
        f"[out:json][timeout:15];"
        f"("
        f"  way[\"natural\"=\"water\"](around:{radius_m},{lat},{lng});"
        f"  relation[\"natural\"=\"water\"](around:{radius_m},{lat},{lng});"
        f"  way[\"landuse\"=\"reservoir\"](around:{radius_m},{lat},{lng});"
        f"  relation[\"landuse\"=\"reservoir\"](around:{radius_m},{lat},{lng});"
        f");"
        f"out geom;"
    )
    for mirror in OVERPASS_MIRRORS:
        try:
            r = requests.post(mirror, data={"data": query}, timeout=15)
            if r.status_code == 200:
                return r.json().get("elements", [])
        except Exception:
            continue
    return []


def _query_overpass_waterways(lat: float, lng: float, radius_m: int = 500) -> list:
    query = (
        f"[out:json][timeout:12];"
        f"("
        f"  way[\"waterway\"=\"drain\"](around:{radius_m},{lat},{lng});"
        f"  way[\"waterway\"=\"canal\"](around:{radius_m},{lat},{lng});"
        f"  way[\"waterway\"=\"stream\"](around:{radius_m},{lat},{lng});"
        f");"
        f"out geom;"
    )
    for mirror in OVERPASS_MIRRORS:
        try:
            r = requests.post(mirror, data={"data": query}, timeout=12)
            if r.status_code == 200:
                return r.json().get("elements", [])
        except Exception:
            continue
    return []


def check_rajkaluve_proximity(lat: float, lng: float) -> dict:
    """
    Check proximity to BBMP Rajkaluves (storm water drains/channels).
    Buffer: 50m for primary (canals + named drains), 25m for secondary (unnamed drains/streams).
    Per BBMP Rajkaluve Protection By-laws and BDA RMP 2031.
    Rajkaluves are linear OSM ways — uses LineString distance, not Polygon.
    """
    plot_pt = Point(_to_utm(lng, lat))
    elements = _query_overpass_waterways(lat, lng, radius_m=500)

    candidates = []
    for el in elements:
        if el.get("type") != "way" or "geometry" not in el:
            continue
        try:
            coords = [_to_utm(n["lon"], n["lat"]) for n in el["geometry"]]
            if len(coords) < 2:
                continue
            line = LineString(coords)
            dist = round(plot_pt.distance(line), 1)
            tags = el.get("tags", {})
            wtype = tags.get("waterway", "drain")
            name = tags.get("name") or tags.get("name:en") or ""
            is_primary = (wtype == "canal") or (wtype == "drain" and bool(name))
            candidates.append({
                "name":       name or f"Unnamed {wtype}",
                "is_named":   bool(name),
                "waterway":   wtype,
                "is_primary": is_primary,
                "distance_m": dist,
            })
        except Exception:
            continue

    if not candidates:
        return {
            "checked": True,
            "drain_found": False,
            "message": "No storm water drains found within 500m",
        }

    candidates.sort(key=lambda c: c["distance_m"])
    primary = next((c for c in candidates if c["is_primary"]), None)
    nearest = candidates[0]
    drain = primary if (primary and primary["distance_m"] <= nearest["distance_m"] + 100) else nearest

    required_buffer = 50 if drain["is_primary"] else 25
    in_buffer = drain["distance_m"] < required_buffer

    result = {
        "checked":           True,
        "drain_found":       True,
        "nearest_drain":     drain["name"],
        "drain_type":        drain["waterway"],
        "is_primary":        drain["is_primary"],
        "distance_m":        drain["distance_m"],
        "required_buffer_m": required_buffer,
        "in_buffer_zone":    in_buffer,
        "warning": (
            f"Plot is within {required_buffer}m buffer zone of '{drain['name']}' "
            f"({'primary' if drain['is_primary'] else 'secondary'} Rajkaluve). "
            "BBMP approval may require drain setback compliance."
        ) if in_buffer else None,
        "regulation_ref": (
            "BBMP Rajkaluve Protection By-laws — "
            f"{'50m' if drain['is_primary'] else '25m'} buffer from "
            f"{'primary' if drain['is_primary'] else 'secondary'} storm water drain."
        ),
    }

    named_drains = [
        {"name": c["name"], "distance_m": c["distance_m"], "type": c["waterway"]}
        for c in candidates if c["is_named"]
    ]
    if named_drains:
        result["named_drains_nearby"] = named_drains

    return result


def check_water_body_proximity(lat: float, lng: float) -> dict:
    """
    Check if a coordinate is within the BBMP-mandated No-Development Zone of a water body.
    Buffer rules: 75m for lakes >10 acres (40,000 m²), 30m for all others.
    Per BBMP Water Bodies Conservation & Management By-laws 2020 + Karnataka HC WP 817/2008.

    Handles both OSM way and relation (multipolygon) elements so that large named lakes
    stored as relations (e.g. Ulsoor Lake) are detected correctly.
    Prefers named water bodies over unnamed ones when distances are comparable.
    """
    plot_pt = Point(_to_utm(lng, lat))
    elements = _query_overpass_water(lat, lng)

    candidates = []

    for el in elements:
        try:
            poly = _extract_polygon(el)
            if poly is None:
                continue
            tags = el.get("tags", {})
            name = tags.get("name") or tags.get("name:en") or ""
            dist = round(plot_pt.distance(poly), 1)
            candidates.append({
                "name":        name or "Unnamed water body",
                "is_named":    bool(name),
                "type":        tags.get("natural") or tags.get("landuse", "water"),
                "area_m2":     round(poly.area, 1),
                "distance_m":  dist,
                "in_water_body": dist < 0.5,
            })
        except Exception:
            continue

    if not candidates:
        return {
            "checked": True,
            "water_body_found": False,
            "message": "No water bodies found within 1500m",
        }

    # Sort by distance
    candidates.sort(key=lambda c: c["distance_m"])
    nearest = candidates[0]

    # Prefer a named water body if it's within 300m extra distance of the nearest
    named = next((c for c in candidates if c["is_named"]), None)
    if named and named["distance_m"] <= nearest["distance_m"] + 300:
        primary = named
    else:
        primary = nearest

    # BBMP/HC buffer: 75m for large lakes (>10 acres / 40,000 m²), 30m for others
    required_buffer = 75 if primary["area_m2"] >= 40_000 else 30
    in_buffer = primary["distance_m"] < required_buffer

    result = {
        "checked": True,
        "water_body_found": True,
        "in_water_body":        primary["in_water_body"],
        "nearest_water_body":   primary["name"],
        "water_body_type":      primary["type"],
        "water_body_area_m2":   primary["area_m2"],
        "distance_m":           primary["distance_m"],
        "required_buffer_m":    required_buffer,
        "in_buffer_zone":       in_buffer,
        "warning": (
            f"Plot is within {required_buffer}m buffer zone of '{primary['name']}'. "
            "Construction requires BBMP/NGT environmental clearance. "
            "Verify lake boundary with a licensed surveyor before proceeding."
        ) if in_buffer else None,
        "regulation_ref": (
            "BBMP Water Bodies Conservation & Management By-laws 2020 + "
            f"Karnataka HC WP 817/2008 — {required_buffer}m No-Development Zone."
        ),
    }

    # Surface all named lakes found within 1500m as additional context
    named_nearby = [
        {"name": c["name"], "distance_m": c["distance_m"], "area_acres": round(c["area_m2"] / 4047, 1)}
        for c in candidates if c["is_named"]
    ]
    if named_nearby:
        result["named_lakes_nearby"] = named_nearby

    return result