from fastapi import FastAPI, Response, Request
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

# Routers
app.include_router(auth_router)
app.include_router(projects_router)

class QuestionRequest(BaseModel):
    question: str

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    return answer_question_from_bylaws(body.question)

@app.post("/planning")
@limiter.limit("10/minute")
def planning_tool(request: Request, body: PlanningRequest):
    return calculate_plot_planning(body)

@app.post("/chat")
@limiter.limit("20/minute")
def chat_endpoint(request: Request, data: dict):
    answer = chat_with_context(
        question      = data.get("question"),
        planning_data = data.get("planning_data"),
        scenario_data = data.get("scenario_data"),
        cost_estimate = data.get("cost_estimate"),
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

@app.post("/planning-ranchi")
@limiter.limit("10/minute")
def planning_ranchi(request: Request, data: dict):
    return calculate_ranchi_planning(
        zone              = str(data.get("zone",              "general_zone")),
        plot_length_m     = float(data.get("plot_length",              15)),
        plot_width_m      = float(data.get("plot_width",               10)),
        road_width_m      = float(data.get("road_width",                9)),
        building_height_m = float(data.get("building_height",          10)),
        usage             = str(data.get("usage",          "residential")),
        corner_plot       = bool(data.get("corner_plot",          False)),
        basement          = bool(data.get("basement",             False)),
        floor_height_m    = float(data.get("floor_height",           3.2)),
        locality          = str(data.get("locality",            "Ranchi")),
        ward              = str(data.get("ward",                      "")),
    )
