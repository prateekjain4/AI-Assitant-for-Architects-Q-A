"""
hyderabad_planning_service.py
──────────────────────────────
Full planning calculation for Hyderabad GHMC / HMDA
AP Building Rules 2012 (G.O.Ms.No.168).

Mirrors the output shape of calculate_ranchi_planning() and
calculate_plot_planning() so the Angular frontend can reuse the
same result-panel template.
"""
import json
import math
from pathlib import Path

# ── Load rules JSON once ───────────────────────────────────────────────────────
_RULES_PATH = Path(__file__).parent.parent.parent / "city_rules" / "hyderabad_hmda.json"
_rules: dict | None = None


def _load() -> dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            _rules = json.load(f)
    return _rules


# ── Unit helpers ───────────────────────────────────────────────────────────────
def _sqm_to_sqft(sqm: float) -> float:
    return round(sqm * 10.7639, 2)


# ── Zone normalisation ─────────────────────────────────────────────────────────
# Maps incoming zone codes (including aliases) to canonical JSON keys
_ZONE_MAP = {
    # Residential
    "R1": "R1", "R2": "R2", "R3": "R3", "R4": "R4", "R5": "R5",
    # Commercial
    "C1": "C1", "C2": "C2", "C3": "C3",
    # Mixed Use
    "MU": "MU1", "MU1": "MU1", "MU2": "MU2", "MIXED": "MU1",
    # Industrial
    "I": "I3", "IND": "I3", "I1": "I1", "I2": "I2", "I3": "I3", "I4": "I4",
    # Public, Transport, Open Space, Agriculture
    "PSP": "PSP", "T": "T", "OS": "OS", "AG": "AG",
}


def _normalise_zone(zone: str) -> str:
    z = zone.upper().strip()
    return _ZONE_MAP.get(z, "R2")


def _zone_display(zone: str) -> str:
    """Return human-readable label from the JSON zones table (no FAR shown)."""
    rules = _load()
    zone_entry = rules["zones"].get(zone, {})
    label = zone_entry.get("label", zone)
    return f"{zone} — {label}"


# ── FAR lookup ─────────────────────────────────────────────────────────────────
def _get_far(zone: str) -> float:
    rules = _load()
    return rules["zones"].get(zone, {}).get("far", 2.0)


# ── Ground coverage ────────────────────────────────────────────────────────────
def _get_coverage(zone: str, plot_area_sqm: float, is_high_rise: bool) -> int:
    rules = _load()
    if is_high_rise:
        return rules["ground_coverage_pct"]["high_rise"]
    # Prefer zone-specific coverage from zones table
    zone_cov = rules["zones"].get(zone, {}).get("ground_coverage_pct")
    if zone_cov is not None:
        return zone_cov
    gc = rules["ground_coverage_pct"]
    return gc["plot_upto_750sqm"] if plot_area_sqm <= 750 else gc["plot_above_750sqm"]


