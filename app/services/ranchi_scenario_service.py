"""
ranchi_scenario_service.py
──────────────────────────
Building scenarios for Ranchi (RMC / RRDA) anchored to JBBL height thresholds.
Mirrors scenario_service.py structure but uses Ranchi-specific fire NOC rules:
  - Fire NOC: height > 16 m (vs Bengaluru's 15 m)
  - Three bylaw breakpoints: 12 m, 16 m, max FAR
"""
import math
from app.services.ranchi_rules_engine import (
    get_far, get_setbacks, get_ground_coverage,
    fire_noc_required, lift_mandatory,
)
from app.ai.scenario_advisor import advise_scenarios

DEFAULT_FLOOR_HEIGHT_M = 3.2

# JBBL regulatory height thresholds
BYLAW_HEIGHT_THRESHOLDS = [
    (12.0, "No Special Building"),   # below fire NOC trigger, compact setbacks
    (16.0, "No Fire NOC"),           # max density before Fire NOC at 16 m
    (22.0, "Below 22m"),             # before progressive extra setbacks kick in
]


def _fire_rules(height: float, footprint_sqm: float) -> tuple[bool, list]:
    rules = []
    noc = fire_noc_required(height, footprint_sqm)
    if height > 16.0:
        rules += ["Fire Services consent required (Special Building)", "NBC Part IV compliance mandatory"]
    if height > 22.0:
        rules += ["Progressive additional setbacks apply above 22 m (Table 2A-I)"]
    if footprint_sqm > 500 and not height > 16.0:
        rules.append("Ground coverage > 500 sqm — Special Building (fire consent required)")
    return noc, rules


def _compute_scenario(
    label: str,
    floors: int,
    plot_area_sqm: float,
    plot_length_m: float,
    plot_width_m: float,
    far: float,
    road_width: float,
    zone: str,
    usage: str,
    corner_plot: bool,
    gc_pct: int,
    floor_height_m: float,
    authority: str,
) -> dict:
    building_height = floors * floor_height_m
    max_built_sqm   = round(plot_area_sqm * far, 2)
    max_built_sqft  = round(max_built_sqm * 10.7639, 1)

    sb = get_setbacks(
        plot_depth_m=plot_length_m, plot_width_m=plot_width_m,
        building_height_m=building_height, usage=usage,
        road_width_m=road_width, authority=authority,
    )

    if sb["not_permitted"]:
        front, side, rear = 3.0, 1.5, 1.5
    else:
        front, side, rear = sb["front"], sb["side"], sb["rear"]

    footprint_gc  = plot_area_sqm * (gc_pct / 100)
    footprint_sb  = max(0.0, plot_length_m - front - rear) * max(0.0, plot_width_m - side * 2)
    footprint_sqm = min(footprint_gc, footprint_sb)
    footprint_sqft = round(footprint_sqm * 10.7639, 1)

    # Build floor table capped at FAR
    remaining = max_built_sqft
    floor_table = []
    for i in range(floors):
        area = round(min(footprint_sqft, max(0.0, remaining)), 1)
        remaining -= area
        floor_table.append({
            "floor": i,
            "label": "Ground" if i == 0 else f"Floor {i}",
            "area_sqft": area,
            "area_sqm": round(area / 10.7639, 1),
            "setback_rule": f"F:{front}m R:{rear}m S:{side}m",
        })

    total_built_sqft = round(sum(f["area_sqft"] for f in floor_table), 1)
    total_built_sqm  = round(total_built_sqft / 10.7639, 2)
    far_used         = round(total_built_sqft / (plot_area_sqm * 10.7639 or 1), 2)

    fire_noc, fire_reqs = _fire_rules(building_height, footprint_sqm)
    lift_req = lift_mandatory(floors)

    # Parking (simplified)
    u = usage.lower()
    if "residential" in u:
        parking_car = max(1, math.ceil(total_built_sqm / 60))
    elif any(k in u for k in ("commercial", "office", "retail")):
        parking_car = max(1, math.ceil(total_built_sqm / 50))
    else:
        parking_car = max(1, math.ceil(total_built_sqm / 75))
    parking_2w = parking_car * 2

    warnings = []
    if building_height > 16.0:
        warnings.append("Above 16 m: Fire Services consent required before building permit")
    if fire_noc:
        warnings.append("Fire NOC required — add 4–6 weeks to approval timeline")
    if lift_req:
        warnings.append("Lift mandatory above G+3 (JBBL Bye-Law 17.6.1j)")
    if sb.get("high_rise_extra"):
        warnings.append("Progressive extra setbacks applied above 22 m (Table 2A-I)")

    return {
        "label":              label,
        "num_floors":         floors,
        "floors_label":       f"G+{floors - 1}",
        "building_height_m":  round(building_height, 1),
        "far":                far,
        "far_used":           far_used,
        "far_efficiency_pct": round((far_used / far) * 100, 1) if far else 0,
        "total_built_sqft":   total_built_sqft,
        "total_built_sqm":    round(total_built_sqm, 1),
        "footprint_sqm":      round(footprint_sqm, 1),
        "footprint_sqft":     footprint_sqft,
        "avg_floor_area_sqft": round(total_built_sqft / floors, 1) if floors else 0,
        "setbacks":           {"front": front, "side": side, "rear": rear, "high_rise_rule": building_height > 16.0},
        "fire_noc_required":  fire_noc,
        "fire_rules":         fire_reqs,
        "lift_mandatory":     lift_req,
        "num_staircases":     2 if total_built_sqm > 2000 else 1,
        "parking_car":        parking_car,
        "parking_2w":         parking_2w,
        "floor_table":        floor_table,
        "warnings":           warnings,
        "far_pct":            round(far_used / far, 2) if far else 0,
        "far_target_sqft":    max_built_sqft,
        "exceeds_far":        False,
    }


