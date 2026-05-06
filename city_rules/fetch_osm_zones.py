#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
"""
fetch_osm_zones.py

Fetches Bangalore land use polygons from OpenStreetMap via Overpass API
and converts them to the BDA zone GeoJSON format used by zone_service.py.

Outputs:
  bangalore_zones_osm_raw.geojson   — raw converted OSM features (review first)
  bangalore_zones_merged.geojson    — OSM + existing, ready to replace bangalore_zones.geojson

Usage:
  cd <project root>
  python city_rules/fetch_osm_zones.py

After review:
  copy bangalore_zones_merged.geojson bangalore_zones.geojson
"""

import json
import sys
import time
import requests
from shapely.geometry import shape

# ── Bangalore BDA Local Planning Area bounding box ─────────────────
# south, west, north, east  (covers BDA LPA extent)
BBOX = "12.83,77.46,13.18,77.78"

# ── OSM tag value → (BDA zone code, zone name) ─────────────────────
# Covers landuse=*, leisure=*, amenity=* area tags
OSM_TO_BDA: dict[str, tuple[str, str]] = {
    # Residential
    "residential":       ("R",   "Residential Zone"),
    "construction":      ("R",   "Residential Zone"),  # typically upcoming residential
    # Commercial
    "commercial":        ("C2",  "Commercial Zone C2"),
    "retail":            ("C2",  "Commercial Zone C2"),
    "mixed_use":         ("RM",  "Residential Mixed Zone"),
    "marketplace":       ("C2",  "Commercial Zone C2"),
    # Industrial
    "industrial":        ("I",   "Industrial Zone"),
    "port":              ("I",   "Industrial Zone"),
    "brownfield":        ("I",   "Industrial Zone"),
    "quarry":            ("I",   "Industrial Zone"),
    # Transportation
    "railway":           ("T",   "Transportation Zone"),
    "garages":           ("T",   "Transportation Zone"),
    "depot":             ("T",   "Transportation Zone"),
    "parking":           ("T",   "Transportation Zone"),
    "aerodrome":         ("T",   "Transportation Zone"),
    # Public Semi-Public (PSP)
    "education":         ("PSP", "Public Semi-Public Zone"),
    "institutional":     ("PSP", "Public Semi-Public Zone"),
    "religious":         ("PSP", "Public Semi-Public Zone"),
    "civic":             ("PSP", "Public Semi-Public Zone"),
    "government":        ("PSP", "Public Semi-Public Zone"),
    "military":          ("PSP", "Public Semi-Public Zone"),
    "cemetery":          ("PSP", "Public Semi-Public Zone"),
    "hospital":          ("PSP", "Public Semi-Public Zone"),
    "school":            ("PSP", "Public Semi-Public Zone"),
    "college":           ("PSP", "Public Semi-Public Zone"),
    "university":        ("PSP", "Public Semi-Public Zone"),
    "place_of_worship":  ("PSP", "Public Semi-Public Zone"),
    "stadium":           ("PSP", "Public Semi-Public Zone"),
    "sports_centre":     ("PSP", "Public Semi-Public Zone"),
    # Parks & Open Space
    "recreation_ground": ("P",   "Parks & Open Space"),
    "village_green":     ("P",   "Parks & Open Space"),
    "grass":             ("P",   "Parks & Open Space"),
    "park":              ("P",   "Parks & Open Space"),
    "garden":            ("P",   "Parks & Open Space"),
    "pitch":             ("P",   "Parks & Open Space"),
    # Green Belt
    "forest":            ("GB",  "Green Belt"),
    "nature_reserve":    ("GB",  "Green Belt"),
    # Agricultural
    "meadow":            ("AG",  "Agricultural Zone"),
    "farmland":          ("AG",  "Agricultural Zone"),
    "farmyard":          ("AG",  "Agricultural Zone"),
    "allotments":        ("AG",  "Agricultural Zone"),
    "orchard":           ("AG",  "Agricultural Zone"),
}

# IT zone override — detected when feature name contains these keywords
# (OSM doesn't have an "IT" landuse tag; these areas are mapped commercial/mixed)
IT_KEYWORDS = [
    "whitefield", "electronic city", "electroniccity", "e-city",
    "marathahalli", "bellandur", "sarjapur", "doddathoguru",
    "bagmane", "manyata", "cessna", "salarpuria", "prestige tech",
    "it park", "tech park", "ites", "global village", "ecospace",
    "outer ring road it", "export promotion industrial park",
]

# Minimum polygon area to keep (sqm, approx).
# Filters noise like tiny road medians tagged landuse=grass.
MIN_AREA_SQM = 2_000

# Overpass endpoints — kumi mirror first (main instance blocks without User-Agent)
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

