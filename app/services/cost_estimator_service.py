"""
Cost Estimator Service
======================
Structure & basement costs   →  KPWD Common SR 2022 (Vol I), BBMP +10% surcharge applied
Brickwork / plaster / waterproofing → KPWD SR 2022 (now calculated from wall/area, not market est.)
Site development             →  KPWD SR 2022 (compound wall, sump, septic, approach road)
Flooring / doors / MEP       →  Market estimates (Bangalore 2024, clearly flagged)
Steel                        →  KPWD SR 2022: Fe500 = ₹69,357/tonne
AI narrative                 →  gpt-4o-mini (optional, 2-3 sentences)
"""

import math
from app.services.services import get_openai_client

# ── KPWD Common SR 2022 — Concrete (₹/m³) + BBMP +10%
CONCRETE_RATES_M3 = {
    "M20": 6471 * 1.10,   # ₹7,118
    "M25": 6492 * 1.10,   # ₹7,141
    "M30": 7022 * 1.10,   # ₹7,724
}

# Formwork additionality % on concrete rate (KPWD SR Appendix I)
FORMWORK_PCT = {
    "foundation":  0.03,
    "column":      0.10,
    "beam_lintel": 0.20,
    "roof_slab":   0.20,
}

# Steel — Fe500D @ ₹69,357/tonne (KPWD SR 2022) + BBMP 10%
STEEL_RATE_PER_TONNE = 69357 * 1.10   # ₹76,293
STEEL_KG_PER_M3_RCC  = 110            # avg residential/commercial framed structure

# Floor lift: +1% per floor above ground (KPWD SR note)
FLOOR_LIFT_PCT_PER_FLOOR = 0.01

# KPWD SR 2022 — Excavation (₹/m³) + BBMP +10%
EXCAVATION_RATES = {
    "mechanical_0_3m":  49  * 1.10,   # ₹54
    "mechanical_3_6m":  56  * 1.10,   # ₹62
    "manual_0_1.5m":   186  * 1.10,   # ₹205
    "manual_1.5_3m":   199  * 1.10,   # ₹219
    "manual_3_4.5m":   288  * 1.10,   # ₹317
}

# KPWD SR 2022 — Plinth filling ₹2,177/m³ + 10%
PLINTH_FILL_RATE = 2177 * 1.10

# ── KPWD SR 2022 — Masonry, Plastering & Waterproofing + BBMP 10%
# These replace the previous market estimates for these sub-items
BRICK_MASONRY_M3     = 4200 * 1.10   # 230mm brick CM 1:6  → ₹4,620/m³
PLASTER_12MM_M2      =  195 * 1.10   # 12mm cement (1:6)   → ₹214.5/m²
PLASTER_20MM_M2      =  240 * 1.10   # 20mm cement (1:4)   → ₹264/m²
WATERPROOF_BRICKBAT  =  620 * 1.10   # Brick bat coba (terrace) → ₹682/m²
WATERPROOF_BITUMEN   =  380 * 1.10   # Hot bitumen 2-coat (basement) → ₹418/m²

# Wall area ratio: m² of wall per m² of floor area
# Assumes avg 3m floor ht, typical room layout, ~30% openings (doors/windows)
WALL_AREA_RATIO = 0.65   # m² wall / m² floor

# ── KPWD SR 2022 — Site Development + BBMP 10%
COMPOUND_WALL_RM     = 2800 * 1.10   # 230mm brick, 1.8m ht → ₹3,080/running metre
SUMP_10KL_LUMP       = 85_000 * 1.10 # UG sump brick masonry 10KL → ₹93,500
SUMP_20KL_LUMP       = 140_000 * 1.10# UG sump 20KL → ₹1,54,000
SEPTIC_TANK_LUMP     = 45_000 * 1.10 # Septic tank + soak pit → ₹49,500
APPROACH_ROAD_M2     =  380 * 1.10   # 50mm WBM road → ₹418/m²
GATE_MARKET          = 35_000        # MS fabricated gate — market estimate

