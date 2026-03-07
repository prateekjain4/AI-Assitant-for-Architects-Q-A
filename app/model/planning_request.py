from pydantic import BaseModel

class PlanningRequest(BaseModel):
    zone: str
    plot_length: float
    plot_width: float
    road_width: float
    building_height: float
    usage: str