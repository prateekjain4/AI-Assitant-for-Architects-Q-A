"""
ranchi_planning_service.py
──────────────────────────
Full planning calculation for Ranchi RMC Bye-Laws 2009.
Mirrors the output shape of calculate_plot_planning() so the Angular
frontend can reuse the same result-panel template with minimal changes.
"""
import math
from app.services.ranchi_rules_engine import (
    get_far, get_setbacks, get_ground_coverage,
    fire_noc_required, lift_mandatory, get_parking,
    max_height_for_road, max_height_for_plot_width,
    normalise_zone, zone_display_name,
)


def _sqm_to_sqft(sqm: float) -> float:
    return round(sqm * 10.7639, 2)


def _sqft_to_sqm(sqft: float) -> float:
    return round(sqft / 10.7639, 2)


def calculate_ranchi_planning(
    zone:             str,
    plot_length_m:    float,
    plot_width_m:     float,
    road_width_m:     float,
    building_height_m: float,
    usage:            str   = "residential",
    corner_plot:      bool  = False,
    basement:         bool  = False,
    floor_height_m:   float = 3.2,
    locality:         str   = "Ranchi",
    ward:             str   = "",
) -> dict:

    canon_zone   = normalise_zone(zone)
    plot_area_m2 = round(plot_length_m * plot_width_m, 2)
    plot_area_sqft = round(_sqm_to_sqft(plot_area_m2), 0)

    # ── Height cap ────────────────────────────────────────────────
    road_ht_cap  = max_height_for_road(road_width_m)
    width_ht_cap = max_height_for_plot_width(plot_width_m, usage)
    effective_ht = min(building_height_m, road_ht_cap, width_ht_cap)

    ht_capped    = effective_ht < building_height_m
    ht_cap_reason = ""
    if effective_ht == road_ht_cap and ht_capped:
        ht_cap_reason = f"Road width {road_width_m} m caps height to {road_ht_cap} m (RMC Sec 21.2a)"
    elif effective_ht == width_ht_cap and ht_capped:
        ht_cap_reason = f"Plot width ≤10 m caps height to {width_ht_cap} m (RMC Bye-Law)"

    # ── FAR ───────────────────────────────────────────────────────
    far_data     = get_far(canon_zone, road_width_m, plot_area_m2)
    far_val      = far_data["total"]

    # ── Ground coverage ───────────────────────────────────────────
    cov_pct      = get_ground_coverage(plot_area_m2, effective_ht)

    # ── Setbacks ──────────────────────────────────────────────────
    sb = get_setbacks(
        plot_depth_m      = plot_length_m,   # depth = length (front-to-rear)
        plot_width_m      = plot_width_m,
        building_height_m = effective_ht,
        usage             = usage,
        road_width_m      = road_width_m,
    )

    if sb["not_permitted"]:
        # Return a structured error that the frontend can show
        return {
            "error":            True,
            "error_message":    sb["note"],
            "zone":             canon_zone,
            "zone_display":     zone_display_name(canon_zone),
            "plot_area":        plot_area_sqft,
            "plot_area_sqm":    plot_area_m2,
            "building_height_m": effective_ht,
        }

    front_m = sb["front"]
    side_m  = sb["side"]
    rear_m  = sb["rear"]

    # ── Footprint (after setbacks) ────────────────────────────────
    buildable_length = max(0.0, plot_length_m - front_m - rear_m)
    buildable_width  = max(0.0, plot_width_m  - 2 * side_m)
    footprint_m2     = round(buildable_length * buildable_width, 2)
    footprint_sqft   = round(_sqm_to_sqft(footprint_m2), 0)

    # Apply coverage cap
    max_footprint_m2 = round(plot_area_m2 * cov_pct / 100, 2)
    if footprint_m2 > max_footprint_m2:
        footprint_m2   = max_footprint_m2
        footprint_sqft = round(_sqm_to_sqft(footprint_m2), 0)

    # ── Max built-up area ─────────────────────────────────────────
    max_built_m2   = round(plot_area_m2 * far_val, 2)
    max_built_sqft = round(_sqm_to_sqft(max_built_m2), 0)

    # ── Floors feasible by height ─────────────────────────────────
    floors_by_ht  = max(1, int(effective_ht / floor_height_m))
    # Floors needed to consume max FAR given footprint
    min_floors_for_far = max(1, math.ceil(max_built_m2 / max(footprint_m2, 1)))

    # ── Staircase / lift ──────────────────────────────────────────
    num_floors     = floors_by_ht
    lift_req       = lift_mandatory(num_floors)

    # Staircase dimensions (NBC norms)
    stair_width    = 1.5 if num_floors > 4 else 1.2
    stair_label    = f"G+{num_floors - 1}" if num_floors > 1 else "Ground only"

    # ── Fire NOC ──────────────────────────────────────────────────
    footprint_for_fire = footprint_m2
    noc_req = fire_noc_required(effective_ht, footprint_for_fire)

    fire_rules = []
    if effective_ht > 16.0:
        fire_rules.append("Director of Fire Services consent required before building permit (Special Building)")
        fire_rules.append("Joint inspection by RMC + Director of Fire Services before occupancy certificate")
        fire_rules.append("NBC Part IV (Fire and Life Safety) — means of egress compliance mandatory")
    if footprint_for_fire > 500:
        fire_rules.append("Ground coverage > 500 sqm — classified as Special Building (fire consent required)")

    # ── Parking ───────────────────────────────────────────────────
    num_units   = max(1, int(max_built_m2 / 60)) if usage == "residential" else 1
    parking     = get_parking(usage, max_built_m2, num_units)

    # ── Trees ─────────────────────────────────────────────────────
    if plot_area_m2 <= 250:
        trees = "2–4"
    elif plot_area_m2 <= 1000:
        trees = "4–6"
    else:
        trees = "8+"

    # ── Compliance checks ─────────────────────────────────────────
    compliance = []
    if effective_ht > 12.0 and road_width_m < 6.0:
        compliance.append("⚠ Buildings above 12 m require minimum 6 m access road (RMC Sec 21.2a)")
    if effective_ht > 16.0 and road_width_m < 12.0:
        compliance.append("⚠ Buildings above 16 m require minimum 12 m access road (RMC Sec 21.2a)")
    if basement:
        compliance.append("Basement must follow same setback norms as superstructure (Table 2A Note 11)")
        compliance.append("Basement area counted for fee calculation but NOT towards FAR")
    if num_floors > 4:
        compliance.append("Lift mandatory — building exceeds G+3 (RMC Bye-Law 17.6.1j)")
    compliance.append("Rain water harvesting mandatory (Bye-Law 5.3.1vi)")
    compliance.append(f"Plant {trees} trees on plot (Bye-Law 20.1.6)")
    if usage in ("commercial", "mixed"):
        compliance.append("Lighting poles (min 6 m, 150 W) every 15 m of front boundary connected to generator")

    # ── Warnings ──────────────────────────────────────────────────
    warnings = []
    if ht_capped:
        warnings.append(f"Building height reduced to {effective_ht} m — {ht_cap_reason}")
    if sb.get("high_rise_extra"):
        warnings.append("Progressive additional setbacks applied above 22 m (Table 2A-I Note)")
    if footprint_m2 <= 0:
        warnings.append("⚠ No buildable area after setbacks — plot is too narrow/shallow for this height")

    # ── Summary sections ──────────────────────────────────────────
    section_summaries = {
        "far": (
            f"Zone: {zone_display_name(canon_zone)} · FAR {far_val} · "
            f"Max built-up {max_built_sqft:,.0f} sq ft ({max_built_m2:,.0f} sqm)"
        ),
        "setbacks": (
            f"Front {front_m} m · Side {side_m} m · Rear {rear_m} m"
            + (" · Progressive extras above 22 m apply" if sb.get("high_rise_extra") else "")
        ),
        "staircase": (
            f"{stair_label} · {floors_by_ht} floors feasible · "
            f"{'Lift mandatory' if lift_req else 'Lift optional'}"
        ),
    }

    return {
        # Identity
        "city":              "ranchi",
        "authority":         "RMC",
        "zone":              canon_zone,
        "zone_display":      zone_display_name(canon_zone),
        "locality":          locality,
        "ward":              ward,
        "usage":             usage,

        # Plot
        "plot_area":         plot_area_sqft,
        "plot_area_sqm":     plot_area_m2,
        "plot_length_m":     plot_length_m,
        "plot_width_m":      plot_width_m,
        "road_width_m":      road_width_m,

        # FAR
        "far":               far_val,
        "far_base":          far_data["base"],
        "far_tdr":           0.0,
        "max_built_area":    max_built_sqft,
        "max_built_sqm":     max_built_m2,

        # Coverage & footprint
        "ground_coverage_pct": cov_pct,
        "footprint_sqm":     footprint_m2,
        "footprint_sqft":    footprint_sqft,

        # Setbacks
        "setbacks": {
            "front":         front_m,
            "side":          side_m,
            "rear":          rear_m,
            "corner_relaxation": corner_plot,
            "high_rise_rule": bool(sb.get("high_rise_extra")),
        },

        # Height
        "building_height_m":   effective_ht,
        "requested_height_m":  building_height_m,
        "height_capped":       ht_capped,
        "floor_height_m":      floor_height_m,

        # Staircase / floors
        "staircase": {
            "num_floors":      num_floors,
            "label":           stair_label,
            "stair_width_m":   stair_width,
            "lift_mandatory":  lift_req,
        },
        "min_floors_for_max_far": min_floors_for_far,

        # Fire
        "fire_data": {
            "noc_required":    noc_req,
            "rules":           fire_rules,
        },
        "fire_rules":          fire_rules,

        # Parking
        "parking": {
            "required": {
                "cars":         parking["cars"],
                "two_wheelers": parking["two_wheelers"],
            },
        },

        # Basement
        "basement": {
            "requested":       basement,
            "same_setbacks":   True,
            "counted_in_far":  False,
            "note":            "Basement follows superstructure setbacks. Not counted in FAR.",
        },

        # Compliance & warnings
        "compliance":        compliance,
        "warnings":          warnings,
        "section_summaries": section_summaries,
        "planning_zone":     "ranchi_rmc",
    }