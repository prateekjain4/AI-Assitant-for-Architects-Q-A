from pydantic import BaseModel

class ParkingRequest(BaseModel):
    usage:          str
    built_up_sqft:  float
    num_units:      int   = 1
    plot_length_m:  float = 0
    plot_width_m:   float = 0
    basement:       bool  = False
    stilt:          bool  = False