"""
ranchi_rules_engine.py
──────────────────────
Rules engine for Ranchi Municipal Corporation (RMC) Building Bye-Laws 2009.
Reads ranchi_rmc.json and exposes FAR, ground coverage, setbacks, and
fire/lift thresholds as clean functions.

Key differences from BDA Bengaluru:
  - FAR is zone-based only (no road-width matrix)
  - Three zones: district_and_commercial_centre (3.0), core_inner_zone (2.5), general_zone (2.0)
  - Height tiers: ≤12 m, 12–16 m, >16 m
  - Setbacks depend on BOTH plot depth (front/rear) AND plot width (sides)
  - Fire NOC required for buildings > 16 m OR ground coverage > 500 sqm
  - Lift mandatory above G+3
"""
import json
from pathlib import Path

_RULES_PATH = Path(__file__).parent.parent.parent / "city_rules" / "ranchi_rmc.json"
_rules: dict | None = None


def _load() -> dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            _rules = json.load(f)
    return _rules


# ── Zone normalisation ────────────────────────────────────────────────────────
_ZONE_ALIASES = {
    # canonical keys
    "district_and_commercial_centre": "district_and_commercial_centre",
    "core_inner_zone":                "core_inner_zone",
    "general_zone":                   "general_zone",
    # short aliases users might type
    "DC":      "district_and_commercial_centre",
    "DIST":    "district_and_commercial_centre",
    "COMM":    "district_and_commercial_centre",
    "CORE":    "core_inner_zone",
    "INNER":   "core_inner_zone",
    "GEN":     "general_zone",
    "GENERAL": "general_zone",
}


def normalise_zone(zone: str) -> str:
    key = zone.strip().upper()
    # Try full lower-case match first
    lower = zone.strip().lower()
    if lower in _ZONE_ALIASES:
        return _ZONE_ALIASES[lower]
    if key in _ZONE_ALIASES:
        return _ZONE_ALIASES[key]
    # Partial match
    for alias, canonical in _ZONE_ALIASES.items():
        if alias in key:
            return canonical
    return "general_zone"   # safe fallback


def zone_display_name(zone: str) -> str:
    return {
        "district_and_commercial_centre": "District & Commercial Centre",
        "core_inner_zone":                "Core / Inner Zone",
        "general_zone":                   "General Zone",
    }.get(zone, zone)


# ── FAR ───────────────────────────────────────────────────────────────────────
def get_far(zone: str, road_width_m: float = 9.0, plot_area_sqm: float = 0.0) -> dict:
    """
    Returns {"base": float, "tdr": 0.0, "total": float, "coverage_pct": int}.
    Ranchi FAR is uniform per zone (no road-width matrix).
    Road width still governs max HEIGHT (see height constraints).
    """
    rules = _load()
    canon = normalise_zone(zone)
    far_map = rules["far"]["zones"]
    entry   = far_map.get(canon, far_map["general_zone"])
    far_val = entry["far"]

    # Coverage: 60 % if plot ≤ 1000 sqm (height checked at planning time)
    cov = 60 if plot_area_sqm <= 1000 else 50

    return {
        "base":         far_val,
        "tdr":          0.0,
        "total":        far_val,
        "coverage_pct": cov,
        "zone_display": zone_display_name(canon),
    }


# ── Height constraints ────────────────────────────────────────────────────────
def max_height_for_road(road_width_m: float) -> float:
    """
    Section 21.2(a) — road-width-linked height cap.
    Road < 6 m  → max 12 m
    Road < 12 m → max 16 m
    Road ≥ 12 m → no statutory cap (FAR governs)
    """
    if road_width_m < 6.0:
        return 12.0
    if road_width_m < 12.0:
        return 16.0
    return 999.0


def max_height_for_plot_width(plot_width_m: float, usage: str = "residential") -> float:
    """Plot width ≤ 10 m restricts height to 11.4 m (res) or 12 m (comm)."""
    if plot_width_m <= 10.0:
        return 11.40 if usage == "residential" else 12.0
    return 999.0


# ── Height-tier key ───────────────────────────────────────────────────────────
def _ht_tier(h: float) -> str:
    if h <= 12.0:  return "ht_upto_12m"
    if h <= 16.0:  return "ht_12_to_16m"
    return          "ht_above_16m"


