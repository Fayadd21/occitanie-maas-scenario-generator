from __future__ import annotations

import geopandas as gpd
import numpy as np
import os
import pandas as pd

from synthesis.output.io import write_table
from synthesis.output.policy import apply_population_policy
from synthesis.output.population_outputs import (
    attach_locations,
    prepare_activities,
    prepare_persons,
    write_activities,
    write_households,
)
from synthesis.output.spatial_outputs import (
    write_activity_geometries,
    write_commutes,
    write_homes,
    write_trip_geometries,
)
from synthesis.output.static_resources_outputs import export_static_resources
from synthesis.output.trip_outputs import merge_mode_choice, prepare_trips, write_trips


def _resolve_baseline_run(context, output_path: str) -> tuple[str | None, str | None]:
    baseline_run_id = context.config("baseline_run_id")
    baseline_run_path_cfg = context.config("baseline_run_path")
    baseline_run_path = None

    if baseline_run_path_cfg:
        baseline_run_path = str(baseline_run_path_cfg)
        if not os.path.isdir(baseline_run_path):
            raise RuntimeError(f"Baseline run directory does not exist: {baseline_run_path}")
        if not baseline_run_id:
            baseline_run_id = os.path.basename(os.path.normpath(baseline_run_path))
    elif baseline_run_id:
        baseline_run_path = os.path.join(output_path, "jobs", str(baseline_run_id))
        if not os.path.isdir(baseline_run_path):
            raise RuntimeError(f"Baseline run directory does not exist: {baseline_run_path}")

    return baseline_run_id, baseline_run_path


def _baseline_file_path(baseline_run_path: str, baseline_run_id: str, suffix: str) -> str:
    path = os.path.join(baseline_run_path, f"{baseline_run_id}_{suffix}")
    if not os.path.exists(path):
        raise RuntimeError(f"Missing baseline {suffix} file: {path}")
    return path


def configure(context):
    context.config("output_path")
    context.config("output_prefix", "ile_de_france_")
    context.config("output_formats", ["csv", "gpkg"])
    context.config("bikesharing_path", "bikesharing_occitanie")
    context.config("gbfs_path", "gbfs")
    context.config("gtfs_path", "gtfs_idf")
    context.config("carsharing_path", "carsharing_occitanie/station_information_carsharing_citiz_occitanie.json")
    context.config("carpooling_path", "carpooling_occitanie/infrastructures-de-covoiturage-en-occitanie-v2.csv")
    context.config("taxi_data_paths", ["taxi_pmr_occitanie/taxis_toulouse.json", "taxi_pmr_occitanie/pmr_taxis_delivery_Montpellier.json"])
    context.config("pmr_data_paths", ["taxi_pmr_occitanie/pmr_Toulouse.json", "taxi_pmr_occitanie/pmr_taxis_delivery_Montpellier.json"])
    context.config("parking_data_paths", [
        "parking_occitanie/etat-des-parkings-en-temps-reel-ville-de-nimes.csv",
        "parking_occitanie/VilleMTP_MTP_ParkingOuv-montpellier.csv",
        "parking_occitanie/parcs-de-stationnement-toulouse.csv",
    ])
    context.config("pnr_data_paths", [])
    context.config("population_filter_geojson", None)
    context.config("target_population", None)
    context.config("target_households", None)
    context.config("allowed_latent_classes", None)
    context.config("outskirts_bias", 0.0)
    context.config("export_static_resources", True)
    context.config("export_trips", True)
    context.config("sampling_rate")
    context.config("extra_enriched_attributes", [])
    context.config("baseline_run_id", None)
    context.config("baseline_run_path", None)
    context.config("profiles_path", None)
    context.config("assign_latent_classes", False)

    baseline_mode = bool(context.config("baseline_run_path")) or bool(context.config("baseline_run_id"))
    if not baseline_mode:
        context.stage("synthesis.population.enriched")
        context.stage("synthesis.population.activities")
        context.stage("synthesis.population.trips")
        context.stage("synthesis.vehicles.vehicles")
        context.stage("synthesis.population.spatial.locations")

    if context.config("export_static_resources"):
        context.stage("data.gtfs.cleaned")

    context.stage("documentation.meta_output")

    if context.config("mode_choice", False):
        context.stage("matsim.simulation.prepare")


def validate(context):
    if not os.path.isdir(context.config("output_path")):
        raise RuntimeError("Output directory must exist: %s" % context.config("output_path"))


