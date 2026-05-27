from __future__ import annotations

import pandas as pd

from synthesis.output.io import write_table


def prepare_persons(context, output_path: str, output_prefix: str, output_formats: list[str]) -> pd.DataFrame:
    df_persons = context.stage("synthesis.population.enriched").rename(
        columns={"has_license": "has_driving_license"}
    )
    columns = [
        "person_id",
        "household_id",
        "age",
        "employed",
        "sex",
        "socioprofessional_class",
        "has_driving_license",
        "has_pt_subscription",
        "census_person_id",
        "hts_id",
    ] + context.config("extra_enriched_attributes")
    df_persons = df_persons[columns]
    write_table(df_persons, output_path, output_prefix, "persons", output_formats)
    return df_persons


def prepare_activities(context, df_persons: pd.DataFrame) -> pd.DataFrame:
    df_activities = context.stage("synthesis.population.activities").rename(
        columns={"trip_index": "following_trip_index"}
    )
    df_activities = pd.merge(df_activities, df_persons[["person_id", "household_id"]], on="person_id")
    df_activities["preceding_trip_index"] = df_activities["following_trip_index"].shift(1)
    df_activities.loc[df_activities["is_first"], "preceding_trip_index"] = -1
    df_activities["preceding_trip_index"] = df_activities["preceding_trip_index"].astype(int)
    return df_activities


def attach_locations(context, df_activities: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_locations = context.stage("synthesis.population.spatial.locations")[
        ["person_id", "iris_id", "commune_id", "departement_id", "region_id", "activity_index", "geometry"]
    ]
    df_activities = pd.merge(
        df_activities,
        df_locations[
            ["person_id", "iris_id", "commune_id", "departement_id", "region_id", "activity_index", "geometry"]
        ],
        how="left",
        on=["person_id", "activity_index"],
    )
    return df_activities, df_locations


def write_activities(df_activities: pd.DataFrame, output_path: str, output_prefix: str, output_formats: list[str]) -> pd.DataFrame:
    output_df = df_activities[
        [
            "person_id",
            "household_id",
            "activity_index",
            "iris_id",
            "commune_id",
            "departement_id",
            "region_id",
            "preceding_trip_index",
            "following_trip_index",
            "purpose",
            "start_time",
            "end_time",
            "is_first",
            "is_last",
        ]
    ]
    write_table(output_df, output_path, output_prefix, "activities", output_formats)
    return output_df


def write_households(
    context,
    df_activities: pd.DataFrame,
    df_persons: pd.DataFrame,
    selected_person_ids: set | None,
    output_path: str,
    output_prefix: str,
    output_formats: list[str],
) -> pd.DataFrame:
    df_households = context.stage("synthesis.population.enriched").rename(
        columns={"household_income": "income"}
    ).drop_duplicates("household_id")
    df_households = pd.merge(
        df_households,
        df_activities[df_activities["purpose"] == "home"][
            ["household_id", "iris_id", "commune_id", "departement_id", "region_id"]
        ].drop_duplicates("household_id"),
        how="left",
    )
    df_households = df_households[
        [
            "household_id",
            "iris_id",
            "commune_id",
            "departement_id",
            "region_id",
            "car_availability",
            "bike_availability",
            "use_motorcycle",
            "number_of_vehicles",
            "number_of_bikes",
            "income",
            "census_household_id",
        ]
    ]
    if selected_person_ids is not None:
        selected_household_ids = set(df_persons["household_id"].astype(str).unique())
        df_households = df_households[df_households["household_id"].astype(str).isin(selected_household_ids)].copy()
    write_table(df_households, output_path, output_prefix, "households", output_formats)
    return df_households