# ── Depth-bracket key ────────────────────────────────────────────────────────
def _depth_key(depth_m: float) -> str:
    if depth_m <= 10:  return "upto_10m"
    if depth_m <= 15:  return "10_to_15m"
    if depth_m <= 21:  return "15_to_21m"
    if depth_m <= 27:  return "21_to_27m"
    if depth_m <= 33:  return "27_to_33m"
    if depth_m <= 39:  return "33_to_39m"
    if depth_m <= 45:  return "39_to_45m"
    return "above_45m"


def _width_key(width_m: float) -> str:
    if width_m <= 10:  return "upto_10m"
    if width_m <= 15:  return "10_to_15m"
    if width_m <= 21:  return "15_to_21m"
    if width_m <= 27:  return "21_to_27m"
    if width_m <= 33:  return "27_to_33m"
    if width_m <= 39:  return "33_to_39m"
    if width_m <= 45:  return "39_to_45m"
    return "above_45m"


# ── Setbacks ──────────────────────────────────────────────────────────────────
def get_setbacks(
    plot_depth_m:      float,
    plot_width_m:      float,
    building_height_m: float,
    usage:             str = "residential",
    road_width_m:      float = 9.0,
) -> dict:
    """
    Returns {"front": m, "side": m, "rear": m, "not_permitted": bool,
             "high_rise_extra": dict | None, "note": str}.

    'not_permitted' = True means this height is not allowed for this plot size.
    """
    rules = _load()
    tier  = _ht_tier(building_height_m)
    dk    = _depth_key(plot_depth_m)
    wk    = _width_key(plot_width_m)

    use_key = "residential" if usage in ("residential", "mixed") else "commercial"
    sb      = rules["setbacks"][use_key]

    # Front / rear by plot depth
    fr_row  = sb["front_rear_by_plot_depth"].get(dk, {})
    fr_vals = fr_row.get(tier)
    if fr_vals is None:
        # Height not permitted for this plot depth
        return {
            "front": 0, "side": 0, "rear": 0,
            "not_permitted": True,
            "note": f"Height {building_height_m} m not permitted for plot depth {plot_depth_m} m per RMC Bye-Laws.",
        }

    # Sides by plot width
    sw_row  = sb["sides_by_plot_width"].get(wk, {})
    side    = sw_row.get(tier)
    if side is None:
        return {
            "front": 0, "side": 0, "rear": 0,
            "not_permitted": True,
            "note": f"Height {building_height_m} m not permitted for plot width {plot_width_m} m per RMC Bye-Laws.",
        }

    # Additional setbacks for buildings > 22 m (applied on top)
    extra = None
    add   = sb.get("additional_above_22m")
    if add and building_height_m > 22.0:
        if building_height_m <= 28.0:
            extra = add["22_to_28m"]
        elif building_height_m <= 34.0:
            extra = add["28_to_34m"]
        else:
            extra = add["above_34m"]

    front = fr_vals["front"] + (extra["extra_front"] if extra else 0)
    rear  = fr_vals["rear"]  + (extra["extra_rear"]  if extra else 0)
    side  = side             + (extra["extra_side"]  if extra else 0)

    return {
        "front":         round(front, 2),
        "side":          round(side,  2),
        "rear":          round(rear,  2),
        "not_permitted": False,
        "high_rise_extra": extra,
        "note": "Progressive setbacks apply above 22 m per RMC Table 2A." if extra else "",
    }


# ── Ground coverage ───────────────────────────────────────────────────────────
def get_ground_coverage(plot_area_sqm: float, building_height_m: float) -> int:
    """60% for plot ≤1000 sqm and height ≤16 m; 50% otherwise."""
    if plot_area_sqm <= 1000 and building_height_m <= 16.0:
        return 60
    return 50


# ── Fire NOC ──────────────────────────────────────────────────────────────────
def fire_noc_required(building_height_m: float, ground_coverage_sqm: float) -> bool:
    """Special building → Fire NOC: height > 16 m OR coverage > 500 sqm."""
    return building_height_m > 16.0 or ground_coverage_sqm > 500.0


# ── Lift ─────────────────────────────────────────────────────────────────────
def lift_mandatory(num_floors: int) -> bool:
    """Lift mandatory above G+3 (num_floors > 4 counting Ground)."""
    return num_floors > 4   # Ground + 3 upper = 4 total


# ── Parking (simplified — full table not in bye-law PDF) ─────────────────────
def get_parking(usage: str, built_up_sqm: float, num_units: int = 1) -> dict:
    if usage == "residential":
        cars = max(1, num_units)
        tw   = max(1, num_units)
    else:
        cars = max(1, int(built_up_sqm / 100) * 2)
        tw   = max(2, int(built_up_sqm / 100) * 4)
    return {"cars": cars, "two_wheelers": tw}