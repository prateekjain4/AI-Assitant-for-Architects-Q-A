"""
anekal_planning_service.py
──────────────────────────
Full planning calculation for Anekal Local Planning Area (BMRDA).
Regulations: Master Plan for Anekal LPA 2031 — Zoning Regulations
G.O. No. UDD 151 BMR 2013 Dated 03.09.2014.

Output shape mirrors calculate_hyderabad_planning() for frontend reuse.
"""
import json
import math
from pathlib import Path

# ── Load rules JSON once ────────────────────────────────────────────────────────
_RULES_PATH = Path(__file__).parent.parent.parent / "city_rules" / "anekal_lpa.json"
_rules: dict | None = None


def _load() -> dict:
    global _rules
    if _rules is None:
        with open(_RULES_PATH, encoding="utf-8") as f:
            _rules = json.load(f)
    return _rules


# ── Unit helpers ────────────────────────────────────────────────────────────────
def _sqm_to_sqft(sqm: float) -> float:
    return round(sqm * 10.7639, 2)


# ── Zone normalisation ──────────────────────────────────────────────────────────
_ZONE_MAP: dict[str, str] = {
    "R":           "R",
    "RESIDENTIAL": "R",
    "C":           "C",
    "COMMERCIAL":  "C",
    "I":           "I",
    "INDUSTRIAL":  "I",
    "IT":          "I",
    "ITBT":        "I",
    "IT_BT":       "I",
    "PSP":         "PSP",
    "PUBLIC":      "PSP",
    "SEMIPUBLIC":  "PSP",
    "PU":          "PU",
    "UTILITY":     "PU",
    "OS":          "OS",
    "OPENSPACE":   "OS",
    "PARK":        "OS",
    "TC":          "TC",
    "TRANSPORT":   "TC",
    "AG":          "AG",
    "AGRICULTURE": "AG",
    "RURAL":       "AG",
}


def _normalise_zone(zone: str) -> str:
    z = zone.upper().strip().replace(" ", "").replace("-", "_")
    return _ZONE_MAP.get(z, "R")


def _zone_display(zone: str) -> str:
    rules = _load()
    label = rules["zones"].get(zone, {}).get("label", zone)
    return f"{zone} — {label}"


# ── Helpers ──────────────────────────────────────────────────────────────────────
_GROUP_HOUSING_USAGES = ("group_housing", "apartment", "multi_family",
                          "group housing", "multifamily")
_FLATTED_FACTORY_USAGES = ("flatted_factory", "flatted factory", "small_industry")


def _is_group_housing(usage: str) -> bool:
    u = usage.lower().strip()
    return any(gh in u for gh in _GROUP_HOUSING_USAGES)


def _is_flatted_factory(usage: str) -> bool:
    u = usage.lower().strip()
    return any(ff in u for ff in _FLATTED_FACTORY_USAGES)


# ── FAR lookup ──────────────────────────────────────────────────────────────────
def _get_far(zone: str, road_width_m: float, plot_area_sqm: float,
             usage: str = "residential") -> float:
    """Return FAR for the given zone/road combination (Table 4 / Table 6)."""
    rules = _load()

    if zone == "I":
        return _get_industrial_far(plot_area_sqm, usage)

    if zone == "AG":
        return 1.0

    # Table 6 — Group housing: plot ≥1 ha AND road ≥12m in R zone
    gh = rules["far_group_housing"]
    if (zone == "R"
            and _is_group_housing(usage)
            and plot_area_sqm >= gh["min_plot_ha"] * 10_000
            and road_width_m >= gh["min_road_m"]):
        for tier in gh["tiers"]:
            if road_width_m <= tier["road_max"]:
                return tier["far"]
        return gh["tiers"][-1]["far"]

    # Table 4 — Standard FAR by road width
    cat = "residential" if zone == "R" else ("commercial" if zone == "C" else "psp")
    for tier in rules["far_by_road_width"][cat]:
        if road_width_m <= tier["road_max"]:
            return tier["far"]
    return rules["far_by_road_width"][cat][-1]["far"]


