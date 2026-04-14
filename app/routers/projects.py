import json
import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.database import get_db
from app.model.db_models import Project
from app.routers.auth import get_current_user
from app.model.db_models import User

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Pydantic schemas ──────────────────────────────────────────────

class SaveProjectRequest(BaseModel):
    name:           str
    zone:           Optional[str] = ""
    locality:       Optional[str] = ""
    plot_inputs:    Optional[dict] = {}
    planning_result: Optional[dict] = {}
    cost_estimate:  Optional[dict] = {}
    scenarios:      Optional[dict] = {}


class RenameProjectRequest(BaseModel):
    name: str


# ── Helpers ───────────────────────────────────────────────────────

def _to_dict(project: Project) -> dict:
    return {
        "id":              project.id,
        "name":            project.name,
        "zone":            project.zone,
        "locality":        project.locality,
        "created_at":      project.created_at.isoformat(),
        "updated_at":      project.updated_at.isoformat() if project.updated_at else project.created_at.isoformat(),
        "saved_by":        project.user.full_name,
        "plot_inputs":     json.loads(project.plot_inputs   or "{}"),
        "planning_result": json.loads(project.planning_result or "{}"),
        "cost_estimate":   json.loads(project.cost_estimate  or "{}"),
        "scenarios":       json.loads(project.scenarios      or "{}"),
    }


# ── Routes ────────────────────────────────────────────────────────

@router.post("/save")
def save_project(
    req: SaveProjectRequest,
    db:  Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = Project(
        name            = req.name.strip(),
        firm_id         = current_user.firm_id,
        user_id         = current_user.id,
        zone            = req.zone or "",
        locality        = req.locality or "",
        plot_inputs     = json.dumps(req.plot_inputs or {}),
        planning_result = json.dumps(req.planning_result or {}),
        cost_estimate   = json.dumps(req.cost_estimate or {}),
        scenarios       = json.dumps(req.scenarios or {}),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return {"message": "Project saved", "id": project.id, "name": project.name}


@router.get("/")
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    projects = (
        db.query(Project)
        .filter(Project.firm_id == current_user.firm_id)
        .order_by(Project.updated_at.desc())
        .all()
    )
    # Return summary list (no heavy JSON blobs)
    return [
        {
            "id":         p.id,
            "name":       p.name,
            "zone":       p.zone,
            "locality":   p.locality,
            "saved_by":   p.user.full_name,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat() if p.updated_at else p.created_at.isoformat(),
        }
        for p in projects
    ]


@router.get("/{project_id}")
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.firm_id == current_user.firm_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _to_dict(project)


@router.patch("/{project_id}/rename")
def rename_project(
    project_id: int,
    req: RenameProjectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.firm_id == current_user.firm_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project.name       = req.name.strip()
    project.updated_at = datetime.datetime.utcnow()
    db.commit()
    return {"message": "Renamed", "name": project.name}


@router.delete("/{project_id}")
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.firm_id == current_user.firm_id,
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return {"message": "Deleted"}