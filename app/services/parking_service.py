import math

# ── Parking requirements — BDA RMP 2031 Sec 4.13 / Table 4 ──────
PARKING_RULES = {
    "residential": {
        "bike_per_car":  2,    # 2 two-wheelers per car space (BBMP convention)
        "visitor_pct":  10,    # 10% extra for visitors
        "note": "BDA RMP 2031 Sec 4.13 / Table 4 — Residential Multi-Dwelling"
    },
    "residential_single": {
        "bike_per_car":  2,
        "visitor_pct":  10,
        "note": "BDA RMP 2031 Sec 4.13 / Table 4 — Residential Single Dwelling (1 car / 100 sqm BUA)"
    },
    "commercial": {
        "car_per_100sqm": 2,   # 1 car per 50 sqm (office/retail, Table 4)
        "bike_per_car":   2,
        "visitor_pct":   20,
        "note": "BDA RMP 2031 Sec 4.13 / Table 4 — Commercial (Office/Retail)"
    },
    "mixed": {
        "car_per_100sqm": 2,
        "bike_per_car":   2,
        "visitor_pct":   15,
        "note": "BDA RMP 2031 Sec 4.13 / Table 4 — Mixed Use"
    },
    "industrial": {
        "car_per_100sqm": 1,   # 1 car per 100 sqm (Table 4)
        "bike_per_car":   3,
        "visitor_pct":   10,
        "note": "BDA RMP 2031 Sec 4.13 / Table 4 — Industrial"
    },
}

# ── Standard parking space dimensions (IRC + BBMP) ────────────────
CAR_SPACE = {
    "length_m":  5.0,
    "width_m":   2.5,
    "area_sqm":  12.5,
}
BIKE_SPACE = {
    "length_m":  2.0,
    "width_m":   1.0,
    "area_sqm":  2.0,
}
DRIVE_AISLE_WIDTH_M   = 6.0    # two-way drive aisle
RAMP_AREA_SQM         = 20.0   # ramp allowance per basement
WALL_CLEARANCE_M      = 0.5    # wall to parking space clearance


def calculate_parking(
    usage:           str,
    built_up_sqft:   float,
    num_units:       int   = 1,
    avg_unit_sqm:    float = 0,
    plot_length_m:   float = 0,
    plot_width_m:    float = 0,
    basement:        bool  = False,
    stilt:           bool  = False,
) -> dict:
    """
    Calculate mandatory parking per BDA RMP 2031 Sec 4.13 / Table 4
    and generate a layout plan showing how spaces fit.
    """
    raw_usage = (usage or "").lower().strip()
    # Normalise usage → rules key
    if raw_usage.startswith("residential"):
        if "single" in raw_usage or "dwelling" in raw_usage:
            usage_key = "residential_single"
        else:
            usage_key = "residential"
    elif raw_usage in PARKING_RULES:
        usage_key = raw_usage
    else:
        usage_key = "residential"
    rules     = PARKING_RULES[usage_key]
    built_sqm = built_up_sqft / 10.7639

    # ── Calculate required spaces (BDA Table 4) ──────────────────
    if usage_key == "residential_single":
        # Single dwelling: 1 car per 100 sqm BUA (mandatory for plots ≥ 90 sqm)
        cars_req     = max(1, math.ceil(built_sqm / 100))
        bikes_req    = cars_req * rules["bike_per_car"]
        visitor_cars = max(1, math.ceil(cars_req * rules["visitor_pct"] / 100))
        total_cars   = cars_req + visitor_cars
    elif usage_key == "residential":
        # Multi-dwelling — tiered by avg DU size (BDA Table 4)
        #   DU <  50 sqm : 1 car per 2 DUs
        #   DU 50-120    : 1 car per DU
        #   DU > 120     : 1 car + 1 per 120 sqm above 120 per DU
        avg_unit        = avg_unit_sqm if avg_unit_sqm > 0 else 130
        estimated_units = max(1, math.ceil(built_sqm / avg_unit))
        actual_units    = num_units if num_units > 1 else estimated_units
        if avg_unit < 50:
            cars_per_unit = 0.5
        elif avg_unit <= 120:
            cars_per_unit = 1.0
        else:
            cars_per_unit = 1 + math.floor((avg_unit - 120) / 120)
        cars_req     = math.ceil(actual_units * cars_per_unit)
        bikes_req    = cars_req * rules["bike_per_car"]
        visitor_cars = max(1, math.ceil(cars_req * rules["visitor_pct"] / 100))
        total_cars   = cars_req + visitor_cars
    else:
        cars_req     = math.ceil(built_sqm / 100 * rules["car_per_100sqm"])
        bikes_req    = cars_req * rules["bike_per_car"]
        visitor_cars = math.ceil(cars_req * rules["visitor_pct"] / 100)
        total_cars   = cars_req + visitor_cars

    total_bikes = bikes_req

    # ── Area needed ───────────────────────────────────────────────
    car_area_sqm  = total_cars  * CAR_SPACE["area_sqm"]
    bike_area_sqm = total_bikes * BIKE_SPACE["area_sqm"]

    # Aisle area: 1 aisle per 2 rows of cars
    rows_of_cars  = math.ceil(total_cars / 5)   # ~5 cars per row
    aisle_area    = rows_of_cars * DRIVE_AISLE_WIDTH_M * max(plot_width_m, 8)
    ramp_area     = RAMP_AREA_SQM if basement else 0

    total_parking_area_sqm = (
        car_area_sqm + bike_area_sqm + aisle_area + ramp_area
    )

    # ── Layout plan (for canvas drawing) ─────────────────────────
    layout = build_layout(
        total_cars  = total_cars,
        total_bikes = total_bikes,
        plot_width_m  = plot_width_m  or 15,
        plot_length_m = plot_length_m or 20,
        basement      = basement,
    )

    # ── Compliance check ──────────────────────────────────────────
    available_sqm = (plot_width_m * plot_length_m) if (plot_width_m and plot_length_m) else 0
    compliant     = available_sqm == 0 or total_parking_area_sqm <= available_sqm * 0.4

    return {
        "usage":               usage_key,
        "built_up_sqft":       round(built_up_sqft, 1),
        "built_up_sqm":        round(built_sqm, 1),
        "required": {
            "cars":            total_cars,
            "cars_resident":   cars_req,
            "cars_visitor":    visitor_cars,
            "bikes":           total_bikes,
        },
        "area": {
            "car_spaces_sqm":  round(car_area_sqm, 1),
            "bike_spaces_sqm": round(bike_area_sqm, 1),
            "aisles_sqm":      round(aisle_area, 1),
            "ramp_sqm":        ramp_area,
            "total_sqm":       round(total_parking_area_sqm, 1),
        },
        "location":   "Basement" if basement else ("Stilt" if stilt else "Surface"),
        "compliant":  compliant,
        "bylaw_ref":  rules["note"],
        "dimensions": {
            "car_space_m":    f"{CAR_SPACE['length_m']}m × {CAR_SPACE['width_m']}m",
            "bike_space_m":   f"{BIKE_SPACE['length_m']}m × {BIKE_SPACE['width_m']}m",
            "drive_aisle_m":  f"{DRIVE_AISLE_WIDTH_M}m wide",
        },
        "layout": layout,
        "warnings": build_warnings(
            total_cars, total_bikes, basement, stilt,
            total_parking_area_sqm, available_sqm
        ),
    }


