from app.services.services import get_openai_client
from app.services.city_rules_engine import (
    get_far, get_setbacks, lift_mandatory_floors,
    get_basement_rules, get_basement_ventilation, get_balcony_rules,
    get_accessibility_rules, get_compound_wall_rules,
    validate_usage_in_zone, validate_space_standards,
    get_usage_staircase_width, get_staircase_height_threshold, get_staircase_count_threshold,
    is_solar_required, get_solar_note,
    get_hotel_basement_uses, get_fire_travel_distance,
    get_fire_tender_access, get_fire_refuge_area, get_rainwater_harvesting,
)
from shapely.geometry import Polygon
from pyproj import Transformer
from shapely.ops import transform
import math
from app.services.parking_service import calculate_parking
from app.services.proximity_service import check_water_body_proximity, check_rajkaluve_proximity

# ─────────────────────────────────────────────────────────────────
# Area calculation
# ─────────────────────────────────────────────────────────────────
def calculate_area_sqft(coords_lng_lat: list) -> float:
    polygon_wgs84 = Polygon(coords_lng_lat)
    transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:32643",
        always_xy=True
    )
    polygon_utm = transform(transformer.transform, polygon_wgs84)
    return round(polygon_utm.area * 10.7639, 2)


# ─────────────────────────────────────────────────────────────────
# Bylaw context from FAISS — called INSIDE the function, not outside
# ─────────────────────────────────────────────────────────────────
def get_bylaw_context(question: str) -> str:
    """Pull relevant bylaw sections from FAISS for a specific question."""
    from app.services.services import answer_question_from_bylaws
    result = answer_question_from_bylaws(question)
    return result.get("answer", "")


# ─────────────────────────────────────────────────────────────────
# Ground coverage — delegated to city_rules_engine (BDA RMP 2031)
# ─────────────────────────────────────────────────────────────────
def get_ground_coverage(zone: str, road_width: float, plot_area_sqm: float = 200.0,
                        planning_zone: str = "zone_A") -> int:
    return get_far(zone, road_width, plot_area_sqm, planning_zone).get("coverage_pct", 60)


# ─────────────────────────────────────────────────────────────────
# Fire requirements
# ─────────────────────────────────────────────────────────────────
def get_fire_requirements(building_height: float, max_built_area: float, usage: str) -> dict:
    fire = {
        "noc_required": False,
        "requirements": [],
        "tender_access": {},
        "refuge_area": {},
        "thresholds_note": "",
        "travel_distance_m": get_fire_travel_distance(usage),
        "travel_distance_note": (
            f"Max travel distance to exit: {get_fire_travel_distance(usage)}m "
            f"for {usage} use (NBC 2016 Part IV)"
        ),
    }

    _non_residential = usage.lower() not in ("residential", "residential_single", "dwelling")
    if building_height > 15:
        fire["noc_required"] = True
        fire["thresholds_note"] = "Fire NOC from KSFES mandatory above 15m"
    elif max_built_area > 5000 and _non_residential:
        # BDA RMP 2031: non-residential buildings ≥ 5,000 sqm BUA require fire arrangements
        fire["noc_required"] = True
        fire["thresholds_note"] = "Fire NOC mandatory for non-residential buildings ≥ 5,000 sqm BUA (BDA RMP 2031)"

    if building_height > 9:
        _stair_w = "1.5m" if building_height > 15 else "1.2m"
        fire["requirements"] += [
            f"Fire escape staircase — minimum {_stair_w} clear width",
            "Fire-rated doors on staircase landings",
            "Emergency lighting in corridors and staircases",
        ]
        _ta = get_fire_tender_access()
        fire["tender_access"] = {
            "required": True,
            "min_road_width_m":       _ta.get("min_road_width_m", 4.5),
            "min_height_clearance_m": _ta.get("min_height_clearance_m", 4.5),
            "turning_radius_m":       _ta.get("turning_radius_m", 9.0),
            "dead_end_max_m":         _ta.get("dead_end_max_m", 45),
            "note":                   _ta.get("note", "Fire tender access road required on at least 3 sides above 15m (NBC 2016 Part IV Cl. 4.1)"),
        }

    if building_height > 15:
        fire["requirements"] += [
            "Automatic sprinkler system throughout",
            "Fire lift — minimum 1.1m × 2.1m car, 630kg capacity",
            "Wet riser system",
            "Public address system",
            "Fire detection and alarm system",
            "Hose reel and extinguishers on every floor",
            "Terrace tank — minimum 25,000 litres",
        ]

    if building_height > 24:
        fire["requirements"] += [
            "Fire command centre at ground level",
            "Pressurisation of staircases",
            "Two separate fire escape staircases mandatory",
        ]
        _ra = get_fire_refuge_area()
        fire["refuge_area"] = {
            "required":     True,
            "frequency":    f"Every {_ra.get('frequency_floors', 7)} floors",
            "min_area_sqm": _ra.get("min_area_sqm", 15),
            "note":         _ra.get("note", "Refuge area NOT counted in FAR (NBC 2016 Part IV Section 4.11)"),
        }

    return fire
