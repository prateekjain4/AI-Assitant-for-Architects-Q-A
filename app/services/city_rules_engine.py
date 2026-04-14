"""
city_rules_engine.py
────────────────────
Reads BDA RMP 2031 rules from city_rules/bengaluru_bda.json and exposes
clean accessor functions for FAR, ground coverage, setbacks, and other
regulatory limits.

Design principles:
 - Load JSON once at import; all lookups are pure functions.
 - Unknown zones fall back to R-Residential (logged, not silently wrong).
 - All public functions return plain dicts / primitives — no exceptions.
"""
import json
from pathlib import Path

# ── JSON load (once) ──────────────────────────────────────────────────────────
_RULES_PATH = Path(__file__).parent.parent.parent / "city_rules" / "bengaluru_bda.json"
_rules: dict | None = None


def _load() -> dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            _rules = json.load(f)
    return _rules


# ── Zone normalisation ────────────────────────────────────────────────────────
_ZONE_MAP = {
    "C1": "C", "C2": "C", "C3": "C", "C4": "C", "C5": "C",
    "I1": "I", "I2": "IT_HITECH", "I3": "I", "I4": "I", "I5": "I",
    "IT": "IT_HITECH",   # IT park / Hi-Tech = I2: gets Commercial base FAR + 0.25 bonus
    "PSP1": "PSP", "PSP2": "PSP", "PSP3": "PSP", "PSP4": "PSP", "PSP": "PSP",
    "T1": "T", "T2": "T", "T3": "T", "T4": "T",
    "R": "R", "RM": "R",
}

# Zones that do NOT exist in BDA RMP 2031 — we fall back to R but flag it
_UNKNOWN_ZONES: set[str] = set()


def _zone_cat(zone: str) -> str:
    z = zone.upper().strip()
    cat = _ZONE_MAP.get(z)
    if cat is None:
        _UNKNOWN_ZONES.add(z)   # track for logging / warnings
        return "UNKNOWN"
    return cat


# ── R-zone diagonal lookup tables ─────────────────────────────────────────────
# The R-zone FAR table in BDA RMP 2031 is a diagonal matrix:
# each plot-size row has exactly one road-width bracket.
# Larger plot → requires wider road → higher FAR.
# For a given (plot_area, road_width), take the MINIMUM tier index so
# that a narrow road doesn't grant the FAR reserved for a wide road.
_R_PLOT_TIERS = [
    ("plot_upto_60",       60.0),
    ("plot_60_to_120",    120.0),
    ("plot_120_to_240",   240.0),
    ("plot_240_to_360",   360.0),
    ("plot_360_to_750",   750.0),
    ("plot_750_to_2000", 2000.0),
    ("plot_2000_to_4000",4000.0),
    ("plot_4000_to_20000", 20_000.0),
]
_R_ROAD_TIERS = [
    ("road_below_6",         6.0),
    ("road_6_to_9.5",        9.5),
    ("road_9.5_to_12.5",    12.5),
    ("road_12.5_to_15.5",   15.5),
    ("road_15.5_to_18.5",   18.5),
    ("road_18.5_to_24.5",   24.5),
    ("road_24.5_to_30.5",   30.5),
    ("road_30.5_and_above", 9999.0),
]

# C-zone road brackets (same for both planning zones)
_C_ROAD_TIERS = [
    ("road_below_9.5",       9.5),
    ("road_9.5_to_12.5",    12.5),
    ("road_12.5_to_18.5",   18.5),
    ("road_18.5_to_24.5",   24.5),
    ("road_24.5_to_30.5",   30.5),
    ("road_30.5_and_above", 9999.0),
]


def _tier_idx(tiers: list, value: float) -> int:
    for i, (_, upper) in enumerate(tiers):
        if value <= upper:
            return i
    return len(tiers) - 1


