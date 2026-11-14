"""Central settings for the MODIS / VIIRS hotspot harmonization pipeline."""

from dataclasses import dataclass, field

# Bounding boxes as (lon_min, lat_min, lon_max, lat_max)
REGIONS = {
    "punjab_pk": (69.3, 27.7, 75.4, 34.1),
    "pakistan": (60.8, 23.6, 77.9, 37.1),
    "argentina": (-73.6, -55.1, -53.6, -21.7),
    "india_nw": (73.8, 27.4, 80.6, 32.8),
    "parana_delta_ar": (-60.9, -34.4, -58.3, -32.6),
    "cordoba_ar": (-65.8, -35.0, -61.7, -29.5),
}

# Earliest dates each platform's FIRMS record can start. The pipeline uses the
# later of this and the first date actually present in your files, and the last
# date in your files as the end. These only tell a true zero (sensor flying, no
# fire) from missing data (sensor not flying).
PLATFORM_START = {
    "Terra": "2000-11-01",
    "Aqua": "2002-07-04",
    "SNPP": "2012-01-20",
    "NOAA20": "2018-04-01",
    "NOAA21": "2023-03-01",
}

SENSOR_OF = {
    "Terra": "MODIS",
    "Aqua": "MODIS",
    "SNPP": "VIIRS",
    "NOAA20": "VIIRS",
    "NOAA21": "VIIRS",
}


@dataclass
class Settings:
    # Analysis grid used for the calendar and the transfer model (degrees)
    grid_deg: float = 0.1
    # Fine grid used to count "unique ~1 km active cells" (degrees)
    dedup_deg: float = 0.01

    # Filtering
    vegetation_only: bool = True  # keep FIRMS type 0 (or missing type, as in NRT)
    modis_min_confidence: int = 30  # MODIS confidence is 0 to 100
    viirs_keep_confidence: tuple = ("n", "h")  # VIIRS l / n / h
    mask_static_sources: bool = True
    static_min_calendar_months: int = 9  # active in at least this many of the 12 calendar months
    static_min_month_fraction: float = 0.30  # and in at least this share of all record months
    static_min_years: int = 3

    # Harmonization
    reference_platform: str = "SNPP"  # harmonized unit: SNPP VIIRS-equivalent detections
    overlap_start: str = "2012-02-01"  # first full SNPP month
    shrinkage_k: float = 20.0  # pseudo-count for cell ratio shrinkage
    # Cell coordinates as model inputs. Off by default: in testing they acted
    # like a stored climatology and pulled quiet years toward the average.
    use_location: bool = False
    # Extra per cell columns you add to the panel, e.g. a MODIS land cover class
    # ("landcover") that describes the fire regime rather than its level.
    extra_features: tuple = ()
    gbm_max_iter: int = 400
    gbm_learning_rate: float = 0.05
    random_state: int = 42

    # Calendar
    baseline_years: tuple | None = None  # e.g. (2003, 2022); None means all years

    extra: dict = field(default_factory=dict)
