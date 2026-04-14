from pydantic import BaseModel
class ScenarioRequest(BaseModel):
    zone:            str
    road_width:      float
    plot_area_sqft:  float
    plot_length_m:   float
    plot_width_m:    float
    usage:           str   = "residential"
    corner_plot:     bool  = False
    basement:        bool  = False
    scenarios:       list  = None   # reserved; scenarios are derived from bylaw thresholds
    floor_height_m:  float = 3.2
    building_height_m: float = 0.0   # 0 = no height cap, use FAR only