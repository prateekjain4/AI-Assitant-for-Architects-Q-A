from app.services import find_far_rule, get_openai_client
from shapely.geometry import Polygon
def calculate_plot_planning(request):
    zone = request.zone
    road_width = request.road_width
    building_height = request.building_height
    usage = request.usage

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
Explain the building planning regulations for the following plot:

Zone: {zone}
Plot Area: {plot_area} sq ft
Road Width: {road_width} m
FAR: {far}
Maximum Built Area: {max_built_area} sq ft
Building Height: {building_height} m

Setbacks:
Front: {front_setback} m
Side: {side_setback} m
Rear: {rear_setback} m

Fire Rules: {fire_rules}

Explain clearly what the architect can build and what regulations apply.
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