HEADERS = {"User-Agent": "BylawMonitor/1.0 (educational project; bylaw compliance tool)"}


# ── Overpass fetch ──────────────────────────────────────────────────

def _build_query(bbox: str) -> str:
    return f"""
[out:json][timeout:120];
(
  way["landuse"]({bbox});
  relation["landuse"]({bbox});
  way["leisure"~"^(park|garden|nature_reserve|pitch|stadium|sports_centre)$"]({bbox});
  relation["leisure"~"^(park|garden|nature_reserve)$"]({bbox});
  way["amenity"~"^(university|school|college|hospital|place_of_worship|parking|marketplace)$"]({bbox});
  relation["amenity"~"^(university|school|college|hospital|place_of_worship)$"]({bbox});
);
out geom;
"""


def fetch_overpass(bbox: str) -> dict:
    query = _build_query(bbox)
    last_err = None

    for url in OVERPASS_URLS:
        for attempt in range(1, 4):
            try:
                print(f"  Querying {url} (attempt {attempt})…")
                r = requests.post(url, data={"data": query}, headers=HEADERS, timeout=150)
                if r.status_code == 429:
                    wait = 30 * attempt
                    print(f"  Rate-limited. Waiting {wait}s…")
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                data = r.json()
                n = len(data.get("elements", []))
                print(f"  Got {n} elements.")
                return data
            except Exception as exc:
                last_err = exc
                print(f"  Error: {exc}. Retrying…")
                time.sleep(10)

    raise RuntimeError(f"All Overpass attempts failed. Last error: {last_err}")


# ── Zone classification ─────────────────────────────────────────────

def classify_zone(tags: dict) -> tuple[str, str] | None:
    """
    Returns (zone_code, zone_name) or None to skip this element.
    IT zone is detected by name keywords before tag lookup.
    """
    name_lower = " ".join([
        tags.get("name", ""),
        tags.get("addr:suburb", ""),
        tags.get("operator", ""),
    ]).lower()

    if any(kw in name_lower for kw in IT_KEYWORDS):
        return "IT", "IT / ITES Zone"

    for tag_key in ("landuse", "leisure", "amenity"):
        val = tags.get(tag_key, "")
        if val in OSM_TO_BDA:
            return OSM_TO_BDA[val]

    return None


# ── Geometry reconstruction ────────────────────────────────────────

def way_to_ring(element: dict) -> list | None:
    """Convert Overpass way with inline geometry to a closed coordinate ring."""
    pts = element.get("geometry", [])
    if len(pts) < 4:
        return None
    coords = [[p["lon"], p["lat"]] for p in pts]
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    return coords


def relation_to_geojson_geometry(element: dict) -> dict | None:
    """
    Reconstruct GeoJSON Polygon / MultiPolygon from an Overpass relation.
    Handles outer and inner (hole) rings.
    """
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
        # Single outer ring + holes → Polygon
        return {"type": "Polygon", "coordinates": [outer[0]] + inner}
    else:
        # Multiple outer rings → MultiPolygon (holes ignored for simplicity)
        return {"type": "MultiPolygon", "coordinates": [[[ring]] for ring in outer]}


def approx_area_sqm(geometry: dict) -> float:
    """
    Rough area in sqm using Shapely in geographic degrees.
    At Bangalore's latitude (13°N), 1° ≈ 111,200m lat / 108,200m lon.
    We use the geometric mean for a quick estimate — good enough for filtering.
    """
    try:
        s = shape(geometry)
        return s.area * (111_200 * 108_200)
    except Exception:
        return 0.0


# ── Name / locality extraction ─────────────────────────────────────

def extract_locality_ward(tags: dict) -> tuple[str, str]:
    locality = (
        tags.get("name") or
        tags.get("addr:suburb") or
        tags.get("addr:quarter") or
        ""
    ).strip()

    ward = (
        tags.get("addr:suburb") or
        tags.get("is_in:ward") or
        tags.get("addr:neighbourhood") or
        "Bengaluru"
    ).strip()

    return locality, ward


def make_zone_id(zone_code: str, locality: str, idx: int) -> str:
    abbr = "".join(w[:3].upper() for w in locality.split()[:2]) if locality else "OSM"
    return f"BLR-{zone_code}-{abbr}-{idx:04d}"


# ── Main conversion ────────────────────────────────────────────────

