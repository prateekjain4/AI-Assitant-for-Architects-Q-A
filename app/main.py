from fastapi import FastAPI, Response, Request
from fastapi.staticfiles import StaticFiles
import json
import os
from app.services.services import run_full_pipeline, JSON_FILE, change_report
from pydantic import BaseModel
from app.services.services import answer_question_from_bylaws
from fastapi.middleware.cors import CORSMiddleware
from app.model.planning_request import Coordinate, PlanningRequest
from app.services.planning_request_service import calculate_plot_planning
from app.services.chat_service import chat_with_context
from app.services.zone_service import detect_zone_from_coordinate
from app.services.report_service import generate_planning_report
from app.model.scenario_request import ScenarioRequest
from app.services.scenario_service import calculate_scenarios
from app.model.parking_request import ParkingRequest
from app.services.parking_service import calculate_parking
from app.services.floor_plan_service import generate_floor_plan
from app.services.cost_estimator_service import estimate_cost
from app.services.ranchi_planning_service import calculate_ranchi_planning
from app.services.ranchi_scenario_service import calculate_ranchi_scenarios
from app.services.hyderabad_planning_service import calculate_hyderabad_planning
from app.services.hyderabad_scenario_service import calculate_hyderabad_scenarios
# from app.services.anekal_planning_service import calculate_anekal_planning
# from app.services.anekal_scenario_service import calculate_anekal_scenarios
# from app.services.hoskote_planning_service import calculate_hoskote_planning, calculate_hoskote_scenarios
# from app.services.nelamangala_planning_service import calculate_nelamangala_planning, calculate_nelamangala_scenarios
# from app.services.kanakapura_planning_service import calculate_kanakapura_planning, calculate_kanakapura_scenarios
# from app.services.ramanagara_planning_service import calculate_ramanagara_planning, calculate_ramanagara_scenarios
# from app.services.biaapa_planning_service import calculate_biaapa_planning, calculate_biaapa_scenarios
from app.routers.auth import router as auth_router
from app.routers.projects import router as projects_router
from app.db.database import engine
from app.model import db_models
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Create DB tables on startup (SQLite file: bylaw_app.db)
db_models.Base.metadata.create_all(bind=engine)

# ── Rate limiter (keyed by client IP) ────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="AI Bylaw Monitor API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Serve regulation PDFs as static files at /docs
_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pdfs")
app.mount("/docs", StaticFiles(directory=_DOCS_DIR, html=False), name="docs")

# Routers
app.include_router(auth_router)
app.include_router(projects_router)

class QuestionRequest(BaseModel):
    question: str
    city: str = "bangalore"

class ChatRequest(BaseModel):
    question: str
    city: str = "bangalore"
    planning_data: dict = None
    scenario_data: dict = None
    cost_estimate: dict = None

_ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:4200"
).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
@app.get("/")
def home():
    return {"message": "AI Bylaw Monitor Running"}


@app.post("/check-updates")
def check_updates():
    result = run_full_pipeline()
    return result


@app.get("/sections")
def get_sections():
    if not os.path.exists(JSON_FILE):
        return {"error": "No sections found. Run /check-updates first."}

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        sections = json.load(f)

    return sections


@app.get("/changes")
def get_changes():
    return change_report

@app.post("/ask")
@limiter.limit("30/minute")
def ask_question(request: Request, body: QuestionRequest):
    return answer_question_from_bylaws(body.question, city=body.city)

@app.post("/planning")
@limiter.limit("10/minute")
def planning_tool(request: Request, body: PlanningRequest):
    return calculate_plot_planning(body)

@app.post("/chat")
@limiter.limit("20/minute")
def chat_endpoint(request: Request, data: ChatRequest):
    answer = chat_with_context(
        question      = data.question,
        city          = data.city,
        planning_data = data.planning_data,
        scenario_data = data.scenario_data,
        cost_estimate = data.cost_estimate,
    )
    return {"answer": answer}

