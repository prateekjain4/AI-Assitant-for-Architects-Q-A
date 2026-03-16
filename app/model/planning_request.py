from pydantic import BaseModel
from typing import List, Optional

class Coordinate(BaseModel):
    lat: float
    lng: float

class PlanningRequest(BaseModel):
    zone: str
    plot_length: Optional[float] = None
    plot_width: Optional[float] = None
    coordinates: List[Coordinate]
    road_width: float
    building_height: float
    usage: str