# ── Public: FAR lookup ────────────────────────────────────────────────────────
def get_far(
    zone: str,
    road_width_m: float,
    plot_area_sqm: float,
    planning_zone: str = "zone_A",   # "zone_A" (within ORR) or "zone_B"
) -> dict:
    """
    Returns {"base": float, "tdr": float, "total": float, "coverage_pct": int}.

    Use 'total' for architects (base + maximum TDR).
    planning_zone: BDA divides Bengaluru into Zone A (within ORR) and
    Zone B (outside ORR to conurbation limit).
    """
    rules = _load()
    cat   = _zone_cat(zone)
    fs    = rules["far"]

    if cat == "R":
        pz = fs["R"].get(planning_zone) or fs["R"]["zone_A"]
        ri  = _tier_idx(_R_ROAD_TIERS, road_width_m)
        pi  = _tier_idx(_R_PLOT_TIERS, plot_area_sqm)
        idx = min(ri, pi)           # binding constraint
        pkey = _R_PLOT_TIERS[idx][0]
        rkey = _R_ROAD_TIERS[idx][0]
        tier = pz.get(pkey) or {}
        entry = tier.get(rkey) or {"base": 1.50, "tdr": 0.0, "total": 1.50}
        return {
            "base": entry.get("base", 1.50),
            "tdr":  entry.get("tdr",  0.0),
            "total": entry.get("total", 1.50),
            "coverage_pct": tier.get("coverage_pct", 60) or 60,
        }

    if cat == "C":
        pz = fs["C"].get(planning_zone) or fs["C"]["zone_A"]
        for key, upper in _C_ROAD_TIERS:
            if road_width_m <= upper:
                e = pz.get(key) or {}
                return {
                    "base": e.get("base_far", 1.20),
                    "tdr":  e.get("tdr_far",  0.0),
                    "total": e.get("total_far", 1.20),
                    "coverage_pct": e.get("coverage_pct", 60) or 60,
                }
        e = pz.get("road_30.5_and_above") or {}
        return {"base": e.get("base_far", 1.50), "tdr": e.get("tdr_far", 0.9),
                "total": e.get("total_far", 2.40), "coverage_pct": 40}

    if cat == "I":
        i_sec = fs["I"]
        for key, upper in [
            ("plot_upto_250",      250), ("plot_250_to_500",   500),
            ("plot_500_to_1000",  1000), ("plot_1000_to_2000", 2000),
            ("plot_2000_to_4000", 4000), ("plot_4000_to_8000", 8000),
            ("plot_above_8000",   9999),
        ]:
            if plot_area_sqm <= upper:
                e = i_sec.get(key) or {}
                return {"base": e.get("far", 1.50), "tdr": 0.0,
                        "total": e.get("far", 1.50),
                        "coverage_pct": e.get("coverage_pct") or 55}
        e = i_sec.get("plot_above_8000") or {}
        return {"base": e.get("far", 2.25), "tdr": 0.0,
                "total": e.get("far", 2.25), "coverage_pct": 55}

    if cat == "PSP":
        p_sec = fs["PSP"]
        for key, upper in [
            ("plot_upto_500",     500),  ("plot_upto_1000",    1000),
            ("plot_1000_to_2000", 2000), ("plot_above_2000",   9999),
        ]:
            if plot_area_sqm <= upper:
                e = p_sec.get(key) or {}
                return {"base": e.get("far", 1.50), "tdr": 0.0,
                        "total": e.get("far", 1.50),
                        "coverage_pct": e.get("coverage_pct") or 55}
        e = p_sec.get("plot_above_2000") or {}
        return {"base": e.get("far", 2.25), "tdr": 0.0,
                "total": e.get("far", 2.25), "coverage_pct": 45}

    if cat == "T":
        t_sec = fs["T"]
        for key, upper in [
            ("plot_upto_500",      500), ("plot_500_to_1000",  1000),
            ("plot_1000_to_2000", 9999),
        ]:
            if plot_area_sqm <= upper:
                e = t_sec.get(key) or {}
                return {"base": e.get("far", 1.00), "tdr": 0.0,
                        "total": e.get("far", 1.00),
                        "coverage_pct": e.get("coverage_pct") or 55}

    if cat == "IT_HITECH":
        # BDA RMP 2031: I2 Hi-Tech / IT parks get Commercial base FAR + 0.25 bonus.
        c_result = get_far("C1", road_width_m, plot_area_sqm, planning_zone)
        return {
            "base":         round(c_result["base"] + 0.25, 2),
            "tdr":          c_result["tdr"],
            "total":        round(c_result["total"] + 0.25, 2),
            "coverage_pct": c_result["coverage_pct"],
            "note":         "IT/I2 Hi-Tech: Commercial FAR + 0.25 bonus (BDA RMP 2031)",
        }

    if cat == "UNKNOWN":
        # Zone not in BDA RMP 2031 — return safe fallback with a warning flag
        return {
            "base": 1.50, "tdr": 0.0, "total": 1.50, "coverage_pct": 60,
            "warning": f"Zone '{zone}' not found in BDA RMP 2031. Using minimum FAR 1.50. "
                       "Verify the correct zone with the local planning authority.",
        }

    return {"base": 1.75, "tdr": 0.0, "total": 1.75, "coverage_pct": 60}


