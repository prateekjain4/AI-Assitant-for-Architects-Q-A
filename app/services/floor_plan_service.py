from app.ai.floor_plan import generate_zones

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

    data = generate_zones(
        buildable_w=buildable_w,
        buildable_d=buildable_d,
        building_height_m=building_height_m,
        num_floors=num_floors,
        floor_height_m=floor_height_m,
        usage=usage,
        zone=zone,
        ground_coverage_pct=ground_coverage_pct,
        road_width_m=road_width_m,
        corner_plot=corner_plot,
        basement=basement,
    )

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
