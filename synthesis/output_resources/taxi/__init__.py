"""Taxi stands, demand zones, and fleet generation for scenario export."""

from __future__ import annotations

from synthesis.output_resources.taxi.demand import (
    TaxiDemandConfig,
    demand_zones_dataframe,
    load_taxi_demand_config,
    sample_booking_location,
    sample_demand_zone,
)
from synthesis.output_resources.taxi.fleet import (
    TaxiFleetConfig,
    WEEKDAYS,
    generate_taxi_operator_payload,
    load_taxi_fleet_config,
    load_taxi_stands_csv,
    write_taxi_fleet_run,
)
from synthesis.output_resources.taxi.stands import (
    classify_zone_type,
    finalize_taxi_stands_dataframe,
    taxi_stand_points_from_dataframe,
    trip_duration_minutes,
    zone_weight,
)
from synthesis.output_resources.taxi.stands_loader import (
    TAXI_CITY_PROFILES,
    load_raw_taxi_stand_records,
    load_taxi_stands_dataframe,
    summarize_taxi_stand_sources,
)

__all__ = [
    "TAXI_CITY_PROFILES",
    "TaxiDemandConfig",
    "TaxiFleetConfig",
    "WEEKDAYS",
    "classify_zone_type",
    "demand_zones_dataframe",
    "finalize_taxi_stands_dataframe",
    "generate_taxi_operator_payload",
    "load_raw_taxi_stand_records",
    "load_taxi_demand_config",
    "load_taxi_fleet_config",
    "load_taxi_stands_csv",
    "load_taxi_stands_dataframe",
    "sample_booking_location",
    "sample_demand_zone",
    "summarize_taxi_stand_sources",
    "taxi_stand_points_from_dataframe",
    "trip_duration_minutes",
    "write_taxi_fleet_run",
    "zone_weight",
]
