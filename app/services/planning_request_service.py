from app.services.services import find_far_rule, get_openai_client
from shapely.geometry import Polygon
def calculate_plot_planning(request):
    zone = request.zone
    road_width = request.road_width
    building_height = request.building_height
    usage = request.usage
    locality = getattr(request, 'locality', 'Bangalore')
    corner_plot = getattr(request, 'corner_plot', False)
    basement = getattr(request, 'basement', False)
    # ---------------------------
    # Plot Area
    # ---------------------------

    if request.coordinates:

        coords = [(p.lng, p.lat) for p in request.coordinates]

        polygon = Polygon(coords)

        area_m2 = polygon.area

        plot_area = area_m2 * 10.7639   # convert to sq ft

    else:

        plot_length = request.plot_length
        plot_width = request.plot_width

        plot_area = plot_length * plot_width

    # ---------------------------
    # FAR Lookup
    # ---------------------------

    road_query = f"{int(road_width)}m"

    far = find_far_rule(road_query)

    if not far:
        far = 1.75   # fallback default

    try:
        far = float(far)
    except:
        far = 1.75   # fallback FAR

    # ---------------------------
    # Max Built Area
    # ---------------------------

    max_built_area = plot_area * far

    # ---------------------------
    # Setback Estimation (simplified)
    # ---------------------------

    if plot_area < 1500:
        front_setback = 3
        side_setback = 1
        rear_setback = 1
    else:
        front_setback = 4
        side_setback = 1.5
        rear_setback = 2

    setbacks = {
        "front": front_setback,
        "side": side_setback,
        "rear": rear_setback
    }

    # ---------------------------
    # Fire Safety Rules
    # ---------------------------

    fire_rules = []

    if building_height > 15:
        fire_rules.append("Fire lift required")
        fire_rules.append("Automatic sprinkler system required")
        fire_rules.append("Fire escape staircase required")

    if building_height > 24:
        fire_rules.append("Fire command center required")

    # ---------------------------
    # Parking Rules (simplified)
    # ---------------------------

    if usage.lower() == "residential":
        parking = "1 car parking space per dwelling unit"
    else:
        parking = "Parking requirement depends on building usage and floor area"

    # ---------------------------
    # AI Explanation
    # ---------------------------

    client = get_openai_client()

    prompt = f"""
EYou are an expert Bangalore building regulations assistant helping a licensed architect.

You have access to:
- BBMP Building Bylaws
- BDA RMP 2031 Zoning Regulations  
- NBC 2016 Fire Safety (Part IV)

A client has a plot with these details:
- Zone: {zone}
- Locality: {locality}
- Plot Area: {plot_area} sq ft ({round(plot_area / 10.764, 1)} sq m)
- Road Width: {road_width} m
- Building Height proposed: {building_height} m
- Usage: {usage}
- Corner Plot: {corner_plot}
- Basement proposed: {basement}

Computed values (use these, do not recalculate):
- FAR: {far}
- Maximum Built-up Area: {max_built_area} sq ft
- Front Setback: {front_setback} m
- Side Setback: {side_setback} m  
- Rear Setback: {rear_setback} m

Note: Floor-wise areas are estimates assuming uniform floor plates. 
Actual areas reduce above 11.5m due to increased setback requirements.

Your task — answer each section below using ONLY the bylaw documents:

1. SETBACK ANALYSIS
   - Confirm setbacks from bylaws for this plot size and height
   - If corner plot, state the relaxation available under BBMP Bylaws
   - Cite the specific bylaw section or table number

2. WHAT CAN BE BUILT
   - How many floors are feasible given {building_height}m height and FAR {far}?
   - Estimated floor-wise built-up area breakdown
   - Ground coverage percentage allowed for this zone

3. PARKING REQUIREMENTS
   - How many car and two-wheeler parking spaces are mandatory?
   - Based on usage: {usage} and built-up area: {max_built_area} sq ft
   - Cite bylaw table

4. FIRE SAFETY
   - Is fire NOC mandatory for {building_height}m height? State the threshold
   - List specific requirements: sprinklers, fire lift, refuge area, escape staircase
   - Cite NBC 2016 Part IV section

5. MANDATORY COMPLIANCES
   - Rainwater harvesting — required for this plot size?
   - Solar panels — required?
   - STP (Sewage Treatment Plant) — required?
   - State the threshold for each

6. APPROVAL PROCESS
   - Which authority approves this — BBMP or BDA?
   - Key documents the architect needs to submit
   - Any special NOCs required before plan sanction

7. WATCH OUT
   - Any restrictions or common mistakes for {zone} zone in {locality}
   - Any recent bylaw amendments that apply

Be specific, cite section numbers, and do not repeat the input data back.
Keep each section concise — 2 to 4 bullet points maximum.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are an urban planning regulatory assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    explanation = response.choices[0].message.content.strip()

    # ---------------------------
    # Final Result
    # ---------------------------

    return {
        "zone": zone,
        "plot_area": plot_area,
        "far": far,
        "max_built_area": max_built_area,
        "setbacks": setbacks,
        "fire_rules": fire_rules,
        "parking": parking,
        "ai_explanation": explanation
    }