# ── Setbacks: BDA RMP 2031 Table 1 + Table 2 ─────────────────────────────────
def _front_by_road(road_m: float) -> float:
    """Table 1 — minimum front setback by abutting road width."""
    if road_m <= 6:   return 1.0
    if road_m <= 7.5: return 1.0
    if road_m <= 9:   return 1.75
    if road_m <= 12:  return 2.0
    if road_m <= 15:  return 2.5
    if road_m <= 18:  return 3.5
    if road_m <= 24:  return 3.5
    if road_m <= 30:  return 4.0
    return 6.0          # 30m+


def get_setbacks(
    plot_area_sqm: float,
    building_height_m: float,
    road_width_m: float,
    corner_plot: bool = False,
) -> dict:
    """
    Table 2 — progressive all-round setbacks by building height (BDA RMP 2031).
    Front setback = max(Table 1 by road width, Table 2 by height).
    Returns {"front": m, "side": m, "rear": m}.

    Key breakpoints:
      ≤ 15 m  → plot-area tiers (1–4 m)
      15–18 m → 6 m all sides  (G+5)
      18–21 m → 7 m            (G+6)
      21–24 m → 8 m            (G+7)
      24–27 m → 9 m            (G+8)
      27–30 m → 10 m           (G+9)
      30–36 m → 11 m           (G+11)
      36–42 m → 12 m           (G+13)
      42–48 m → 13 m           (G+15)
      48–54 m → 14 m           (G+17)
      54–60 m → 15 m           (G+19)
      > 60 m  → 16 m
    """
    h = building_height_m

    if h <= 15.0:
        # Plot-area based (BDA Table 2, G+1 to G+4)
        if plot_area_sqm <= 60:
            f2, ar = 1.0, 0.5
        elif plot_area_sqm <= 120:
            f2, ar = 1.0, 1.0
        elif plot_area_sqm <= 240:
            f2, ar = 2.0, 2.0
        elif plot_area_sqm <= 360:
            f2, ar = 3.0, 3.0
        else:
            f2, ar = 4.0, 4.0
    elif h <= 18.0:  f2 = ar = 6.0
    elif h <= 21.0:  f2 = ar = 7.0
    elif h <= 24.0:  f2 = ar = 8.0
    elif h <= 27.0:  f2 = ar = 9.0
    elif h <= 30.0:  f2 = ar = 10.0
    elif h <= 36.0:  f2 = ar = 11.0
    elif h <= 42.0:  f2 = ar = 12.0
    elif h <= 48.0:  f2 = ar = 13.0
    elif h <= 54.0:  f2 = ar = 14.0
    elif h <= 60.0:  f2 = ar = 15.0
    else:            f2 = ar = 16.0

    front = max(f2, _front_by_road(road_width_m))
    side  = ar
    rear  = ar
    if corner_plot:
        side = max(1.0, side - 1.0)
    return {"front": front, "side": side, "rear": rear}


# ── Public: lift & staircase thresholds ──────────────────────────────────────
def lift_mandatory_floors() -> int:
    """BDA RMP 2031: lift mandatory above G+3 (more than 3 floors above ground)."""
    return 3   # i.e. num_floors > 3  →  lift required


# ── Public: basement rules ────────────────────────────────────────────────────
def get_basement_rules() -> dict:
    rules = _load()
    return rules.get("basement", {})


# ── Public: balcony rules ─────────────────────────────────────────────────────
def get_balcony_rules() -> dict:
    rules = _load()
    return rules.get("balcony", {})


# ── Public: fire NOC threshold ────────────────────────────────────────────────
def fire_noc_non_residential_bua_sqm() -> float:
    """BDA RMP 2031: non-residential buildings > 5,000 sqm BUA require fire arrangement."""
    rules = _load()
    return rules.get("fire_safety", {}).get("non_residential_bua_threshold_sqm", 5000)