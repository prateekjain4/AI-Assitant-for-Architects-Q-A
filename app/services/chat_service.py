from app.services.services import get_openai_client, answer_question_from_bylaws


def _fmt(val, unit="", fallback="—"):
    """Format a value; return fallback if None/empty."""
    if val is None or val == "":
        return fallback
    return f"{val}{(' ' + unit) if unit else ''}"


def _build_planning_context(planning_data: dict) -> str:
    """
    Convert the full /planning response into a readable context block.
    Field names verified against planning_request_service.py return dict.
    """
    if not planning_data:
        return ""

    zone         = _fmt(planning_data.get("zone"))
    locality     = _fmt(planning_data.get("locality"))
    road_width   = _fmt(planning_data.get("road_width"), "m")
    plot_sqft    = _fmt(planning_data.get("plot_area"), "sqft")
    plot_sqm     = _fmt(planning_data.get("plot_area_sqm"), "sqm")
    far          = _fmt(planning_data.get("far"))
    far_base     = _fmt(planning_data.get("far_base"))
    far_tdr      = _fmt(planning_data.get("far_tdr"))
    planning_zone= _fmt(planning_data.get("planning_zone"))
    max_built    = _fmt(planning_data.get("max_built_area"), "sqft")
    gc_pct       = _fmt(planning_data.get("ground_coverage_pct"), "%")
    min_fl_far   = _fmt(planning_data.get("min_floors_for_max_far"))

    # setbacks — dict with keys: front, side, rear, corner_relaxation
    sb          = planning_data.get("setbacks") or {}
    sb_front    = _fmt(sb.get("front"), "m")
    sb_side     = _fmt(sb.get("side"), "m")
    sb_rear     = _fmt(sb.get("rear"), "m")
    sb_corner   = sb.get("corner_relaxation") or "N/A"

    # fire_data — keys: noc_required (bool), requirements (list)
    fire        = planning_data.get("fire_data") or {}
    fire_noc    = "Required" if fire.get("noc_required") else "Not required"
    fire_reqs   = "; ".join(fire.get("requirements") or []) or "None"

    # staircase — keys: min_staircase_width_m, lift_mandatory, num_staircases,
    #                    staircase_note, lift_note, num_floors
    stair       = planning_data.get("staircase") or {}
    stair_width = _fmt(stair.get("min_staircase_width_m"), "m")
    stair_count = _fmt(stair.get("num_staircases"))
    num_floors  = _fmt(stair.get("num_floors"))
    lift        = "Mandatory" if stair.get("lift_mandatory") else "Not mandatory"
    lift_note   = stair.get("lift_note", "")

    # compliance — keys: score (int), status (str), issues (list)
    comp        = planning_data.get("compliance") or {}
    comp_score  = _fmt(comp.get("score"))
    comp_status = _fmt(comp.get("status"))
    comp_issues = "; ".join(comp.get("issues") or []) or "None"

    # parking — keys: required.cars, required.bikes
    parking     = planning_data.get("parking") or {}
    park_req    = parking.get("required") or {}
    park_cars   = _fmt(park_req.get("cars"))
    park_2w     = _fmt(park_req.get("bikes"))

    return f"""
── PLOT & ZONING (BDA RMP 2031) ──────────────────────
Zone            : {zone}  |  Locality: {locality}  |  Planning zone: {planning_zone}
Road width      : {road_width}
Plot area       : {plot_sqft}  ({plot_sqm})
FAR allowed     : {far}  (base {far_base} + TDR {far_tdr})
Max built-up    : {max_built}
Ground coverage : {gc_pct}
Floors feasible : {num_floors} (by building height)
Min floors for max FAR : {min_fl_far} (minimum floors to use full FAR budget)

── SETBACKS (BDA RMP 2031 Table 2 — progressive) ────
Front  : {sb_front}
Side   : {sb_side}
Rear   : {sb_rear}
Corner : {sb_corner}
Note   : Setbacks are height-dependent. Above 15 m they increase progressively:
         6 m at 15–18 m, 7 m at 18–21 m, 8 m at 21–24 m, up to 16 m above 60 m.
         Below 15 m setbacks are plot-area based (1–4 m per BDA Table 2).

── FIRE & SAFETY (NBC 2016 / BDA RMP 2031) ──────────
Fire NOC        : {fire_noc}
Requirements    : {fire_reqs}

── STAIRCASE & LIFT ──────────────────────────────────
Min stair width : {stair_width}  |  Number of staircases: {stair_count}
Lift            : {lift}  ({lift_note})
Note            : Lift mandatory above G+3 per BDA RMP 2031.
                  Dual staircase required above 200 sqm BUA per NBC 2016.

── COMPLIANCE RISK ───────────────────────────────────
Score  : {comp_score} / 100  |  Status: {comp_status}
Issues : {comp_issues}

── PARKING (BBMP Table 23 approx.) ──────────────────
Car spaces      : {park_cars}
Two-wheelers    : {park_2w}
"""


