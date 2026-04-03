from app.services.services import find_far_rule, get_openai_client
from shapely.geometry import Polygon
from pyproj import Transformer
from shapely.ops import transform
import math
from app.services.parking_service import calculate_parking

# ─────────────────────────────────────────────────────────────────
# Area calculation
# ─────────────────────────────────────────────────────────────────
def calculate_area_sqft(coords_lng_lat: list) -> float:
    polygon_wgs84 = Polygon(coords_lng_lat)
    transformer = Transformer.from_crs(
        "EPSG:4326",
        "EPSG:32643",
        always_xy=True
    )
    polygon_utm = transform(transformer.transform, polygon_wgs84)
    return round(polygon_utm.area * 10.7639, 2)


# ─────────────────────────────────────────────────────────────────
# Bylaw context from FAISS — called INSIDE the function, not outside
# ─────────────────────────────────────────────────────────────────
def get_bylaw_context(question: str) -> str:
    """Pull relevant bylaw sections from FAISS for a specific question."""
    from app.services.services import answer_question_from_bylaws
    result = answer_question_from_bylaws(question)
    return result.get("answer", "")


# ─────────────────────────────────────────────────────────────────
# Ground coverage by zone + road width (BDA RMP 2031)
# ─────────────────────────────────────────────────────────────────
GROUND_COVERAGE = {
    "R":   {12: 70, 18: 65, 24: 60, 9999: 55},
    "RM":  {12: 70, 18: 65, 24: 60, 9999: 55},
    "C1":  {12: 65, 18: 60, 24: 55, 9999: 50},
    "C2":  {12: 60, 18: 55, 24: 55, 9999: 50},
    "C3":  {12: 60, 18: 55, 24: 55, 9999: 50},
    "IT":  {12: 50, 18: 50, 24: 45, 9999: 40},
    "PSP": {12: 40, 18: 40, 24: 40, 9999: 40},
}

def get_ground_coverage(zone: str, road_width: float) -> int:
    zone_map = GROUND_COVERAGE.get(zone.upper(), GROUND_COVERAGE["R"])
    for threshold in sorted(zone_map.keys()):
        if road_width <= threshold:
            return zone_map[threshold]
    return 55


# ─────────────────────────────────────────────────────────────────
# Fire requirements
# ─────────────────────────────────────────────────────────────────
def get_fire_requirements(building_height: float, max_built_area: float, usage: str) -> dict:
    fire = {
        "noc_required": False,
        "requirements": [],
        "tender_access": {},
        "refuge_area": {},
        "thresholds_note": ""
    }

    if building_height > 15:
        fire["noc_required"] = True
        fire["thresholds_note"] = "Fire NOC from KSFES mandatory above 15m"
    elif max_built_area > 500 and usage.lower() in ["commercial", "mixed"]:
        fire["noc_required"] = True
        fire["thresholds_note"] = "Fire NOC mandatory for commercial buildings above 500 sqm BUA"

    if building_height > 9:
        fire["requirements"] += [
            "Fire escape staircase — minimum 1.2m clear width",
            "Fire-rated doors on staircase landings",
            "Emergency lighting in corridors and staircases",
        ]
        fire["tender_access"] = {
            "required": True,
            "min_road_width_m": 4.5,
            "min_height_clearance_m": 4.5,
            "turning_radius_m": 9.0, 
            "dead_end_max_m": 45,
            "note": "Fire tender access road required on at least 3 sides above 15m (NBC 2016 Part IV Cl. 4.1)"
        }

    if building_height > 15:
        fire["requirements"] += [
            "Automatic sprinkler system throughout",
            "Fire lift — minimum 1.1m × 2.1m car, 630kg capacity",
            "Wet riser system",
            "Public address system",
            "Fire detection and alarm system",
            "Hose reel and extinguishers on every floor",
            "Terrace tank — minimum 25,000 litres",
        ]

    if building_height > 24:
        fire["requirements"] += [
            "Fire command centre at ground level",
            "Pressurisation of staircases",
            "Two separate fire escape staircases mandatory",
        ]
        fire["refuge_area"] = {
            "required": True,
            "frequency": "Every 7 floors",
            "min_area_sqm": 15,
            "note": "Refuge area NOT counted in FAR (NBC 2016 Part IV Section 4.11)"
        }

    return fire