@app.post("/detect-zone")
@limiter.limit("30/minute")
def detect_zone(request: Request, body: Coordinate):
    result = detect_zone_from_coordinate(body.lat, body.lng)
    if not result["found"]:
        return {"found": False, "message": "Coordinate is outside mapped zone boundaries."}
    return result

@app.post("/generate-report")
@limiter.limit("5/minute")
def generate_report(request: Request, data: dict):
    pdf_bytes = generate_planning_report(data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="planning-report.pdf"'
        }
    )

@app.post("/scenarios")
@limiter.limit("15/minute")
def get_scenarios(request: Request, body: ScenarioRequest):
    return calculate_scenarios(
        zone              = body.zone,
        road_width        = body.road_width,
        plot_area_sqft    = body.plot_area_sqft,
        plot_length_m     = body.plot_length_m,
        plot_width_m      = body.plot_width_m,
        usage             = body.usage,
        corner_plot       = body.corner_plot,
        basement          = body.basement,
        scenarios         = body.scenarios,
        floor_height_m    = body.floor_height_m,
        building_height_m = body.building_height_m,
    )

@app.post("/estimate-cost")
@limiter.limit("15/minute")
def cost_estimate_endpoint(request: Request, data: dict):
    return estimate_cost(
        plot_length_m     = float(data.get("plot_length_m",      20)),
        plot_width_m      = float(data.get("plot_width_m",       15)),
        built_up_sqm      = float(data.get("built_up_sqm",      500)),
        num_floors        = int(data.get("num_floors",             3)),
        floor_height_m    = float(data.get("floor_height_m",     3.2)),
        setback_front     = float(data.get("setback_front",        3)),
        setback_side      = float(data.get("setback_side",       1.5)),
        setback_rear      = float(data.get("setback_rear",       1.5)),
        usage             = str(data.get("usage",      "residential")),
        zone              = str(data.get("zone",                 "RM")),
        fire_noc_required = bool(data.get("fire_noc_required",  False)),
        basement          = bool(data.get("basement",           False)),
        car_spaces        = int(data.get("car_spaces",              0)),
        tier              = str(data.get("tier",                "mid")),
    )

@app.post("/generate-floor-plan")
@limiter.limit("15/minute")
def floor_plan_endpoint(request: Request, data: dict):
    return generate_floor_plan(
        plot_length_m       = float(data.get("plot_length_m",       20)),
        plot_width_m        = float(data.get("plot_width_m",        15)),
        setback_front       = float(data.get("setback_front",        3)),
        setback_side        = float(data.get("setback_side",       1.5)),
        setback_rear        = float(data.get("setback_rear",       1.5)),
        building_height_m   = float(data.get("building_height_m",   10)),
        num_floors          = int(data.get("num_floors",              3)),
        floor_height_m      = float(data.get("floor_height_m",      3.2)),
        usage               = str(data.get("usage",       "residential")), 
        zone                = str(data.get("zone",                  "RM")),
        ground_coverage_pct = float(data.get("ground_coverage_pct",  60)),
        road_width_m        = float(data.get("road_width_m",          6)),
        corner_plot         = bool(data.get("corner_plot",        False)),
        basement            = bool(data.get("basement",           False)),
    )

@app.post("/parking")
@limiter.limit("20/minute")
def parking_calculator(request: Request, body: ParkingRequest):
    return calculate_parking(
        usage          = body.usage,
        built_up_sqft  = body.built_up_sqft,
        num_units      = body.num_units,
        plot_length_m  = body.plot_length_m,
        plot_width_m   = body.plot_width_m,
        basement       = body.basement,
        stilt          = body.stilt,
    )

