"""
hyderabad_scenario_service.py
─────────────────────────────
Scenario comparison for Hyderabad GHMC / HMDA (AP Building Rules 2012,
G.O.Ms.No.168).

Mirrors the output shape of `calculate_scenarios()` in
scenario_service.py (Bengaluru BDA) so the same Angular
"Building Scenarios — Bylaw Thresholds" card can render it.

Regulatory breakpoints driving distinct scenarios:
  • 15.0 m → lift mandatory + commercial fire NOC trigger
  • 18.0 m → high-rise threshold (setback table shifts, residential fire NOC)
  • Max FAR → full FAR utilisation (peak total built-up)
"""
import math
from app.services.hyderabad_planning_service import (
    _load,
    _normalise_zone,
    _get_far,
    _get_coverage,
    _get_non_high_rise_setbacks,
    _get_high_rise_setbacks,
    _max_height_for_road,
    _get_parking,
    _fire_noc_required,
    _get_fire_rules,
)

DEFAULT_FLOOR_HEIGHT_M = 3.0


# ── Setback dispatch (non-high-rise vs high-rise) ─────────────────────────────
def _setbacks_at_height(
    plot_area_sqm: float,
    road_width_m:  float,
    height_m:      float,
) -> dict:
    if height_m >= 18.0:
        return _get_high_rise_setbacks(height_m, road_width_m)
    return _get_non_high_rise_setbacks(plot_area_sqm, road_width_m, height_m)


# ── Footprint & built-up at N floors ──────────────────────────────────────────
def _built_at_floors(
    floors:         int,
    plot_area_sqm:  float,
    cov_pct:        int,
    plot_length_m:  float,
    plot_width_m:   float,
    road_width_m:   float,
    floor_height_m: float,
) -> float:
    height_m = floors * floor_height_m
    sb = _setbacks_at_height(plot_area_sqm, road_width_m, height_m)
    buildable_l = max(0.0, plot_length_m - sb["front"] - sb["rear"])
    buildable_w = max(0.0, plot_width_m  - 2 * sb["side"])
    fp_setback  = buildable_l * buildable_w
    fp_cov      = plot_area_sqm * cov_pct / 100
    fp          = min(fp_setback, fp_cov)
    return fp * floors   # in sqm


def _floors_for_peak_far(
    plot_area_sqm:  float,
    cov_pct:        int,
    plot_length_m:  float,
    plot_width_m:   float,
    road_width_m:   float,
    floor_height_m: float,
    ceiling_floors: int,
) -> int:
    """Floor count that gives the HIGHEST total built area within ceiling."""
    best_floors, best_built = 1, 0.0
    declining, prev = 0, 0.0
    for floors in range(1, ceiling_floors + 1):
        built = _built_at_floors(floors, plot_area_sqm, cov_pct,
                                 plot_length_m, plot_width_m,
                                 road_width_m, floor_height_m)
        if built <= 0:
            break
        if built > best_built:
            best_built, best_floors, declining = built, floors, 0
        elif built < prev:
            declining += 1
            if declining >= 3:
                break
        prev = built
    return best_floors


