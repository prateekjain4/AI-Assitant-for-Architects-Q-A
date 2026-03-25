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

app = FastAPI(title="AI Bylaw Monitor API")

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