@app.get("/permissible-usages")
@limiter.limit("60/minute")
def permissible_usages(request: Request, zone: str = "R", road_width: float = 9.0):
    """
    Return the list of usages allowed in the given zone at the given road width.
    Used by the frontend to dynamically filter the Usage dropdown.
    """
    from app.services.city_rules_engine import get_allowed_usages_for_zone
    return {"usages": get_allowed_usages_for_zone(zone, road_width)}


@app.post("/estimate-valuation")
@limiter.limit("15/minute")
def estimate_valuation_endpoint(request: Request, data: dict):
    """
    Market valuation estimator for Bengaluru (Karnataka SRO guidance values +
    optional OpenStreetMap Overpass amenity uplift).
    """
    from app.services.valuation_service import estimate_valuation
    return estimate_valuation(
        city                    = str(data.get("city",    "bengaluru")),
        zone                    = str(data.get("zone",    "R")),
        usage                   = str(data.get("usage",   "residential")),
        max_built_sqm           = float(data.get("max_built_sqm",   0)),
        num_floors              = int(data.get("num_floors",         1)),
        plot_area_sqm           = float(data.get("plot_area_sqm",   0)),
        total_construction_cost = float(data.get("total_construction_cost", 0)),
        lat                     = data.get("lat"),
        lng                     = data.get("lng"),
    )


@app.post("/valuation-analysis")
@limiter.limit("10/minute")
def valuation_analysis_endpoint(request: Request, data: dict):
    """Accepts a /estimate-valuation response body; returns AI-generated narrative explaining the numbers."""
    from app.services.valuation_service import generate_valuation_analysis
    return generate_valuation_analysis(data)


@app.post("/valuation-chat")
@limiter.limit("20/minute")
def valuation_chat_endpoint(request: Request, data: dict):
    """Math-grounded Q&A chat for Market Valuation. Injects full valuation context."""
    from app.services.valuation_service import answer_valuation_question
    return {"answer": answer_valuation_question(
        question          = str(data.get("question", "")),
        valuation_context = data.get("valuation_context", {}),
        city              = str(data.get("city", "bengaluru")),
    )}


@app.get("/permissible-usages-hyderabad")
@limiter.limit("60/minute")
def permissible_usages_hyderabad(request: Request, zone: str = "R2", road_width: float = 9.0):
    """Return usage options allowed in the given GHMC/HMDA zone at that road width."""
    from app.services.hyderabad_planning_service import get_allowed_usages_for_hyderabad_zone
    return {"usages": get_allowed_usages_for_hyderabad_zone(zone, road_width)}


@app.post("/planning-ranchi")
@limiter.limit("10/minute")
def planning_ranchi(request: Request, data: dict):
    import math
    area_sqm = data.get("plot_area_sqm")
    if area_sqm and float(area_sqm) > 0:
        side = round(math.sqrt(float(area_sqm)), 2)
        plot_l, plot_w = side, side
    else:
        plot_l = float(data.get("plot_length", 15))
        plot_w = float(data.get("plot_width",  10))
    return calculate_ranchi_planning(
        zone              = str(data.get("zone",              "general_zone")),
        plot_length_m     = plot_l,
        plot_width_m      = plot_w,
        road_width_m      = float(data.get("road_width",                9)),
        building_height_m = float(data.get("building_height",           0)),
        usage             = str(data.get("usage",          "residential")),
        corner_plot       = bool(data.get("corner_plot",          False)),
        basement          = bool(data.get("basement",             False)),
        floor_height_m    = float(data.get("floor_height",           3.2)),
        locality          = str(data.get("locality",            "Ranchi")),
        ward              = str(data.get("ward",                      "")),
        authority         = str(data.get("authority",               "rmc")),
    )


