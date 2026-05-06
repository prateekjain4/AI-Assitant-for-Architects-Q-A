#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""
fetch_osm_zones_hyderabad.py

Fetches Hyderabad land use polygons from OpenStreetMap and converts them
to the HMDA zone GeoJSON format for zone_service.py / Leaflet overlay.

Outputs:
  hyderabad_zones_osm_raw.geojson   — raw (review first)
  hyderabad_zones_merged.geojson    — ready to use

Usage:
  cd <project root>
  python city_rules/fetch_osm_zones_hyderabad.py

After review:
  copy hyderabad_zones_merged.geojson hyderabad_zones.geojson
  copy hyderabad_zones_merged.geojson <Angular>/public/assets/hyderabad_zones_display.geojson
"""

import json
import sys
import time
import requests
from shapely.geometry import shape
from shapely.validation import make_valid

# ── Hyderabad HMDA bounding box ────────────────────────────────────
# Covers HMDA jurisdiction: Hyderabad + Cyberabad + Secunderabad
BBOX = "17.20,78.25,17.65,78.65"

HEADERS = {"User-Agent": "BylawMonitor/1.0 (educational project; bylaw compliance tool)"}

OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# ── OSM tag → HMDA zone code mapping ──────────────────────────────
# HMDA uses zone codes similar to BDA but adapted for Hyderabad
OSM_TO_HMDA: dict[str, tuple[str, str]] = {
    "residential":       ("R1",  "Residential Zone R1"),
    "construction":      ("R1",  "Residential Zone R1"),
    "commercial":        ("C1",  "Commercial Zone C1"),
    "retail":            ("C1",  "Commercial Zone C1"),
    "mixed_use":         ("MX",  "Mixed Use Zone"),
    "marketplace":       ("C1",  "Commercial Zone C1"),
    "industrial":        ("I1",  "Industrial Zone I1"),
    "port":              ("I1",  "Industrial Zone I1"),
    "brownfield":        ("I1",  "Industrial Zone I1"),
    "quarry":            ("I1",  "Industrial Zone I1"),
    "railway":           ("T",   "Transportation Zone"),
    "garages":           ("T",   "Transportation Zone"),
    "depot":             ("T",   "Transportation Zone"),
    "parking":           ("T",   "Transportation Zone"),
    "aerodrome":         ("T",   "Transportation Zone"),
    "education":         ("PSP", "Public Semi-Public Zone"),
    "institutional":     ("PSP", "Public Semi-Public Zone"),
    "religious":         ("PSP", "Public Semi-Public Zone"),
    "civic":             ("PSP", "Public Semi-Public Zone"),
    "government":        ("PSP", "Public Semi-Public Zone"),
    "governmental":      ("PSP", "Public Semi-Public Zone"),
    "military":          ("PSP", "Public Semi-Public Zone"),
    "cemetery":          ("PSP", "Public Semi-Public Zone"),
    "cementry":          ("PSP", "Public Semi-Public Zone"),  # OSM typo in Hyd data
    "hospital":          ("PSP", "Public Semi-Public Zone"),
    "school":            ("PSP", "Public Semi-Public Zone"),
    "college":           ("PSP", "Public Semi-Public Zone"),
    "university":        ("PSP", "Public Semi-Public Zone"),
    "place_of_worship":  ("PSP", "Public Semi-Public Zone"),
    "stadium":           ("PSP", "Public Semi-Public Zone"),
    "sports_centre":     ("PSP", "Public Semi-Public Zone"),
    "police":            ("PSP", "Public Semi-Public Zone"),
    "research_institute": ("PSP", "Public Semi-Public Zone"),
    "community_centre":  ("PSP", "Public Semi-Public Zone"),
    "library":           ("PSP", "Public Semi-Public Zone"),
    "recreation_ground": ("P",   "Parks & Open Space"),
    "village_green":     ("P",   "Parks & Open Space"),
    "grass":             ("P",   "Parks & Open Space"),
    "park":              ("P",   "Parks & Open Space"),
    "garden":            ("P",   "Parks & Open Space"),
    "pitch":             ("P",   "Parks & Open Space"),
    "forest":            ("GB",  "Green Belt"),
    "nature_reserve":    ("GB",  "Green Belt"),
    "basin":             ("GB",  "Green Belt"),
    "reservoir":         ("GB",  "Green Belt"),
    "aquaculture":       ("GB",  "Green Belt"),
    "meadow":            ("AG",  "Agricultural Zone"),
    "farmland":          ("AG",  "Agricultural Zone"),
    "farmyard":          ("AG",  "Agricultural Zone"),
    "farm":              ("AG",  "Agricultural Zone"),
    "allotments":        ("AG",  "Agricultural Zone"),
    "orchard":           ("AG",  "Agricultural Zone"),
    "plant_nursery":     ("AG",  "Agricultural Zone"),
    "greenfield":        ("AG",  "Agricultural Zone"),
    "landfill":          ("I1",  "Industrial Zone I1"),
}

# IT zone detection by name (HITEC City, Madhapur, Gachibowli map as commercial in OSM)
IT_KEYWORDS = [
    "hitec city", "hitech city", "madhapur", "gachibowli",
    "nanakramguda", "kondapur", "raidurgam", "financial district",
    "cyberabad", "it park", "tech park", "ites", "software",
    "infosys", "wipro", "tcs campus", "microsoft", "google",
    "amazon", "dlo it", "incor", "mindspace",
]

MIN_AREA_SQM = 2_000
SIMPLIFY_TOLERANCE = 0.00008  # ~8m


# ── Overpass ────────────────────────────────────────────────────────

def fetch_overpass(bbox: str) -> dict:
    query = f"""
