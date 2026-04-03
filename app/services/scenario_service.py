import math
from app.services.services import find_far_rule

FLOOR_HEIGHT_M   = 3.2
HIGH_RISE_CUTOFF = 11.5

GROUND_COVERAGE = {
    "R":   {12: 70, 18: 65, 24: 60, 9999: 55},
    "RM":  {12: 70, 18: 65, 24: 60, 9999: 55},
    "C1":  {12: 65, 18: 60, 24: 55, 9999: 50},
    "C2":  {12: 60, 18: 55, 24: 55, 9999: 50},
    "C3":  {12: 60, 18: 55, 24: 55, 9999: 50},
    "IT":  {12: 50, 18: 50, 24: 45, 9999: 40},
    "PSP": {12: 40, 18: 40, 24: 40, 9999: 40},
}

def _get_ground_coverage(zone: str, road_width: float) -> int:
    zone_map = GROUND_COVERAGE.get(zone.upper(), GROUND_COVERAGE["R"])
    for threshold in sorted(zone_map.keys()):
        if road_width <= threshold:
            return zone_map[threshold]
    return 55

def _get_setbacks(plot_area: float, building_height: float, corner_plot: bool):
    if plot_area < 1500:
        front, side, rear = 3.0, 1.0, 1.0
    else:
        front, side, rear = 4.0, 1.5, 2.0
    if building_height > HIGH_RISE_CUTOFF:
        front = max(front, 5.0)
        side  = max(side,  5.0)
        rear  = max(rear,  5.0)
    if corner_plot:
        side = max(1.0, side - 1.0)
    return front, side, rear

def _fire_rules(height: float, max_built: float, usage: str):
    rules = []
    noc   = False
    if height > 15:
        noc = True
        rules += ["Fire NOC from KSFES", "Sprinkler system", "Fire lift", "Wet riser"]
    if height > 24:
        rules += ["Fire command centre", "2 separate staircases", "Refuge area every 7 floors"]
    if not noc and max_built > 500 and usage.lower() == "commercial":
        noc = True
        rules.append("Fire NOC (commercial >500 sqm)")
    return noc, rules

def _compute_scenario(
    label: str,
    floors: int,
    plot_area_sqft: float,
    plot_area_sqm:  float,
    plot_length_m:  float,
    plot_width_m:   float,
    far: float,
    road_width: float,
    zone: str,
    usage: str,
    corner_plot: bool,
    basement: bool,
) -> dict:

    building_height = floors * FLOOR_HEIGHT_M
    ground_cov_pct  = _get_ground_coverage(zone, road_width)
    max_built_sqft  = round(plot_area_sqft * far, 1)
    front, side, rear = _get_setbacks(plot_area_sqft, building_height, corner_plot)

    # Footprint — lower floors (below cutoff)
    max_footprint_gc   = plot_area_sqm * (ground_cov_pct / 100)
    footprint_setback  = max(0, (plot_length_m - front - rear)) * max(0, (plot_width_m - side * 2))
    footprint_low_sqm  = min(max_footprint_gc, footprint_setback)
    footprint_low_sqft = round(footprint_low_sqm * 10.7639, 1)

    # Footprint — upper floors (above 11.5m cutoff → 5m all sides)
    footprint_high_sqm  = max(0, (plot_length_m - 10)) * max(0, (plot_width_m - 10))
    footprint_high_sqft = round(footprint_high_sqm * 10.7639, 1)

    cutoff_floor = math.ceil(HIGH_RISE_CUTOFF / FLOOR_HEIGHT_M)  # = 4

    # Build floor table
    floor_table     = []
    cumulative      = 0.0
    remaining_far   = max_built_sqft

    for i in range(floors):
        is_high = i >= cutoff_floor
        fp      = footprint_high_sqft if is_high else footprint_low_sqft
        area    = round(min(fp, max(0, remaining_far)), 1)
        cumulative    += area
        remaining_far -= area
        floor_table.append({
            "floor":        i,
            "label":        "Ground" if i == 0 else f"Floor {i}",
            "area_sqft":    area,
            "area_sqm":     round(area / 10.7639, 1),
            "is_high_rise": is_high,
            "setback_rule": "5m all sides" if is_high else f"F:{front}m R:{rear}m S:{side}m",
        })

    total_built = round(sum(f["area_sqft"] for f in floor_table), 1)
    far_used    = round(total_built / (plot_area_sqft or 1), 2)

    fire_noc, fire_reqs = _fire_rules(building_height, total_built, usage)

    num_floors_label  = f"G+{floors - 1}"
    lift_mandatory    = floors > 4
    num_staircases    = 2 if total_built > 2000 else 1

    if usage.lower() == "residential":
        # BBMP Table 23: 1 car per dwelling unit
        # Estimate units: avg Bangalore apartment = 120-150 sqm
        avg_unit_sqm = 130
        estimated_units = max(1, math.ceil((total_built / 10.7639) / avg_unit_sqm))
        parking_car = estimated_units + max(1, math.ceil(estimated_units * 0.10))  # +10% visitor
        parking_2w = estimated_units
    else:
        # Commercial: 3 cars per 100 sqm
        parking_car = math.ceil((total_built / 10.7639) / 100 * 3)
        parking_2w = parking_car * 2

    return {
        "label":              label,
        "num_floors":         floors,
        "floors_label":       num_floors_label,
        "building_height_m":  round(building_height, 1),
        "far":                far,
        "far_used":           far_used,
        "far_efficiency_pct": round((far_used / far) * 100, 1),
        "ground_coverage_pct": ground_cov_pct,
        "max_built_sqft":     max_built_sqft,
        "total_built_sqft":   total_built,
        "total_built_sqm":    round(total_built / 10.7639, 1),
        "footprint_sqft":     footprint_low_sqft,
        "setbacks": {
            "front": front, "side": side, "rear": rear,
            "high_rise_rule": building_height > HIGH_RISE_CUTOFF
        },
        "fire_noc_required":  fire_noc,
        "fire_rules":         fire_reqs,
        "lift_mandatory":     lift_mandatory,
        "num_staircases":     num_staircases,
        "parking_car":        parking_car,
        "parking_2w":         parking_2w,
        "floor_table":        floor_table,
        "basement_allowed":   basement,
        "warnings":           _get_warnings(building_height, total_built, fire_noc, lift_mandatory, plot_area_sqft),
    }