@app.post("/scenarios-ranchi")
@limiter.limit("15/minute")
def scenarios_ranchi(request: Request, data: dict):
    return calculate_ranchi_scenarios(
        zone              = str(data.get("zone",              "general_zone")),
        road_width        = float(data.get("road_width",                9)),
        plot_length_m     = float(data.get("plot_length",              15)),
        plot_width_m      = float(data.get("plot_width",               10)),
        usage             = str(data.get("usage",          "residential")),
        corner_plot       = bool(data.get("corner_plot",          False)),
        basement          = bool(data.get("basement",             False)),
        floor_height_m    = float(data.get("floor_height",           3.2)),
        building_height_m = float(data.get("building_height",          0)),
        authority         = str(data.get("authority",               "rmc")),
    )


@app.post("/planning-hyderabad")
@limiter.limit("10/minute")
def planning_hyderabad(request: Request, data: dict):
    import math
    area_sqm = data.get("plot_area_sqm")
    if area_sqm and float(area_sqm) > 0:
        side = round(math.sqrt(float(area_sqm)), 2)
        plot_l, plot_w = side, side
    else:
        plot_l = float(data.get("plot_length", 15))
        plot_w = float(data.get("plot_width",  10))
    return calculate_hyderabad_planning(
        zone              = str(data.get("zone",              "R2")),
        plot_length_m     = plot_l,
        plot_width_m      = plot_w,
        road_width_m      = float(data.get("road_width",                9)),
        building_height_m = float(data.get("building_height",           0)),
        usage             = str(data.get("usage",          "residential")),
        corner_plot       = bool(data.get("corner_plot",          False)),
        basement          = bool(data.get("basement",             False)),
        floor_height_m    = float(data.get("floor_height",            3.0)),
        locality          = str(data.get("locality",        "Hyderabad")),
    )

@app.post("/scenarios-hyderabad")
@limiter.limit("15/minute")
def scenarios_hyderabad(request: Request, data: dict):
    return calculate_hyderabad_scenarios(
        zone              = str(data.get("zone",              "R2")),
        road_width        = float(data.get("road_width",                9)),
        plot_length_m     = float(data.get("plot_length",              15)),
        plot_width_m      = float(data.get("plot_width",               10)),
        usage             = str(data.get("usage",          "residential")),
        corner_plot       = bool(data.get("corner_plot",          False)),
        basement          = bool(data.get("basement",             False)),
        floor_height_m    = float(data.get("floor_height",            3.0)),
        building_height_m = float(data.get("building_height",           0)),
        locality          = str(data.get("locality",        "Hyderabad")),
    )


# ── BMRDA / ANEKAL ──────────────────────────────────────────────────────────────
# @app.get("/permissible-usages-anekal")
# @limiter.limit("60/minute")
# def permissible_usages_anekal(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.anekal_planning_service import get_allowed_usages_for_anekal_zone
#     return {"usages": get_allowed_usages_for_anekal_zone(zone, road_width)}
#
#
# @app.post("/planning-anekal")
# @limiter.limit("10/minute")
# def planning_anekal(request: Request, data: dict):
#     return calculate_anekal_planning(
#         zone              = str(data.get("zone",              "R")),
#         plot_length_m     = float(data.get("plot_length",     15)),
#         plot_width_m      = float(data.get("plot_width",      10)),
#         road_width_m      = float(data.get("road_width",       9)),
#         building_height_m = float(data.get("building_height",  0)),
#         usage             = str(data.get("usage",  "residential")),
#         corner_plot       = bool(data.get("corner_plot",   False)),
#         basement          = bool(data.get("basement",      False)),
#         floor_height_m    = float(data.get("floor_height",   3.0)),
#         locality          = str(data.get("locality",      "Anekal")),
#     )
#
#
# @app.post("/scenarios-anekal")
# @limiter.limit("15/minute")
# def scenarios_anekal(request: Request, data: dict):
#     return calculate_anekal_scenarios(
#         zone              = str(data.get("zone",              "R")),
#         road_width        = float(data.get("road_width",       9)),
#         plot_length_m     = float(data.get("plot_length",     15)),
#         plot_width_m      = float(data.get("plot_width",      10)),
#         usage             = str(data.get("usage",  "residential")),
#         corner_plot       = bool(data.get("corner_plot",   False)),
#         basement          = bool(data.get("basement",      False)),
#         floor_height_m    = float(data.get("floor_height",   3.0)),
#         building_height_m = float(data.get("building_height",  0)),
#         locality          = str(data.get("locality",      "Anekal")),
#     )