# ─────────────────────────────────────────────────────────────────
# Feasibility & Compliance requirements
# ─────────────────────────────────────────────────────────────────
def generate_feasibility_summary(plot_area, max_built_area, far_floors):
    avg_unit_size = 900  # sqft assumption
    total_units = int(max_built_area / avg_unit_size)

    typology = "Apartment" if far_floors >= 4 else "Independent Floors"

    risk = "High" if far_floors >= 5 else "Medium" if far_floors >= 3 else "Low"

    return {
        "typology": typology,
        "floors": f"G+{far_floors-1}",
        "units": total_units,
        "risk": risk,
        "approval": f"{80 - (far_floors * 5)}%"
    }


def generate_design_options(far_floors, max_built_area):
    return [
        {
            "title": "Max FAR Apartment",
            "floors": f"G+{far_floors-1}",
            "units": int(max_built_area / 900),
            "parking": "Basement required",
            "risk": "High"
        },
        {
            "title": "Balanced Development",
            "floors": f"G+{max(2, far_floors-2)}",
            "units": int(max_built_area / 1200),
            "parking": "Stilt + surface",
            "risk": "Medium"
        },
        {
            "title": "Low Density",
            "floors": "G+1",
            "units": 1,
            "parking": "Surface",
            "risk": "Low"
        }
    ]


def generate_compliance_score(fire_data, parking, far_floors):
    score = 100
    issues = []

    if fire_data.get("noc_required"):
        score -= 15
        issues.append("Fire NOC required")

    cars_required = parking.get("required", {}).get("cars", 0)
    if cars_required > 50:
        score -= 10
        issues.append("High parking demand")

    if far_floors >= 5:
        score -= 10
        issues.append("High-rise complexity")

    if score >= 80:
        status = "Low Risk"
    elif score >= 60:
        status = "Moderate Risk"
    else:
        status = "High Risk"

    return {
        "score": score,
        "status": status,
        "issues": issues
    }

# ─────────────────────────────────────────────────────────────────
# Staircase & lift requirements
# ─────────────────────────────────────────────────────────────────
def get_staircase_requirements(building_height: float, max_built_area: float, far_floors: float) -> dict:
    num_floors = far_floors if far_floors > 0 else math.ceil(building_height / 3.2)

    if building_height <= 11.5:
        min_width = 1.0
        width_note = "Minimum 1.0m clear width (BBMP Bylaws)"
    else:
        min_width = 1.2
        width_note = "Minimum 1.2m clear width for buildings above 11.5m"

    if max_built_area > 2000:
        num_staircases = 2
        staircase_note = "2 staircases mandatory above 2000 sqm BUA"
    else:
        num_staircases = 1
        staircase_note = "1 staircase sufficient for this BUA"

    lift_mandatory = num_floors > 4
    lift_note = (
        f"Lift mandatory — {num_floors} floors (above G+4 threshold)"
        if lift_mandatory
        else f"Lift not mandatory — {num_floors} floors (G+{num_floors - 1})"
    )

    return {
        "min_staircase_width_m": min_width,
        "staircase_note":        width_note,
        "num_staircases":        num_staircases,
        "staircase_extra":       staircase_note,
        "lift_mandatory":        lift_mandatory,
        "lift_note":             lift_note,
        "num_floors":            num_floors,
    }