# ── Setback lookup ─────────────────────────────────────────────────────────────
def _get_non_high_rise_setbacks(
    plot_area_sqm: float,
    road_width_m: float,
    building_height_m: float,
) -> dict:
    """
    Returns front, side, rear setbacks (m) from Table III of G.O.Ms.No.168.
    For non-high-rise buildings (height < 18m).
    """
    rules = _load()
    tbl = rules["setbacks_non_high_rise"]

    # Pick plot size bracket
    if plot_area_sqm < 50:
        bracket = tbl["plot_upto_50"]
    elif plot_area_sqm <= 100:
        bracket = tbl["plot_50_to_100"]
    elif plot_area_sqm <= 200:
        bracket = tbl["plot_100_to_200"]
    elif plot_area_sqm <= 300:
        bracket = tbl["plot_200_to_300"]
    elif plot_area_sqm <= 400:
        bracket = tbl["plot_300_to_400"]
    elif plot_area_sqm <= 500:
        bracket = tbl["plot_400_to_500"]
    elif plot_area_sqm <= 750:
        bracket = tbl["plot_500_to_750"]
    elif plot_area_sqm <= 1000:
        bracket = tbl["plot_750_to_1000"]
    elif plot_area_sqm <= 1500:
        bracket = tbl["plot_1000_to_1500"]
    elif plot_area_sqm <= 2500:
        bracket = tbl["plot_1500_to_2500"]
    else:
        bracket = tbl["plot_above_2500"]

    # Road width bracket for front setback
    road_key = "9999"
    for k in ["12", "18", "24", "30"]:
        if road_width_m <= float(k):
            road_key = k
            break

    # Front setback — some brackets have height-sub-tables
    front_table = bracket.get("front", {})
    if isinstance(front_table, dict) and "7m_height" in front_table:
        # plot_200_to_300 style
        ht_key = "10m_height" if building_height_m > 7 else "7m_height"
        front_m = float(front_table[ht_key].get(road_key, 3.0))
    elif isinstance(front_table, dict):
        front_m = float(front_table.get(road_key, 3.0))
    else:
        front_m = 3.0

    # Side/rear setback
    side_rear = bracket.get("side_rear_m", 1.5)
    if isinstance(side_rear, dict):
        # Pick by building height
        if building_height_m <= 7:
            side_m = float(side_rear.get("7m", side_rear.get("no_parking", 1.5)))
        elif building_height_m <= 10:
            side_m = float(side_rear.get("10m", side_rear.get("with_parking",
                           side_rear.get("7m", 1.5))))
        elif building_height_m <= 12:
            side_m = float(side_rear.get("12m", side_rear.get("10m", 1.5)))
        elif building_height_m <= 15:
            side_m = float(side_rear.get("15m", side_rear.get("12m", 2.5)))
        else:
            side_m = float(side_rear.get("18m", side_rear.get("15m", 3.0)))
    else:
        side_m = float(side_rear)

    return {"front": front_m, "side": side_m, "rear": side_m}


def _get_high_rise_setbacks(building_height_m: float, road_width_m: float) -> dict:
    """
    Returns all-round setback from Table IV of G.O.Ms.No.168.
    Front = max(road-dependent Table III front, all-round).
    """
    rules = _load()
    tbl = rules["setbacks_high_rise"]

    # Find the matching height bracket
    allround_m = 7.0
    for key in ["21", "24", "27", "30", "35", "40", "45", "50", "55"]:
        if building_height_m <= float(key):
            allround_m = float(tbl[key]["allround_m"])
            break
    else:
        # above 55m: 16 + 0.5m per 5m above 55m
        extra = math.ceil((building_height_m - 55) / 5) * tbl.get("above_55_increment_per_5m", 0.5)
        allround_m = 16.0 + extra

    # Front setback: derive road-based front from Table III equivalent for large plots
    # For high-rise, use standard road-based fronts: ≤12m→3m, ≤18m→4m, ≤24m→5m, ≤30m→6m, >30m→7.5m
    if road_width_m <= 12:
        front_road = 3.0
    elif road_width_m <= 18:
        front_road = 4.0
    elif road_width_m <= 24:
        front_road = 5.0
    elif road_width_m <= 30:
        front_road = 6.0
    else:
        front_road = 7.5

    front_m = max(front_road, allround_m)

    return {"front": front_m, "side": allround_m, "rear": allround_m, "allround": allround_m}


# ── Minimum road width check ───────────────────────────────────────────────────
def _min_road_for_height(building_height_m: float) -> float:
    if building_height_m <= 18:
        return 9.0
    elif building_height_m <= 24:
        return 12.0
    elif building_height_m <= 30:
        return 18.0
    elif building_height_m <= 35:
        return 24.0
    elif building_height_m <= 45:
        return 24.0
    elif building_height_m <= 55:
        return 30.0
    else:
        return 30.0


# ── Max height cap by road width ───────────────────────────────────────────────
def _max_height_for_road(road_width_m: float) -> float:
    """Soft cap: return the max height permitted for this road width."""
    if road_width_m < 9.0:
        return 10.0   # old areas / narrow roads
    elif road_width_m < 12.0:
        return 18.0   # non-high-rise only
    elif road_width_m < 18.0:
        return 24.0
    elif road_width_m < 24.0:
        return 30.0
    elif road_width_m < 30.0:
        return 55.0
    else:
        return 9999.0  # no height cap for 30m+ roads


