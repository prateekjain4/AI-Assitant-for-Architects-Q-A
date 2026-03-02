from fastapi import FastAPI
import json
import os
from app.services import run_full_pipeline, JSON_FILE, SECTION_HASH_FILE

app = FastAPI(title="AI Bylaw Monitor API")


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
    if not os.path.exists(SECTION_HASH_FILE):
        return {"error": "No change data available."}

    with open(SECTION_HASH_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data