# ─────────────────────────────────────────────────────────────────
# Feasibility & Compliance requirements
# ─────────────────────────────────────────────────────────────────
def generate_feasibility_summary(plot_area, max_built_area, far_floors):
    avg_unit_size = 84  # sqm (~900 sqft per unit)
    total_units = int(max_built_area / avg_unit_size)

    typology = "Apartment" if far_floors >= 4 else "Independent Floors"

    risk = "High" if far_floors >= 5 else "Medium" if far_floors >= 3 else "Low"

    return {
        "typology": typology,
        "floors": f"G+{far_floors-1}",
        "units": total_units,
        "risk": risk,
        "approval": f"{80 - (far_floors * 5)}%"
    }


def generate_design_options(far_floors, max_built_area):
    return [
        {
            "title": "Max FAR Apartment",
            "floors": f"G+{far_floors-1}",
            "units": int(max_built_area / 84),    # ~900 sqft per unit
            "parking": "Basement required",
            "risk": "High"
        },
        {
            "title": "Balanced Development",
            "floors": f"G+{max(2, far_floors-2)}",
            "units": int(max_built_area / 111),    # ~1200 sqft per unit
            "parking": "Stilt + surface",
            "risk": "Medium"
        },
        {
            "title": "Low Density",
            "floors": "G+1",
            "units": 1,
            "parking": "Surface",
            "risk": "Low"
        }
    ]


def generate_compliance_score(fire_data, parking, far_floors):
    score = 100
    issues = []

    if fire_data.get("noc_required"):
        score -= 15
        issues.append("Fire NOC required")

    cars_required = parking.get("required", {}).get("cars", 0)
    if cars_required > 50:
        score -= 10
        issues.append("High parking demand")

    if far_floors >= 5:
        score -= 10
        issues.append("High-rise complexity")

    if score >= 80:
        status = "Low Risk"
    elif score >= 60:
        status = "Moderate Risk"
    else:
        status = "High Risk"

    return {
        "score": score,
        "status": status,
        "issues": issues
    }