# ── Finishing — Market estimates (Bangalore 2024)
# Brickwork / plaster / waterproofing removed — now calculated from KPWD above
# Flagged as estimates — replace with PWD Buildings SR Vol II when available
FINISHING_RATES_SQM = {
    "residential": {
        "low":  {"flooring": 800,  "doors_windows": 600,  "painting": 250},
        "mid":  {"flooring": 1800, "doors_windows": 1100, "painting": 400},
        "high": {"flooring": 4500, "doors_windows": 2500, "painting": 750},
    },
    "commercial": {
        "low":  {"flooring": 900,  "doors_windows": 700,  "painting": 280},
        "mid":  {"flooring": 2200, "doors_windows": 1400, "painting": 450},
        "high": {"flooring": 6000, "doors_windows": 3000, "painting": 900},
    },
    "mixed": {
        "low":  {"flooring": 850,  "doors_windows": 650,  "painting": 260},
        "mid":  {"flooring": 2000, "doors_windows": 1200, "painting": 420},
        "high": {"flooring": 5200, "doors_windows": 2700, "painting": 820},
    },
    "industrial": {
        "low":  {"flooring": 500,  "doors_windows": 400,  "painting": 180},
        "mid":  {"flooring": 900,  "doors_windows": 700,  "painting": 280},
        "high": {"flooring": 1500, "doors_windows": 1200, "painting": 400},
    },
}

# MEP rates per sqm — market estimates Bangalore 2024
MEP_RATES_SQM = {
    "residential": {"low": 900,  "mid": 1500, "high": 2500},
    "commercial":  {"low": 1100, "mid": 1900, "high": 3200},
    "mixed":       {"low": 1000, "mid": 1700, "high": 2800},
    "industrial":  {"low": 800,  "mid": 1300, "high": 2000},
}

# Parking bay cost per car space — market estimate
PARKING_BAY_COST = {
    "surface":  75_000,
    "stilt":   110_000,
    "basement": 200_000,
}

CONTINGENCY_PCT  = 0.08
FIRE_NOC_COST    = 350_000   # ₹3.5L (sprinklers + signage + emergency lighting)


