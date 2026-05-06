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

# ── JSON load (once each) ─────────────────────────────────────────────────────
_RULES_PATH      = Path(__file__).parent.parent.parent / "city_rules" / "bengaluru_bda.json"
_BBMP_RULES_PATH = Path(__file__).parent.parent.parent / "city_rules" / "bbmp_bylaws.json"
_rules:      dict | None = None
_bbmp_rules: dict | None = None


def _load() -> dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            _rules = json.load(f)
    return _rules


def _load_bbmp() -> dict:
    global _bbmp_rules
    if _bbmp_rules is None:
        with open(_BBMP_RULES_PATH, encoding="utf-8") as f:
            _bbmp_rules = json.load(f)
    return _bbmp_rules


def _bbmp_or_bda(bbmp_keys: list, bda_keys: list, default=None):
    """Walk BBMP JSON first; if result is None walk BDA JSON; else return default."""
    val = _load_bbmp()
    for k in bbmp_keys:
        val = val.get(k) if isinstance(val, dict) else None
        if val is None:
            break
    if val is not None:
        return val
    val = _load()
    for k in bda_keys:
        val = val.get(k) if isinstance(val, dict) else None
        if val is None:
            break
    return val if val is not None else default


# ── Zone normalisation ────────────────────────────────────────────────────────
_ZONE_MAP = {
    "C1": "C", "C2": "C", "C3": "C", "C4": "C", "C5": "C",
    "I1": "I", "I2": "IT_HITECH", "I3": "I", "I4": "I", "I5": "I",
    "IT": "IT_HITECH",   # IT park / Hi-Tech = I2: gets Commercial base FAR + 0.25 bonus
    "PSP1": "PSP", "PSP2": "PSP", "PSP3": "PSP", "PSP4": "PSP", "PSP": "PSP",
    "T": "T", "T1": "T", "T2": "T", "T3": "T", "T4": "T",
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
    ("road_below_9_5m",       9.5),
    ("road_9_5_to_12_5m",    12.5),
    ("road_12_5_to_18_5m",   18.5),
    ("road_18_5_to_24_5m",   24.5),
    ("road_24_5_to_30_5m",   30.5),
    ("road_above_30_5m",     9999.0),
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
        tier = pz.get(pkey) or {}
        return {
            "base": tier.get("base_far", 1.50),
            "tdr":  tier.get("tdr_far",  0.0),
            "total": tier.get("total_max_far", 1.50),
            "coverage_pct": tier.get("max_coverage_pct", 60) or 60,
        }

    if cat == "C":
        pz = fs["C"].get(planning_zone) or fs["C"]["zone_A"]
        for key, upper in _C_ROAD_TIERS:
            if road_width_m <= upper:
                e = pz.get(key) or {}
                return {
                    "base": e.get("base_far", 1.20),
                    "tdr":  e.get("tdr_far",  0.0),
                    "total": e.get("total_max_far", 1.20),
                    "coverage_pct": e.get("max_coverage_pct", 60) or 60,
                }
        e = pz.get("road_above_30_5m") or {}
        return {"base": e.get("base_far", 1.50), "tdr": e.get("tdr_far", 0.9),
                "total": e.get("total_max_far", 2.40), "coverage_pct": e.get("max_coverage_pct", 40)}

    if cat == "I":
        i_sec = fs["I"].get("I3_to_I5_other", fs["I"])
        for key, upper in [
            ("plot_upto_250",      250), ("plot_250_to_500",   500),
            ("plot_500_to_1000",  1000), ("plot_1000_to_2000", 2000),
            ("plot_2000_to_4000", 4000), ("plot_4000_to_8000", 8000),
            ("plot_above_8000",   9999),
        ]:
            if plot_area_sqm <= upper:
                e = i_sec.get(key) or {}
                return {"base": e.get("base_far", 1.50), "tdr": 0.0,
                        "total": e.get("base_far", 1.50),
                        "coverage_pct": e.get("coverage_pct") or 55}
        e = i_sec.get("plot_above_8000") or {}
        return {"base": e.get("base_far", 2.25), "tdr": 0.0,
                "total": e.get("base_far", 2.25), "coverage_pct": 55}

    if cat == "PSP":
        p_sec = fs["PSP"]
        for key, upper in [
            ("plot_upto_500",     500),  ("plot_upto_1000",    1000),
            ("plot_1000_to_2000", 2000), ("plot_above_2000",   9999),
        ]:
            if plot_area_sqm <= upper:
                e = p_sec.get(key) or {}
                return {"base": e.get("max_allowable_far", 1.50), "tdr": 0.0,
                        "total": e.get("max_allowable_far", 1.50),
                        "coverage_pct": e.get("max_coverage_pct") or 55}
        e = p_sec.get("plot_above_2000") or {}
        return {"base": e.get("max_allowable_far", 2.25), "tdr": 0.0,
                "total": e.get("max_allowable_far", 2.25), "coverage_pct": e.get("max_coverage_pct", 45)}

    if cat == "T":
        t_sec = fs["T"]
        for key, upper in [
            ("plot_upto_500",      500), ("plot_500_to_1000",  1000),
            ("plot_1000_to_2000", 9999),
        ]:
            if plot_area_sqm <= upper:
                e = t_sec.get(key) or {}
                return {"base": e.get("max_far", 1.00), "tdr": 0.0,
                        "total": e.get("max_far", 1.00),
                        "coverage_pct": e.get("max_coverage_pct") or 55}

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
    """Lift mandatory above G+3 per BDA RMP 2031 / BBMP Bye-Laws."""
    bbmp = _load_bbmp()
    return bbmp.get("lifts", {}).get("mandatory_above_floors", 3)


def get_staircase_height_threshold(building_height_m: float) -> dict:
    """
    BBMP bye-laws define three height tiers for minimum staircase clear width.
    Returns {"min_clear_width_m": float, "note": str}.
    """
    bbmp = _load_bbmp()
    thresholds = bbmp.get("staircase", {}).get("height_based_minimums", {})
    if building_height_m <= 11.5:
        return thresholds.get("upto_11_5m", {"min_clear_width_m": 1.0, "note": "Residential up to G+3"})
    if building_height_m <= 15.0:
        return thresholds.get("11_5m_to_15m", {"min_clear_width_m": 1.2, "note": "Buildings 11.5–15 m"})
    return thresholds.get("above_15m", {"min_clear_width_m": 1.5, "note": "Fire-escape above 15 m"})


def get_staircase_count_threshold() -> int:
    """Minimum BUA (sqm) above which 2 staircases are mandatory (BBMP Bye-Laws 2003)."""
    bbmp = _load_bbmp()
    return bbmp.get("staircase", {}).get("count_thresholds", {}).get("two_staircases_above_bua_sqm", 2000)


# ── Public: basement rules ────────────────────────────────────────────────────
def get_basement_rules() -> dict:
    return _bbmp_or_bda(
        ["basement"],
        ["building_regulations", "basement"],
        default={},
    )


def get_basement_ventilation() -> dict:
    """Returns mechanical ventilation spec for basements (BBMP + NBC 2016)."""
    bbmp = _load_bbmp()
    return bbmp.get("basement", {}).get("ventilation", {"min_air_changes_per_hour": 6})


# ── Public: balcony rules ─────────────────────────────────────────────────────
def get_balcony_rules() -> dict:
    return _bbmp_or_bda(
        ["miscellaneous", "projections_in_setback", "balcony"],
        ["setbacks", "projections_in_setback", "balcony"],
        default={},
    )


# ── Public: accessibility rules ──────────────────────────────────────────────
def get_accessibility_rules() -> dict:
    return _bbmp_or_bda(
        ["accessibility"],
        ["accessibility"],
        default={},
    )


# ── Public: compound wall rules ───────────────────────────────────────────────
def get_compound_wall_rules() -> dict:
    return _bbmp_or_bda(
        ["compound_wall"],
        ["compound_wall"],
        default={},
    )


# ── Public: fire rules ────────────────────────────────────────────────────────
def fire_noc_non_residential_bua_sqm() -> float:
    """Non-residential buildings > 5,000 sqm BUA require fire arrangement (BDA RMP 2031)."""
    bbmp = _load_bbmp()
    return bbmp.get("fire_safety", {}).get("non_residential_fire_arrangement_above_sqm", 5000)


def get_fire_tender_access() -> dict:
    """Fire tender access road specifications (NBC 2016 Part IV / BBMP Bye-Laws)."""
    bbmp = _load_bbmp()
    return bbmp.get("fire_safety", {}).get("tender_access", {
        "min_road_width_m": 4.5,
        "min_height_clearance_m": 4.5,
        "turning_radius_m": 9.0,
        "dead_end_max_m": 45,
    })


def get_fire_refuge_area() -> dict:
    """Refuge area specification for high-rise buildings (NBC 2016 Part IV)."""
    bbmp = _load_bbmp()
    return bbmp.get("fire_safety", {}).get("refuge_area", {
        "required_above_height_m": 24,
        "frequency_floors": 7,
        "min_area_sqm": 15,
        "counted_in_far": False,
    })


def get_rainwater_harvesting() -> dict:
    """Rainwater harvesting requirements (BBMP Bye-Laws 2003 Section 25)."""
    bbmp = _load_bbmp()
    return bbmp.get("rainwater_harvesting", {"mandatory_above_plot_sqm": 120})


def get_parking_standards() -> dict:
    """Physical parking space standards (BBMP Table 23)."""
    bbmp = _load_bbmp()
    return bbmp.get("parking_standards", {})


# ── Master usage option catalogue ────────────────────────────────────────────
_ALL_USAGE_OPTIONS = [
    {"value": "residential", "label": "Residential (Dwelling)",              "group": "Residential",               "bda_cats": {"R"}},
    {"value": "commercial",  "label": "Commercial / Retail / Office",        "group": "Commercial",                "bda_cats": {"C2", "C3"}},
    {"value": "restaurant",  "label": "Restaurant / Food & Beverage",        "group": "Commercial",                "bda_cats": {"C2", "C3"}},
    {"value": "hotel",       "label": "Hotel / Guest House",                 "group": "Commercial",                "bda_cats": {"C3"}},
    {"value": "mixed",       "label": "Mixed Use (Residential + Commercial)", "group": "Commercial",               "bda_cats": {"C3"}},
    {"value": "hospital",    "label": "Hospital / Nursing Home",             "group": "Institutional / Healthcare", "bda_cats": {"PSP3"}},
    {"value": "educational", "label": "Educational (School / College)",      "group": "Institutional / Healthcare", "bda_cats": {"PSP2", "PSP3"}},
    {"value": "industrial",  "label": "Industrial (General)",                "group": "Industrial",                "bda_cats": {"I3", "I4", "I5"}},
    {"value": "it_bt",       "label": "IT / BT / Hi-Tech Office",            "group": "Industrial",                "bda_cats": {"I2"}},
]

_SPACE_STD_USAGES = {"hotel", "hospital", "educational", "it_bt"}


def get_allowed_usages_for_zone(zone: str, road_width_m: float) -> list:
    """
    Return usage options allowed in the given BDA zone at that road width.
    Each item: {value, label, group, requires_space_standards}.
    BDA RMP 2031 — Tables 5 (R zone), 11 (C zone), 19 (PSP zone).
    """
    z    = zone.upper().strip()
    road = float(road_width_m)

    if z in ("R", "RM"):
        allowed: set = {"residential"}
        if road >= 12.5: allowed |= {"commercial", "restaurant"}
        if road >= 15.5: allowed |= {"hotel", "mixed", "hospital", "educational"}
        if road >= 18.5: allowed |= {"it_bt"}

    elif z.startswith("C"):
        allowed = {"residential", "commercial", "restaurant", "hotel", "mixed"}
        if road >= 12.5: allowed |= {"hospital", "educational", "it_bt"}
        if road >= 18.5: allowed |= {"industrial"}

    elif z.startswith("PSP"):
        allowed = {"hospital", "educational"}
        if road >= 12.5: allowed |= {"commercial", "restaurant", "residential"}
        if road >= 18.5: allowed |= {"hotel", "mixed"}

    elif z in ("IT",) or (z.startswith("I") and len(z) <= 2):
        if z == "I1":
            allowed = {"industrial"}
        elif z in ("I2", "IT"):
            allowed = {"it_bt", "commercial"}
        else:
            allowed = {"industrial", "it_bt"}

    elif z.startswith("T"):
        allowed = {"commercial", "mixed"}

    else:
        allowed = {o["value"] for o in _ALL_USAGE_OPTIONS}

    result = []
    for opt in _ALL_USAGE_OPTIONS:
        if opt["value"] not in allowed:
            continue
        needs_ss = opt["value"] in _SPACE_STD_USAGES and z in ("R", "RM") and road >= 15.5
        result.append({
            "value":                    opt["value"],
            "label":                    opt["label"] + (" *" if needs_ss else ""),
            "group":                    opt["group"],
            "requires_space_standards": needs_ss,
        })
    return result


# ── Usage → BDA zone category ─────────────────────────────────────────────────
_USAGE_TO_ZONE_CAT = {
    "residential": "R", "residential_single": "R", "dwelling": "R",
    "shop": "C2", "petty_shop": "C2", "bakery": "C2", "tailoring": "C2",
    "restaurant": "C2", "eatery": "C2", "clinic": "C2", "gym": "C2",
    "retail": "C2", "bank": "C2",
    "hotel": "C3", "hotel_lodge": "C3", "lodge": "C3",
    "star_hotel": "C3", "luxury_hotel": "C3",
    "office": "C3", "corporate_office": "C3", "commercial": "C3",
    "mall": "C3", "cinema": "C3", "mixed": "C3",
    "hospital": "PSP3", "nursing_home": "PSP3", "polyclinic": "PSP3",
    "medical": "PSP3", "institutional": "PSP3",
    "school": "PSP2", "primary_school": "PSP2",
    "college": "PSP3", "university": "PSP3",
    "industrial": "I3", "light_industrial": "I3",
    "it_park": "I2", "software": "I2", "tech_park": "I2",
    "warehouse": "C4",
}


def get_usage_zone_category(usage: str) -> str:
    """Map descriptive usage to BDA zone category code, e.g. 'hotel' → 'C3'."""
    return _USAGE_TO_ZONE_CAT.get(usage.lower().strip().replace(" ", "_"), "R")


# ── Permissible-use road brackets ─────────────────────────────────────────────
def _r_road_bracket(road_m: float) -> str:
    if road_m < 9.5:  return "road_below_9_5m"
    if road_m < 12.5: return "road_9_5_to_12_5m"
    if road_m < 15.5: return "road_12_5_to_15_5m"
    if road_m < 18.5: return "road_15_5_to_18_5m"
    if road_m < 24.5: return "road_18_5_to_24_5m"
    return "road_24_5_and_above"


def _c_road_bracket(road_m: float) -> str:
    if road_m < 9.5:  return "road_below_9_5m"
    if road_m < 12.5: return "road_9_5_to_12_5m"
    if road_m < 18.5: return "road_12_5_to_18_5m"
    if road_m < 24.5: return "road_18_5_to_24_5m"
    return "road_24_5_and_above"


def _psp_road_bracket(road_m: float) -> str:
    if road_m < 12.5: return "road_below_12_5m"
    if road_m < 18.5: return "road_12_5_to_18_5m"
    if road_m < 24.0: return "road_18_to_24m"
    return "road_above_24m"


def get_permissible_uses(zone: str, road_width_m: float) -> dict:
    """Return permissible uses for zone + road width (BDA Tables 5, 11, 19)."""
    rules = _load()
    cat = _zone_cat(zone)
    if cat == "R":
        table = rules.get("permissible_uses_residential_zone", {})
        bracket = _r_road_bracket(road_width_m)
        return {
            "zone_category": "R", "road_bracket": bracket,
            "permissible": table.get(bracket, []),
            "ancillary_note": table.get("ancillary_use_limit", {}).get("note", ""),
        }
    if cat == "C":
        table = rules["far"]["C"].get("permissible_uses_by_road_width", {})
        bracket = _c_road_bracket(road_width_m)
        return {
            "zone_category": "C", "road_bracket": bracket,
            "permissible": table.get(bracket, ""),
            "note": table.get("_note", "* = Subject to space standards in Table 25"),
        }
    if cat == "PSP":
        table = rules["far"]["PSP"].get("permissible_uses_by_road_width", {})
        bracket = _psp_road_bracket(road_width_m)
        return {"zone_category": "PSP", "road_bracket": bracket, "permissible": table.get(bracket, "")}
    return {"zone_category": cat, "road_bracket": "any", "permissible": "all permitted"}


def validate_usage_in_zone(usage: str, zone: str, road_width_m: float) -> dict:
    """
    Check whether the given usage is permissible in zone + road width.
    Returns {"valid": bool, "warning": str | None, "requires_space_standards": bool}.
    BDA RMP 2031 Tables 5, 11, 19.
    """
    u = usage.lower().strip()
    zone_cat = _zone_cat(zone)
    pu = get_permissible_uses(zone, road_width_m)
    perm = pu.get("permissible", [])
    perm_str = (" ".join(perm) if isinstance(perm, list) else str(perm)).upper()
    norm = lambda s: s.replace("-", "").replace(" ", "")

    # usage → BDA category code to look for in the permissible string
    _check_map = {
        "hotel": ("C3", 15.5), "hotel_lodge": ("C3", 15.5), "lodge": ("C3", 15.5),
        "star_hotel": ("C3", 15.5), "luxury_hotel": ("C3", 15.5),
        "hospital": ("PSP3", 15.5), "nursing_home": ("PSP3", 15.5),
        "polyclinic": ("PSP3", 12.5), "medical": ("PSP3", 15.5),
        "office": ("C3", 12.5), "corporate_office": ("C3", 12.5),
        "commercial": ("C3", 12.5), "mall": ("C3", 15.5),
        "school": ("PSP2", 12.5), "college": ("PSP3", 15.5),
        "institutional": ("PSP3", 15.5), "mixed": ("C3", 12.5),
        "retail": ("C2", 9.5), "restaurant": ("C2", 9.5),
    }

    if u not in _check_map or zone_cat in ("C", "PSP", "I"):
        return {"valid": True, "warning": None, "requires_space_standards": False}

    required_cat, min_road = _check_map[u]
    is_present = norm(required_cat) in norm(perm_str)
    requires_ss = "SPACE STANDARDS" in perm_str and is_present

    if not is_present and zone_cat == "R":
        return {
            "valid": False,
            "warning": (
                f"{usage.title()} ({required_cat}) is NOT permissible in R zone at {road_width_m}m road. "
                f"Minimum road width required: {min_road}m (BDA RMP 2031 Table 5)."
            ),
            "requires_space_standards": False,
        }
    return {
        "valid": True,
        "warning": (
            f"{usage.title()} is permissible here but subject to BDA Table 25 space standards."
            if requires_ss else None
        ),
        "requires_space_standards": requires_ss,
    }


# ── Space standards (Table 25) ────────────────────────────────────────────────
_USAGE_TO_SPACE_STD = {
    "hotel":           ("lodging", "hotels_lodges"),
    "hotel_lodge":     ("lodging", "hotels_lodges"),
    "lodge":           ("lodging", "hotels_lodges"),
    "service_apartment": ("lodging", "service_apartments_hostels"),
    "star_hotel":      ("lodging", "star_hotel_upto_3_star"),
    "luxury_hotel":    ("lodging", "star_hotel_above_3_star"),
    "hospital":        ("health",  "specialty_hospital_above_50_beds"),
    "nursing_home":    ("health",  "nursing_home_11_30_beds"),
    "polyclinic":      ("health",  "polyclinic_maternity_upto_10_beds"),
    "medical":         ("health",  "nursing_home_hospital_31_50_beds"),
    "primary_school":  ("educational", "primary_middle_school_1_to_8"),
    "school":          ("educational", "high_school_1_to_10"),
    "college":         ("educational", "integrated_residential_college"),
    "office":          ("office_commercial", "office_commercial_c3_i2_upto_1000sqm"),
    "commercial":      ("office_commercial", "office_commercial_c3_i2_upto_1000sqm"),
    "mall":            ("socio_cultural", "kalyana_mantap_multiplex_mall_convention_auditorium_game_sports"),
    "cinema":          ("socio_cultural", "kalyana_mantap_multiplex_mall_convention_auditorium_game_sports"),
}


def get_space_standards(usage: str) -> dict | None:
    """Return min plot area and road width for usage from BDA Table 25. None if not applicable."""
    rules = _load()
    ss = rules.get("space_standards", {})
    key = usage.lower().strip().replace(" ", "_")
    mapping = _USAGE_TO_SPACE_STD.get(key)
    if not mapping:
        return None
    category, sub_key = mapping
    entry = ss.get(category, {}).get(sub_key)
    if not entry:
        return None
    return {
        "usage": usage,
        "min_plot_sqm": entry.get("min_plot_sqm"),
        "min_road_width_m": entry.get("min_road_width_m"),
        "source": "BDA RMP 2031 Table 25",
        "note": entry.get("note"),
    }


def validate_space_standards(usage: str, plot_area_sqm: float, road_width_m: float) -> dict:
    """Validate plot meets Table 25 minimums for the usage. Returns warnings list."""
    std = get_space_standards(usage)
    if not std:
        return {"valid": True, "warnings": [], "standards": None}
    warnings = []
    min_plot = std.get("min_plot_sqm")
    min_road = std.get("min_road_width_m")
    if min_plot and isinstance(min_plot, (int, float)) and plot_area_sqm < min_plot:
        warnings.append(
            f"{usage.title()} requires min plot area {min_plot} sqm (BDA Table 25); "
            f"current plot is {plot_area_sqm:.0f} sqm."
        )
    if min_road and road_width_m < min_road:
        warnings.append(
            f"{usage.title()} requires min road width {min_road}m (BDA Table 25); "
            f"current road is {road_width_m}m."
        )
    return {"valid": len(warnings) == 0, "warnings": warnings, "standards": std}


# ── Staircase width by usage (BBMP Bye-Laws 2003 Sec 20.6) ───────────────────
def get_usage_staircase_width(usage: str, building_height_m: float = 0.0) -> float:
    """Return minimum staircase clear width (m) for the usage type."""
    stair = _load_bbmp().get("staircase", {}).get("usage_based_widths", {})
    u = usage.lower().strip()
    if any(k in u for k in ("hospital", "nursing", "medical", "institutional")):
        if building_height_m > 24:
            return stair.get("educational_above_24m_height_min_width_m", 2.0)
        return stair.get("institutional_above_10beds_min_width_m", 2.0)
    if any(k in u for k in ("assembly", "cinema", "auditorium", "theatre")):
        return stair.get("assembly_cinema_auditorium_min_width_m", 1.5)
    if any(k in u for k in ("school", "college", "university", "educational")):
        if building_height_m > 24:
            return stair.get("educational_above_24m_height_min_width_m", 2.0)
        return stair.get("educational_upto_24m_height_min_width_m", 1.5)
    if any(k in u for k in ("hotel", "hostel", "lodge", "service_apartment")):
        return stair.get("hostel_min_width_m", 1.5)
    if any(k in u for k in ("office", "commercial", "mall", "retail", "mixed", "restaurant")):
        return stair.get("all_other_buildings_min_width_m", 1.5)
    return stair.get("residential_min_width_m", 1.0)


# ── Solar requirement (BDA RMP 2031 Sec 4.15) ─────────────────────────────────
def is_solar_required(usage: str) -> bool:
    """True if solar water heating + lighting system is mandatory for this usage."""
    u = usage.lower()
    return any(k in u for k in ("hotel", "hospital", "nursing_home", "nursing"))


def get_solar_note() -> str:
    bbmp = _load_bbmp()
    return bbmp.get("solar_and_green", {}).get("solar_water_heating", {}).get(
        "requirement",
        "Solar Water Heating System + Solar Lighting in common areas mandatory (BDA RMP 2031 Sec 4.15)"
    )


# ── Hotel 3-star+ basement special uses ──────────────────────────────────────
def get_hotel_basement_uses() -> list:
    """Basement uses permitted only for 3-star+ hotels (BBMP / BDA RMP 2031 Sec 4.9.2)."""
    return _bbmp_or_bda(
        ["basement", "permitted_only_for_3star_plus_hotels"],
        ["building_regulations", "basement", "permitted_only_for_3star_plus_hotels"],
        default=[],
    )


# ── Fire travel distance to exit (NBC 2016 Part IV) ──────────────────────────
def get_fire_travel_distance(usage: str) -> float:
    """Max travel distance to nearest exit in metres for the usage (BBMP / BDA / NBC 2016)."""
    td = _bbmp_or_bda(
        ["fire_safety", "travel_distance_to_exit_m"],
        ["fire_safety", "travel_distance_to_exit_m"],
        default={},
    )
    u = usage.lower()
    if any(k in u for k in ("residential", "dwelling")):
        return td.get("residential", 22.5)
    if any(k in u for k in ("hospital", "nursing", "institutional")):
        return td.get("institutional", 22.5)
    if any(k in u for k in ("school", "college", "educational")):
        return td.get("educational", 22.5)
    if any(k in u for k in ("assembly", "cinema", "auditorium", "theatre")):
        return td.get("assembly", 30.0)
    if any(k in u for k in ("hotel", "restaurant", "retail", "mall", "lodge")):
        return td.get("commercial", 30.0)
    if any(k in u for k in ("office", "commercial", "corporate", "mixed")):
        return td.get("business", 45.0)
    if any(k in u for k in ("industrial", "warehouse", "factory")):
        return td.get("industrial", 30.0)
    if any(k in u for k in ("storage", "godown")):
        return td.get("storage", 30.0)
    return td.get("commercial", 30.0)