def _get_industrial_far(plot_area_sqm: float, usage: str) -> float:
    rules = _load()
    # Table 9 — Flatted factories get their own FAR
    if _is_flatted_factory(usage):
        ff = rules["flatted_factories"]
        return ff["far_road_above_12m"]  # conservative: use higher tier

    if "it" in usage.lower() or "bt" in usage.lower():
        tiers = rules["it_bt_by_plot_area"]["tiers"]
    else:
        tiers = rules["industrial_by_plot_area"]["tiers"]
    for tier in tiers:
        if plot_area_sqm <= tier["plot_max_sqm"]:
            return tier["far"]
    return tiers[-1]["far"]


# ── Ground coverage ─────────────────────────────────────────────────────────────
def _get_coverage(zone: str, plot_area_sqm: float, usage: str,
                  road_width_m: float = 9.0) -> int:
    rules = _load()

    if zone == "I":
        # Table 9 — Flatted factories
        if _is_flatted_factory(usage):
            return rules["flatted_factories"]["max_coverage_pct"]
        if "it" in usage.lower() or "bt" in usage.lower():
            tiers = rules["it_bt_by_plot_area"]["tiers"]
        else:
            tiers = rules["industrial_by_plot_area"]["tiers"]
        for tier in tiers:
            if plot_area_sqm <= tier["plot_max_sqm"]:
                return tier["coverage_pct"]
        return tiers[-1]["coverage_pct"]

    # Table 6 — Group housing coverage (varies by road width)
    gh = rules["far_group_housing"]
    if (zone == "R"
            and _is_group_housing(usage)
            and plot_area_sqm >= gh["min_plot_ha"] * 10_000
            and road_width_m >= gh["min_road_m"]):
        for tier in gh["tiers"]:
            if road_width_m <= tier["road_max"]:
                return tier["coverage_pct"]
        return gh["tiers"][-1]["coverage_pct"]

    return rules["zones"].get(zone, {}).get("ground_coverage_pct", 60)


# ── Setback lookup ──────────────────────────────────────────────────────────────
def _get_setbacks(zone: str, plot_width_m: float, plot_length_m: float,
                  road_width_m: float, building_height_m: float,
                  plot_area_sqm: float, corner_plot: bool,
                  usage: str) -> dict:
    """
    Returns setbacks (m) for the given plot and building height.
    - Buildings ≤ 10m: Table 2 (site-width-based)
    - Buildings > 10m: Table 3 (height-based all-round)
    """
    rules = _load()
    site_width = min(plot_width_m, plot_length_m)

    # Industrial plots use their own setback tables
    if zone == "I":
        return _get_industrial_setbacks(plot_area_sqm, usage, building_height_m)

    # Large plot override: plots ≥4000 sqm → minimum 5.0m all sides
    large_plot_min = 0.0
    if plot_area_sqm >= rules["setbacks_standard"]["large_plot_threshold_sqm"]:
        large_plot_min = rules["setbacks_standard"]["large_plot_min_all_m"]

    if building_height_m > 10.0:
        # Table 3: all-round setback by height
        all_round = 4.5  # default
        for entry in rules["setbacks_high_rise"]["by_height"]:
            if entry["height_above"] < building_height_m <= entry["height_upto"]:
                all_round = entry["all_round_m"]
                break

        all_round = max(all_round, large_plot_min)
        # Front: max(road-based front from Table 2, all-round)
        road_front = _road_based_front(road_width_m)
        front = max(road_front, all_round)
        return {
            "front": front, "rear": all_round,
            "side_left": all_round, "side_right": all_round,
            "all_round": all_round, "high_rise_rule": True,
        }

    # Table 2: site-width-based setbacks for buildings ≤10m
    tiers = rules["setbacks_standard"]["by_site_width"]
    row = tiers[-1]
    for tier in tiers:
        if site_width <= tier["site_width_max"]:
            row = tier
            break

    front = max(row["front_m"], large_plot_min)
    rear  = max(row["rear_m"],  large_plot_min)
    sl    = max(row["side_left_m"],  large_plot_min)
    sr    = max(row["side_right_m"], large_plot_min)

    if corner_plot:
        # Both street-facing sides get front setback
        sr = max(sr, front)

    return {
        "front": front, "rear": rear,
        "side_left": sl, "side_right": sr,
        "all_round": None, "high_rise_rule": False,
    }