def _build_scenario_context(scenario_data: dict) -> str:
    """
    Convert the /scenarios response into a readable context block.
    Field names verified against scenario_service.py return dict.
    """
    if not scenario_data:
        return ""

    far           = _fmt(scenario_data.get("far"))
    far_base      = _fmt(scenario_data.get("far_base"))
    far_tdr       = _fmt(scenario_data.get("far_tdr"))
    max_built     = _fmt(scenario_data.get("max_built_sqft"), "sqft")
    zone          = _fmt(scenario_data.get("zone"))
    road          = _fmt(scenario_data.get("road_width"), "m")
    planning_zone = _fmt(scenario_data.get("planning_zone"))
    rec           = _fmt(scenario_data.get("recommended"))
    scenarios     = scenario_data.get("scenarios") or []

    lines = [
        "── BUILDING SCENARIOS (BDA RMP 2031 BYLAW THRESHOLDS) ─",
        f"Zone: {zone}  |  Road: {road}  |  Planning zone: {planning_zone}",
        f"FAR: {far}  (base {far_base} + TDR {far_tdr})  |  Max built-up: {max_built}",
        f"Recommended scenario: {rec}",
        "Note: Scenarios are anchored to BDA regulatory height thresholds.",
        "      Progressive setbacks above 15 m increase with every height tier.",
        "",
    ]

    for s in scenarios:
        label       = s.get("label", "")
        fl_label    = s.get("floors_label", "")
        height      = _fmt(s.get("building_height_m"), "m")
        built_sqft  = _fmt(s.get("total_built_sqft"), "sqft")
        built_sqm   = _fmt(s.get("total_built_sqm"), "sqm")
        far_eff     = _fmt(s.get("far_efficiency_pct"), "%")
        footprint   = _fmt(s.get("footprint_sqft"), "sqft")
        avg_fl_area = _fmt(s.get("avg_floor_area_sqft"), "sqft/floor")
        noc         = "Yes" if s.get("fire_noc_required") else "No"
        lift        = "Mandatory" if s.get("lift_mandatory") else "Optional"
        cars        = _fmt(s.get("parking_car"))
        tw          = _fmt(s.get("parking_2w"))

        sb     = s.get("setbacks") or {}
        sb_str = (
            f"Front {_fmt(sb.get('front'), 'm')} · "
            f"Side {_fmt(sb.get('side'), 'm')} · "
            f"Rear {_fmt(sb.get('rear'), 'm')}"
        )
        if sb.get("high_rise_rule"):
            sb_str += " (progressive setbacks apply — BDA RMP 2031 Table 2)"

        lines += [
            f"  [{label}]  {fl_label}  ·  Height: {height}  |  FAR used: {far_eff}",
            f"    Built-up    : {built_sqft} ({built_sqm})",
            f"    Avg floor   : {avg_fl_area}  |  Ground footprint: {footprint}",
            f"    Setbacks    : {sb_str}",
            f"    Fire NOC    : {noc}  |  Lift: {lift}",
            f"    Parking     : {cars} cars  ·  {tw} two-wheelers",
            "",
        ]

    return "\n".join(lines)