def osm_elements_to_features(elements: list) -> list:
    features = []
    skipped_no_zone = 0
    skipped_tiny = 0
    skipped_no_geom = 0
    idx = 1

    for elem in elements:
        tags = elem.get("tags", {})
        etype = elem["type"]

        # Classify zone
        zone = classify_zone(tags)
        if zone is None:
            skipped_no_zone += 1
            continue

        zone_code, zone_name = zone

        # Build geometry
        if etype == "way":
            ring = way_to_ring(elem)
            if not ring:
                skipped_no_geom += 1
                continue
            geometry = {"type": "Polygon", "coordinates": [ring]}
        elif etype == "relation":
            geometry = relation_to_geojson_geometry(elem)
            if not geometry:
                skipped_no_geom += 1
                continue
        else:
            continue

        # Filter tiny slivers
        area = approx_area_sqm(geometry)
        if area < MIN_AREA_SQM:
            skipped_tiny += 1
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
                "area_sqm":          round(area),
                "osm_id":            f"{etype}/{elem['id']}",
                "osm_tag":           (
                    tags.get("landuse") or
                    tags.get("leisure") or
                    tags.get("amenity", "")
                ),
                "source": "osm",
            },
        })
        idx += 1

    print(
        f"  Converted:      {len(features)} features\n"
        f"  Skipped (zone): {skipped_no_zone}\n"
        f"  Skipped (tiny): {skipped_tiny}\n"
        f"  Skipped (geom): {skipped_no_geom}"
    )
    return features


# ── Merge with existing GeoJSON ────────────────────────────────────

def merge_features(new_features: list, existing_features: list) -> list:
    """
    Existing (hand-curated) features take full priority.
    An OSM feature is dropped if it overlaps > 50% with any existing feature.
    """
    if not existing_features:
        return new_features

    existing_shapes = []
    for feat in existing_features:
        try:
            existing_shapes.append(shape(feat["geometry"]))
        except Exception:
            pass

    kept, dropped = [], 0

    for feat in new_features:
        try:
            s = shape(feat["geometry"])
        except Exception:
            continue

        overlaps = False
        for ex in existing_shapes:
            try:
                if s.intersects(ex):
                    intersection_area = s.intersection(ex).area
                    if intersection_area / max(s.area, 1e-12) > 0.5:
                        overlaps = True
                        break
            except Exception:
                pass

        if overlaps:
            dropped += 1
        else:
            kept.append(feat)

    merged = list(existing_features) + kept
    print(
        f"  Existing:  {len(existing_features)}\n"
        f"  OSM kept:  {len(kept)}\n"
        f"  OSM dropped (overlap): {dropped}\n"
        f"  Total:     {len(merged)}"
    )
    return merged


def load_geojson(path: str) -> list:
    try:
        with open(path) as f:
            return json.load(f).get("features", [])
    except FileNotFoundError:
        return []


def save_geojson(path: str, features: list) -> None:
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)
    print(f"  Saved -> {path}  ({len(features)} features)")


# ── Entry point ────────────────────────────────────────────────────

def main() -> None:
    import os

    # Paths relative to project root (run script from project root)
    EXISTING     = "bangalore_zones.geojson"
    RAW_OUTPUT   = "bangalore_zones_osm_raw.geojson"
    MERGED_OUTPUT = "bangalore_zones_merged.geojson"

    print("=" * 60)
    print("Step 1: Fetching OSM land use data")
    print("=" * 60)
    osm_data = fetch_overpass(BBOX)

    print("\n" + "=" * 60)
    print("Step 2: Converting OSM elements -> BDA zone features")
    print("=" * 60)
    new_features = osm_elements_to_features(osm_data.get("elements", []))

    print("\n" + "=" * 60)
    print(f"Step 3: Saving raw OSM output -> {RAW_OUTPUT}")
    print("=" * 60)
    save_geojson(RAW_OUTPUT, new_features)

    print("\n" + "=" * 60)
    print("Step 4: Merging with existing zones")
    print("=" * 60)
    existing = load_geojson(EXISTING)
    print(f"  Loaded {len(existing)} existing features from {EXISTING}")
    merged = merge_features(new_features, existing)

    print("\n" + "=" * 60)
    print(f"Step 5: Saving merged output -> {MERGED_OUTPUT}")
    print("=" * 60)
    save_geojson(MERGED_OUTPUT, merged)

    print("\n" + "=" * 60)
    print("Done.")
    print("=" * 60)
    print(f"""
Next steps:
  1. Open bangalore_zones_osm_raw.geojson in QGIS or geojson.io
     to spot-check OSM zone classifications look correct.

  2. If satisfied, replace the live file:
       copy bangalore_zones_merged.geojson bangalore_zones.geojson   (Windows)
       cp bangalore_zones_merged.geojson bangalore_zones.geojson     (Linux/Mac)

  3. Restart the FastAPI server — zone_service.py loads the file on startup.

  4. To improve accuracy, manually edit planning_district on key features
     using the 47 district names from BDA RMP 2015.
""")


if __name__ == "__main__":
    main()