def _road_based_front(road_width_m: float) -> float:
    """Approximate front setback from Table 2 based on road width alone."""
    if road_width_m <= 6:
        return 1.0
    elif road_width_m <= 9:
        return 1.5
    elif road_width_m <= 12:
        return 2.0
    elif road_width_m <= 18:
        return 2.5
    elif road_width_m <= 24:
        return 3.0
    return 4.0


def _get_industrial_setbacks(plot_area_sqm: float, usage: str,
                              building_height_m: float) -> dict:
    rules = _load()
    if "it" in usage.lower() or "bt" in usage.lower():
        tiers = rules["it_bt_by_plot_area"]["tiers"]
        for tier in tiers:
            if plot_area_sqm <= tier["plot_max_sqm"]:
                ar = tier["all_round_setback_m"]
                front = max(tier["front_setback_m"], ar)
                return {
                    "front": front, "rear": ar,
                    "side_left": ar, "side_right": ar,
                    "all_round": ar, "high_rise_rule": False,
                }
        t = tiers[-1]
        return {"front": t["front_setback_m"], "rear": t["all_round_setback_m"],
                "side_left": t["all_round_setback_m"], "side_right": t["all_round_setback_m"],
                "all_round": t["all_round_setback_m"], "high_rise_rule": False}

    tiers = rules["industrial_by_plot_area"]["tiers"]
    for tier in tiers:
        if plot_area_sqm <= tier["plot_max_sqm"]:
            return {
                "front": tier["front_setback_m"],
                "rear": tier["side_setback_m"],
                "side_left": tier["side_setback_m"],
                "side_right": tier["side_setback_m"],
                "all_round": None, "high_rise_rule": False,
            }
    t = tiers[-1]
    return {"front": t["front_setback_m"], "rear": t["side_setback_m"],
            "side_left": t["side_setback_m"], "side_right": t["side_setback_m"],
            "all_round": None, "high_rise_rule": False}


# ── Height calculation ──────────────────────────────────────────────────────────
def _auto_height(plot_area_sqm: float, road_width_m: float, zone: str) -> float:
    """Estimate optimal building height from road width constraints."""
    rules = _load()
    is_hr = rules["high_rise_threshold_m"]
    if road_width_m < 9:
        return 10.0
    elif road_width_m < 12:
        return is_hr
    elif road_width_m < 18:
        return 21.0
    elif road_width_m < 24:
        return 27.0
    return 40.0


# ── Parking ─────────────────────────────────────────────────────────────────────
def _get_parking(usage: str, built_sqm: float, plot_area_sqm: float) -> dict:
    rules = _load()
    u = usage.lower()

    if "residential" in u:
        if "multi" in u or "apartment" in u or "group" in u:
            cars = math.ceil(built_sqm / 100)
        else:
            cars = math.ceil(built_sqm / 120)
    elif "hotel" in u or "lodg" in u:
        cars = math.ceil(built_sqm / (6 * 30))  # approx 1 per 6 rooms (~30 sqm/room)
    elif "hospital" in u:
        cars = math.ceil(built_sqm / 100)
    elif "educational" in u or "school" in u or "college" in u:
        cars = math.ceil(built_sqm / 200)
    elif "industrial" in u or "it" in u or "bt" in u:
        cars = math.ceil(built_sqm / 100)
    else:
        # office, retail, restaurant, etc.
        cars = math.ceil(built_sqm / 75)

    cars = max(1, cars)
    scooters = math.ceil(cars * 0.25)

    return {
        "cars": cars,
        "scooters": scooters,
        "car_area_sqm": round(cars * 13.75, 1),
        "note": rules["parking"]["car_dimensions"],
    }


