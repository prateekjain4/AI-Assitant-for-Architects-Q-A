from fastapi import FastAPI, Response
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
from app.routers.auth import router as auth_router
from app.db.database import engine
from app.model import db_models

# Create DB tables on startup (SQLite file: bylaw_app.db)
db_models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Bylaw Monitor API")

# Auth routes
app.include_router(auth_router)

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
def ask_question(request: QuestionRequest):
    return answer_question_from_bylaws(request.question)

@app.post("/planning")
def planning_tool(request: PlanningRequest):
    return calculate_plot_planning(request)

@app.post("/chat")
def chat_endpoint(data: dict):

    question = data.get("question")
    planning_data = data.get("planning_data", None)

    answer = chat_with_context(question, planning_data)

    return {"answer": answer}

@app.post("/detect-zone")
def detect_zone(request: Coordinate):
    result = detect_zone_from_coordinate(request.lat, request.lng)
    if not result["found"]:
        return {"found": False, "message": "Coordinate is outside mapped zone boundaries."}
    return result

@app.post("/generate-report")
def generate_report(data: dict):
    pdf_bytes = generate_planning_report(data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="planning-report.pdf"'
        }
    )


@app.post("/scenarios")
def get_scenarios(request: ScenarioRequest):
    return calculate_scenarios(
        zone              = request.zone,
        road_width        = request.road_width,
        plot_area_sqft    = request.plot_area_sqft,
        plot_length_m     = request.plot_length_m,
        plot_width_m      = request.plot_width_m,
        usage             = request.usage,
        corner_plot       = request.corner_plot,
        basement          = request.basement,
        scenarios         = request.scenarios,
        floor_height_m    = request.floor_height_m,
        building_height_m = request.building_height_m,
    )


@app.post("/estimate-cost")
def cost_estimate_endpoint(data: dict):
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
def floor_plan_endpoint(data: dict):
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
def parking_calculator(request: ParkingRequest):
    return calculate_parking(
        usage          = request.usage,
        built_up_sqft  = request.built_up_sqft,
        num_units      = request.num_units,
        plot_length_m  = request.plot_length_m,
        plot_width_m   = request.plot_width_m,
        basement       = request.basement,
        stilt          = request.stilt,
    )