# ── BMRDA / HOSKOTE ─────────────────────────────────────────────────────────────
# @app.get("/permissible-usages-hoskote")
# @limiter.limit("60/minute")
# def permissible_usages_hoskote(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.hoskote_planning_service import get_allowed_usages_for_hoskote_zone
#     return {"usages": get_allowed_usages_for_hoskote_zone(zone, road_width)}
#
#
# @app.post("/planning-hoskote")
# @limiter.limit("10/minute")
# def planning_hoskote(request: Request, data: dict):
#     return calculate_hoskote_planning(
#         zone              = str(data.get("zone",              "R")),
#         plot_length_m     = float(data.get("plot_length",     15)),
#         plot_width_m      = float(data.get("plot_width",      10)),
#         road_width_m      = float(data.get("road_width",       9)),
#         building_height_m = float(data.get("building_height",  0)),
#         usage             = str(data.get("usage",  "residential")),
#         corner_plot       = bool(data.get("corner_plot",   False)),
#         basement          = bool(data.get("basement",      False)),
#         floor_height_m    = float(data.get("floor_height",   3.0)),
#         locality          = str(data.get("locality",    "Hoskote")),
#     )
#
#
# @app.post("/scenarios-hoskote")
# @limiter.limit("15/minute")
# def scenarios_hoskote(request: Request, data: dict):
#     return calculate_hoskote_scenarios(
#         zone              = str(data.get("zone",              "R")),
#         road_width        = float(data.get("road_width",       9)),
#         plot_length_m     = float(data.get("plot_length",     15)),
#         plot_width_m      = float(data.get("plot_width",      10)),
#         usage             = str(data.get("usage",  "residential")),
#         corner_plot       = bool(data.get("corner_plot",   False)),
#         basement          = bool(data.get("basement",      False)),
#         floor_height_m    = float(data.get("floor_height",   3.0)),
#         building_height_m = float(data.get("building_height",  0)),
#         locality          = str(data.get("locality",    "Hoskote")),
#     )


# ── BMRDA / NELAMANGALA ─────────────────────────────────────────────────────────
# @app.get("/permissible-usages-nelamangala")
# @limiter.limit("60/minute")
# def permissible_usages_nelamangala(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.nelamangala_planning_service import get_allowed_usages_for_nelamangala_zone
#     return {"usages": get_allowed_usages_for_nelamangala_zone(zone, road_width)}
#
#
# @app.post("/planning-nelamangala")
# @limiter.limit("10/minute")
# def planning_nelamangala(request: Request, data: dict):
#     return calculate_nelamangala_planning(
#         zone              = str(data.get("zone",                  "R")),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         road_width_m      = float(data.get("road_width",           9)),
#         building_height_m = float(data.get("building_height",      0)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         locality          = str(data.get("locality",    "Nelamangala")),
#     )
#
#
# @app.post("/scenarios-nelamangala")
# @limiter.limit("15/minute")
# def scenarios_nelamangala(request: Request, data: dict):
#     return calculate_nelamangala_scenarios(
#         zone              = str(data.get("zone",                  "R")),
#         road_width        = float(data.get("road_width",           9)),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         building_height_m = float(data.get("building_height",      0)),
#         locality          = str(data.get("locality",    "Nelamangala")),
#     )


