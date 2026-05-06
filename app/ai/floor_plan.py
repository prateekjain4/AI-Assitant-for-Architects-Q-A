"""
Floor plan generation using Claude Opus 4.7 with adaptive thinking.

Why Claude here instead of GPT-4o-mini:
- Adaptive thinking lets Claude reason about spatial constraints (no gaps, no
  overlaps, full coverage) before committing to coordinates.
- Better adherence to multi-constraint prompts (BBMP bylaw rules, zone adjacency).
- System prompt is cached — repeated calls pay ~10% of first-call token cost.
"""

import json
import re
from app.ai.client import get_anthropic

# Stable system prompt — marked for prompt caching.
# Everything variable (dimensions, zone, usage) goes in the user message.
_SYSTEM = """You are an expert architect designing regulatory-compliant floor plans for Bangalore, India (BDA RMP 2031 + BBMP bylaws).

COORDINATE SYSTEM:
- Origin (0,0) is the BOTTOM-LEFT corner of the buildable footprint
- x increases RIGHT (east), y increases UP (north)
- y=0 = FRONT facing road (south) — lobby/entrance must be here
- y=buildable_d = REAR (north) — services/utilities go here

TILING RULES — verify before outputting:
1. Every zone: x≥0, y≥0, x+w≤buildable_w, y+h≤buildable_d
2. No two zones overlap (check every pair)
3. Zones must cover the ENTIRE footprint with NO gaps > 0.2m
4. Minimum zone size: 3m × 3m | Use 5–10 zones

BYLAW CONSTRAINTS:
- Lobby/entrance at y=0 (BBMP access requirement)
- Staircase/core within 25m travel from any point (BBMP Sec 20.6 fire rule)
- Services/utilities at y close to buildable_d (rear, north)
- Staircase min width 1.5m; lift mandatory if > 4 floors

OUTPUT: Return ONLY valid JSON — no markdown fences, no text outside JSON.
{
  "floor": 0,
  "label": "Ground Floor — <Usage>",
  "buildable_w": <number>,
  "buildable_d": <number>,
  "zones": [
    {"label": "...", "x": 0.0, "y": 0.0, "w": 10.0, "h": 8.0,
     "type": "circulation|commercial|residential|core|services|parking|open"}
  ],
  "annotations": ["Decision with bylaw reference e.g. BBMP Sec X.Y"]
}"""


def generate_zones(
    buildable_w: float,
    buildable_d: float,
    building_height_m: float,
    num_floors: int,
    floor_height_m: float,
    usage: str,
    zone: str,
    ground_coverage_pct: float,
    road_width_m: float,
    corner_plot: bool,
    basement: bool,
) -> dict:
    """
    Call Claude Opus 4.7 and return raw parsed JSON (zones not yet enriched).
    Raises json.JSONDecodeError or anthropic.APIError on failure.
    """
    buildable_area = round(buildable_w * buildable_d, 1)

    user_msg = f"""Design a ground floor plan for this plot:

- Zone: {zone} | Usage: {usage}
- Buildable footprint: {buildable_w}m wide × {buildable_d}m deep ({buildable_area} sqm)
- Building: {building_height_m}m tall | {num_floors} floors | {floor_height_m}m floor height
- Road: {road_width_m}m wide on SOUTH/FRONT (y=0)
- Corner plot: {corner_plot} | Basement: {basement}
- Ground coverage limit: {ground_coverage_pct}%

Fill the full {buildable_w}×{buildable_d}m footprint. Lobby at y=0, services at y≈{buildable_d}.
Think through the spatial layout carefully — verify all zones tile without gaps or overlaps."""

    client = get_anthropic()

    with client.messages.stream(
        model="claude-opus-4-7",
        max_tokens=8000,
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

    # Strip markdown fences if model includes them
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$",     "", raw, flags=re.MULTILINE)

    return json.loads(raw)