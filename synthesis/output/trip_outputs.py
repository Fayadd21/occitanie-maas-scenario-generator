from __future__ import annotations

import gzip
import os
import shutil

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


def merge_mode_choice(context, df_trips: pd.DataFrame, output_path: str, output_prefix: str) -> pd.DataFrame:
    trips_path = f"{context.path('matsim.simulation.prepare')}/mode_choice/output_trips.csv"
    if not os.path.exists(trips_path):
        trips_path = f"{context.path('matsim.simulation.prepare')}/mode_choice/output_trips.csv.gz"

    df_mode_choice = pd.read_csv(trips_path, delimiter=";").rename(columns={"person_trip_id": "trip_index"})
    columns_to_keep = ["person_id", "trip_index"]
    columns_to_keep.extend([c for c in df_trips.columns if c not in df_mode_choice.columns])
    df_trips = df_trips[columns_to_keep]
    df_trips = pd.merge(
        df_trips,
        df_mode_choice,
        on=["person_id", "trip_index"],
        how="left",
        validate="one_to_one",
    )

    for mode_file, output_name in (("output_pt_legs.csv", "pt_legs.csv"), ("output_legs.csv", "legs.csv")):
        source_path = f"{context.path('matsim.simulation.prepare')}/mode_choice/{mode_file}"
        if not os.path.exists(source_path):
            source_path = f"{source_path}.gz"
        output_target = f"{output_path}/{output_prefix}{output_name}"
        if source_path.endswith(".gz"):
            with gzip.open(source_path, "rb") as f_in:
                with open(output_target, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
        else:
            shutil.copy(source_path, output_target)

    return df_trips


def write_trips(df_trips: pd.DataFrame, output_path: str, output_prefix: str, output_formats: list[str]) -> None:
    write_table(df_trips, output_path, output_prefix, "trips", output_formats)