# ── BMRDA / KANAKAPURA ──────────────────────────────────────────────────────────
# @app.get("/permissible-usages-kanakapura")
# @limiter.limit("60/minute")
# def permissible_usages_kanakapura(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.kanakapura_planning_service import get_allowed_usages_for_kanakapura_zone
#     return {"usages": get_allowed_usages_for_kanakapura_zone(zone, road_width)}
#
#
# @app.post("/planning-kanakapura")
# @limiter.limit("10/minute")
# def planning_kanakapura(request: Request, data: dict):
#     return calculate_kanakapura_planning(
#         zone              = str(data.get("zone",                  "R")),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         road_width_m      = float(data.get("road_width",           9)),
#         building_height_m = float(data.get("building_height",      0)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         locality          = str(data.get("locality",    "Kanakapura")),
#     )
#
#
# @app.post("/scenarios-kanakapura")
# @limiter.limit("15/minute")
# def scenarios_kanakapura(request: Request, data: dict):
#     return calculate_kanakapura_scenarios(
#         zone              = str(data.get("zone",                  "R")),
#         road_width        = float(data.get("road_width",           9)),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         building_height_m = float(data.get("building_height",      0)),
#         locality          = str(data.get("locality",    "Kanakapura")),
#     )


# ── BMRDA / RAMANAGARA ──────────────────────────────────────────────────────────
# @app.get("/permissible-usages-ramanagara")
# @limiter.limit("60/minute")
# def permissible_usages_ramanagara(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.ramanagara_planning_service import get_allowed_usages_for_ramanagara_zone
#     return {"usages": get_allowed_usages_for_ramanagara_zone(zone, road_width)}
#
#
# @app.post("/planning-ramanagara")
# @limiter.limit("10/minute")
# def planning_ramanagara(request: Request, data: dict):
#     return calculate_ramanagara_planning(
#         zone              = str(data.get("zone",                  "R")),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         road_width_m      = float(data.get("road_width",           9)),
#         building_height_m = float(data.get("building_height",      0)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         locality          = str(data.get("locality",    "Ramanagara")),
#     )
#
#
# @app.post("/scenarios-ramanagara")
# @limiter.limit("15/minute")
# def scenarios_ramanagara(request: Request, data: dict):
#     return calculate_ramanagara_scenarios(
#         zone              = str(data.get("zone",                  "R")),
#         road_width        = float(data.get("road_width",           9)),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         building_height_m = float(data.get("building_height",      0)),
#         locality          = str(data.get("locality",    "Ramanagara")),
#     )


# ── BIAAPA ──────────────────────────────────────────────────────────────────────
# @app.get("/permissible-usages-biaapa")
# @limiter.limit("60/minute")
# def permissible_usages_biaapa(request: Request, zone: str = "R", road_width: float = 9.0):
#     from app.services.biaapa_planning_service import get_allowed_usages_for_biaapa_zone
#     return {"usages": get_allowed_usages_for_biaapa_zone(zone, road_width)}
#
#
# @app.post("/planning-biaapa")
# @limiter.limit("10/minute")
# def planning_biaapa(request: Request, data: dict):
#     return calculate_biaapa_planning(
#         zone              = str(data.get("zone",                  "R")),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         road_width_m      = float(data.get("road_width",           9)),
#         building_height_m = float(data.get("building_height",      0)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         locality          = str(data.get("locality",       "BIAAPA")),
#     )
#
#
# @app.post("/scenarios-biaapa")
# @limiter.limit("15/minute")
# def scenarios_biaapa(request: Request, data: dict):
#     return calculate_biaapa_scenarios(
#         zone              = str(data.get("zone",                  "R")),
#         road_width        = float(data.get("road_width",           9)),
#         plot_length_m     = float(data.get("plot_length",         15)),
#         plot_width_m      = float(data.get("plot_width",          10)),
#         usage             = str(data.get("usage",      "residential")),
#         corner_plot       = bool(data.get("corner_plot",       False)),
#         basement          = bool(data.get("basement",          False)),
#         floor_height_m    = float(data.get("floor_height",       3.0)),
#         building_height_m = float(data.get("building_height",      0)),
#         locality          = str(data.get("locality",       "BIAAPA")),
#     )