# ── Fire NOC ─────────────────────────────────────────────────────────────────────
def _fire_noc_required(height_m: float, usage: str, plot_sqm: float) -> bool:
    rules = _load()
    threshold = rules["fire_safety"]["high_rise_noc_above_m"]
    if height_m >= threshold:
        return True
    psp_types = ("hospital", "cinema", "educational", "assembly",
                 "function_hall", "institutional", "nursing_home")
    if any(t in usage.lower() for t in psp_types) and plot_sqm >= 300:
        return True
    return False


def _get_fire_rules(height_m: float, usage: str) -> list[str]:
    rules = _load()
    if height_m >= rules["fire_safety"]["high_rise_noc_above_m"]:
        return rules["fire_safety"]["requirements_above_15m"]
    return []


# ── Staircase / lift ─────────────────────────────────────────────────────────────
def _staircase_info(num_floors: int, built_sqm: float) -> dict:
    # Anekal adopts BBMP byelaws for stair details
    label = f"G+{num_floors - 1}" if num_floors > 1 else "G"
    lift = num_floors >= 5  # G+4 is the high-rise threshold
    stair_width = 1.0 if num_floors <= 2 else (1.5 if num_floors <= 5 else 2.0)
    return {
        "label": label,
        "num_floors": num_floors,
        "lift_mandatory": lift,
        "stair_width_m": stair_width,
    }


# ── Accessibility ─────────────────────────────────────────────────────────────────
def _get_accessibility(usage: str, plot_sqm: float) -> dict:
    rules = _load()
    acc = rules["accessibility"]
    psp_types = ("institutional", "hospital", "educational", "public",
                 "assembly", "psp", "cinema", "function_hall")
    required = any(t in usage.lower() for t in psp_types) or plot_sqm >= acc["mandatory_above_sqm"]
    return {
        "required": required,
        "access_path_width_m": acc["access_path_width_m"] if required else None,
        "max_gradient_pct": acc["max_gradient_pct"] if required else None,
    }


# ── Compliance warnings ────────────────────────────────────────────────────────
def _build_compliance(
    zone: str, usage: str, road_width_m: float, building_height_m: float,
    plot_area_sqm: float, fire_noc: bool, basement: bool,
) -> list[str]:
    rules = _load()
    items: list[str] = []

    if fire_noc:
        items.append(f"Fire NOC required: building height {building_height_m:.1f}m exceeds 15m threshold (NBC 2016 Part IV applies)")

    # Group housing note
    gh = rules["far_group_housing"]
    if (zone == "R" and _is_group_housing(usage)
            and plot_area_sqm >= gh["min_plot_ha"] * 10_000
            and road_width_m >= gh["min_road_m"]):
        items.append(
            "Group Housing FAR applied (Table 6): plot ≥1 ha + road ≥12m qualifies for "
            "higher FAR. Mandatory: 5% civic amenity land, 10% parks/open space, "
            "10% visitor parking of total area."
        )
    elif _is_group_housing(usage) and plot_area_sqm < gh["min_plot_ha"] * 10_000:
        items.append(
            f"Group Housing (Table 6) FAR not applied: plot {plot_area_sqm:.0f} sqm < "
            "10,000 sqm (1 ha) minimum. Standard residential FAR used."
        )

    # Flatted factory note
    if zone == "I" and _is_flatted_factory(usage):
        items.append(
            "Flatted Factory (Table 9): non-hazardous small industrial units, max 50 workers. "
            "Min plot 1000 sqm, max coverage 40%, approach road ≥12m required."
        )

    rh = rules["rainwater_harvesting"]
    if plot_area_sqm >= rh["mandatory_plot_area_sqm"]:
        items.append("Rainwater harvesting mandatory (Section 11.3.11 — plot ≥ 9m×12m)")

    if "residential" in usage.lower() and plot_area_sqm >= 400:
        items.append("Solar water heater mandatory: residential plot ≥ 400 sqm (Table 14)")

    wb = rules["water_body_buffers"]
    items.append(
        f"Water body setbacks apply: lake ≥40ha → {wb['lake_above_40ha_m']}m, "
        f"smaller lakes → {wb['lake_others_m']}m, canals → {wb['canal_raj_kaluve_m']}m"
    )

    if basement:
        items.append("Basement: may extend in setbacks except front; min 1.5m from property line")

    if building_height_m > 10:
        items.append(f"All-round setback applies (Table 3) as building exceeds 10m height")

    if plot_area_sqm >= rules["setbacks_standard"]["large_plot_threshold_sqm"]:
        items.append("Plot ≥ 4000 sqm: minimum 5.0m setback on all sides (Table 2 note)")

    return items