# ─────────────────────────────────────────────────────────────────
def estimate_cost(
    plot_length_m:      float,
    plot_width_m:       float,
    built_up_sqm:       float,
    num_floors:         int,
    floor_height_m:     float,
    setback_front:      float,
    setback_side:       float,
    setback_rear:       float,
    usage:              str,
    zone:               str,
    fire_noc_required:  bool,
    basement:           bool,
    car_spaces:         int,
    tier:               str = "mid",
) -> dict:

    usage_key = usage.lower() if usage.lower() in FINISHING_RATES_SQM else "residential"
    tier_key  = tier if tier in ("low", "mid", "high") else "mid"

    buildable_w   = max(1.0, plot_length_m - 2 * setback_side)
    buildable_d   = max(1.0, plot_width_m  - setback_front - setback_rear)
    footprint_sqm = buildable_w * buildable_d
    plot_area_sqm = plot_length_m * plot_width_m

    # ── 1. STRUCTURE (KPWD SR 2022) ─────────────────────────────
    concrete_grade    = "M25"
    concrete_rate_m3  = CONCRETE_RATES_M3[concrete_grade]
    concrete_m3_per_sqm = 0.15

    structure_total = 0.0
    floor_breakdown = []
    for f in range(num_floors):
        lift_factor    = 1 + f * FLOOR_LIFT_PCT_PER_FLOOR
        formwork_extra = concrete_rate_m3 * FORMWORK_PCT["roof_slab"]
        concrete_cost  = footprint_sqm * concrete_m3_per_sqm * (concrete_rate_m3 + formwork_extra) * lift_factor
        steel_cost     = footprint_sqm * concrete_m3_per_sqm * STEEL_KG_PER_M3_RCC * (STEEL_RATE_PER_TONNE / 1000)
        floor_cost     = concrete_cost + steel_cost
        structure_total += floor_cost
        floor_breakdown.append({
            "floor":              f,
            "label":              "GF" if f == 0 else f"F{f}",
            "cost":               round(floor_cost),
            "concrete_cost":      round(concrete_cost),
            "steel_cost":         round(steel_cost),
            "lift_factor":        round(lift_factor, 3),
            "footprint_sqm":      round(footprint_sqm, 1),
            "formula":            (
                f"{footprint_sqm:.0f} m² × {concrete_m3_per_sqm} m³/m² × "
                f"₹{concrete_rate_m3 + formwork_extra:,.0f}/m³ × {lift_factor:.2f} lift "
                f"= ₹{concrete_cost:,.0f} (concrete) + "
                f"₹{steel_cost:,.0f} (steel)"
            ),
        })

    # ── 2. BASEMENT (KPWD SR 2022) ──────────────────────────────
    basement_cost = 0.0
    basement_breakdown = {}
    if basement:
        depth_m         = 3.5
        exc_vol_m3      = plot_area_sqm * depth_m
        exc_rate        = EXCAVATION_RATES["mechanical_3_6m"] if depth_m > 3 else EXCAVATION_RATES["mechanical_0_3m"]
        excavation_cost = exc_vol_m3 * exc_rate
        raft_concrete   = plot_area_sqm * 0.30 * CONCRETE_RATES_M3["M30"]
        waterproof_bsmt = plot_area_sqm * WATERPROOF_BITUMEN     # KPWD SR 2022
        retaining_cost  = (2 * (plot_length_m + plot_width_m)) * depth_m * 3500
        basement_cost   = excavation_cost + raft_concrete + waterproof_bsmt + retaining_cost
        basement_breakdown = {
            "excavation": {
                "cost": round(excavation_cost), "source": "KPWD SR 2022",
                "qty": f"{exc_vol_m3:.0f} m³", "rate": round(exc_rate),
                "formula": f"{plot_area_sqm:.0f} m² × {depth_m}m × ₹{exc_rate:.0f}/m³ = ₹{excavation_cost:,.0f}",
            },
            "raft_slab": {
                "cost": round(raft_concrete), "source": "KPWD SR 2022",
                "qty": f"{plot_area_sqm:.0f} m² × 0.30m", "rate": round(CONCRETE_RATES_M3["M30"]),
                "formula": f"{plot_area_sqm:.0f} m² × 0.30 m × ₹{CONCRETE_RATES_M3['M30']:,.0f}/m³ = ₹{raft_concrete:,.0f}",
            },
            "waterproofing": {
                "cost": round(waterproof_bsmt), "source": "KPWD SR 2022",
                "qty": f"{plot_area_sqm:.0f} m²", "rate": round(WATERPROOF_BITUMEN),
                "formula": f"{plot_area_sqm:.0f} m² × ₹{WATERPROOF_BITUMEN:.0f}/m² = ₹{waterproof_bsmt:,.0f}",
            },
            "retaining_walls": {
                "cost": round(retaining_cost), "source": "Market estimate",
                "qty": f"{2*(plot_length_m+plot_width_m):.0f} rm × {depth_m}m", "rate": 3500,
                "formula": f"2×({plot_length_m:.0f}+{plot_width_m:.0f})m × {depth_m}m × ₹3,500/m³ = ₹{retaining_cost:,.0f}",
            },
            "total":  round(basement_cost),
            "source": "KPWD SR 2022 (excavation, concrete, waterproofing) + market (retaining walls)",
        }

    # ── 3. FINISHING — KPWD items + market items ─────────────────
    # KPWD SR 2022: brickwork, plastering, terrace waterproofing
    wall_area_total  = built_up_sqm * WALL_AREA_RATIO          # m² wall across all floors
    terrace_area     = footprint_sqm                            # top slab waterproofing
    brick_vol        = wall_area_total * 0.23                   # 230mm thickness → m³
    brick_cost       = brick_vol * BRICK_MASONRY_M3
    plaster_cost     = wall_area_total * 2 * PLASTER_12MM_M2   # both faces
    waterproof_cost  = terrace_area * WATERPROOF_BRICKBAT

    # Market estimate: flooring, doors/windows, painting
    fin_rates        = FINISHING_RATES_SQM[usage_key][tier_key]
    flooring_cost    = built_up_sqm * fin_rates["flooring"]
    doors_win_cost   = built_up_sqm * fin_rates["doors_windows"]
    painting_cost    = built_up_sqm * fin_rates["painting"]

    finishing_cost = brick_cost + plaster_cost + waterproof_cost + flooring_cost + doors_win_cost + painting_cost
    finishing_breakdown = {
        "brickwork": {
            "cost": round(brick_cost), "source": "KPWD SR 2022",
            "qty": f"{wall_area_total:.0f} m² × 0.23 m = {brick_vol:.0f} m³",
            "rate": BRICK_MASONRY_M3,
            "formula": f"{wall_area_total:.0f} m² wall × 0.23 m thick × ₹{BRICK_MASONRY_M3:,.0f}/m³ = ₹{brick_cost:,.0f}",
        },
        "plastering": {
            "cost": round(plaster_cost), "source": "KPWD SR 2022",
            "qty": f"{wall_area_total:.0f} m² × 2 faces",
            "rate": PLASTER_12MM_M2,
            "formula": f"{wall_area_total:.0f} m² × 2 faces × ₹{PLASTER_12MM_M2:.1f}/m² = ₹{plaster_cost:,.0f}",
        },
        "waterproofing_terrace": {
            "cost": round(waterproof_cost), "source": "KPWD SR 2022",
            "qty": f"{terrace_area:.0f} m²",
            "rate": WATERPROOF_BRICKBAT,
            "formula": f"{terrace_area:.0f} m² terrace × ₹{WATERPROOF_BRICKBAT:.0f}/m² = ₹{waterproof_cost:,.0f}",
        },
        "flooring": {
            "cost": round(flooring_cost), "source": "Market estimate",
            "qty": f"{built_up_sqm:.0f} sqm",
            "rate": fin_rates["flooring"],
            "formula": f"{built_up_sqm:.0f} sqm × ₹{fin_rates['flooring']:,}/sqm = ₹{flooring_cost:,.0f}",
        },
        "doors_windows": {
            "cost": round(doors_win_cost), "source": "Market estimate",
            "qty": f"{built_up_sqm:.0f} sqm",
            "rate": fin_rates["doors_windows"],
            "formula": f"{built_up_sqm:.0f} sqm × ₹{fin_rates['doors_windows']:,}/sqm = ₹{doors_win_cost:,.0f}",
        },
        "painting": {
            "cost": round(painting_cost), "source": "Market estimate",
            "qty": f"{built_up_sqm:.0f} sqm",
            "rate": fin_rates["painting"],
            "formula": f"{built_up_sqm:.0f} sqm × ₹{fin_rates['painting']:,}/sqm = ₹{painting_cost:,.0f}",
        },
        "total": round(finishing_cost),
    }

    # ── 4. MEP (market estimate) ─────────────────────────────────
    mep_rate  = MEP_RATES_SQM[usage_key][tier_key]
    mep_cost  = built_up_sqm * mep_rate
    mep_breakdown = {
        "rate_per_sqm": mep_rate,
        "qty_sqm":      round(built_up_sqm),
        "total":        round(mep_cost),
        "formula":      f"{built_up_sqm:.0f} sqm × ₹{mep_rate:,}/sqm = ₹{mep_cost:,.0f}",
        "source":       "Market estimate — Bangalore 2024",
    }

    # ── 5. PARKING ───────────────────────────────────────────────
    parking_type = "basement" if basement else "surface"
    parking_cost = car_spaces * PARKING_BAY_COST[parking_type]
    parking_breakdown = {
        "car_spaces":   car_spaces,
        "type":         parking_type,
        "cost_per_bay": PARKING_BAY_COST[parking_type],
        "total":        round(parking_cost),
        "formula":      f"{car_spaces} bays × ₹{PARKING_BAY_COST[parking_type]:,}/bay ({parking_type}) = ₹{parking_cost:,.0f}",
        "source":       "Market estimate — Bangalore 2024",
    }

    # ── 6. SITE DEVELOPMENT (KPWD SR 2022) ──────────────────────
    perimeter_m       = 2 * (plot_length_m + plot_width_m)
    compound_len      = perimeter_m * 0.75        # 25% opening for gate / entrance gap
    compound_cost     = compound_len * COMPOUND_WALL_RM
    sump_cost         = SUMP_20KL_LUMP if plot_area_sqm > 200 else SUMP_10KL_LUMP
    sump_label        = "20KL" if plot_area_sqm > 200 else "10KL"
    septic_cost       = SEPTIC_TANK_LUMP
    approach_w        = max(3.0, plot_width_m * 0.4)   # driveway width
    approach_area     = approach_w * 6.0               # 6m depth from road
    approach_cost     = approach_area * APPROACH_ROAD_M2
    gate_cost         = GATE_MARKET

    site_dev_cost = compound_cost + sump_cost + septic_cost + approach_cost + gate_cost
    site_dev_breakdown = {
        "compound_wall":       {"cost": round(compound_cost), "qty": f"{compound_len:.0f} rm",  "source": "KPWD SR 2022"},
        "underground_sump":    {"cost": round(sump_cost),     "qty": sump_label,                "source": "KPWD SR 2022"},
        "septic_tank":         {"cost": round(septic_cost),   "qty": "1 unit",                  "source": "KPWD SR 2022"},
        "approach_road":       {"cost": round(approach_cost), "qty": f"{approach_area:.0f} m²", "source": "KPWD SR 2022"},
        "gate":                {"cost": round(gate_cost),     "qty": "1 unit",                  "source": "Market estimate"},
        "total":               round(site_dev_cost),
        "source":              "KPWD SR 2022 (compound wall, sump, septic, road) + market estimate (gate)",
    }

    # ── 7. FIRE NOC ──────────────────────────────────────────────
    fire_cost = FIRE_NOC_COST if fire_noc_required else 0

    # ── 8. SUBTOTALS + CONTINGENCY ───────────────────────────────
    subtotal    = structure_total + basement_cost + finishing_cost + mep_cost + parking_cost + site_dev_cost + fire_cost
    contingency = subtotal * CONTINGENCY_PCT
    total       = subtotal + contingency

    # ── 9. AI NARRATIVE ──────────────────────────────────────────
    narrative = _generate_narrative(
        usage=usage, zone=zone, tier=tier,
        built_up_sqm=built_up_sqm, num_floors=num_floors,
        total=total, structure_total=structure_total,
        finishing_cost=finishing_cost, mep_cost=mep_cost,
        site_dev_cost=site_dev_cost,
        basement=basement, fire_noc_required=fire_noc_required,
        car_spaces=car_spaces,
    )

    # Count how many cost items are KPWD-sourced
    kpwd_items_count = 5  # structure, basement, brickwork, plastering, waterproofing, site_dev

    return {
        "tier":             tier_key,
        "usage":            usage,
        "zone":             zone,
        "built_up_sqm":     round(built_up_sqm),
        "footprint_sqm":    round(footprint_sqm, 1),
        "plot_area_sqm":    round(plot_area_sqm, 1),
        "num_floors":       num_floors,
        # Summary cards
        "structure_cost":   round(structure_total),
        "basement_cost":    round(basement_cost),
        "finishing_cost":   round(finishing_cost),
        "mep_cost":         round(mep_cost),
        "parking_cost":     round(parking_cost),
        "site_dev_cost":    round(site_dev_cost),
        "fire_cost":        round(fire_cost),
        "contingency":      round(contingency),
        "total_cost":       round(total),
        "cost_per_sqm":     round(total / built_up_sqm) if built_up_sqm > 0 else 0,
        "cost_per_floor":   round(total / num_floors) if num_floors > 0 else 0,
        # Breakdowns
        "floor_breakdown":        floor_breakdown,
        "basement_breakdown":     basement_breakdown,
        "finishing_breakdown":    finishing_breakdown,
        "mep_breakdown":          mep_breakdown,
        "parking_breakdown":      parking_breakdown,
        "site_dev_breakdown":     site_dev_breakdown,
        # AI
        "narrative":        narrative,
        # Flags
        "structure_source": "KPWD Common SR 2022 — Vol I (BBMP +10% surcharge applied)",
        "estimate_flags": [
            "Structure, basement, brickwork, plastering, waterproofing & site development from KPWD SR 2022",
            "Flooring, doors/windows, MEP & gate are market estimates (Bangalore 2024) — verify with contractor",
            "BBMP area surcharge of 10% applied on all KPWD SR rates",
            *(["Fire NOC compliance cost included (sprinklers, signage, emergency lighting)"] if fire_noc_required else []),
        ],
    }