# ── Parking calculation ────────────────────────────────────────────────────────
def _get_parking(usage: str, built_up_sqm: float) -> dict:
    """
    Parking per Table V of G.O.Ms.No.168 (HMDA/GHMC area).
    Returns required car spaces based on % of built-up area.
    """
    rules = _load()
    pct_table = rules["parking"]["pct_of_bua"]
    car_area = rules["parking"]["space_dimensions"]["car_area_sqm"]  # 12.5 sqm

    usage_lower = usage.lower()
    if usage_lower in ("multiplex",):
        pct = pct_table["multiplexes"]["hmda_ghmc"]
    elif usage_lower in ("mall", "ites", "it"):
        pct = pct_table["malls_above_4000sqm_ites"]["hmda_ghmc"]
    elif usage_lower in ("commercial", "hotel", "restaurant", "office"):
        pct = pct_table["hotels_restaurants_commercial_highrise_nonres"]["hmda_ghmc"]
    else:
        # residential, hospital, institutional, industrial, educational
        pct = pct_table["residential_hospitals_institutional_industrial_educational"]["hmda_ghmc"]

    parking_area_sqm = built_up_sqm * pct / 100
    cars = max(1, int(parking_area_sqm / car_area))
    bikes = cars * 2  # 2 bikes per car (GHMC norm)

    return {
        "pct_of_bua": pct,
        "parking_area_sqm": round(parking_area_sqm, 1),
        "cars": cars,
        "two_wheelers": bikes,
    }


# ── Fire NOC ───────────────────────────────────────────────────────────────────
def _fire_noc_required(height_m: float, usage: str, plot_sqm: float) -> bool:
    usage_lower = usage.lower()
    commercial_types = ("commercial", "hotel", "restaurant", "office", "mall",
                        "multiplex", "ites", "it")
    public_types = ("hospital", "cinema", "assembly", "function hall", "educational",
                    "institutional")

    if height_m >= 18.0:
        return True
    if usage_lower in commercial_types and height_m >= 15.0:
        return True
    if usage_lower in public_types and (plot_sqm >= 500 or height_m > 6.0):
        return True
    return False


def _get_fire_rules(height_m: float, usage: str) -> list[str]:
    rules = []
    rules_data = _load()["fire_safety"]

    if height_m >= 15.0 and usage.lower() in ("commercial", "hotel", "restaurant",
                                                "office", "mall", "multiplex", "ites"):
        rules.extend(rules_data["requirements_above_15m_commercial"])

    if height_m >= 18.0:
        rules.extend(rules_data["requirements_above_18m"])

    return rules


# ── Accessibility ─────────────────────────────────────────────────────────────
def _get_accessibility(usage: str, plot_area_sqm: float) -> dict:
    rules = _load()
    acc = rules["accessibility"]
    psp_usages = ("institutional", "hospital", "educational", "public",
                  "assembly", "psp", "cinema", "function hall")
    required = usage.lower() in psp_usages or plot_area_sqm >= 300
    return {
        "required": required,
        "trigger": acc["applicability"],
        "access_path": acc["access_path"],
        "parking": acc["parking"],
        "ramp": acc["ramp"],
        "door": acc["door"],
        "staircase": acc["staircase"],
        "toilet": acc["toilet"],
        "controls": acc["controls"],
        "handrails": acc["handrails"],
        "source": acc["_source"],
    }


# ── Open space ─────────────────────────────────────────────────────────────────
def _get_open_space(plot_area_sqm: float, is_high_rise: bool, num_units: int) -> dict:
    rules = _load()
    os_rules = rules["open_space"]
    if is_high_rise:
        base = os_rules["high_rise"]
    elif plot_area_sqm >= 4000:
        base = os_rules["group_development_above_4000sqm"]
    elif plot_area_sqm > 750:
        base = os_rules["non_high_rise_above_750sqm"]
    else:
        base = {"note": "No organised open space requirement for plots ≤ 750 sqm"}
    amenities = os_rules["group_housing_above_100_units"] if num_units >= 100 else None
    return {
        "requirement": base,
        "group_housing_amenities": amenities,
        "chowk": os_rules["chowk_inner_courtyard"],
        "inter_block": os_rules["inter_block_spacing"],
    }


# ── Solar mandatory check ──────────────────────────────────────────────────────
def _solar_mandatory(usage: str, num_units: int) -> bool:
    solar_usages = ("hospital", "nursing home", "hotel")
    return num_units >= 100 or usage.lower() in solar_usages


