from __future__ import annotations

import pandas as pd

from synthesis.output.io import write_table


def prepare_trips(context, selected_person_ids: set | None) -> pd.DataFrame:
    df_trips = context.stage("synthesis.population.trips").rename(
        columns={"is_first_trip": "is_first", "is_last_trip": "is_last"}
    )
    df_trips["preceding_activity_index"] = df_trips["trip_index"]
    df_trips["following_activity_index"] = df_trips["trip_index"] + 1
    df_trips = df_trips[
        [
            "person_id",
            "trip_index",
            "preceding_activity_index",
            "following_activity_index",
            "departure_time",
            "arrival_time",
            "preceding_purpose",
            "following_purpose",
            "is_first",
            "is_last",
        ]
    ]
    if selected_person_ids is not None:
        df_trips = df_trips[df_trips["person_id"].isin(selected_person_ids)].copy()
    return df_trips


def write_trips(df_trips: pd.DataFrame, output_path: str, output_prefix: str, output_formats: list[str]) -> None:
    write_table(df_trips, output_path, output_prefix, "trips", output_formats)