# ─────────────────────────────────────────────────────────────────
# Basement regulations
# ─────────────────────────────────────────────────────────────────
def get_basement_regulations(plot_area: float, basement_requested: bool) -> dict:
    if not basement_requested:
        return {"requested": False}

    plot_area_sqm = plot_area / 10.7639
    return {
        "requested": True,
        "max_basements": 2,
        "permitted_uses": [
            "Car parking (primary use)",
            "Two-wheeler parking",
            "Electrical room, pump room, generator",
            "AC plant room",
            "Storage (ancillary only)",
        ],
        "not_permitted": [
            "Habitable rooms or residential use",
            "Retail or commercial use",
            "Kitchens or restaurants",
        ],
        "setback_in_basement": "May extend up to plot boundary if used for parking/services only — subject to structural stability certificate",
        "ventilation": "Mechanical ventilation mandatory — minimum 6 air changes per hour (NBC 2016)",
        "max_depth_m": 3.6,
        "far_counted": False,
        "far_note": "Basement NOT counted in FAR if used for parking/services only",
        "fire_requirements": [
            "Sprinklers mandatory in basement regardless of height",
            "Minimum 2 means of escape from basement",
            "Smoke extraction system required",
            "Emergency lighting mandatory",
        ] if plot_area_sqm > 200 else [
            "Fire extinguishers mandatory",
            "Adequate ventilation required",
        ]
    }


# ─────────────────────────────────────────────────────────────────
# Balcony & projection rules
# ─────────────────────────────────────────────────────────────────
def get_projection_rules(road_width: float) -> dict:
    return {
        "balcony_max_projection_m": 1.5,
        "balcony_far_note": "Balconies up to 1.5m excluded from FAR if total ≤ 20% of floor area (BBMP Bylaws Section 15)",
        "chajja_max_projection_m": 0.75,
        "chajja_note": "Chajja/sun shade up to 0.75m — not counted in FAR",
        "projection_into_setback": "Projections may extend up to 50% into required setback but not beyond plot boundary",
        "road_overhang_note": f"No projection over road boundary — {road_width}m road setback must be maintained",
    }


# ─────────────────────────────────────────────────────────────────
# FAR exclusions list
# ─────────────────────────────────────────────────────────────────
FAR_EXCLUSIONS = [
    "Staircase and lift shafts (full height)",
    "Lift machine room (up to 16 sqm)",
    "Staircase headroom / mumty (up to 2.4m height)",
    "Basement parking floors — not counted in FAR",
    "Balconies up to 1.5m projection (within 20% of floor area)",
    "Utility ducts and service shafts",
    "Watchman cabin up to 9 sqm at entrance",
    "Refuge area (not counted in FAR per NBC 2016 Part IV Section 4.11)",
    "Ramps for disabled access",
]