# ─────────────────────────────────────────────────────────────────
# Staircase & lift requirements
# ─────────────────────────────────────────────────────────────────
def get_staircase_requirements(
    building_height: float, max_built_area: float, far_floors: float,
    usage: str = "residential"
) -> dict:
    num_floors = far_floors if far_floors > 0 else math.ceil(building_height / 3.2)

    # Height-based minimum (BBMP Bye-Laws 2003 — read from bbmp_bylaws.json)
    ht = get_staircase_height_threshold(building_height)
    height_min = ht["min_clear_width_m"]
    width_note = ht["note"]

    # Usage-based minimum (BBMP Bye-Laws 2003 Sec 20.6)
    usage_min = get_usage_staircase_width(usage, building_height)
    min_width = max(height_min, usage_min)

    # Override note when usage drives the width
    u = usage.lower()
    if usage_min > height_min:
        if any(k in u for k in ("hospital", "nursing", "institutional")):
            width_note = f"Minimum {min_width}m for institutional/hospital buildings (BBMP Bye-Laws 2003 Sec 20.6)"
        elif any(k in u for k in ("hotel", "hostel", "lodge")):
            width_note = f"Minimum {min_width}m for hotel/hostel buildings (BBMP Bye-Laws 2003 Sec 20.6)"
        elif any(k in u for k in ("school", "college", "educational")):
            width_note = f"Minimum {min_width}m for educational buildings (BBMP Bye-Laws 2003 Sec 20.6)"
        elif any(k in u for k in ("assembly", "cinema", "theatre")):
            width_note = f"Minimum {min_width}m for assembly/cinema buildings (BBMP Bye-Laws 2003 Sec 20.6)"

    _stair_threshold = get_staircase_count_threshold()
    if max_built_area > _stair_threshold:
        num_staircases = 2
        staircase_note = f"2 staircases mandatory above {_stair_threshold} sqm BUA (BBMP Bye-Laws 2003)"
    else:
        num_staircases = 1
        staircase_note = "1 staircase sufficient for this BUA"

    lift_mandatory = num_floors > lift_mandatory_floors()   # BDA: mandatory above G+3
    lift_note = (
        f"Lift mandatory — {num_floors} floors (above G+3 per BDA RMP 2031)"
        if lift_mandatory
        else f"Lift not mandatory — {num_floors} floors (G+{num_floors - 1})"
    )

    return {
        "min_staircase_width_m": min_width,
        "staircase_note":        width_note,
        "num_staircases":        num_staircases,
        "staircase_extra":       staircase_note,
        "lift_mandatory":        lift_mandatory,
        "lift_note":             lift_note,
        "num_floors":            num_floors,
    }


# ─────────────────────────────────────────────────────────────────
# Basement regulations
# ─────────────────────────────────────────────────────────────────
def get_basement_regulations(plot_area_sqm: float, basement_requested: bool) -> dict:
    if not basement_requested:
        return {"requested": False}

    bsmt = get_basement_rules()
    vent = get_basement_ventilation()
    vent_note = (
        f"Mechanical ventilation mandatory — minimum {vent.get('min_air_changes_per_hour', 6)} "
        f"air changes per hour (NBC 2016)"
    )
    fire_key = "fire_requirements_above_200sqm" if plot_area_sqm > 200 else "fire_requirements_small_plot"
    return {
        "requested":     True,
        "max_basements": bsmt.get("max_levels_for_parking", 5),
        "permitted_uses": bsmt.get("permitted_uses", [
            "Car parking (primary use — up to 5 levels)",
            "Electrical room, pump room, generator",
            "AC handling units and utilities/services",
        ]),
        "not_permitted": bsmt.get("not_permitted", [
            "Habitable rooms or residential use",
            "Retail or commercial use",
            "Kitchens or restaurants",
        ]),
        "setback_in_basement": (
            f"Minimum {bsmt.get('setbacks', {}).get('min_from_boundary_m', 2.0)} m from plot boundary; "
            f"+{bsmt.get('setbacks', {}).get('additional_per_extra_level_m', 1.0)} m per additional level "
            f"(BDA RMP 2031 Sec 4.9.2 / BBMP Bye-Laws 2003 Sec 18)"
        ),
        "ventilation":     vent_note,
        "max_depth_m":     bsmt.get("max_overall_height_m", 4.5),
        "far_counted":     bsmt.get("far_counted", False),
        "far_note":        bsmt.get("far_note", "Basement NOT counted in FAR if used for parking/services only"),
        "fire_requirements": bsmt.get(fire_key, [
            "Sprinklers mandatory in basement regardless of height",
            "Minimum 2 means of escape from basement",
            "Smoke extraction system required",
            "Emergency lighting mandatory",
        ]),
    }


