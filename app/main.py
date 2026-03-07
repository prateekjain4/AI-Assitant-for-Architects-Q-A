from fastapi import FastAPI
import json
import os
from app.services import run_full_pipeline, JSON_FILE, change_report
from pydantic import BaseModel
from app.services import answer_question_from_bylaws
from fastapi.middleware.cors import CORSMiddleware
from app.model.planning_request import PlanningRequest
from app.planning_request_service import calculate_plot_planning

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