# ── Main calculation ────────────────────────────────────────────────────────────
def calculate_anekal_planning(
    zone:              str,
    plot_length_m:     float,
    plot_width_m:      float,
    road_width_m:      float,
    building_height_m: float = 0,
    usage:             str   = "residential",
    corner_plot:       bool  = False,
    basement:          bool  = False,
    floor_height_m:    float = 3.0,
    locality:          str   = "Anekal",
) -> dict:
    rules = _load()

    zone = _normalise_zone(zone)
    usage = usage.lower().strip()

    plot_area_sqm  = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(_sqm_to_sqft(plot_area_sqm), 2)

    # FAR and coverage
    far = _get_far(zone, road_width_m, plot_area_sqm, usage)
    gc_pct = _get_coverage(zone, plot_area_sqm, usage, road_width_m)

    # Auto-compute height if not supplied
    if building_height_m <= 0:
        building_height_m = _auto_height(plot_area_sqm, road_width_m, zone)

    is_high_rise = building_height_m >= rules["high_rise_threshold_m"]

    # Setbacks
    sb = _get_setbacks(
        zone, plot_width_m, plot_length_m, road_width_m,
        building_height_m, plot_area_sqm, corner_plot, usage,
    )

    # Max built-up area from FAR
    max_built_sqm  = round(plot_area_sqm * far, 2)
    max_built_sqft = round(_sqm_to_sqft(max_built_sqm), 2)

    # Footprint from coverage and setbacks
    front = sb["front"]
    rear  = sb["rear"]
    sl    = sb["side_left"]
    sr    = sb["side_right"]

    fp_gc  = plot_area_sqm * (gc_pct / 100)
    fp_sb  = max(0.0, plot_length_m - front - rear) * max(0.0, plot_width_m - sl - sr)
    fp_sqm = round(min(fp_gc, fp_sb), 2)
    fp_sqft= round(_sqm_to_sqft(fp_sqm), 2)

    # Floors
    fh = floor_height_m or 3.0
    num_floors = max(1, math.ceil(building_height_m / fh))

    # Fire
    fire_noc   = _fire_noc_required(building_height_m, usage, plot_area_sqm)
    fire_rules = _get_fire_rules(building_height_m, usage)

    # Parking
    parking = _get_parking(usage, max_built_sqm, plot_area_sqm)

    # Staircase
    stair = _staircase_info(num_floors, max_built_sqm)

    # Accessibility
    accessibility = _get_accessibility(usage, plot_area_sqm)

    # Compliance
    compliance = _build_compliance(
        zone, usage, road_width_m, building_height_m,
        plot_area_sqm, fire_noc, basement,
    )

    warnings: list[str] = []
    if road_width_m < 9 and is_high_rise:
        warnings.append("Warning: road width < 9m is insufficient for high-rise construction")
    if zone == "AG":
        warnings.append("Agricultural zone: max FAR 1.0, max G+1 floor permitted")
    if zone == "OS":
        warnings.append("Open Space zone: development highly restricted; verify with authority")

    solar = rules["solar"]
    rw    = rules["rainwater_harvesting"]
    acc   = rules["accessibility"]

    return {
        # Identity
        "city":           "anekal",
        "authority":      "Anekal Planning Authority / BMRDA",
        "zone":           zone,
        "zone_display":   _zone_display(zone),
        "locality":       locality,
        "usage":          usage,
        "bylaw_ref":      "Master Plan for Anekal LPA 2031 — Zoning Regulations (G.O. No. UDD 151 BMR 2013)",
        "far_table":      ("Table 6 — Group Housing" if _is_group_housing(usage) and plot_area_sqm >= 10_000 and road_width_m >= 12 and zone == "R"
                           else "Table 9 — Flatted Factory" if zone == "I" and _is_flatted_factory(usage)
                           else "Table 4 — Standard FAR"),

        # Plot
        "plot_area":      plot_area_sqft,
        "plot_area_sqm":  plot_area_sqm,
        "plot_length_m":  plot_length_m,
        "plot_width_m":   plot_width_m,
        "road_width_m":   road_width_m,

        # FAR & built-up
        "far":            far,
        "max_built_area": max_built_sqft,
        "max_built_sqm":  max_built_sqm,

        # Coverage & footprint
        "ground_coverage_pct": gc_pct,
        "footprint_sqm":  fp_sqm,
        "footprint_sqft": fp_sqft,

        # Setbacks
        "setbacks": {
            "front":         front,
            "rear":          rear,
            "side_left":     sl,
            "side_right":    sr,
            "all_round":     sb.get("all_round"),
            "high_rise_rule": sb["high_rise_rule"],
            "corner_plot":   corner_plot,
        },

        # Height & floors
        "building_height_m": building_height_m,
        "is_high_rise":      is_high_rise,
        "floor_height_m":    fh,
        "num_floors":        num_floors,

        # Staircase & lift
        "staircase": stair,

        # Fire & safety
        "fire_data": {
            "noc_required": fire_noc,
            "rules":        fire_rules,
            "threshold_m":  rules["fire_safety"]["high_rise_noc_above_m"],
        },

        # Parking (Table 11)
        "parking": {
            "required":   {"cars": parking["cars"], "scooters": parking["scooters"]},
            "car_area_sqm": parking["car_area_sqm"],
            "note":       parking["note"],
        },

        # Basement
        "basement": {
            "requested":   basement,
            "permitted":   zone not in ("OS",),
            "setback_m":   1.5,
            "counted_in_far": False,
            "max_projection_above_ground_m": rules["basement"]["max_projection_above_ground_m"],
        },

        # Compliance & warnings
        "compliance":  compliance,
        "warnings":    warnings,

        # Supplementary data
        "accessibility":         accessibility,
        "solar":                 solar,
        "rainwater_harvesting":  rw,
        "water_body_buffers":    rules["water_body_buffers"],
        "transit_tod_far_bonus": rules["transit_oriented_development"]["additional_far"],

        "planning_zone": "anekal_lpa",
    }