# ─────────────────────────────────────────────────────────────────
# Balcony & projection rules
# ─────────────────────────────────────────────────────────────────
def get_projection_rules(road_width: float) -> dict:
    bda_bal = get_balcony_rules()
    ground_str = bda_bal.get("ground_floor", "NOT permitted")
    ground_floor_allowed = bda_bal.get("ground_floor_allowed",
        "not permitted" not in str(ground_str).lower())
    return {
        "balcony_ground_floor_allowed": ground_floor_allowed,
        "balcony_first_floor_max_projection_m": bda_bal.get("first_floor_max_projection_m", 1.20),
        "balcony_above_first_floor_max_projection_m": bda_bal.get(
            "above_second_floor_max_projection_m",
            bda_bal.get("second_floor_and_above_max_projection_m", 1.75)),
        "balcony_far_note": "Balconies excluded from FAR within permitted projection limits (BDA RMP 2031 Sec 4.9.5)",
        "balcony_ground_note": "Ground floor balconies NOT permitted (BDA RMP 2031)",
        "chajja_max_projection_m": 0.75,
        "chajja_note": "Chajja/sun shade up to 0.75m — not counted in FAR",
        "projection_rule": bda_bal.get("max_projection_as_fraction_of_setback",
            bda_bal.get("projection_rule", "1/3rd of setback or max projection limit — whichever is less")),
        "road_overhang_note": f"No projection over road boundary — {road_width}m road setback must be maintained",
    }


# ─────────────────────────────────────────────────────────────────
# FAR exclusions list
# ─────────────────────────────────────────────────────────────────
FAR_EXCLUSIONS = [
    "Staircase and lift shafts (full height)",
    "Lift machine room (up to 16 sqm)",
    "Staircase headroom / mumty (up to 2.4m height)",
    "Basement parking floors — not counted in FAR",
    "Balconies up to 1.5m projection (within 20% of floor area)",
    "Utility ducts and service shafts",
    "Watchman cabin up to 9 sqm at entrance",
    "Refuge area (not counted in FAR per NBC 2016 Part IV Section 4.11)",
    "Ramps for disabled access",
]


# ─────────────────────────────────────────────────────────────────
# Accessibility requirements (BBMP Schedule XI)
# ─────────────────────────────────────────────────────────────────
def get_accessibility_requirements(usage: str, plot_area_sqm: float, zone: str) -> dict:
    rules = get_accessibility_rules()
    mandatory_zones = rules.get("mandatory_for_zones", ["PSP"])
    mandatory_area  = rules.get("mandatory_covered_area_sqm", 300)
    is_psp = zone.upper().startswith("PSP")
    # BBMP Schedule XI: mandatory for all public/semi-public buildings ≥ 300 sqm covered area.
    # Hospitals, hotels, educational, commercial, and institutional are all public buildings.
    _public_usages = {
        "commercial", "mixed", "institutional", "public",
        "hospital", "nursing_home", "nursing", "medical",
        "hotel", "star_hotel", "luxury_hotel", "lodge",
        "educational", "school", "college",
        "restaurant", "retail", "mall", "office",
    }
    is_public_usage = any(k in usage.lower() for k in _public_usages)
    required        = is_psp or (is_public_usage and plot_area_sqm >= mandatory_area)

    return {
        "required":         required,
        "trigger":          f"Mandatory for PSP zones and public/semi-public buildings ≥ {mandatory_area} sqm covered area (BBMP Schedule XI)",
        "ramp":             rules.get("ramp", {}),
        "access_path":      rules.get("access_path", {}),
        "corridor_min_width_m": rules.get("corridor_min_width_m", 1.80),
        "staircase":        rules.get("staircase", {}),
        "lift":             rules.get("lift", {}),
        "wheelchair":       rules.get("wheelchair", {}),
        "toilet":           rules.get("toilet", {}),
        "handrails":        rules.get("handrails", {}),
        "guiding_floor":    rules.get("guiding_floor_material", {}),
        "signage":          rules.get("signage", {}),
        "source":           "BBMP Building Bye-Laws 2003, Schedule XI (Bye-law 31.0)",
    }


