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
    # new fields
    locality: Optional[str] = "Bangalore"
    ward: Optional[str] = ""
    corner_plot: Optional[bool] = False
    basement: Optional[bool] = False
    number_of_floors: Optional[int] = None
    number_of_units: Optional[int] = 1
    property_type: Optional[str] = "residential"