"""
Cost Estimator Service
======================
Structure & basement costs  →  KPWD Common SR 2022 (Vol I), BBMP +10% surcharge applied
Finishing & MEP costs       →  Market estimates (Bangalore 2024, clearly flagged)
Steel                       →  KPWD SR 2022: Fe500 = ₹69,357/tonne
AI narrative                →  gpt-4o-mini (optional, 2-3 sentences)
"""

import math
from app.services.services import get_openai_client

# ── KPWD Common SR 2022 — Concrete rates (₹/m³, superstructure)
# Source: Vol I Common SR, Chapter 2, + BBMP +10% surcharge
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

# Steel reinforcement — Fe500 @ ₹69,357/tonne (KPWD SR 2022) + BBMP 10%
STEEL_RATE_PER_TONNE = 69357 * 1.10   # ₹76,293
STEEL_KG_PER_M3_RCC  = 110            # avg for residential/commercial framed structure

# Floor lift additionality: +1% per floor above ground (KPWD SR note)
FLOOR_LIFT_PCT_PER_FLOOR = 0.01

# KPWD SR 2022 — Excavation rates (₹/m³) + BBMP +10%
EXCAVATION_RATES = {
    "mechanical_0_3m":  49  * 1.10,   # ₹54
    "mechanical_3_6m":  56  * 1.10,   # ₹62
    "manual_0_1.5m":   186  * 1.10,   # ₹205
    "manual_1.5_3m":   199  * 1.10,   # ₹219
    "manual_3_4.5m":   288  * 1.10,   # ₹317
}

# KPWD SR 2022 — Plinth filling with sand ₹2,177/m³ + 10%
PLINTH_FILL_RATE = 2177 * 1.10

# ── Finishing & MEP — Market estimates (Bangalore 2024)
# Flagged as estimates — replace with PWD Buildings SR Vol II when available
FINISHING_RATES_SQM = {
    "residential": {
        "low":  {"brickwork_plaster": 900,  "flooring": 800,  "doors_windows": 600,  "painting": 250, "waterproofing": 180},
        "mid":  {"brickwork_plaster": 1400, "flooring": 1800, "doors_windows": 1100, "painting": 400, "waterproofing": 280},
        "high": {"brickwork_plaster": 2000, "flooring": 4500, "doors_windows": 2500, "painting": 750, "waterproofing": 450},
    },
    "commercial": {
        "low":  {"brickwork_plaster": 950,  "flooring": 900,  "doors_windows": 700,  "painting": 280, "waterproofing": 200},
        "mid":  {"brickwork_plaster": 1500, "flooring": 2200, "doors_windows": 1400, "painting": 450, "waterproofing": 320},
        "high": {"brickwork_plaster": 2200, "flooring": 6000, "doors_windows": 3000, "painting": 900, "waterproofing": 500},
    },
    "mixed": {
        "low":  {"brickwork_plaster": 920,  "flooring": 850,  "doors_windows": 650,  "painting": 260, "waterproofing": 190},
        "mid":  {"brickwork_plaster": 1450, "flooring": 2000, "doors_windows": 1200, "painting": 420, "waterproofing": 300},
        "high": {"brickwork_plaster": 2100, "flooring": 5200, "doors_windows": 2700, "painting": 820, "waterproofing": 470},
    },
    "industrial": {
        "low":  {"brickwork_plaster": 700,  "flooring": 500,  "doors_windows": 400,  "painting": 180, "waterproofing": 150},
        "mid":  {"brickwork_plaster": 1000, "flooring": 900,  "doors_windows": 700,  "painting": 280, "waterproofing": 220},
        "high": {"brickwork_plaster": 1400, "flooring": 1500, "doors_windows": 1200, "painting": 400, "waterproofing": 320},
    },
}

# MEP rates per sqm — market estimates Bangalore 2024
MEP_RATES_SQM = {
    "residential": {"low": 900,  "mid": 1500, "high": 2500},
    "commercial":  {"low": 1100, "mid": 1900, "high": 3200},
    "mixed":       {"low": 1000, "mid": 1700, "high": 2800},
    "industrial":  {"low": 800,  "mid": 1300, "high": 2000},
}

# Parking bay cost (construction) per car space — market estimate
PARKING_BAY_COST = {
    "surface":  75_000,
    "stilt":   110_000,
    "basement": 200_000,
}