# ─────────────────────────────────────────────────────────────────
# Compound / boundary wall rules (BBMP Section 20.8)
# ─────────────────────────────────────────────────────────────────
def get_boundary_wall_rules(corner_plot: bool) -> dict:
    rules = get_compound_wall_rules()
    result = {
        "front_and_side_max_m": rules.get("front_and_side_max_height_m", 1.5),
        "rear_max_m":           rules.get("rear_max_height_m", 2.0),
        "barbed_wire":          rules.get("barbed_wire_fence", "Prohibited"),
        "prickly_hedge":        rules.get("prickly_hedge", "Prohibited"),
        "source":               "BBMP Building Bye-Laws 2003, Section 20.8",
    }
    if corner_plot:
        cp = rules.get("corner_plot", {})
        result["corner_plot_restriction"] = {
            "height_m":         cp.get("restricted_height_m", 0.75),
            "length_from_intersection_m": cp.get("restricted_length_from_intersection_m", 5),
            "note":             cp.get("note", "Corners must be rounded off or chamfered at intersection"),
        }
    return result


# ── BDA height cap by road width (BDA RMP 2031 Table 1 + formula) ─────────
def _max_height_for_road_bda(road_width_m: float) -> float:
    """Return the maximum building height (m) permitted for this road width under BDA norms."""
    if road_width_m < 6.0:
        return 9.0
    if road_width_m < 9.0:
        return 11.5
    if road_width_m < 12.0:
        return 15.0
    if road_width_m < 18.0:
        return 21.0
    if road_width_m < 24.0:
        return 30.0
    return 999.0  # FAR governs on wide roads


