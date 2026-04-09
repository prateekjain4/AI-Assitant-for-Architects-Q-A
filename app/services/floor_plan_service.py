import json
import re
from app.services.services import get_openai_client

ZONE_COLORS = {
    "circulation": "#bfdbfe",
    "commercial":  "#dcfce7",
    "residential": "#fef9c3",
    "core":        "#fee2e2",
    "services":    "#f3e8ff",
    "parking":     "#e0f2fe",
    "open":        "#f0fdf4",
}

BYLAW_REFS = {
    "circulation": "BBMP Sec 20.6 — Min corridor 1.2m; lobby width ≥ 3m",
    "core":        "BBMP Sec 20.6-20.7 — Staircase min 1.5m; lift if > 4 floors",
    "parking":     "BBMP Table 23 — Parking norms per built-up sqm",
    "services":    "NBC 2016 Part IV — Service zones away from main exit routes",
    "commercial":  "BDA RMP 2031 — Commercial FAR applicable",
    "residential": "BDA RMP 2031 — Residential FAR applicable",
    "open":        "BBMP — Open to sky area / light court",
}

COMPLIANCE = {
    "circulation": ["Width ≥ 3m", "Direct road access", "Fire exit within 25m"],
    "core":        ["Staircase ≥ 1.5m wide", "Central position for max travel ≤ 25m"],
    "parking":     ["Min 2.5m × 5m per car bay", "Drive aisle ≥ 6m"],
    "services":    ["Separate from main entry", "Ventilation required"],
    "commercial":  ["Counted in FAR", "Ground floor frontage preferred"],
    "residential": ["Natural light & ventilation required", "Min room 9.5 sqm"],
    "open":        ["Not counted in FAR", "Min dimension ≥ 3m"],
}


def generate_floor_plan(
    plot_length_m: float,
    plot_width_m: float,
    setback_front: float,
    setback_side: float,
    setback_rear: float,
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

    buildable_w = round(plot_length_m - 2 * setback_side, 2)
    buildable_d = round(plot_width_m - setback_front - setback_rear, 2)
    buildable_area = round(buildable_w * buildable_d, 1)

    prompt = f"""
You are an expert architect designing a regulatory-compliant floor plan for Bangalore, India.

PLOT & REGULATIONS:
- Zone: {zone}
- Usage: {usage}
- Buildable footprint: {buildable_w}m wide × {buildable_d}m deep  ({buildable_area} sq m)
- Building height: {building_height_m}m  |  {num_floors} floors  |  Floor height: {floor_height_m}m
- Road: {road_width_m}m wide on the SOUTH/FRONT side
- Corner plot: {corner_plot}  |  Basement: {basement}
- Ground coverage: {ground_coverage_pct}%

COORDINATE SYSTEM (critical — read carefully):
- Origin (0,0) is at the BOTTOM-LEFT corner of the buildable footprint
- x increases to the RIGHT (east), max = {buildable_w}
- y increases UPWARD (north), max = {buildable_d}
- y=0 means FRONT (facing road, south) — put lobby/entrance here
- y={buildable_d} means REAR (north) — put services/utilities here

BYLAW CONSTRAINTS:
1. Lobby/entrance MUST be at y=0 (front, road side) — BBMP access requirement
2. Staircase/core within 25m of any point (BBMP fire rule Sec 20.6)
3. Service/utility at y close to {buildable_d} (rear, north side)
4. ALL zones together must cover the ENTIRE {buildable_w}m × {buildable_d}m footprint
5. No zone: x<0, y<0, x+w>{buildable_w}, y+h>{buildable_d}
6. Zones must tile with NO overlaps and NO gaps > 0.5m
7. Minimum zone size: 3m × 3m

TASK: Design ONE complete ground floor layout filling the full {buildable_w}×{buildable_d}m footprint.
Return ONLY a JSON object (no markdown, no explanation outside JSON):

{{
  "floor": 0,
  "label": "Ground Floor — {usage.title()}",
  "buildable_w": {buildable_w},
  "buildable_d": {buildable_d},
  "zones": [
    {{
      "label": "Zone Name",
      "x": 0.0,
      "y": 0.0,
      "w": 10.0,
      "h": 8.0,
      "type": "circulation|commercial|residential|core|services|parking|open"
    }}
  ],
  "annotations": [
    "Decision with bylaw reference (e.g. BBMP Sec X.Y)"
  ]
}}

Use 5–10 zones. Cover the full footprint. Lobby at y=0, services at y≈{buildable_d}.
"""

    client = get_openai_client()
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise architect. Return only valid JSON, no markdown fences."},
            {"role": "user",   "content": prompt}
        ],
        temperature=0.3,
        max_tokens=900,
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown fences if model adds them despite instruction
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*',     '', raw)
    raw = re.sub(r'\s*```$',     '', raw)

    data = json.loads(raw)

    # Validate & clamp zones to buildable area
    bw, bd = buildable_w, buildable_d
    validated_zones = []
    for z in data.get("zones", []):
        x = max(0.0, float(z.get("x", 0)))
        y = max(0.0, float(z.get("y", 0)))
        w = float(z.get("w", 5))
        h = float(z.get("h", 5))
        # Clamp so zone stays inside buildable footprint
        w = min(w, bw - x)
        h = min(h, bd - y)
        if w < 1 or h < 1:
            continue
        ztype = z.get("type", "commercial")
        validated_zones.append({
            "label":      z.get("label", "Zone"),
            "x":          round(x, 2),
            "y":          round(y, 2),
            "w":          round(w, 2),
            "h":          round(h, 2),
            "type":       ztype,
            "color":      ZONE_COLORS.get(ztype, "#e2e8f0"),
            "bylawRef":   BYLAW_REFS.get(ztype, ""),
            "compliance": COMPLIANCE.get(ztype, []),
        })

    return {
        "floor":        data.get("floor", 0),
        "label":        data.get("label", f"Ground Floor — {usage.title()}"),
        "buildable_w":  bw,
        "buildable_d":  bd,
        "zones":        validated_zones,
        "annotations":  data.get("annotations", []),
    }