CONTINGENCY_PCT  = 0.08   # 8% contingency
FIRE_NOC_COST    = 350_000  # ₹3.5L base (sprinklers/signs for NOC-required buildings)


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
    tier:               str = "mid",   # low | mid | high
) -> dict:

    usage_key = usage.lower() if usage.lower() in FINISHING_RATES_SQM else "residential"
    tier_key  = tier if tier in ("low", "mid", "high") else "mid"

    buildable_w   = max(1.0, plot_length_m - 2 * setback_side)
    buildable_d   = max(1.0, plot_width_m  - setback_front - setback_rear)
    footprint_sqm = buildable_w * buildable_d
    slab_sqm      = footprint_sqm   # per floor

    # ── 1. STRUCTURE (KPWD SR 2022) ─────────────────────────────
    concrete_grade    = "M25"
    concrete_rate_m3  = CONCRETE_RATES_M3[concrete_grade]
    concrete_m3_per_sqm = 0.15    # avg slab + column + beam per sqm floor area

    structure_total = 0.0
    floor_breakdown = []
    for f in range(num_floors):
        lift_factor    = 1 + f * FLOOR_LIFT_PCT_PER_FLOOR
        formwork_extra = concrete_rate_m3 * FORMWORK_PCT["roof_slab"]
        concrete_cost  = slab_sqm * concrete_m3_per_sqm * (concrete_rate_m3 + formwork_extra) * lift_factor
        steel_cost     = slab_sqm * concrete_m3_per_sqm * STEEL_KG_PER_M3_RCC * (STEEL_RATE_PER_TONNE / 1000)
        floor_cost     = concrete_cost + steel_cost
        structure_total += floor_cost
        floor_breakdown.append({
            "floor":    f,
            "label":    "GF" if f == 0 else f"F{f}",
            "cost":     round(floor_cost),
        })

    # ── 2. BASEMENT (KPWD SR 2022) ──────────────────────────────
    basement_cost = 0.0
    basement_breakdown = {}
    if basement:
        depth_m         = 3.5     # typical one basement level
        bsmt_area       = plot_length_m * plot_width_m
        exc_vol_m3      = bsmt_area * depth_m
        exc_rate        = EXCAVATION_RATES["mechanical_3_6m"] if depth_m > 3 else EXCAVATION_RATES["mechanical_0_3m"]
        excavation_cost = exc_vol_m3 * exc_rate
        raft_concrete   = bsmt_area * 0.30 * CONCRETE_RATES_M3["M30"]   # 300mm raft
        waterproof_cost = bsmt_area * 800   # market estimate
        retaining_cost  = (2 * (plot_length_m + plot_width_m)) * depth_m * 3500   # retaining walls
        basement_cost   = excavation_cost + raft_concrete + waterproof_cost + retaining_cost
        basement_breakdown = {
            "excavation":     round(excavation_cost),
            "raft_slab":      round(raft_concrete),
            "waterproofing":  round(waterproof_cost),
            "retaining_walls":round(retaining_cost),
            "total":          round(basement_cost),
            "source":         "KPWD SR 2022 (excavation + concrete) + market estimate (waterproofing)",
        }

    # ── 3. FINISHING (market estimate) ──────────────────────────
    fin_rates   = FINISHING_RATES_SQM[usage_key][tier_key]
    fin_total_rate = sum(fin_rates.values())
    finishing_cost = built_up_sqm * fin_total_rate
    finishing_breakdown = {k: round(built_up_sqm * v) for k, v in fin_rates.items()}
    finishing_breakdown["total"] = round(finishing_cost)
    finishing_breakdown["source"] = "Market estimate — Bangalore 2024 (replace with PWD Buildings SR Vol II)"

    # ── 4. MEP (market estimate) ─────────────────────────────────
    mep_rate  = MEP_RATES_SQM[usage_key][tier_key]
    mep_cost  = built_up_sqm * mep_rate
    mep_breakdown = {
        "rate_per_sqm": mep_rate,
        "total":        round(mep_cost),
        "source":       "Market estimate — Bangalore 2024",
    }

    # ── 5. PARKING ───────────────────────────────────────────────
    parking_type = "basement" if basement else "surface"
    parking_cost = car_spaces * PARKING_BAY_COST[parking_type]
    parking_breakdown = {
        "car_spaces":    car_spaces,
        "type":          parking_type,
        "cost_per_bay":  PARKING_BAY_COST[parking_type],
        "total":         round(parking_cost),
        "source":        "Market estimate — Bangalore 2024",
    }

    # ── 6. FIRE NOC COMPLIANCE ───────────────────────────────────
    fire_cost = FIRE_NOC_COST if fire_noc_required else 0

    # ── 7. SUBTOTALS + CONTINGENCY ───────────────────────────────
    subtotal = structure_total + basement_cost + finishing_cost + mep_cost + parking_cost + fire_cost
    contingency = subtotal * CONTINGENCY_PCT
    total = subtotal + contingency

    # ── 8. AI NARRATIVE ──────────────────────────────────────────
    narrative = _generate_narrative(
        usage=usage, zone=zone, tier=tier,
        built_up_sqm=built_up_sqm, num_floors=num_floors,
        total=total, structure_total=structure_total,
        finishing_cost=finishing_cost, mep_cost=mep_cost,
        basement=basement, fire_noc_required=fire_noc_required,
        car_spaces=car_spaces,
    )

    return {
        "tier":             tier_key,
        "usage":            usage,
        "zone":             zone,
        "built_up_sqm":     round(built_up_sqm),
        "num_floors":       num_floors,
        # Summary cards
        "structure_cost":   round(structure_total),
        "basement_cost":    round(basement_cost),
        "finishing_cost":   round(finishing_cost),
        "mep_cost":         round(mep_cost),
        "parking_cost":     round(parking_cost),
        "fire_cost":        round(fire_cost),
        "contingency":      round(contingency),
        "total_cost":       round(total),
        "cost_per_sqm":     round(total / built_up_sqm) if built_up_sqm > 0 else 0,
        "cost_per_floor":   round(total / num_floors) if num_floors > 0 else 0,
        # Breakdowns
        "floor_breakdown":      floor_breakdown,
        "basement_breakdown":   basement_breakdown,
        "finishing_breakdown":  finishing_breakdown,
        "mep_breakdown":        mep_breakdown,
        "parking_breakdown":    parking_breakdown,
        # AI
        "narrative":        narrative,
        # Flags
        "structure_source": "KPWD Common SR 2022 — Vol I (BBMP +10% surcharge applied)",
        "estimate_flags": [
            "Finishing & MEP rates are market estimates (Bangalore 2024) — verify with contractor",
            "Structure & basement rates from KPWD Common SR 2022 (government reference rates)",
            f"BBMP area surcharge of 10% applied on all KPWD SR rates",
            *(["Fire NOC compliance cost included (sprinklers, signage, emergency lighting)"] if fire_noc_required else []),
        ],
    }