def execute(context):
    output_path = context.config("output_path")
    output_prefix = context.config("output_prefix")
    output_formats = context.config("output_formats")

    baseline_run_id, baseline_run_path = _resolve_baseline_run(context, output_path)
    df_households_for_profiles = None

    if baseline_run_path is None:
        df_persons = prepare_persons(context, output_path, output_prefix, output_formats)
        df_activities = prepare_activities(context, df_persons)
        df_activities, df_locations = attach_locations(context, df_activities)
    else:
        assert baseline_run_id is not None
        persons_path = _baseline_file_path(baseline_run_path, baseline_run_id, "persons.csv")
        activities_path = _baseline_file_path(baseline_run_path, baseline_run_id, "activities.csv")
        activities_gpkg_path = _baseline_file_path(baseline_run_path, baseline_run_id, "activities.gpkg")
        households_path = _baseline_file_path(baseline_run_path, baseline_run_id, "households.csv")

        df_persons = pd.read_csv(persons_path, sep=";")
        df_activities = pd.read_csv(activities_path, sep=";")
        df_households_for_profiles = pd.read_csv(households_path, sep=";")
        gdf_activities = gpd.read_file(activities_gpkg_path)
        keep_cols = [
            c
            for c in ["person_id", "activity_index", "iris_id", "commune_id", "departement_id", "region_id", "geometry"]
            if c in gdf_activities.columns
        ]
        df_locations = gdf_activities[keep_cols].copy()
        geo_cols = [c for c in ["person_id", "activity_index", "geometry"] if c in df_locations.columns]
        if len(geo_cols) == 3:
            df_activities = pd.merge(
                df_activities,
                df_locations[geo_cols],
                on=["person_id", "activity_index"],
                how="left",
            )

    if context.config("assign_latent_classes"):
        from synthesis.profiles.loader import assign_latent_classes

        df_persons = assign_latent_classes(
            df_persons,
            context.config("profiles_path"),
            df_households=df_households_for_profiles,
            random_seed=context.config("random_seed"),
        )

    df_persons, df_activities, selected_person_ids = apply_population_policy(
        df_persons,
        df_activities,
        df_locations,
        context.config("population_filter_geojson"),
        context.config("target_population"),
        context.config("target_households"),
        context.config("allowed_latent_classes"),
        context.config("outskirts_bias"),
        context.config("random_seed"),
    )
    write_table(df_persons, output_path, output_prefix, "persons", output_formats)
    write_activities(df_activities, output_path, output_prefix, output_formats)
    if baseline_run_path is None:
        write_households(
            context,
            df_activities,
            df_persons,
            selected_person_ids,
            output_path,
            output_prefix,
            output_formats,
        )
    else:
        assert baseline_run_id is not None
        households_path = _baseline_file_path(baseline_run_path, baseline_run_id, "households.csv")
        df_households = df_households_for_profiles if df_households_for_profiles is not None else pd.read_csv(households_path, sep=";")
        selected_household_ids = set(df_persons["household_id"].astype(str).unique())
        if "household_id" in df_households.columns:
            df_households = df_households[df_households["household_id"].astype(str).isin(selected_household_ids)].copy()
        write_table(df_households, output_path, output_prefix, "households", output_formats)

    df_trips = pd.DataFrame()
    if context.config("export_trips"):
        if baseline_run_path is None:
            df_trips = prepare_trips(context, selected_person_ids)
        else:
            assert baseline_run_id is not None
            trips_path = _baseline_file_path(baseline_run_path, baseline_run_id, "trips.csv")
            df_trips = pd.read_csv(trips_path, sep=";")
            if selected_person_ids is not None and "person_id" in df_trips.columns:
                df_trips = df_trips[df_trips["person_id"].isin(selected_person_ids)].copy()
        if context.config("mode_choice"):
            df_trips = merge_mode_choice(context, df_trips, output_path, output_prefix)
            assert not np.any(df_trips["mode"].isna())
        write_trips(df_trips, output_path, output_prefix, output_formats)

    if baseline_run_path is None:
        df_vehicle_types, df_vehicles = context.stage("synthesis.vehicles.vehicles")
    else:
        assert baseline_run_id is not None
        vehicle_types_path = _baseline_file_path(baseline_run_path, baseline_run_id, "vehicle_types.csv")
        vehicles_path = _baseline_file_path(baseline_run_path, baseline_run_id, "vehicles.csv")
        df_vehicle_types = pd.read_csv(vehicle_types_path, sep=";")
        df_vehicles = pd.read_csv(vehicles_path, sep=";")
    if selected_person_ids is not None and "person_id" in df_vehicles.columns:
        df_vehicles = df_vehicles[df_vehicles["person_id"].isin(selected_person_ids)].copy()
    write_table(df_vehicle_types, output_path, output_prefix, "vehicle_types", output_formats)
    write_table(df_vehicles, output_path, output_prefix, "vehicles", output_formats)

    if context.config("export_static_resources"):
        export_static_resources(
            context,
            output_path,
            output_prefix,
            output_formats,
            context.config("bikesharing_path"),
            context.config("gbfs_path"),
            context.config("gtfs_path"),
            context.config("carsharing_path"),
            context.config("carpooling_path"),
            context.config("taxi_data_paths"),
            context.config("pmr_data_paths"),
            context.config("parking_data_paths"),
            context.config("pnr_data_paths"),
        )

    df_spatial = write_activity_geometries(df_activities, df_locations, output_path, output_prefix, output_formats)
    write_homes(df_spatial, output_path, output_prefix, output_formats)
    write_commutes(df_spatial, df_locations, output_path, output_prefix, output_formats)
    if context.config("export_trips"):
        write_trip_geometries(df_trips, df_locations, output_path, output_prefix, output_formats)