# ── Per-scenario compute ──────────────────────────────────────────────────────
def _compute_scenario(
    label:          str,
    floors:         int,
    plot_area_sqm:  float,
    plot_area_sqft: float,
    plot_length_m:  float,
    plot_width_m:   float,
    far:            float,
    cov_pct:        int,
    road_width_m:   float,
    usage:          str,
    corner_plot:    bool,
    basement:       bool,
    floor_height_m: float,
) -> dict:
    height_m        = round(floors * floor_height_m, 2)
    max_built_sqm   = round(plot_area_sqm * far, 2)
    max_built_sqft  = round(max_built_sqm * 10.7639, 1)
    is_high_rise    = height_m >= 18.0

    sb = _setbacks_at_height(plot_area_sqm, road_width_m, height_m)
    front, side, rear = sb["front"], sb["side"], sb["rear"]
    if corner_plot:
        side = max(1.0, side - 0.5)

    # Footprint: min(coverage cap, setback-constrained)
    fp_cov_sqm     = plot_area_sqm * cov_pct / 100
    fp_setback_sqm = max(0.0, plot_length_m - front - rear) * max(0.0, plot_width_m - 2 * side)
    footprint_sqm  = min(fp_cov_sqm, fp_setback_sqm)
    footprint_sqft = round(footprint_sqm * 10.7639, 1)

    # Floor table — uniform footprint; FAR headroom caps each floor
    floor_table, remaining = [], max_built_sqft
    for i in range(floors):
        area = round(min(footprint_sqft, max(0.0, remaining)), 1)
        remaining -= area
        floor_table.append({
            "floor":     i,
            "label":     "Ground" if i == 0 else f"Floor {i}",
            "area_sqft": area,
            "area_sqm":  round(area / 10.7639, 1),
            "is_high_rise": is_high_rise,
            "setback_rule": f"F:{front}m R:{rear}m S:{side}m",
        })

    total_built_sqft = round(sum(f["area_sqft"] for f in floor_table), 1)
    total_built_sqm  = round(total_built_sqft / 10.7639, 2)
    far_used         = round(total_built_sqft / (plot_area_sqft or 1), 2)

    # Fire & lift (AP Building Rules 2012 thresholds)
    noc_req    = _fire_noc_required(height_m, usage, plot_area_sqm)
    fire_rules = _get_fire_rules(height_m, usage)
    thresholds = _load()["staircase_lift"]
    lift_mandatory = (height_m > thresholds["lift_mandatory_above_height_m"]
                      or floors > thresholds["lift_mandatory_above_floors"])
    num_staircases = 2 if (is_high_rise or total_built_sqm > 500) else 1

    # Parking — Table V, % of BUA
    parking = _get_parking(usage, total_built_sqm)

    avg_floor_area_sqft = round(total_built_sqft / floors, 1) if floors else 0

    return {
        "label":               label,
        "num_floors":          floors,
        "floors_label":        f"G+{floors - 1}",
        "building_height_m":   height_m,
        "far":                 far,
        "far_used":            far_used,
        "far_efficiency_pct":  round((far_used / far) * 100, 1) if far else 0,
        "ground_coverage_pct": cov_pct,
        "max_built_sqft":      max_built_sqft,
        "total_built_sqft":    total_built_sqft,
        "total_built_sqm":     total_built_sqm,
        "footprint_sqft":      footprint_sqft,
        "avg_floor_area_sqft": avg_floor_area_sqft,
        "setbacks": {
            "front": front, "side": side, "rear": rear,
            "high_rise_rule": is_high_rise,
        },
        "fire_noc_required":   noc_req,
        "fire_rules":          fire_rules,
        "lift_mandatory":      lift_mandatory,
        "num_staircases":      num_staircases,
        "parking_car":         parking["cars"],
        "parking_2w":          parking["two_wheelers"],
        "floor_table":         floor_table,
        "basement_allowed":    basement and plot_area_sqm >= 750,
        "warnings":            _warnings(height_m, is_high_rise, plot_area_sqm, noc_req, lift_mandatory),
    }


def _warnings(height_m, is_high_rise, plot_area_sqm, noc_req, lift_mandatory):
    w = []
    if is_high_rise and plot_area_sqm < 2000:
        w.append(
            f"High-rise requires plot ≥ 2000 sqm — current plot {plot_area_sqm:.0f} sqm "
            "(Rule 7, AP Building Rules 2012)"
        )
    if is_high_rise:
        w.append(
            "Above 18m all-round setbacks apply (Table IV) — buildable area shrinks on each tier"
        )
    if noc_req:
        w.append("Fire NOC from AP State Disaster Response & Fire Services required — adds 4–6 weeks")
    if lift_mandatory:
        w.append("Lift mandatory — height > 15m OR floors > G+4 (NBC 2005 / Rule 15)")
    return w


# ── Regulatory threshold scenarios ────────────────────────────────────────────
# AP Building Rules 2012 key breakpoints:
#   15.0 m → lift trigger + commercial fire NOC
#   18.0 m → high-rise setback table; residential fire NOC
BYLAW_HEIGHT_THRESHOLDS = [
    (15.0, "No Lift"),          # below lift mandate and commercial fire NOC
    (18.0, "Non High-Rise"),    # max density before high-rise setbacks kick in
]