def _get_warnings(height, built, fire_noc, lift, plot_area):
    w = []
    if height > HIGH_RISE_CUTOFF:
        w.append("Setbacks jump to 5m all sides above 11.5m — buildable area reduces significantly on upper floors")
    if fire_noc:
        w.append("Fire NOC from KSFES required — add 4–6 weeks to approval timeline")
    if lift:
        w.append("Lift shaft must be planned — reduces net usable area per floor")
    if plot_area < 1200 and height > 9.6:
        w.append("Small plot with high building — verify structural feasibility with engineer")
    return w

# REPLACE the entire calculate_scenarios() function

def calculate_scenarios(
    zone: str,
    road_width: float,
    plot_area_sqft: float,
    plot_length_m:  float,
    plot_width_m:   float,
    usage:          str,
    corner_plot:    bool = False,
    basement:       bool = False,
    scenarios:      list = None,
) -> dict:

    far = find_far_rule(f"{road_width}m") or 1.75
    try:
        far = float(far)
    except Exception:
        far = 1.75

    plot_area_sqm = round(plot_area_sqft / 10.7639, 2)

    # ── How many floors does FAR actually allow? ──────────────────
    ground_cov_pct = _get_ground_coverage(zone, road_width)
    footprint_sqm  = plot_area_sqm * (ground_cov_pct / 100)
    max_built_sqm  = plot_area_sqm * far
    far_max_floors = math.ceil(max_built_sqm / max(footprint_sqm, 1))
    far_max_floors = max(1, min(far_max_floors, 15))

    if not scenarios:
        scenarios = [2, 3, 4, 5]

    results = []
    for floors in scenarios:
        label = f"G+{floors - 1}"
        s = _compute_scenario(
            label=label, floors=floors,
            plot_area_sqft=plot_area_sqft, plot_area_sqm=plot_area_sqm,
            plot_length_m=plot_length_m, plot_width_m=plot_width_m,
            far=far, road_width=road_width, zone=zone,
            usage=usage, corner_plot=corner_plot, basement=basement,
        )
        # ── Mark FAR-exceeded scenarios ───────────────────────────
        s["exceeds_far"]    = floors > far_max_floors
        s["far_max_floors"] = far_max_floors
        if s["exceeds_far"]:
            s["warnings"].insert(0,
                f"Exceeds FAR {far} — only {far_max_floors} floors "
                f"(G+{far_max_floors-1}) are viable on this {plot_area_sqm:.0f} sqm plot"
            )
        results.append(s)

    # ── Recommended: highest built-up among FAR-viable, prefer no NOC ──
    viable    = [s for s in results if not s["exceeds_far"]]
    no_noc    = [s for s in viable  if not s["fire_noc_required"]]
    best_pool = no_noc if no_noc else (viable if viable else results)
    best      = max(best_pool, key=lambda s: s["total_built_sqft"])

    return {
        "plot_area_sqft": plot_area_sqft,
        "plot_area_sqm":  plot_area_sqm,
        "far":            far,
        "far_max_floors": far_max_floors,          # ← new field
        "zone":           zone,
        "road_width":     road_width,
        "recommended":    best["label"],
        "scenarios":      results,
    }