# ─────────────────────────────────────────────────────────────────
# Main planning function
# ─────────────────────────────────────────────────────────────────
def calculate_plot_planning(request):
    zone            = request.zone
    road_width      = request.road_width
    building_height = request.building_height
    usage           = request.usage
    locality        = getattr(request, 'locality', 'Bangalore')
    corner_plot     = getattr(request, 'corner_plot', False)
    basement        = getattr(request, 'basement', False)

    # ── Plot Area ─────────────────────────────────────────────────
    if request.coordinates:
        coords    = [(p.lng, p.lat) for p in request.coordinates]
        plot_area = calculate_area_sqft(coords)
    else:
        plot_length = request.plot_length or 0
        plot_width  = request.plot_width  or 0
        plot_area   = round((plot_length * plot_width) * 10.7639, 2)

    plot_area_sqm = round(plot_area / 10.7639, 2)

    # ── FAR ───────────────────────────────────────────────────────
    far = find_far_rule(f"{road_width}m") or 1.75

    # ── Ground Coverage ───────────────────────────────────────────
    ground_coverage_pct = get_ground_coverage(zone, road_width)
    footprint_sqm       = plot_area_sqm * (ground_coverage_pct / 100)
    # ── Max Built Area ────────────────────────────────────────────
    max_built_sqm  = round(plot_area_sqm * far, 2)
    max_built_area = round(max_built_sqm * 10.7639, 2)   # sqft for display/return
    # How many floors does FAR actually allow?
    far_floors = math.ceil(max_built_sqm / max(footprint_sqm, 1))
    far_floors = max(1, min(far_floors, 15))

    # ── Setbacks ──────────────────────────────────────────────────

    if plot_area < 1500:
        front_setback = 3.0
        side_setback  = 1.0
        rear_setback  = 1.0
    else:
        front_setback = 4.0
        side_setback  = 1.5
        rear_setback  = 2.0

    if corner_plot:
        side_setback = max(1.0, side_setback - 1.0)

    setbacks = {
        "front": front_setback,
        "side":  side_setback,
        "rear":  rear_setback,
        "corner_relaxation": "Side setback reduced by 1m on secondary road side" if corner_plot else None
    }

    # ── Computed sections ─────────────────────────────────────────
    far_building_height = far_floors * 3.2  # actual buildable height from FAR
    fire_data      = get_fire_requirements(far_building_height, max_built_area, usage)
    staircase_data = get_staircase_requirements(far_building_height, max_built_area, far_floors)
    basement_data    = get_basement_regulations(plot_area, basement)
    projection_rules = get_projection_rules(road_width)

    fire_rules = fire_data["requirements"]

    # ── Parking ───────────────────────────────────────────────────
    parking_data = calculate_parking(
        usage=usage,
        built_up_sqft=max_built_area,
        num_units=getattr(request, "number_of_units", 1),
        plot_length_m=request.plot_length or 0,
        plot_width_m=request.plot_width or 0,
        basement=basement,
        stilt=False
    )

    parking = parking_data  # return full structured data

    # ── Bylaw context from FAISS — called HERE inside function ────
    setback_context   = get_bylaw_context(
        f"setback requirements plot area {plot_area_sqm} sqm height {building_height}m"
    )
    staircase_context = get_bylaw_context(
        f"staircase width lift requirements building height {building_height}m floors"
    )
    balcony_context   = get_bylaw_context(
        "balcony projection FAR exclusion cantilever chajja rules"
    )
    fire_context      = get_bylaw_context(
        f"fire safety NOC requirements building height {building_height}m sprinkler"
    )
    basement_context  = get_bylaw_context(
        "basement regulations permitted uses ventilation parking"
    ) if basement else ""

    summary = generate_feasibility_summary(plot_area, max_built_area, far_floors)
    design_options = generate_design_options(far_floors, max_built_area)
    compliance = generate_compliance_score(fire_data, parking, far_floors)

    # ── Prompt ────────────────────────────────────────────────────
    client = get_openai_client()

    prompt = f"""
You are an expert Bangalore building regulations assistant helping a licensed architect.

VERIFIED BYLAW CONTEXT (retrieved directly from official PDFs — use ONLY this):
─────────────────────────────────────────────────────────────────────────────
SETBACKS (BBMP Bylaws):
{setback_context}

STAIRCASE & LIFT (BBMP Bylaws):
{staircase_context}

BALCONY & PROJECTIONS (BBMP Bylaws):
{balcony_context}

FIRE SAFETY (NBC 2016 Part IV):
{fire_context}

{f"BASEMENT (BBMP Bylaws):{chr(10)}{basement_context}" if basement else ""}
─────────────────────────────────────────────────────────────────────────────

Plot inputs:
- Zone: {zone} | Locality: {locality}
- Plot Area: {plot_area:,.0f} sq ft ({plot_area_sqm} sq m)
- Road Width: {road_width}m | Effective Height (based on FAR): {far_building_height:.1f}m
- Usage: {usage} | Corner Plot: {corner_plot} | Basement: {basement}

Pre-computed facts — treat as EXACT, do NOT recalculate:
- FAR: {far} | Ground Coverage: {ground_coverage_pct}%
- Max Built-up Area: {max_built_area:,.0f} sq ft
- Setbacks: Front {front_setback}m | Side {side_setback}m | Rear {rear_setback}m
- Fire NOC required: {fire_data['noc_required']}
- Lift mandatory: {staircase_data['lift_mandatory']} ({staircase_data['lift_note']})
- Staircases required: {staircase_data['num_staircases']}

Using ONLY the bylaw context above, answer each section below.
Cite the exact section number. If context doesn't cover a point, write "verify with BBMP".
Keep each section to 3–5 bullet points. Do NOT repeat input data.

1. SETBACK ANALYSIS
   - Confirm setbacks for this plot size and height from bylaws
   - State the 11.5m threshold rule where setbacks increase to 5m all sides
   - Corner plot relaxation if applicable

2. FAR & WHAT COUNTS
   - What is included vs excluded from FAR (staircase, basement, balcony, refuge)
   - How many floors feasible at {far_building_height:.1f}m with FAR {far}
   - Ground coverage: {ground_coverage_pct}% for {zone} zone on {road_width}m road

3. STAIRCASE & LIFT
   - Min width: {staircase_data['min_staircase_width_m']}m | Staircases: {staircase_data['num_staircases']}
   - Lift mandatory: {staircase_data['lift_mandatory']}
   - Cite BBMP section

4. BALCONY, PROJECTIONS & CANTILEVERS
   - Max balcony projection: 1.5m | Chajja: 0.75m
   - FAR counting rule for balconies (20% rule)
   - Projection into setback allowance

5. {"BASEMENT REGULATIONS" if basement else "BASEMENT (not requested — skip this section)"}
   {"- Permitted uses, FAR counting, ventilation, fire requirements" if basement else ""}

6. PARKING
   - Parking already computed separately — DO NOT calculate again
   - Explain only general BBMP Table 23 rule

7. FIRE SAFETY
   - NOC required: {fire_data['noc_required']} | Threshold: 15m height
   - Key requirements for {building_height}m building
   - Fire tender access: 4.5m wide road, 9m turning radius
   - Refuge area required: {bool(fire_data.get('refuge_area', {}).get('required', False))}
   - Cite NBC 2016 Part IV sections

8. MANDATORY COMPLIANCES
   - Rainwater harvesting threshold for this plot size
   - Solar panels — required?
   - STP — required for this height/usage?
   - Accessibility ramp — required?

9. APPROVAL PROCESS
   - BBMP or BDA jurisdiction for {locality}?
   - Key documents to submit
   - Special NOCs needed before plan sanction

10. WATCH OUT
    - Restrictions specific to {zone} zone in {locality}
    - Common mistakes for this height and usage combination
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You are a precise Bangalore urban planning assistant. Provide confident answers using given context. Use 'subject to local authority approval' only if absolutely necessary."
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    try:
        explanation = response.choices[0].message.content.strip()
    except:
        explanation = "Regulatory analysis could not be generated at this time."

    # ── Return ────────────────────────────────────────────────────
    return {
        "zone":               zone,
        "plot_area":          plot_area,
        "plot_area_sqm":      plot_area_sqm,
        "far":                far,
        "locality":           locality,
        "ward":            getattr(request, 'ward', ''),
        "max_built_area":     max_built_area,
        "feasibility":        summary,
        "design_options":     design_options,
        "compliance":         compliance,
        "road_width":         road_width,
        "ground_coverage_pct": ground_coverage_pct,
        "setbacks":           setbacks,
        "fire_rules":         fire_rules,
        "fire_data":          fire_data,
        "staircase":          staircase_data,
        "basement":           basement_data,
        "projections":        projection_rules,
        "far_exclusions":     FAR_EXCLUSIONS,
        "parking":            parking,
        "ai_explanation":     explanation
    }