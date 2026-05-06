# AI Bylaw Monitor — Project Context for Claude

## What This Project Is
A full-stack AI assistant for architects and real estate developers that answers: **"What can I build on this plot, and is it bylaw-compliant?"**

Covers Indian building bylaws across 3 cities. Users enter plot details (zone, road width, dimensions) and get FAR, setbacks, floors, parking, fire requirements, cost estimates, and scenario comparisons.

---

## Repository Structure

```
D:\AI-Project\bylaw_monitor\AI-Assitant-for-Architects-Q-A\   ← Backend (this repo)
D:\AI-Project\BylawUI\AI-Assitant-for-Architects-Q-A-Angular\ ← Frontend (separate repo)
```

---

## Backend — FastAPI (Python)

**Entry point:** `app/main.py`
**Run with:** `uvicorn app.main:app --reload`
**DB:** SQLite → `bylaw_app.db` (SQLAlchemy)

### API Endpoints

| Method | Route | Service | Description |
|--------|-------|---------|-------------|
| POST | `/planning` | `planning_request_service.py` | Full bylaw analysis for Bengaluru |
| POST | `/bengaluru` | `planning_request_service.py` | Bengaluru-specific planning |
| POST | `/hyderabad` | `hyderabad_planning_service.py` | Hyderabad planning |
| POST | `/ranchi` | `ranchi_planning_service.py` | Ranchi planning |
| POST | `/scenarios` | `scenario_service.py` | Scenario comparison (Bengaluru) |
| POST | `/hyderabad-scenarios` | `hyderabad_scenario_service.py` | Scenario comparison (Hyderabad) |
| POST | `/detect-zone` | `zone_service.py` | Lat/lng → BDA zone from GeoJSON |
| POST | `/chat` | `chat_service.py` | Context-aware AI chat |
| POST | `/ask` | `services.py` | Raw bylaw Q&A via FAISS |
| POST | `/generate-report` | `report_service.py` | Export planning result as PDF |
| POST | `/estimate-cost` | `cost_estimator_service.py` | Construction cost estimate |
| POST | `/generate-floor-plan` | `floor_plan_service.py` | Basic floor plan layout |
| POST | `/check-updates` | `services.py` | Hash-based bylaw change detection |

### Services (`app/services/`)

| File | Purpose |
|------|---------|
| `city_rules_engine.py` | **Core Bengaluru rules engine** — FAR, setbacks, GC, permissible uses, space standards, fire, parking, TDR. Reads `city_rules/bengaluru_bda.json` |
| `planning_request_service.py` | Orchestrates full Bengaluru planning response. Uses Shapely+pyproj for area from polygon coords |
| `scenario_service.py` | Computes multiple building configurations side by side (Bengaluru) |
| `hyderabad_planning_service.py` | Hyderabad (HMDA) planning logic |
| `hyderabad_scenario_service.py` | Scenario comparison for Hyderabad |
| `ranchi_planning_service.py` | Ranchi (RMC) planning logic |
| `zone_service.py` | GeoJSON point-in-polygon zone detection using `bangalore_zones.geojson` |
| `chat_service.py` | LLM chat with planning/scenario/cost context injected as system prompt |
| `services.py` | FAISS vector search, PDF download/parse, bylaw change detection. Uses `all-MiniLM-L6-v2` embeddings |
| `parking_service.py` | Parking requirement calculator by usage type |
| `report_service.py` | PDF report generation using ReportLab |
| `cost_estimator_service.py` | Construction cost estimation (economy/mid/premium tiers) |
| `floor_plan_service.py` | Floor plan layout generator |

### Models (`app/model/`)
- `planning_request.py` — `PlanningRequest`, `Coordinate`
- `scenario_request.py` — `ScenarioRequest`
- `parking_request.py` — `ParkingRequest`
- `db_models.py` — SQLAlchemy: `Firm`, `User`, `Project`

### Auth (`app/routers/`)
- JWT-based auth (`python-jose` + `bcrypt`)
- Firm-level multi-tenancy: `Firm` → `User` → `Project`
- Plan tiers: `trial` (14 days, 3 seats), paid tiers
- `AuthGuard` on all protected routes