def _build_cost_context(cost_estimate: dict) -> str:
    """
    Convert the /estimate-cost response into a readable context block.
    Field names verified against cost_estimator_service.py return dict.
    All monetary values are in INR (rupees).
    """
    if not cost_estimate:
        return ""

    total       = cost_estimate.get("total_cost", 0)
    total_lakhs = round(total / 100_000, 1) if total else 0
    per_sqm     = _fmt(cost_estimate.get("cost_per_sqm"), "INR/sqm")
    tier        = _fmt(cost_estimate.get("tier"))
    floors      = _fmt(cost_estimate.get("num_floors"))
    built_sqm   = _fmt(cost_estimate.get("built_up_sqm"), "sqm")

    def lakhs(val):
        return f"₹{round((val or 0) / 100_000, 1)} L" if val else "—"

    lines = [
        "── COST ESTIMATE (KPWD SR 2022 rates) ───────────────",
        f"Total cost       : ₹{total_lakhs} lakhs  (tier: {tier})",
        f"Cost per sqm     : {per_sqm}",
        f"Built-up area    : {built_sqm}  |  Floors: {floors}",
        "Breakdown:",
        f"  Structure      : {lakhs(cost_estimate.get('structure_cost'))}",
        f"  Finishing      : {lakhs(cost_estimate.get('finishing_cost'))}",
        f"  MEP (services) : {lakhs(cost_estimate.get('mep_cost'))}",
        f"  Basement       : {lakhs(cost_estimate.get('basement_cost'))}",
        f"  Parking        : {lakhs(cost_estimate.get('parking_cost'))}",
        f"  Site dev       : {lakhs(cost_estimate.get('site_dev_cost'))}",
        f"  Fire safety    : {lakhs(cost_estimate.get('fire_cost'))}",
        f"  Contingency    : {lakhs(cost_estimate.get('contingency'))}",
    ]

    return "\n".join(lines)


def chat_with_context(
    question:      str,
    planning_data: dict = None,
    scenario_data: dict = None,
    cost_estimate: dict = None,
) -> str:

    client = get_openai_client()

    # ── STEP 1: Retrieve bylaw knowledge from FAISS ───────────────
    bylaw_context = answer_question_from_bylaws(question).get("answer", "")

    # ── STEP 2: Build structured project context ──────────────────
    planning_block = _build_planning_context(planning_data)
    scenario_block = _build_scenario_context(scenario_data)
    cost_block     = _build_cost_context(cost_estimate)

    has_project = any([planning_block, scenario_block, cost_block])

    project_section = ""
    if has_project:
        project_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROJECT DATA  (calculated output for this specific plot)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{planning_block}
{scenario_block}
{cost_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULE: The project data above is the authoritative output for this
plot. Always prefer and quote exact numbers from it. If a user
mentions a scenario by name (e.g. "80% FAR"), use the values from
that specific scenario row.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

    # ── STEP 3: Compose final prompt ──────────────────────────────
    prompt = f"""You are an expert Bangalore building regulations assistant helping an architect.

BYLAWS REFERENCE KNOWLEDGE:
{bylaw_context}
{project_section}
USER QUESTION:
{question}

Answer clearly and practically. When project data is available, refer to the
exact numbers (plot area, FAR, setbacks, scenario heights, costs) rather than
giving generic guidance.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise Bangalore building regulatory assistant working with BDA RMP 2031 rules. "
                    "Always cite specific numbers from the project data when available. "
                    "Key rules to remember: setbacks are progressive above 15 m (BDA Table 2), not a flat 5 m at 11.5 m. "
                    "Lift is mandatory above G+3 per BDA RMP 2031. "
                    "FAR governs total built-up area, not floor count. "
                    "'Floors feasible' is derived from building height ÷ floor height. "
                    "'Min floors for max FAR' is the minimum floors needed to use the full FAR budget."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    return response.choices[0].message.content.strip()