"""
anekal_scenario_service.py
──────────────────────────
Building scenarios for Anekal LPA (BMRDA).
Mirrors the structure of hyderabad_scenario_service.py.
"""
import math
from app.services.anekal_planning_service import (
    calculate_anekal_planning,
    _get_far,
    _get_coverage,
    _get_setbacks,
    _fire_noc_required,
    _normalise_zone,
)

DEFAULT_FLOOR_HEIGHT_M = 3.0

# Anekal height breakpoints (Table 3 thresholds)
_HEIGHT_THRESHOLDS = [
    (10.0, "Up to 10m (Table 2 setbacks)"),
    (15.0, "Below High-Rise (≤15m)"),
    (21.0, "Below 21m"),
]


def _compute_scenario(
    label:          str,
    floors:         int,
    plot_area_sqm:  float,
    plot_length_m:  float,
    plot_width_m:   float,
    far:            float,
    road_width:     float,
    zone:           str,
    usage:          str,
    corner_plot:    bool,
    gc_pct:         int,
    floor_height_m: float,
) -> dict:
    building_height = floors * floor_height_m
    max_built_sqm   = round(plot_area_sqm * far, 2)
    max_built_sqft  = round(max_built_sqm * 10.7639, 1)

    sb = _get_setbacks(
        zone, plot_width_m, plot_length_m, road_width,
        building_height, plot_area_sqm, corner_plot, usage,
    )
    front = sb["front"]
    rear  = sb["rear"]
    side  = max(sb["side_left"], sb["side_right"])

    fp_gc  = plot_area_sqm * (gc_pct / 100)
    fp_sb  = max(0.0, plot_length_m - front - rear) * max(0.0, plot_width_m - side * 2)
    fp_sqm = min(fp_gc, fp_sb)
    fp_sqft = round(fp_sqm * 10.7639, 1)

    # Floor table capped at FAR
    remaining = max_built_sqft
    floor_table = []
    for i in range(floors):
        area = round(min(fp_sqft, max(0.0, remaining)), 1)
        remaining -= area
        floor_table.append({
            "floor": i,
            "label": "Ground" if i == 0 else f"Floor {i}",
            "area_sqft": area,
            "area_sqm":  round(area / 10.7639, 1),
            "setback_rule": f"F:{front}m R:{rear}m S:{side}m",
        })

    total_built_sqft = round(sum(f["area_sqft"] for f in floor_table), 1)
    total_built_sqm  = round(total_built_sqft / 10.7639, 2)
    far_used         = round(total_built_sqft / (plot_area_sqm * 10.7639 or 1), 2)

    fire_noc = _fire_noc_required(building_height, usage, plot_area_sqm)
    lift_req = building_height >= 15.0  # G+4 = high-rise threshold

    warnings: list[str] = []
    if fire_noc:
        warnings.append("Fire NOC required (building ≥15m — NBC 2016 Part IV applies)")
    if lift_req:
        warnings.append("Lift mandatory (high-rise threshold ≥15m)")

    parking_cars = max(1, math.ceil(total_built_sqm / (75 if "residential" not in usage else 100)))

    return {
        "label":               label,
        "num_floors":          floors,
        "floors_label":        f"G+{floors - 1}" if floors > 1 else "G",
        "building_height_m":   round(building_height, 1),
        "far":                 far,
        "far_used":            far_used,
        "far_efficiency_pct":  round((far_used / far) * 100, 1) if far else 0,
        "total_built_sqft":    total_built_sqft,
        "total_built_sqm":     round(total_built_sqm, 1),
        "footprint_sqm":       round(fp_sqm, 1),
        "footprint_sqft":      fp_sqft,
        "avg_floor_area_sqft": round(total_built_sqft / floors, 1) if floors else 0,
        "setbacks":            {"front": front, "side": side, "rear": rear,
                                "high_rise_rule": building_height > 10.0},
        "fire_noc_required":   fire_noc,
        "lift_mandatory":      lift_req,
        "parking_car":         parking_cars,
        "parking_2w":          math.ceil(parking_cars * 0.25),
        "floor_table":         floor_table,
        "warnings":            warnings,
        "far_pct":             round(far_used / far, 2) if far else 0,
        "far_target_sqft":     max_built_sqft,
    }


