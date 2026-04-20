import math
from app.services.city_rules_engine import get_far, get_setbacks, lift_mandatory_floors

DEFAULT_FLOOR_HEIGHT_M = 3.2

# ── Fire rules ─────────────────────────────────────────────────────────────────
def _fire_rules(height: float, max_built_sqm: float, usage: str):
    """
    BDA / NBC 2016 fire thresholds.
    max_built_sqm: total built-up area in sqm (used for commercial threshold).
    """
    rules = []
    noc   = False

    if height > 15:
        noc = True
        rules += ["Fire NOC from KSFES", "Sprinkler system", "Fire lift", "Wet riser"]
    if height > 24:
        rules += ["Fire command centre", "2 separate staircases", "Refuge area every 7 floors"]

    # BDA RMP 2031: non-residential ≥ 5,000 sqm BUA → fire arrangements required
    if not noc and max_built_sqm >= 5000 and usage.lower() in ("commercial", "mixed"):
        noc = True
        rules.append("Fire NOC (non-residential BUA ≥ 5,000 sqm)")

    return noc, rules


# ── Scenario compute ────────────────────────────────────────────────────────────
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
    gc_pct: int,
    floor_height_m: float = DEFAULT_FLOOR_HEIGHT_M,
) -> dict:

    building_height = floors * floor_height_m
    max_built_sqft  = round(plot_area_sqft * far, 1)
    max_built_sqm   = round(plot_area_sqm  * far, 2)

    # Setbacks: BDA RMP 2031 progressive table (uniform for all floors)
    sb = get_setbacks(plot_area_sqm, building_height, road_width, corner_plot)
    front, side, rear = sb["front"], sb["side"], sb["rear"]

    # Footprint = min(ground coverage cap, setback-constrained area)
    footprint_gc  = plot_area_sqm * (gc_pct / 100)
    footprint_sb  = max(0.0, plot_length_m - front - rear) * max(0.0, plot_width_m - side * 2)
    footprint_sqm = min(footprint_gc, footprint_sb)
    footprint_sqft = round(footprint_sqm * 10.7639, 1)

    # Build floor table — uniform footprint; cap at remaining FAR headroom
    floor_table   = []
    remaining_far = max_built_sqft
    for i in range(floors):
        area = round(min(footprint_sqft, max(0.0, remaining_far)), 1)
        remaining_far -= area
        floor_table.append({
            "floor":     i,
            "label":     "Ground" if i == 0 else f"Floor {i}",
            "area_sqft": area,
            "area_sqm":  round(area / 10.7639, 1),
            "is_high_rise": False,          # BDA: no mid-building setback change
            "setback_rule": f"F:{front}m R:{rear}m S:{side}m",
        })

    total_built     = round(sum(f["area_sqft"] for f in floor_table), 1)
    total_built_sqm = round(total_built / 10.7639, 2)
    far_used        = round(total_built / (plot_area_sqft or 1), 2)

    fire_noc, fire_reqs = _fire_rules(building_height, total_built_sqm, usage)

    # BDA RMP 2031: lift mandatory above G+3 (more than 3 floors above ground)
    lift_mandatory = floors > lift_mandatory_floors()
    num_staircases = 2 if total_built_sqm > 200 else 1   # NBC 2016: dual staircase above 200 sqm

    # Parking — BDA RMP 2031 Sec 4.13 / Table 4
    u = usage.lower().strip()
    if u.startswith("residential"):
        if "single" in u or "dwelling" in u:
            # Single dwelling: 1 car per 100 sqm BUA
            cars_req = math.ceil(total_built_sqm / 100)
        else:
            # Multi-dwelling: tiered by avg DU size
            avg_unit_sqm = 130
            units        = max(1, math.ceil(total_built_sqm / avg_unit_sqm))
            if avg_unit_sqm < 50:
                cars_per_unit = 0.5
            elif avg_unit_sqm <= 120:
                cars_per_unit = 1.0
            else:
                # +1 car per 120 sqm above 120 sqm per DU
                cars_per_unit = 1 + math.floor((avg_unit_sqm - 120) / 120)
            cars_req = math.ceil(units * cars_per_unit)
        visitor_cars = max(1, math.ceil(cars_req * 0.10))
        parking_car  = cars_req + visitor_cars
        parking_2w   = parking_car * 2
    else:
        parking_car = math.ceil(total_built_sqm / 100 * 3)
        parking_2w  = parking_car * 2

    avg_floor_area_sqft = round(total_built / floors, 1) if floors else 0

    return {
        "label":              label,
        "num_floors":         floors,
        "floors_label":       f"G+{floors - 1}",
        "building_height_m":  round(building_height, 1),
        "far":                far,
        "far_used":           far_used,
        "far_efficiency_pct": round((far_used / far) * 100, 1) if far else 0,
        "ground_coverage_pct": gc_pct,
        "max_built_sqft":     max_built_sqft,
        "total_built_sqft":   total_built,
        "total_built_sqm":    round(total_built_sqm, 1),
        "footprint_sqft":     footprint_sqft,
        "avg_floor_area_sqft": avg_floor_area_sqft,
        "setbacks": {
            "front": front, "side": side, "rear": rear,
            "high_rise_rule": building_height > 15.0,
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


def _get_warnings(height, built_sqft, fire_noc, lift, plot_area_sqft):
    w = []
    if height > 15.0:
        w.append(
            f"Above 15m setbacks increase progressively (BDA Table 2): "
            f"6m at 15–18m, 7m at 18–21m, 8m at 21–24m — buildable area reduces on each tier"
        )
    if fire_noc:
        w.append("Fire NOC from KSFES required — add 4–6 weeks to approval timeline")
    if lift:
        w.append("Lift shaft must be planned above G+3 (BDA RMP 2031) — reduces net usable area")
    if plot_area_sqft < 1200 and height > 9.6:
        w.append("Small plot with high building — verify structural feasibility with engineer")
    return w


# ── Regulatory height thresholds ───────────────────────────────────────────────
# BDA RMP 2031 key breakpoints that drive distinct bylaw requirements:
#   11.5 m → below G+3 height range; compact setbacks, no fire requirements
#   15.0 m → last tier before Fire NOC AND before setbacks jump from 4m → 6m
#   24.0 m → before fire command centre + refuge area mandate (G+7)
BYLAW_HEIGHT_THRESHOLDS = [
    (11.5, "No High-Rise"),  # G+3: before setbacks jump and before fire NOC
    (15.0, "No Fire NOC"),   # G+4: max density before the regulatory jump at 15m
    (24.0, "Below 24m"),     # G+7: before fire command centre mandate
]


# ── Floor-count helpers ──────────────────────────────────────────────────────────────────────────────
def _built_at_floors(
    floors: int,
    plot_area_sqm: float,
    gc_pct: int,
    plot_length_m: float,
    plot_width_m: float,
    road_width: float,
    corner_plot: bool,
    floor_height_m: float,
) -> float:
    sb = get_setbacks(plot_area_sqm, floors * floor_height_m, road_width, corner_plot)
    fp = min(plot_area_sqm * gc_pct / 100,
             max(0.0, plot_length_m - sb["front"] - sb["rear"]) *
             max(0.0, plot_width_m  - sb["side"]  * 2))
    return fp * 10.7639 * floors


def _floors_for_peak_far(
    plot_area_sqm: float,
    gc_pct: int,
    plot_length_m: float,
    plot_width_m: float,
    road_width: float,
    corner_plot: bool,
    floor_height_m: float,
) -> int:
    """
    Floor count that gives the HIGHEST total built-up area.

    With BDA progressive setbacks, adding floors beyond a certain point
    REDUCES total built area because the setback jumps eat the footprint
    faster than the extra floor adds area. This finds the peak.
    """
    best_floors, best_built, declining = 1, 0.0, 0
    prev_built = 0.0
    for floors in range(1, 51):
        built = _built_at_floors(floors, plot_area_sqm, gc_pct,
                                 plot_length_m, plot_width_m,
                                 road_width, corner_plot, floor_height_m)
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


def _floors_for_far_pct(
    far_pct: float,
    plot_area_sqft: float,
    plot_area_sqm: float,
    far: float,
    gc_pct: int,
    plot_length_m: float,
    plot_width_m: float,
    zone: str,
    road_width: float,
    corner_plot: bool,
    floor_height_m: float,
) -> int:
    """Minimum floors to reach far_pct of max FAR; falls back to peak if unreachable."""
    target_sqft = plot_area_sqft * far * far_pct
    last_valid  = 1
    for floors in range(1, 51):
        built = _built_at_floors(floors, plot_area_sqm, gc_pct,
                                 plot_length_m, plot_width_m,
                                 road_width, corner_plot, floor_height_m)
        if built <= 0:
            return last_valid
        last_valid = floors
        if built >= target_sqft:
            return floors
    return last_valid


# ── Main entry point ────────────────────────────────────────────────────────────
def calculate_scenarios(
    zone:              str,
    road_width:        float,
    plot_area_sqft:    float,
    plot_length_m:     float,
    plot_width_m:      float,
    usage:             str,
    corner_plot:       bool  = False,
    basement:          bool  = False,
    scenarios:         list  = None,    # reserved; not used
    floor_height_m:    float = DEFAULT_FLOOR_HEIGHT_M,
    building_height_m: float = 0.0,
    planning_zone:     str   = "zone_A",
) -> dict:
    """
    Generate building scenarios anchored to BDA RMP 2031 bylaw height thresholds.

    Four regulatory tiers (deduplicated if plot FAR caps out early):
      • No High-Rise (≤ 11.5 m) — standard setbacks, no fire requirements
      • No Fire NOC  (≤ 15.0 m) — below fire NOC; max density before setback jump
      • Below 24m    (≤ 24.0 m) — avoids fire command centre / refuge area
      • Max FAR      (100 %)    — maximum density allowed by FAR + progressive setbacks
    """
    # ── Plot area: dimensions (in metres) are the source of truth.
    # plot_area_sqft on the request has historically been mis-populated with
    # the sqm value. Derive both from length × width when available.
    if plot_length_m and plot_width_m:
        plot_area_sqm  = round(plot_length_m * plot_width_m, 2)
        plot_area_sqft = round(plot_area_sqm * 10.7639, 2)
    else:
        plot_area_sqm = round(plot_area_sqft / 10.7639, 2)

    # ── FAR and ground coverage from BDA JSON ──────────────────────────────
    far_data  = get_far(zone, road_width, plot_area_sqm, planning_zone)
    far       = far_data["total"]       # use total (base + TDR)
    gc_pct    = far_data["coverage_pct"]

    fh = floor_height_m or DEFAULT_FLOOR_HEIGHT_M
    max_built_sqft = round(plot_area_sqft * far, 1)

    # ── Absolute ceiling from user-supplied height cap ─────────────────────
    height_cap_active = building_height_m > 0
    height_cap_floors = max(1, math.floor(building_height_m / fh)) if height_cap_active else 50

    # Peak FAR: floor count that gives the HIGHEST total built area.
    # With progressive setbacks, adding floors beyond this point actually
    # REDUCES built area (setback jumps eat footprint faster than floors add).
    peak_far_floors = _floors_for_peak_far(
        plot_area_sqm=plot_area_sqm, gc_pct=gc_pct,
        plot_length_m=plot_length_m, plot_width_m=plot_width_m,
        road_width=road_width, corner_plot=corner_plot, floor_height_m=fh,
    )

    # Ceiling for ALL scenarios = user height cap (default: no ceiling)
    ceiling = height_cap_floors   # already set above; 50 if no cap

    # Regulatory threshold scenarios: always show all 3 breakpoints, each
    # clamped only to the ceiling (never to peak_far, so Below24m always appears)
    floor_to_label: dict = {}
    for height_threshold, label in BYLAW_HEIGHT_THRESHOLDS:
        f = max(1, math.floor(height_threshold / fh))
        f = min(f, ceiling)
        if f not in floor_to_label:
            floor_to_label[f] = label

    # Max FAR slot: peak_far_floors clamped to ceiling
    peak_clamped = min(peak_far_floors, ceiling)
    if peak_clamped in floor_to_label:
        floor_to_label[peak_clamped] += " / Max FAR"   # merge with threshold label
    else:
        floor_to_label[peak_clamped] = "Max FAR"

    # Max Height slot: only add when user has an active height cap AND
    # the height cap floor is different from the Max FAR floor
    if height_cap_active and height_cap_floors != peak_clamped:
        if height_cap_floors in floor_to_label:
            floor_to_label[height_cap_floors] += " / Max Height"
        else:
            floor_to_label[height_cap_floors] = "Max Height"

    # ── Compute each unique scenario ───────────────────────────────────────
    results = []
    for floors in sorted(floor_to_label):
        label = floor_to_label[floors]
        s = _compute_scenario(
            label          = label,
            floors         = floors,
            plot_area_sqft = plot_area_sqft,
            plot_area_sqm  = plot_area_sqm,
            plot_length_m  = plot_length_m,
            plot_width_m   = plot_width_m,
            far            = far,
            road_width     = road_width,
            zone           = zone,
            usage          = usage,
            corner_plot    = corner_plot,
            basement       = basement,
            gc_pct         = gc_pct,
            floor_height_m = fh,
        )
        s["far_pct"]         = round(s["far_efficiency_pct"] / 100, 2)
        s["far_target_sqft"] = max_built_sqft   # 100% FAR reference line for bar chart
        s["floors_label"]    = f"G+{floors - 1}"
        s["exceeds_far"]     = False
        results.append(s)

    # ── Recommended: highest density without Fire NOC ──────────────────────
    no_noc    = [s for s in results if not s["fire_noc_required"]]
    best_pool = no_noc if no_noc else results
    best      = max(best_pool, key=lambda s: s["total_built_sqft"])

    return {
        "plot_area_sqft":  plot_area_sqft,
        "plot_area_sqm":   plot_area_sqm,
        "far":             far,
        "far_base":        far_data["base"],
        "far_tdr":         far_data["tdr"],
        "max_built_sqft":  max_built_sqft,
        "zone":            zone,
        "road_width":      road_width,
        "planning_zone":   planning_zone,
        "recommended":     best["label"],
        "scenarios":       results,
    }