# ── Main calculation ───────────────────────────────────────────────────────────
def calculate_hyderabad_planning(
    zone:              str,
    plot_length_m:     float,
    plot_width_m:      float,
    road_width_m:      float,
    building_height_m: float,
    usage:             str   = "residential",
    corner_plot:       bool  = False,
    basement:          bool  = False,
    floor_height_m:    float = 3.0,
    locality:          str   = "Hyderabad",
) -> dict:

    canon_zone   = _normalise_zone(zone)
    plot_area_m2 = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(_sqm_to_sqft(plot_area_m2), 0)
    is_high_rise = building_height_m >= 18.0

    # ── Height cap by road width ───────────────────────────────────
    road_ht_cap   = _max_height_for_road(road_width_m)
    effective_ht  = min(building_height_m, road_ht_cap)
    ht_capped     = effective_ht < building_height_m
    ht_cap_reason = ""
    if ht_capped:
        ht_cap_reason = (
            f"Road width {road_width_m} m caps building height to {effective_ht} m "
            f"(AP Building Rules 2012, Table II / Table IV)"
        )
    is_high_rise = effective_ht >= 18.0

    # ── FAR ───────────────────────────────────────────────────────
    far_val = _get_far(canon_zone)

    # ── Ground coverage ───────────────────────────────────────────
    cov_pct = _get_coverage(canon_zone, plot_area_m2, is_high_rise)

    # ── Setbacks ──────────────────────────────────────────────────
    if is_high_rise:
        sb = _get_high_rise_setbacks(effective_ht, road_width_m)
    else:
        sb = _get_non_high_rise_setbacks(plot_area_m2, road_width_m, effective_ht)

    front_m = sb["front"]
    side_m  = sb["side"]
    rear_m  = sb["rear"]

    # Corner plot: one side treated as front (minor relaxation on other side)
    if corner_plot:
        side_m = max(1.0, side_m - 0.5)

    # ── Footprint after setbacks ──────────────────────────────────
    buildable_length = max(0.0, plot_length_m - front_m - rear_m)
    buildable_width  = max(0.0, plot_width_m  - 2 * side_m)
    footprint_m2     = round(buildable_length * buildable_width, 2)
    footprint_sqft   = round(_sqm_to_sqft(footprint_m2), 0)

    # Apply coverage cap
    max_footprint_m2 = round(plot_area_m2 * cov_pct / 100, 2)
    if footprint_m2 > max_footprint_m2:
        footprint_m2   = max_footprint_m2
        footprint_sqft = round(_sqm_to_sqft(footprint_m2), 0)

    # ── Max built-up area (FAR based) ─────────────────────────────
    max_built_m2   = round(plot_area_m2 * far_val, 2)
    max_built_sqft = round(_sqm_to_sqft(max_built_m2), 0)

    # ── Floors feasible by height ─────────────────────────────────
    num_floors        = max(1, int(effective_ht / floor_height_m))
    min_floors_for_far = max(1, math.ceil(max_built_m2 / max(footprint_m2, 1)))
    stair_label        = f"G+{num_floors - 1}" if num_floors > 1 else "Ground only"

    # ── Staircase / lift ──────────────────────────────────────────
    rules_data      = _load()
    lift_mandatory  = (effective_ht > rules_data["staircase_lift"]["lift_mandatory_above_height_m"]
                       or num_floors > rules_data["staircase_lift"]["lift_mandatory_above_floors"])
    stair_width_m   = rules_data["staircase_lift"]["min_stair_width_m"]  # 1.5m

    # ── Fire NOC ──────────────────────────────────────────────────
    noc_req    = _fire_noc_required(effective_ht, usage, plot_area_m2)
    fire_rules = _get_fire_rules(effective_ht, usage)

    # ── Parking ───────────────────────────────────────────────────
    parking = _get_parking(usage, max_built_m2)

    # ── Compliance checks ─────────────────────────────────────────
    compliance = []
    min_road_needed = _min_road_for_height(effective_ht)
    if road_width_m < min_road_needed:
        compliance.append(
            f"⚠ Building height {effective_ht} m requires minimum {min_road_needed} m "
            f"road width — current road is {road_width_m} m (Table II/IV, AP Building Rules 2012)"
        )
    if is_high_rise and plot_area_m2 < 2000:
        compliance.append(
            f"⚠ High Rise buildings require minimum plot area of 2000 sqm — "
            f"current plot is {plot_area_m2:.0f} sqm (Rule 7, AP Building Rules 2012)"
        )
    if basement and plot_area_m2 < 750:
        compliance.append(
            "⚠ Cellar/basement parking permitted only for plots ≥ 750 sqm (Rule 13, AP Building Rules 2012)"
        )
    if basement:
        compliance.append("Basement: used for parking only — habitation not permitted (Rule 13c iii)")
        compliance.append("Basement ventilation: minimum 2.5% of floor area (Rule 13c iii)")
        bsmt_rules = rules_data["basement"]
        if plot_area_m2 <= 1000:
            compliance.append(f"Basement setback: {bsmt_rules['setback_upto_1000sqm_m']} m from property line (Rule 13c x)")
        elif plot_area_m2 <= 2000:
            compliance.append(f"Basement setback: {bsmt_rules['setback_1000_to_2000sqm_m']} m from property line (Rule 13c x)")
        else:
            compliance.append(f"Basement setback: {bsmt_rules['setback_above_2000sqm_m']} m from property line (Rule 13c x)")
    if lift_mandatory:
        compliance.append("Lift mandatory — building height > 15 m / above G+4 (NBC 2005, AP Building Rules 2012)")
    if plot_area_m2 >= 750:
        compliance.append("Organised open space (tot lot): 5% of site area required (Rule 5f v)")
    if plot_area_m2 >= 4000 and usage == "residential":
        compliance.append("EWS/LIG housing: 20% of developed land required for HMDA area projects ≥ 4000 sqm (Rule 11)")
    compliance.append("Rain Water Harvesting mandatory (G.O.Ms.No.350 MA, Dt.09.06.2000)")
    if is_high_rise:
        compliance.append("Organised open space: min 10% of site area, open to sky, width ≥ 3 m (Rule 7a vii)")
        compliance.append("Green planting strip: min 2 m wide on all sides within setbacks (Rule 7a viii)")
    if noc_req:
        compliance.append(
            "Fire NOC mandatory from AP State Disasters Response & Fire Services Department (Rule 5f xv / Rule 7a vi)"
        )

    # ── Warnings ──────────────────────────────────────────────────
    warnings = []
    if ht_capped:
        warnings.append(f"Building height reduced to {effective_ht} m — {ht_cap_reason}")
    if footprint_m2 <= 0:
        warnings.append("⚠ No buildable area after setbacks — plot is too narrow/shallow for this height")
    if effective_ht > 55:
        warnings.append(
            f"Very tall building ({effective_ht} m) — additional setback of 0.5 m per 5 m above 55 m applies (Table IV)"
        )
    if locality.lower() in ("banjara hills", "jubilee hills"):
        warnings.append(
            "Special zone: Banjara Hills / Jubilee Hills max height 15 m (Table I, AP Building Rules 2012)"
        )

    # ── New enriched sections ─────────────────────────────────────
    num_units_est = max(1, int(max_built_m2 / 75))
    accessibility_data = _get_accessibility(usage, plot_area_m2)
    open_space_data    = _get_open_space(plot_area_m2, is_high_rise, num_units_est)
    solar_mandatory    = _solar_mandatory(usage, num_units_est)

    # ── Section summaries ─────────────────────────────────────────
    section_summaries = {
        "far": (
            f"Zone: {_zone_display(canon_zone)} · FAR {far_val} · "
            f"Max built-up {max_built_sqft:,.0f} sq ft ({max_built_m2:,.0f} sqm)"
        ),
        "setbacks": (
            f"Front {front_m} m · Side {side_m} m · Rear {rear_m} m"
            + (" · High-Rise all-round rules apply" if is_high_rise else "")
        ),
        "staircase": (
            f"{stair_label} · {num_floors} floors feasible · "
            f"{'Lift mandatory' if lift_mandatory else 'Lift optional'}"
        ),
        "accessibility": (
            f"{'Mandatory' if accessibility_data['required'] else 'Recommended'} "
            f"— ramp max 1:12, access path >=1200mm, stair tread >=300mm (Annexure-V, Rule 15.a.v)"
        ),
        "open_space": (
            f"{'10%' if is_high_rise else ('10%' if plot_area_m2 >= 4000 else ('5%' if plot_area_m2 > 750 else 'N/A'))} "
            f"of site as organised open space · Green strip 2m (Rules 5.f.v / 7.a.vii / 8.g)"
        ),
    }

    # ── Basement info ─────────────────────────────────────────────
    bsmt_rules = rules_data["basement"]
    if plot_area_m2 <= 1000:
        bsmt_setback = bsmt_rules["setback_upto_1000sqm_m"]
    elif plot_area_m2 <= 2000:
        bsmt_setback = bsmt_rules["setback_1000_to_2000sqm_m"]
    else:
        bsmt_setback = bsmt_rules["setback_above_2000sqm_m"]

    return {
        # Identity
        "city":          "hyderabad",
        "authority":     "GHMC / HMDA",
        "zone":          canon_zone,
        "zone_display":  _zone_display(canon_zone),
        "locality":      locality,
        "usage":         usage,

        # Plot
        "plot_area":       plot_area_sqft,
        "plot_area_sqm":   plot_area_m2,
        "plot_length_m":   plot_length_m,
        "plot_width_m":    plot_width_m,
        "road_width_m":    road_width_m,

        # FAR
        "far":            far_val,
        "far_base":       far_val,
        "far_tdr":        0.0,
        "max_built_area": max_built_sqft,
        "max_built_sqm":  max_built_m2,

        # Coverage & footprint
        "ground_coverage_pct": cov_pct,
        "footprint_sqm":   footprint_m2,
        "footprint_sqft":  footprint_sqft,

        # Setbacks
        "setbacks": {
            "front":              front_m,
            "side":               side_m,
            "rear":               rear_m,
            "corner_relaxation":  corner_plot,
            "high_rise_rule":     is_high_rise,
            "allround_m":         sb.get("allround", side_m) if is_high_rise else None,
        },

        # Height
        "building_height_m":  effective_ht,
        "requested_height_m": building_height_m,
        "height_capped":      ht_capped,
        "floor_height_m":     floor_height_m,
        "is_high_rise":       is_high_rise,

        # Staircase / floors
        "staircase": {
            "num_floors":    num_floors,
            "label":         stair_label,
            "stair_width_m": stair_width_m,
            "lift_mandatory": lift_mandatory,
        },
        "min_floors_for_max_far": min_floors_for_far,

        # Fire
        "fire_data": {
            "noc_required": noc_req,
            "rules":        fire_rules,
        },
        "fire_rules": fire_rules,

        # Parking
        "parking": {
            "required": {
                "cars":         parking["cars"],
                "two_wheelers": parking["two_wheelers"],
            },
            "pct_of_bua": parking["pct_of_bua"],
            "parking_area_sqm": parking["parking_area_sqm"],
        },

        # Basement
        "basement": {
            "requested":      basement,
            "permitted":      plot_area_m2 >= 750,
            "setback_m":      bsmt_setback,
            "counted_in_far": False,
            "note": (
                f"Basement/cellar permitted for parking only. "
                f"Setback {bsmt_setback} m from property boundary. "
                f"Not counted in FAR. Max 10% for utilities."
            ),
        },

        # Compliance & warnings
        "compliance":        compliance,
        "warnings":          warnings,
        "section_summaries": section_summaries,
        "planning_zone":     "hyderabad_hmda",
        "bylaw_ref":         "AP Building Rules 2012 — G.O.Ms.No.168, Dated 07-04-2012",

        # ── Enriched bylaw sections ────────────────────────────────
        "accessibility":         accessibility_data,
        "open_space":            open_space_data,
        "solar": {
            "mandatory": solar_mandatory,
            **rules_data["solar"],
        },
        "water_recycling":       rules_data["water_recycling"],
        "rainwater_harvesting":  rules_data["rainwater_harvesting"],
        "sanction_clearance":    rules_data["sanction_clearance"],
        "occupancy_certificate": rules_data["occupancy_certificate"],
        "height_exemptions":     rules_data["height_exemptions"],
    }