def _built_at_floors(floors, plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
                     road_width, zone, usage, floor_height_m):
    sb = _get_setbacks(
        zone, plot_width_m, plot_length_m, road_width,
        floors * floor_height_m, plot_area_sqm, False, usage,
    )
    front = sb["front"]
    rear  = sb["rear"]
    side  = max(sb["side_left"], sb["side_right"])
    fp = min(
        plot_area_sqm * gc_pct / 100,
        max(0.0, plot_length_m - front - rear) *
        max(0.0, plot_width_m - side * 2),
    )
    return fp * 10.7639 * floors


def _peak_far_floors(plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
                     road_width, zone, usage, floor_height_m):
    best_floors, best_built, declining = 1, 0.0, 0
    prev_built = 0.0
    for floors in range(1, 51):
        built = _built_at_floors(floors, plot_area_sqm, gc_pct, plot_length_m,
                                 plot_width_m, road_width, zone, usage, floor_height_m)
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


def calculate_anekal_scenarios(
    zone:              str,
    road_width:        float,
    plot_length_m:     float,
    plot_width_m:      float,
    usage:             str   = "residential",
    corner_plot:       bool  = False,
    basement:          bool  = False,
    floor_height_m:    float = DEFAULT_FLOOR_HEIGHT_M,
    building_height_m: float = 0.0,
    locality:          str   = "Anekal",
) -> dict:
    zone           = _normalise_zone(zone)
    plot_area_sqm  = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(plot_area_sqm * 10.7639, 2)

    far    = _get_far(zone, road_width, plot_area_sqm, usage)
    gc_pct = _get_coverage(zone, plot_area_sqm, usage)
    fh     = floor_height_m or DEFAULT_FLOOR_HEIGHT_M

    max_built_sqft = round(plot_area_sqft * far, 1)

    height_cap_active = building_height_m > 0
    ceiling = max(1, math.floor(building_height_m / fh)) if height_cap_active else 50

    peak_far_floors = _peak_far_floors(
        plot_area_sqm, gc_pct, plot_length_m, plot_width_m,
        road_width, zone, usage, fh,
    )

    floor_to_label: dict[int, str] = {}
    for ht, label in _HEIGHT_THRESHOLDS:
        f = max(1, math.floor(ht / fh))
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
        s = _compute_scenario(
            label=floor_to_label[floors],
            floors=floors,
            plot_area_sqm=plot_area_sqm,
            plot_length_m=plot_length_m,
            plot_width_m=plot_width_m,
            far=far,
            road_width=road_width,
            zone=zone,
            usage=usage,
            corner_plot=corner_plot,
            gc_pct=gc_pct,
            floor_height_m=fh,
        )
        results.append(s)

    no_noc = [s for s in results if not s["fire_noc_required"]]
    best_pool = no_noc if no_noc else results
    best = max(best_pool, key=lambda s: s["total_built_sqft"])
    recommended = best["label"]

    try:
        from app.ai.scenario_advisor import advise_scenarios
        ai_advice = advise_scenarios(
            scenarios=results, zone=zone, usage=usage,
            plot_area_sqm=plot_area_sqm, road_width=road_width,
        )
        recommended = ai_advice["recommended"]
    except Exception:
        ai_advice = None

    return {
        "plot_area_sqft": plot_area_sqft,
        "plot_area_sqm":  plot_area_sqm,
        "far":            far,
        "far_base":       far,
        "far_tdr":        0.0,
        "max_built_sqft": max_built_sqft,
        "zone":           zone,
        "road_width":     road_width,
        "authority":      "ANEKAL / BMRDA",
        "recommended":    recommended,
        "ai_advice":      ai_advice,
        "scenarios":      results,
    }