def _generate_narrative(usage, zone, tier, built_up_sqm, num_floors,
                         total, structure_total, finishing_cost,
                         mep_cost, site_dev_cost, basement,
                         fire_noc_required, car_spaces) -> str:
    try:
        client = get_openai_client()
        structure_pct  = round(structure_total  / total * 100) if total else 0
        finishing_pct  = round(finishing_cost   / total * 100) if total else 0
        mep_pct        = round(mep_cost         / total * 100) if total else 0
        site_dev_pct   = round(site_dev_cost    / total * 100) if total else 0

        prompt = f"""
You are a cost consultant for Bangalore construction projects. Write 3 concise sentences:
1. The dominant cost driver and percentage for this project
2. One key risk or cost spike specific to this building type/zone
3. One practical cost-saving tip for this tier

Project: {usage} building, {zone} zone, {num_floors} floors, {built_up_sqm:.0f} sqm built-up
Tier: {tier} finish
Total: ₹{total/10_000_000:.2f} Cr
Structure: {structure_pct}%, Finishing: {finishing_pct}%, MEP: {mep_pct}%, Site dev: {site_dev_pct}%
Basement: {basement}, Fire NOC: {fire_noc_required}, Car spaces: {car_spaces}

Be specific to Bangalore market. Cite BBMP/BDA/KPWD where relevant. Under 80 words total.
"""
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return (
            f"Structure dominates at {round(structure_total/total*100) if total else 0}% of total cost (KPWD SR 2022 rates). "
            f"{'Fire NOC compliance adds ₹3.5L for sprinkler systems. ' if fire_noc_required else ''}"
            f"{'Basement waterproofing is a key risk in Bangalore clay soil. ' if basement else ''}"
            f"Site development (compound wall, sump, approach road) adds ₹{site_dev_cost/100_000:.1f}L — often underestimated."
        )