---

## Rules Data (`city_rules/`)

| File | Contents |
|------|---------|
| `bengaluru_bda.json` | **Primary rules file.** FAR matrix, setbacks, GC, permissible uses (Tables 5/11/19), space standards (Table 25), parking, fire, basement, balcony, accessibility, TDR, solar, compound wall — all from BDA RMP 2031 |
| `hyderabad_hmda.json` | HMDA bylaws rules |
| `ranchi_rmc.json` | RMC bylaws rules |
| `bengaluru.json` | Older/supplemental Bengaluru rules |
| `extract_rules.py` | Script to extract rules from PDFs |
| `extract_amendment.py` | Parses amendment GOs |
| `parse_amendment.py` | Structures amendment data |
| `apply_amendment.py` | Applies parsed amendments to JSON rules |

**Zone data:** `bangalore_zones.geojson` — BDA zone polygons (R, C, PSP, I, T etc.) used by `zone_service.py`

---

## AI / ML Stack

- **LLM:** OpenAI API (via `openai` SDK, key in `.env`)
- **Embeddings:** `sentence-transformers` — model `all-MiniLM-L6-v2`
- **Vector store:** FAISS (`data/bylaw_index.faiss` + `data/section_metadata.json`)
- **Source PDFs indexed:** BBMP Bylaws, BDA Zoning Regulations, NBC 2016, Ranchi Bylaws, Hyderabad Bylaws

---

## Frontend — Angular (`D:\AI-Project\BylawUI\AI-Assitant-for-Architects-Q-A-Angular`)

**Run with:** `ng serve` → `http://localhost:4200`
**Backend CORS:** configured for `http://localhost:4200`

### Routes

| Path | Component | Auth Required |
|------|-----------|--------------|
| `/` | Home | No |
| `/bengaluru` | BengaluruPlanningTool | Yes |
| `/hyderabad` | HyderabadPlanningTool | Yes |
| `/ranchi` | RanchiPlanningTool | Yes |
| `/planning` | PlanningTool | Yes |
| `/ask` | Askai | Yes |
| `/cost-analysis` | CostAnalysisPage | Yes |
| `/updates` | UpdatedBylaw | Yes |
| `/about` | About | No |
| `/login` `/signup` | Auth | No |

### Key Components
- **Map** — plot boundary drawing, zone detection on map
- **SitePlan** — visual site plan layout
- **ScenarioComparison** — side-by-side scenario table
- **ParkingLayout** — parking visualizer
- **CostEstimator** — construction cost inputs
- **Navbar**, **Toast** — UI chrome

---

## Key Technical Details

- **Area calculation:** Plot polygon coords (WGS84 lng/lat) → projected to UTM Zone 43N (EPSG:32643) via pyproj for accurate sqm → converted to sqft
- **Rate limiting:** slowapi — 30/min on `/ask`, 10/min on `/planning`, etc.
- **FAR matrix (Bengaluru):** Diagonal lookup — `min(road_width_tier, plot_area_tier)` is the binding constraint
- **Setbacks:** Progressive by building height (BDA RMP 2031 Table 2). Front = `max(height-based, road-width-based)`
- **Change detection:** Hash each bylaw PDF section; diff on re-run; store in `data/section_hashes.json`

---

## Environment Variables (`.env`)
```
OPENAI_API_KEY=...
SECRET_KEY=...       # JWT signing key
```

---

## Cities & Legal Sources

| City | Authority | Primary Source |
|------|-----------|---------------|
| Bengaluru | BDA | BDA RMP 2031 Zoning Regulations + BBMP Building Byelaws 2003 |
| Hyderabad | HMDA | HMDA Building Rules |
| Ranchi | RMC | Ranchi Municipal Corporation Bylaws |
| Fire (all cities) | National | NBC 2016 Part IV |

---

## Current State (as of April 2026)
- Backend: complete and working
- Frontend: complete with all pages
- Bengaluru rules engine: most detailed (full FAR matrix, space standards, TDR, all use types)
- Hyderabad and Ranchi: functional but less detailed than Bengaluru
- Not yet deployed (local dev only)
- Next planned feature: lake/water body proximity check using BBMP GIS data