def _built_at_floors(floors, plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
                     road_width, usage, floor_height_m, authority):
    sb = get_setbacks(
        plot_depth_m=plot_length_m, plot_width_m=plot_width_m,
        building_height_m=floors * floor_height_m, usage=usage,
        road_width_m=road_width, authority=authority,
    )
    if sb["not_permitted"]:
        return 0.0
    fp = min(
        plot_area_sqm * gc_pct / 100,
        max(0.0, plot_length_m - sb["front"] - sb["rear"]) *
        max(0.0, plot_width_m - sb["side"] * 2),
    )
    return fp * 10.7639 * floors


def _peak_far_floors(plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
                     road_width, usage, floor_height_m, authority):
    best_floors, best_built, declining = 1, 0.0, 0
    prev_built = 0.0
    for floors in range(1, 51):
        built = _built_at_floors(floors, plot_area_sqm, gc_pct, plot_length_m,
                                 plot_width_m, road_width, usage, floor_height_m, authority)
        if built <= 0:
            break
        if built > best_built:
            best_built, best_floors, declining = built, floors, 0
        elif built < prev_built:
            declining += 1
            if declining >= 3:
                break
        prev_built = built
    return best_floors


def calculate_ranchi_scenarios(
    zone:              str,
    road_width:        float,
    plot_length_m:     float,
    plot_width_m:      float,
    usage:             str   = "residential",
    corner_plot:       bool  = False,
    basement:          bool  = False,
    floor_height_m:    float = DEFAULT_FLOOR_HEIGHT_M,
    building_height_m: float = 0.0,
    authority:         str   = "rmc",
) -> dict:
    plot_area_sqm  = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(plot_area_sqm * 10.7639, 2)

    far_data  = get_far(zone, road_width, plot_area_sqm, authority=authority)
    far       = far_data["total"]
    gc_pct    = far_data["coverage_pct"]
    fh        = floor_height_m or DEFAULT_FLOOR_HEIGHT_M

    max_built_sqft = round(plot_area_sqft * far, 1)

    height_cap_active = building_height_m > 0
    ceiling = max(1, math.floor(building_height_m / fh)) if height_cap_active else 50

    peak_far_floors = _peak_far_floors(
        plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
        road_width, usage, fh, authority,
    )

    floor_to_label: dict = {}
    for height_threshold, label in BYLAW_HEIGHT_THRESHOLDS:
        f = max(1, math.floor(height_threshold / fh))
        f = min(f, ceiling)
        if f not in floor_to_label:
            floor_to_label[f] = label

    peak_clamped = min(peak_far_floors, ceiling)
    if peak_clamped in floor_to_label:
        floor_to_label[peak_clamped] += " / Max FAR"
    else:
        floor_to_label[peak_clamped] = "Max FAR"

    results = []
    for floors in sorted(floor_to_label):
        label = floor_to_label[floors]
        s = _compute_scenario(
            label=label, floors=floors,
            plot_area_sqm=plot_area_sqm, plot_length_m=plot_length_m,
            plot_width_m=plot_width_m, far=far, road_width=road_width,
            zone=zone, usage=usage, corner_plot=corner_plot,
            gc_pct=gc_pct, floor_height_m=fh, authority=authority,
        )
        results.append(s)

    # Hardcoded fallback: highest FAR without fire NOC
    no_noc = [s for s in results if not s["fire_noc_required"]]
    best_pool = no_noc if no_noc else results
    best = max(best_pool, key=lambda s: s["total_built_sqft"])
    recommended = best["label"]

    # AI advisor
    ai_advice = None
    try:
        ai_advice = advise_scenarios(
            scenarios=results, zone=zone, usage=usage,
            plot_area_sqm=plot_area_sqm, road_width=road_width,
        )
        recommended = ai_advice["recommended"]
    except Exception:
        pass

    return {
        "plot_area_sqft": plot_area_sqft,
        "plot_area_sqm":  plot_area_sqm,
        "far":            far,
        "far_base":       far_data["base"],
        "far_tdr":        0.0,
        "max_built_sqft": max_built_sqft,
        "zone":           zone,
        "road_width":     road_width,
        "authority":      authority.upper(),
        "recommended":    recommended,
        "ai_advice":      ai_advice,
        "scenarios":      results,
    }