[out:json][timeout:120];
(
  way["landuse"]({bbox});
  relation["landuse"]({bbox});
  way["leisure"~"^(park|garden|nature_reserve|pitch|stadium|sports_centre)$"]({bbox});
  relation["leisure"~"^(park|garden|nature_reserve)$"]({bbox});
  way["amenity"~"^(university|school|college|hospital|place_of_worship|parking)$"]({bbox});
  relation["amenity"~"^(university|school|college|hospital)$"]({bbox});
);
out geom;
"""
    for url in OVERPASS_URLS:
        for attempt in range(1, 4):
            try:
                print(f"  Querying {url} (attempt {attempt})...")
                r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=150)
                if r.status_code == 429:
                    time.sleep(30 * attempt)
                    continue
                r.raise_for_status()
                data = r.json()
                print(f"  Got {len(data.get('elements', []))} elements.")
                return data
            except Exception as exc:
                print(f"  Error: {exc}")
                time.sleep(10)
    raise RuntimeError("All Overpass attempts failed.")


# ── Classification ──────────────────────────────────────────────────

def classify_zone(tags: dict) -> tuple[str, str] | None:
    name_lower = " ".join([
        tags.get("name", ""),
        tags.get("addr:suburb", ""),
        tags.get("operator", ""),
    ]).lower()

    if any(kw in name_lower for kw in IT_KEYWORDS):
        return "IT", "IT / ITES Zone"

    for tag_key in ("landuse", "leisure", "amenity"):
        val = tags.get(tag_key, "")
        if val in OSM_TO_HMDA:
            return OSM_TO_HMDA[val]

    return None


# ── Geometry (reuse same logic as Bangalore script) ─────────────────

def way_to_ring(element: dict) -> list | None:
    pts = element.get("geometry", [])
    if len(pts) < 4:
        return None
    coords = [[p["lon"], p["lat"]] for p in pts]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def relation_to_geojson_geometry(element: dict) -> dict | None:
    outer, inner = [], []
    for member in element.get("members", []):
        if member.get("type") != "way":
            continue
        pts = member.get("geometry", [])
        if len(pts) < 4:
            continue
        coords = [[p["lon"], p["lat"]] for p in pts]
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        if member.get("role", "outer") == "inner":
            inner.append(coords)
        else:
            outer.append(coords)
    if not outer:
        return None
    if len(outer) == 1:
        return {"type": "Polygon", "coordinates": [outer[0]] + inner}
    return {"type": "MultiPolygon", "coordinates": [[[ring]] for ring in outer]}


def approx_area_sqm(geometry: dict) -> float:
    try:
        return shape(geometry).area * (111_200 * 108_200)
    except Exception:
        return 0.0


def extract_locality_ward(tags: dict) -> tuple[str, str]:
    locality = (tags.get("name") or tags.get("addr:suburb") or "").strip()
    ward = (tags.get("addr:suburb") or tags.get("is_in:ward") or "Hyderabad").strip()
    return locality, ward


def make_zone_id(zone_code: str, locality: str, idx: int) -> str:
    abbr = "".join(w[:3].upper() for w in locality.split()[:2]) if locality else "OSM"
    return f"HYD-{zone_code}-{abbr}-{idx:04d}"


# ── Convert elements ────────────────────────────────────────────────

def convert_elements(elements: list) -> list:
    features = []
    skipped = {"no_zone": 0, "tiny": 0, "no_geom": 0}
    idx = 1

    for elem in elements:
        tags = elem.get("tags", {})
        etype = elem["type"]

        zone = classify_zone(tags)
        if zone is None:
            skipped["no_zone"] += 1
            continue

        zone_code, zone_name = zone

        if etype == "way":
            ring = way_to_ring(elem)
            if not ring:
                skipped["no_geom"] += 1
                continue
            geometry = {"type": "Polygon", "coordinates": [ring]}
        elif etype == "relation":
            geometry = relation_to_geojson_geometry(elem)
            if not geometry:
                skipped["no_geom"] += 1
                continue
        else:
            continue

        if approx_area_sqm(geometry) < MIN_AREA_SQM:
            skipped["tiny"] += 1
            continue

        locality, ward = extract_locality_ward(tags)
        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "zone_id":           make_zone_id(zone_code, locality or ward, idx),
                "zone_code":         zone_code,
                "zone_name":         zone_name,
                "locality":          locality,
                "ward":              ward,
                "planning_district": "",
                "area_sqm":          round(approx_area_sqm(geometry)),
                "osm_id":            f"{etype}/{elem['id']}",
                "osm_tag":           tags.get("landuse") or tags.get("leisure") or tags.get("amenity", ""),
                "source":            "osm",
            },
        })
        idx += 1

    print(f"  Converted: {len(features)}  |  skipped zone:{skipped['no_zone']}  tiny:{skipped['tiny']}  geom:{skipped['no_geom']}")
    return features


# ── Build display GeoJSON (simplified, for Leaflet overlay) ─────────

def build_display_geojson(features: list) -> list:
    out = []
    KEEP = {"zone_id", "zone_code", "zone_name", "locality", "ward"}

    def round_coords(obj):
        if isinstance(obj, (int, float)):
            return round(obj, 5)
        if isinstance(obj, list):
            return [round_coords(x) for x in obj]
        return obj

    for feat in features:
        area = feat["properties"].get("area_sqm", 0)
        if area < 5_000:
            continue
        try:
            s = make_valid(shape(feat["geometry"]))
            s = s.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)
            if s.is_empty:
                continue
            from shapely.geometry import mapping
            geom = mapping(s)
            geom["coordinates"] = round_coords(geom["coordinates"])
        except Exception:
            continue

        out.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {k: v for k, v in feat["properties"].items() if k in KEEP},
        })
    return out


def save(path: str, features: list, compact: bool = False) -> None:
    sep = (",", ":") if compact else (", ", ": ")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f,
                  separators=sep if compact else None,
                  indent=None if compact else 2)
    import os
    size_mb = os.path.getsize(path) / 1024 / 1024
    print(f"  Saved -> {path}  ({len(features)} features, {size_mb:.1f} MB)")


# ── Main ────────────────────────────────────────────────────────────

def main() -> None:
    RAW     = "hyderabad_zones_osm_raw.geojson"
    DISPLAY = "hyderabad_zones_display.geojson"

    print("=" * 60)
    print("Step 1: Fetching Hyderabad OSM land use data")
    print("=" * 60)
    osm_data = fetch_overpass(BBOX)

    print("\n" + "=" * 60)
    print("Step 2: Converting to HMDA zone features")
    print("=" * 60)
    features = convert_elements(osm_data.get("elements", []))

    print("\n" + "=" * 60)
    print(f"Step 3: Saving full output -> {RAW}")
    print("=" * 60)
    save(RAW, features)

    print("\n" + "=" * 60)
    print(f"Step 4: Building simplified display GeoJSON -> {DISPLAY}")
    print("=" * 60)
    display_features = build_display_geojson(features)
    save(DISPLAY, display_features, compact=True)

    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)
    print(f"""
Next steps:
  1. Review {RAW} in geojson.io
  2. Copy display file to Angular assets:
       copy {DISPLAY} <Angular>/public/assets/hyderabad_zones_display.geojson
  3. Add zone overlay to hyderabad-planning.ts initMap() (same pattern as bengaluru-planning.ts)
  4. Add getZoneStyle() with HMDA zone codes (R1, C1, I1, IT, PSP, P, GB, AG)
""")


if __name__ == "__main__":
    main()