# ── Permissible usages ─────────────────────────────────────────────────────────
_ZONE_USAGES: dict[str, list[str]] = {
    "R": ["residential", "apartment", "group_housing", "hostel", "school",
          "kindergarten", "library", "place_of_worship", "bank", "nursing_home",
          "hospital", "service_apartment"],
    "C": ["residential", "retail", "office", "hotel", "restaurant", "bank",
          "educational", "hospital", "nursing_home", "cinema", "mall",
          "multiplex", "commercial_complex", "warehouse", "filling_station",
          "service_industry", "cultural"],
    "I": ["light_industry", "medium_industry", "heavy_industry", "it_bt",
          "warehouse", "bus_terminal", "filling_station", "office"],
    "PSP": ["govt_office", "educational", "hospital", "cultural", "library",
            "police_station", "fire_station", "research_institution", "sports_complex"],
    "PU": ["power_substation", "water_treatment", "sewage_treatment",
           "solid_waste_management", "telecom_tower", "fire_station"],
    "OS": ["park", "playground", "stadium", "sports_complex", "cemetery"],
    "TC": ["bus_stand", "railway", "metro_station", "airport", "parking",
           "filling_station", "transport_office"],
    "AG": ["agriculture", "horticulture", "dairy_farm", "poultry_farm",
           "farm_house", "eco_tourism"],
}


def get_allowed_usages_for_anekal_zone(zone: str, road_width: float = 9.0) -> list[str]:
    z = _normalise_zone(zone)
    return _ZONE_USAGES.get(z, _ZONE_USAGES["R"])