def _generate_narrative(usage, zone, tier, built_up_sqm, num_floors,
                         total, structure_total, finishing_cost,
                         mep_cost, basement, fire_noc_required, car_spaces) -> str:
    try:
        client = get_openai_client()
        structure_pct = round(structure_total / total * 100) if total else 0
        finishing_pct = round(finishing_cost  / total * 100) if total else 0
        mep_pct       = round(mep_cost        / total * 100) if total else 0

        prompt = f"""
You are a cost consultant for Bangalore construction projects. Write 3 concise sentences:
1. The dominant cost driver and percentage for this project
2. One key risk or cost spike specific to this building type/zone
3. One practical cost-saving tip for this tier

Project: {usage} building, {zone} zone, {num_floors} floors, {built_up_sqm:.0f} sqm built-up
Tier: {tier} finish
Total: ₹{total/10_000_000:.2f} Cr
Structure: {structure_pct}%, Finishing: {finishing_pct}%, MEP: {mep_pct}%
Basement: {basement}, Fire NOC: {fire_noc_required}, Car spaces: {car_spaces}

Be specific to Bangalore market. Cite BBMP/BDA where relevant. Under 80 words total.
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
            f"Structure dominates at {round(structure_total/total*100) if total else 0}% of total cost. "
            f"{'Fire NOC compliance adds ₹3.5L for sprinkler systems. ' if fire_noc_required else ''}"
            f"{'Basement waterproofing is a key risk in Bangalore clay soil. ' if basement else ''}"
            f"Rates based on KPWD SR 2022 + Bangalore market estimates."
        )