# ── Main entry point ──────────────────────────────────────────────────────────
def calculate_hyderabad_scenarios(
    zone:              str,
    road_width:        float,
    plot_length_m:     float,
    plot_width_m:      float,
    usage:             str   = "residential",
    corner_plot:       bool  = False,
    basement:          bool  = False,
    floor_height_m:    float = DEFAULT_FLOOR_HEIGHT_M,
    building_height_m: float = 0.0,
    locality:          str   = "Hyderabad",
) -> dict:
    """
    Generate building scenarios anchored to AP Building Rules 2012 height thresholds.
    Plot dimensions (in metres) are the authoritative source for area.
    """
    canon_zone     = _normalise_zone(zone)
    plot_area_sqm  = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(plot_area_sqm * 10.7639, 2)

    fh        = floor_height_m or DEFAULT_FLOOR_HEIGHT_M
    far_val   = _get_far(canon_zone)
    # Coverage: high-rise uses HR coverage; start with non-HR for scenario base.
    cov_base  = _get_coverage(canon_zone, plot_area_sqm, is_high_rise=False)

    max_built_sqft = round(plot_area_sqm * far_val * 10.7639, 1)

    # Effective ceiling = min(user-cap, road-cap)
    road_ht_cap       = _max_height_for_road(road_width)
    height_cap_active = building_height_m > 0
    effective_cap_m   = min(
        building_height_m if height_cap_active else 9999.0,
        road_ht_cap,
    )
    ceiling_floors    = max(1, math.floor(effective_cap_m / fh))

    # Peak-FAR floor count (clamped to ceiling)
    # Use coverage that matches the likely regime; _built_at_floors uses non-HR cov
    # up to 18m, so pass non-HR coverage. For pure FAR calc this is fine because
    # we also cap by plot_area × FAR downstream in _compute_scenario.
    peak_floors = _floors_for_peak_far(
        plot_area_sqm  = plot_area_sqm,
        cov_pct        = cov_base,
        plot_length_m  = plot_length_m,
        plot_width_m   = plot_width_m,
        road_width_m   = road_width,
        floor_height_m = fh,
        ceiling_floors = min(ceiling_floors, 50),
    )

    # Regulatory threshold scenarios
    floor_to_label: dict = {}
    for height_threshold, label in BYLAW_HEIGHT_THRESHOLDS:
        f = max(1, math.floor(height_threshold / fh))
        f = min(f, ceiling_floors)
        if f not in floor_to_label:
            floor_to_label[f] = label

    # Max FAR slot (peak clamped to ceiling)
    peak_clamped = min(peak_floors, ceiling_floors)
    if peak_clamped in floor_to_label:
        floor_to_label[peak_clamped] += " / Max FAR"
    else:
        floor_to_label[peak_clamped] = "Max FAR"

    # Max Height slot — only when user-set cap differs from peak
    if height_cap_active:
        cap_floors = max(1, math.floor(min(building_height_m, road_ht_cap) / fh))
        if cap_floors != peak_clamped:
            if cap_floors in floor_to_label:
                floor_to_label[cap_floors] += " / Max Height"
            else:
                floor_to_label[cap_floors] = "Max Height"

    # Compute each unique scenario
    results = []
    for floors in sorted(floor_to_label):
        label          = floor_to_label[floors]
        height_m       = floors * fh
        # Coverage depends on high-rise regime for this scenario
        cov_pct        = _get_coverage(canon_zone, plot_area_sqm, is_high_rise=(height_m >= 18.0))
        s = _compute_scenario(
            label          = label,
            floors         = floors,
            plot_area_sqm  = plot_area_sqm,
            plot_area_sqft = plot_area_sqft,
            plot_length_m  = plot_length_m,
            plot_width_m   = plot_width_m,
            far            = far_val,
            cov_pct        = cov_pct,
            road_width_m   = road_width,
            usage          = usage,
            corner_plot    = corner_plot,
            basement       = basement,
            floor_height_m = fh,
        )
        s["far_pct"]         = round(s["far_efficiency_pct"] / 100, 2)
        s["far_target_sqft"] = max_built_sqft
        s["floors_label"]    = f"G+{floors - 1}"
        s["exceeds_far"]     = False
        results.append(s)

    # Recommended: highest density without Fire NOC
    no_noc    = [s for s in results if not s["fire_noc_required"]]
    best_pool = no_noc if no_noc else results
    best      = max(best_pool, key=lambda s: s["total_built_sqft"])

    return {
        "city":            "hyderabad",
        "authority":       "GHMC / HMDA",
        "bylaw_ref":       "AP Building Rules 2012 — G.O.Ms.No.168",
        "plot_area_sqft":  plot_area_sqft,
        "plot_area_sqm":   plot_area_sqm,
        "far":             far_val,
        "far_base":        far_val,
        "far_tdr":         0.0,
        "max_built_sqft":  max_built_sqft,
        "zone":            canon_zone,
        "road_width":      road_width,
        "recommended":     best["label"],
        "scenarios":       results,
    }