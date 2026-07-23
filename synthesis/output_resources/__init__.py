from __future__ import annotations

from typing import Any

__all__ = [
    "clean_gpkg",
    "_load_bikesharing_stations",
    "_load_gtfs_resources",
    "_load_carsharing_stations",
    "_load_carpooling_stops",
    "_load_taxi_stands",
    "_load_pmr_stands",
    "_load_public_parking",
    "_load_park_and_ride",
    "_load_population_filter_area",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import resources

    return getattr(resources, name)