def build_layout(
    total_cars:    int,
    total_bikes:   int,
    plot_width_m:  float,
    plot_length_m: float,
    basement:      bool,
) -> dict:
    """
    Generate a grid layout for the canvas:
    rows of car spaces + drive aisles + bike zone.
    Returns normalised coordinates (0–1) for canvas scaling.
    """
    cars_per_row  = max(1, math.floor((plot_width_m - 1.0) / (CAR_SPACE["width_m"] + 0.2)))
    car_rows      = math.ceil(total_cars / cars_per_row)
    row_height_m  = CAR_SPACE["length_m"] + DRIVE_AISLE_WIDTH_M

    # Bike zone at bottom
    bikes_per_row = max(1, math.floor((plot_width_m - 1.0) / (BIKE_SPACE["width_m"] + 0.1)))
    bike_rows     = math.ceil(total_bikes / bikes_per_row)
    bike_height_m = bike_rows * (BIKE_SPACE["length_m"] + 0.1)

    total_height  = car_rows * row_height_m + bike_height_m + (4.0 if basement else 0)

    # Build car space list with (row, col, isVisitor flag)
    car_spaces = []
    visitor_start = total_cars - math.ceil(total_cars * 0.1)
    for i in range(total_cars):
        row = i // cars_per_row
        col = i  % cars_per_row
        car_spaces.append({
            "row":       row,
            "col":       col,
            "visitor":   i >= visitor_start,
            "x_m":       WALL_CLEARANCE_M + col * (CAR_SPACE["width_m"] + 0.2),
            "y_m":       (4.0 if basement else 0) + row * row_height_m,
            "w_m":       CAR_SPACE["width_m"],
            "h_m":       CAR_SPACE["length_m"],
        })

    # Build bike space list
    bike_spaces = []
    bike_y_start = (4.0 if basement else 0) + car_rows * row_height_m + 0.5
    for i in range(total_bikes):
        row = i // bikes_per_row
        col = i  % bikes_per_row
        bike_spaces.append({
            "row": row, "col": col,
            "x_m": WALL_CLEARANCE_M + col * (BIKE_SPACE["width_m"] + 0.1),
            "y_m": bike_y_start + row * (BIKE_SPACE["length_m"] + 0.1),
            "w_m": BIKE_SPACE["width_m"],
            "h_m": BIKE_SPACE["length_m"],
        })

    # Drive aisles (one per car row, between spaces and next row)
    aisles = []
    for r in range(car_rows):
        aisles.append({
            "x_m": 0,
            "y_m": (4.0 if basement else 0) + r * row_height_m + CAR_SPACE["length_m"],
            "w_m": plot_width_m,
            "h_m": DRIVE_AISLE_WIDTH_M,
        })

    return {
        "car_spaces":    car_spaces,
        "bike_spaces":   bike_spaces,
        "aisles":        aisles,
        "cars_per_row":  cars_per_row,
        "bike_y_start":  bike_y_start,
        "total_width_m": plot_width_m,
        "total_height_m": max(total_height, 10),
        "has_ramp":      basement,
        "ramp": {
            "x_m": plot_width_m - 4.5,
            "y_m": 0,
            "w_m": 4.0,
            "h_m": 3.5,
        } if basement else None,
    }


def build_warnings(cars, bikes, basement, stilt, needed_sqm, available_sqm):
    warnings = []
    if cars > 20 and not basement:
        warnings.append("More than 20 car spaces — consider basement parking to free up ground level")
    if basement and needed_sqm > available_sqm * 0.5:
        warnings.append("Parking area exceeds 50% of plot — structural design needs careful planning")
    if not basement and not stilt:
        warnings.append("Surface parking reduces buildable ground floor area significantly")
    if cars > 0:
        warnings.append("Adequate turning radius (4.5m min) must be maintained at entry/exit — NBC 2016")
    return warnings