# ─────────────────────────────────────────────────────────────────
# Main planning function
# ─────────────────────────────────────────────────────────────────
def calculate_plot_planning(request):
    zone            = request.zone
    road_width      = request.road_width
    building_height = request.building_height or 0
    usage           = request.usage
    locality        = getattr(request, 'locality', 'Bangalore')
    corner_plot     = getattr(request, 'corner_plot', False)
    basement        = getattr(request, 'basement', False)

    building_height_auto = (building_height <= 0)

    # ── Plot Area (all calculations in sqm) ──────────────────────
    # Priority: direct sqft input > polygon coords > length × width
    _direct_sqft = getattr(request, 'plot_area_sqft', None)
    if _direct_sqft and _direct_sqft > 0:
        plot_area_sqm = round(_direct_sqft / 10.7639, 2)
    elif request.coordinates:
        coords    = [(p.lng, p.lat) for p in request.coordinates]
        plot_area_sqm = round(calculate_area_sqft(coords) / 10.7639, 2)
    else:
        plot_length = request.plot_length or 0
        plot_width  = request.plot_width  or 0
        plot_area_sqm = round(plot_length * plot_width, 2)

    planning_zone = getattr(request, 'planning_zone', 'zone_A') or 'zone_A'

    # ── FAR + Ground Coverage (BDA RMP 2031 — zone & plot-size aware) ─────
    far_data            = get_far(zone, road_width, plot_area_sqm, planning_zone)
    far                 = far_data["total"]    # architects want max (base + TDR)
    far_base            = far_data["base"]
    far_tdr             = far_data["tdr"]
    ground_coverage_pct = far_data["coverage_pct"]
    footprint_sqm       = plot_area_sqm * (ground_coverage_pct / 100)
    # ── Max Built Area ────────────────────────────────────────────
    max_built_sqm  = round(plot_area_sqm * far, 2)

    floor_height_m = getattr(request, 'floor_height', 3.2) or 3.2

    # ── Auto-compute most feasible height from FAR + GC ──────────
    # Derive the minimum floors needed to exhaust FAR at the allowed ground coverage,
    # then cap by the road-width height limit so the result is always bylaw-compliant.
    if building_height_auto:
        gc_fraction   = ground_coverage_pct / 100 if ground_coverage_pct > 0 else 0.5
        floors_needed = max(2, math.ceil(far / gc_fraction))
        road_cap      = _max_height_for_road_bda(road_width)
        raw_ht        = floors_needed * floor_height_m
        building_height = raw_ht if road_cap >= 999 else min(raw_ht, road_cap)
        building_height = max(building_height, floor_height_m * 2)  # at least G+1

    # Round to 1 decimal to eliminate floating-point noise (e.g. 3 × 3.2 = 9.600000001)
    building_height = round(building_height, 1)

    # How many floors are feasible?
    # Height is the architectural ceiling — FAR governs total AREA, not floor count.
    # A tall building with small floors is still valid as long as total_built ≤ max_built.
    # Height constraint: how many full floors fit within the declared building height
    far_floors_by_height = max(1, math.floor(round(building_height / floor_height_m, 6)))
    far_floors = max(1, min(far_floors_by_height, 15))

    # ── Setbacks — BDA RMP 2031 progressive table ─────────────────
    far_building_height_for_setbacks = round(far_floors * floor_height_m, 1)
    sb_data      = get_setbacks(plot_area_sqm, far_building_height_for_setbacks, road_width, corner_plot)
    front_setback = sb_data["front"]
    side_setback  = sb_data["side"]
    rear_setback  = sb_data["rear"]

    # Setback-constrained footprint: use actual buildable area, not just GC cap
    plot_length = request.plot_length or 0
    plot_width  = request.plot_width  or 0
    sb_footprint_sqm = max(0.0, plot_length - front_setback - rear_setback) * \
                       max(0.0, plot_width  - side_setback  * 2)
    effective_footprint = min(footprint_sqm, sb_footprint_sqm) if sb_footprint_sqm > 0 else footprint_sqm
    # Informational: minimum floors to exhaust the full FAR budget at the actual buildable footprint
    min_floors_for_max_far = max(1, math.ceil(max_built_sqm / max(effective_footprint, 1)))

    setbacks = {
        "front": front_setback,
        "side":  side_setback,
        "rear":  rear_setback,
        "corner_relaxation": "Side setback reduced by 1m on secondary road side" if corner_plot else None
    }

    # ── Usage validation (permissible use + space standards) ─────
    usage_zone_check   = validate_usage_in_zone(usage, zone, road_width)
    space_std_check    = validate_space_standards(usage, plot_area_sqm, road_width)
    solar_required     = is_solar_required(usage)
    solar_note         = get_solar_note() if solar_required else None

    # ── Computed sections ─────────────────────────────────────────
    far_building_height = far_floors * floor_height_m  # actual buildable height from FAR
    fire_data      = get_fire_requirements(far_building_height, max_built_sqm, usage)
    staircase_data = get_staircase_requirements(far_building_height, max_built_sqm, far_floors, usage)
    basement_data    = get_basement_regulations(plot_area_sqm, basement)

    # Hotel 3-star+ gets additional basement uses
    u_lower = usage.lower()
    if any(k in u_lower for k in ("hotel", "star_hotel", "luxury_hotel")) and basement:
        hotel_bsmt = get_hotel_basement_uses()
        if isinstance(basement_data, dict) and hotel_bsmt:
            basement_data["hotel_special_uses"] = hotel_bsmt
            basement_data["hotel_special_note"] = (
                "3-star+ hotels may use basement for health club, shopping arcade, "
                "dining, banquet/conference and admin office (BDA RMP 2031 Sec 4.9.2)"
            )

    projection_rules = get_projection_rules(road_width)
    accessibility    = get_accessibility_requirements(usage, plot_area_sqm, zone)
    boundary_wall    = get_boundary_wall_rules(corner_plot)

    fire_rules = fire_data["requirements"]

    # ── Parking ───────────────────────────────────────────────────
    parking_data = calculate_parking(
        usage=usage,
        built_up_sqft=round(max_built_sqm * 10.7639, 2),   # parking service uses sqft internally
        num_units=getattr(request, "number_of_units", 1),
        plot_length_m=request.plot_length or 0,
        plot_width_m=request.plot_width or 0,
        basement=basement,
        stilt=False
    )

    parking = parking_data  # return full structured data

    # ── Bylaw context from FAISS — called HERE inside function ────
    setback_context   = get_bylaw_context(
        f"setback requirements plot area {plot_area_sqm} sqm height {building_height}m"
    )
    staircase_context = get_bylaw_context(
        f"staircase width lift requirements building height {building_height}m floors"
    )
    balcony_context   = get_bylaw_context(
        "balcony projection FAR exclusion cantilever chajja rules"
    )
    fire_context      = get_bylaw_context(
        f"fire safety NOC requirements building height {building_height}m sprinkler"
    )
    basement_context  = get_bylaw_context(
        "basement regulations permitted uses ventilation parking"
    ) if basement else ""

    # ── Water body proximity check ─────────────────────────────────
    coords_list = request.coordinates
    if coords_list:
        centroid_lat = sum(c.lat for c in coords_list) / len(coords_list)
        centroid_lng = sum(c.lng for c in coords_list) / len(coords_list)
        water_proximity = check_water_body_proximity(centroid_lat, centroid_lng)
    else:
        water_proximity = {"checked": False, "reason": "no_map_pin",
                           "message": "Click on the map to enable water body proximity check."}

    if coords_list:
        rajkaluve_proximity = check_rajkaluve_proximity(centroid_lat, centroid_lng)
    else:
        rajkaluve_proximity = {"checked": False, "reason": "no_map_pin",
                               "message": "Click on the map to enable drain proximity check."}

    summary = generate_feasibility_summary(plot_area_sqm, max_built_sqm, far_floors)
    design_options = generate_design_options(far_floors, max_built_sqm)
    compliance = generate_compliance_score(fire_data, parking, far_floors)

    # ── Prompt ────────────────────────────────────────────────────
    client = get_openai_client()

    prompt = f"""
You are an expert Bangalore building regulations assistant helping a licensed architect.

VERIFIED BYLAW CONTEXT (retrieved directly from official PDFs — use ONLY this):
─────────────────────────────────────────────────────────────────────────────
SETBACKS: {setback_context}
STAIRCASE & LIFT: {staircase_context}
BALCONY & PROJECTIONS: {balcony_context}
FIRE SAFETY: {fire_context}
{f"BASEMENT: {basement_context}" if basement else ""}
─────────────────────────────────────────────────────────────────────────────

Plot facts (pre-computed — do NOT recalculate):
Zone: {zone} | Locality: {locality} | Road: {road_width}m | Usage: {usage}
{f"WATER BODY WARNING: {water_proximity['warning']}" if water_proximity.get("in_buffer_zone") else ""}
FAR: {far} | Ground coverage: {ground_coverage_pct}% | Max built-up: {max_built_sqm:,.0f} sqm
Setbacks: Front {front_setback}m | Side {side_setback}m | Rear {rear_setback}m
Lift mandatory: {staircase_data['lift_mandatory']} (trigger: G+3 OR 15m, whichever first — BDA RMP 2031 Sec 4.9.1(iv)) | Staircases: {staircase_data['num_staircases']}
Fire NOC required: {fire_data['noc_required']} | Building height: {building_height}m | Floors: {far_floors} (G+{far_floors-1})
Basement requested: {basement} | Corner plot: {corner_plot}

Return ONLY a JSON object with these keys. Each value must be ONE concise sentence (max 25 words) citing the relevant bylaw section. No bullet points, no markdown.

{{
  "setbacks": "One sentence about these specific setbacks and the 11.5m rule, citing bylaw section.",
  "far": "One sentence about FAR {far} for {zone} zone and what is excluded, citing bylaw section.",
  "staircase": "One sentence about staircase width and lift requirement for this building, citing BBMP section.",
  "projections": "One sentence about max balcony and chajja projection and FAR 20% rule, citing bylaw section.",
  "basement": {"One sentence about permitted uses and FAR exclusion for basement" if basement else "null"},
  "fire": "One sentence about NOC requirement and key fire safety rule for {building_height}m building, citing NBC 2016.",
  "compliance": "One sentence about the most critical mandatory compliance for this plot size and usage.",
  "parking": "One sentence about parking requirement under BDA RMP 2031 Sec 4.13 / Table 4 for this usage.",
}}
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a precise Bangalore urban planning assistant. Return only valid JSON, no markdown fences, no extra text."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    try:
        import json as _json
        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if model adds them
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        section_summaries = _json.loads(raw.strip())
    except Exception:
        section_summaries = {
            "setbacks":    f"Front {front_setback}m, Side {side_setback}m, Rear {rear_setback}m per BBMP bylaws for {zone} zone.",
            "far":         f"FAR {far} allows max {max_built_sqm:,.0f} sqm built-up; basement and staircase excluded from FAR count.",
            "staircase":   f"Min {staircase_data['min_staircase_width_m']}m staircase width required; {'lift mandatory (G+3 or 15m trigger)' if staircase_data['lift_mandatory'] else 'lift not mandatory'} per BDA RMP 2031 Sec 4.9.1(iv).",
            "projections":  "Max 1.5m balcony and 0.75m chajja projection permitted; balconies within 20% of floor area excluded from FAR.",
            "basement":    "Basement permitted for parking and utilities only; excluded from FAR calculation per BBMP Sec 18.2." if basement else None,
            "fire":        f"{'Fire NOC required' if fire_data['noc_required'] else 'Fire NOC not required'} for {building_height}m building under NBC 2016 Part IV.",
            "compliance":  (f"Lift mandatory — {far_floors} floors (G+{far_floors-1}) exceeds G+3 threshold per BDA RMP 2031 Sec 4.9.1(iv)."
                            if staircase_data['lift_mandatory']
                            else f"Rainwater harvesting mandatory for plots above {get_rainwater_harvesting().get('mandatory_above_plot_sqm', 120)} sqm (BBMP Bye-Laws 2003 Sec 25)."),
            "parking":     "Parking calculated per BDA RMP 2031 Sec 4.13 / Table 4 based on built-up area and usage type.",
        }

    # ── Return ────────────────────────────────────────────────────
    return {
        "zone":               zone,
        "plot_area":          plot_area_sqm,
        "plot_area_sqm":      plot_area_sqm,
        "far":                far,
        "far_base":           far_base,
        "far_tdr":            far_tdr,
        "planning_zone":      planning_zone,
        "locality":           locality,
        "ward":            getattr(request, 'ward', ''),
        "max_built_area":     max_built_sqm,
        "feasibility":        summary,
        "design_options":     design_options,
        "compliance":         compliance,
        "road_width":         road_width,
        "ground_coverage_pct": ground_coverage_pct,
        "setbacks":           setbacks,
        "fire_rules":         fire_rules,
        "fire_data":          fire_data,
        "staircase":          staircase_data,
        "basement":           basement_data,
        "projections":        projection_rules,
        "far_exclusions":          FAR_EXCLUSIONS,
        "parking":                 parking,
        "section_summaries":       section_summaries,
        "min_floors_for_max_far":  min_floors_for_max_far,
        "accessibility":           accessibility,
        "boundary_wall":           boundary_wall,
        # ── Usage-specific additions ──────────────────────────────
        "usage_validation": {
            "zone_check":         usage_zone_check,
            "space_std_check":    space_std_check,
            "all_warnings":       (
                ([usage_zone_check["warning"]] if usage_zone_check.get("warning") else [])
                + space_std_check.get("warnings", [])
            ),
        },
        "solar_required":      solar_required,
        "solar_note":          solar_note,
        "building_height_m":   round(far_building_height, 1),
        "building_height_auto": building_height_auto,
        "water_proximity":     water_proximity,
        "rajkaluve_proximity": rajkaluve_proximity,
    }