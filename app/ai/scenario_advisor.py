"""
Scenario advisor using Claude Opus 4.7 with adaptive thinking.

Replaces the hardcoded "highest FAR without fire NOC" recommendation
with genuine multi-constraint reasoning about regulatory trade-offs.
System prompt is cached — repeated calls pay ~10% of first-call token cost.
"""

import json
import re
from app.ai.client import get_anthropic

_SYSTEM = """You are a senior architect and BDA regulatory advisor for Bangalore, India (BDA RMP 2031 + BBMP bylaws).

You are given pre-computed building scenarios for a plot. Your job is to recommend the ONE best scenario and explain why — considering FAR efficiency, fire NOC complexity, setback impacts, parking feasibility, approval timeline, and construction risk.

Key regulatory thresholds to reason about:
- Height > 15m → Fire NOC required (adds 4–6 weeks, sprinkler + fire lift mandatory)
- Height > 24m → Fire command centre + refuge area every 7 floors
- Progressive setbacks: each height tier reduces buildable footprint
- Lift mandatory above G+3

OUTPUT: Return ONLY valid JSON — no markdown fences, no text outside JSON.
{
  "recommended": "<exact scenario label — must match one of the provided labels>",
  "reasoning": "<2–3 sentences: why this scenario wins, what trade-offs make it optimal>",
  "scenario_notes": {
    "<label>": "<1 sentence: key trade-off or risk for this specific scenario>"
  }
}"""


def advise_scenarios(
    scenarios: list,
    zone: str,
    usage: str,
    plot_area_sqm: float,
    road_width: float,
) -> dict:
    """
    Call Claude Opus 4.7 and return recommendation JSON.
    Raises on API failure — caller must handle with try/except.
    """
    # Trim to only the fields Claude needs for reasoning
    slim = [
        {
            "label":             s["label"],
            "floors":            s["num_floors"],
            "floors_label":      s["floors_label"],
            "height_m":          s["building_height_m"],
            "far_efficiency_pct": s["far_efficiency_pct"],
            "fire_noc_required": s["fire_noc_required"],
            "fire_rules":        s["fire_rules"],
            "setbacks":          s["setbacks"],
            "parking_car":       s["parking_car"],
            "total_built_sqm":   s["total_built_sqm"],
            "warnings":          s["warnings"],
        }
        for s in scenarios
    ]

    labels = [s["label"] for s in scenarios]

    user_msg = f"""Plot context:
- Zone: {zone} | Usage: {usage}
- Plot area: {plot_area_sqm} sqm | Road width: {road_width}m

Computed scenarios (pre-verified, do NOT recalculate):
{json.dumps(slim, indent=2)}

Valid scenario labels (your "recommended" MUST be one of these exactly):
{labels}

Recommend the best scenario for this architect. Consider: FAR capture, fire NOC overhead, setback footprint loss, parking, approval complexity."""

    client = get_anthropic()

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=1024,
        thinking={"type": "adaptive"},
        system=[{
            "type": "text",
            "text": _SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        response = stream.get_final_message()

    raw = next(b.text for b in response.content if b.type == "text").strip()

    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",     "", raw, flags=re.MULTILINE)

    data = json.loads(raw)

    # Validate recommended label is one of the actual scenario labels
    if data.get("recommended") not in labels:
        data["recommended"] = labels[0]

    return data