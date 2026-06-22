from __future__ import annotations

import geopandas as gpd
import os
import pandas as pd

from synthesis.output.baseline_spatial import (
    copy_baseline_spatial_layers,
    load_geometry_for_home_distance,
    needs_geometry_for_profiles,
    spatial_subset_unchanged,
)
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
from synthesis.output.trip_outputs import prepare_trips, write_trips


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
    context.config("constraints_path", None)
    context.config("assign_constraints", False)

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


def validate(context):
    if not os.path.isdir(context.config("output_path")):
        raise RuntimeError("Output directory must exist: %s" % context.config("output_path"))


def _subset_households_for_persons(
    df_households: pd.DataFrame | None,
    df_persons: pd.DataFrame,
) -> pd.DataFrame | None:
    if df_households is None or "household_id" not in df_persons.columns:
        return df_households
    selected_household_ids = set(df_persons["household_id"].astype(str).unique())
    households = df_households.copy()
    mask = households["household_id"].astype(str).isin(selected_household_ids)
    return households[mask].copy()


def _empty_locations_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["person_id", "activity_index", "iris_id", "commune_id", "departement_id", "region_id", "geometry"]
    )


def _merge_activity_geometry(
    df_activities: pd.DataFrame,
    df_locations: pd.DataFrame,
) -> pd.DataFrame:
    geo_cols = [c for c in ["person_id", "activity_index", "geometry"] if c in df_locations.columns]
    if len(geo_cols) != 3:
        return df_activities
    return pd.merge(
        df_activities,
        df_locations[geo_cols],
        on=["person_id", "activity_index"],
        how="left",
    )


def _load_baseline_geometry(
    activities_gpkg_path: str,
    person_ids: set | None = None,
) -> pd.DataFrame:
    gdf_activities = gpd.read_file(activities_gpkg_path)
    if person_ids is not None:
        gdf_activities = gdf_activities[gdf_activities["person_id"].isin(person_ids)].copy()
    keep_cols = [
        c
        for c in ["person_id", "activity_index", "iris_id", "commune_id", "departement_id", "region_id", "geometry"]
        if c in gdf_activities.columns
    ]
    return gdf_activities[keep_cols].copy()


def _apply_latent_class_assignment(
    df_persons: pd.DataFrame,
    df_activities: pd.DataFrame,
    df_locations: pd.DataFrame,
    *,
    profiles_path: str | None,
    population_filter_geojson: str | None,
    target_population: int | None,
    target_households: int | None,
    allowed_latent_classes: list[str] | None,
    outskirts_bias: float,
    random_seed: int,
    df_households_for_profiles: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame, set | None]:
    from synthesis.profiles.loader import (
        assign_latent_classes,
        latent_class_filter_restricts_pool,
        maybe_attach_home_destination_distance,
    )

    restricts_pool = latent_class_filter_restricts_pool(allowed_latent_classes, profiles_path)

    if restricts_pool:
        df_persons, df_activities, _ = apply_population_policy(
            df_persons,
            df_activities,
            df_locations,
            population_filter_geojson,
            None,
            None,
            None,
            0.0,
            random_seed,
        )
        households_for_assignment = _subset_households_for_persons(df_households_for_profiles, df_persons)
        df_persons = maybe_attach_home_destination_distance(df_persons, df_activities, profiles_path)
        df_persons = assign_latent_classes(
            df_persons,
            profiles_path,
            df_households=households_for_assignment,
            random_seed=random_seed,
        )

    df_persons, df_activities, selected_person_ids = apply_population_policy(
        df_persons,
        df_activities,
        df_locations,
        population_filter_geojson,
        target_population,
        target_households,
        allowed_latent_classes if restricts_pool else None,
        outskirts_bias,
        random_seed,
    )

    if not restricts_pool:
        households_for_assignment = _subset_households_for_persons(df_households_for_profiles, df_persons)
        df_persons = maybe_attach_home_destination_distance(df_persons, df_activities, profiles_path)
        df_persons = assign_latent_classes(
            df_persons,
            profiles_path,
            df_households=households_for_assignment,
            random_seed=random_seed,
        )
        if selected_person_ids is None:
            selected_person_ids = set(df_persons["person_id"].unique())

    return df_persons, df_activities, selected_person_ids


def execute(context):
    output_path = context.config("output_path")
    output_prefix = context.config("output_prefix")
    output_formats = context.config("output_formats")

    baseline_run_id, baseline_run_path = _resolve_baseline_run(context, output_path)
    df_households_for_profiles = None
    selected_person_ids = None
    population_filter_geojson = context.config("population_filter_geojson")
    assign_latent_classes_enabled = context.config("assign_latent_classes")
    profiles_path = context.config("profiles_path")
    random_seed = context.config("random_seed")
    target_population = context.config("target_population")
    target_households = context.config("target_households")
    target_already_filtered = False
    prefilter_person_ids = None
    initial_person_count = None
    initial_activity_count = None
    activities_gpkg_path = None

    if baseline_run_path is None:
        df_persons = prepare_persons(context, output_path, output_prefix, output_formats)
        df_activities = prepare_activities(context, df_persons)
        df_activities, df_locations = attach_locations(context, df_activities)
        if profiles_path:
            from synthesis.profiles.loader import maybe_attach_home_destination_distance

            df_persons = maybe_attach_home_destination_distance(df_persons, df_activities, profiles_path)
    else:
        assert baseline_run_id is not None
        persons_path = _baseline_file_path(baseline_run_path, baseline_run_id, "persons.csv")
        activities_path = _baseline_file_path(baseline_run_path, baseline_run_id, "activities.csv")
        activities_gpkg_path = _baseline_file_path(baseline_run_path, baseline_run_id, "activities.gpkg")
        households_path = _baseline_file_path(baseline_run_path, baseline_run_id, "households.csv")

        df_persons = pd.read_csv(persons_path, sep=";")
        df_activities = pd.read_csv(activities_path, sep=";")
        df_households_for_profiles = pd.read_csv(households_path, sep=";")
        initial_person_count = len(df_persons)
        initial_activity_count = len(df_activities)
        df_locations = _empty_locations_frame()

        if (
            assign_latent_classes_enabled
            and not population_filter_geojson
            and target_population is not None
        ):
            df_persons, df_activities, _ = apply_population_policy(
                df_persons,
                df_activities,
                df_locations,
                None,
                target_population,
                target_households,
                None,
                context.config("outskirts_bias"),
                random_seed,
            )
            target_already_filtered = True
            prefilter_person_ids = set(df_persons["person_id"].unique())
            if prefilter_person_ids:
                df_activities = df_activities[df_activities["person_id"].isin(prefilter_person_ids)].copy()

        if (
            population_filter_geojson
            or needs_geometry_for_profiles(df_persons, assign_latent_classes_enabled, profiles_path)
        ):
            if population_filter_geojson:
                profile_geometry = _load_baseline_geometry(activities_gpkg_path, prefilter_person_ids)
            else:
                profile_geometry = load_geometry_for_home_distance(activities_gpkg_path, prefilter_person_ids)
            df_activities = _merge_activity_geometry(df_activities, profile_geometry)
            if population_filter_geojson:
                import geopandas as gpd

                if isinstance(profile_geometry, gpd.GeoDataFrame):
                    df_locations = profile_geometry.copy()
                else:
                    df_locations = gpd.GeoDataFrame(
                        profile_geometry,
                        geometry="geometry",
                        crs="EPSG:4326",
                    )

    allowed_latent_classes = context.config("allowed_latent_classes")

    if assign_latent_classes_enabled:
        df_persons, df_activities, selected_person_ids = _apply_latent_class_assignment(
            df_persons,
            df_activities,
            df_locations,
            profiles_path=profiles_path,
            population_filter_geojson=population_filter_geojson,
            target_population=None if target_already_filtered else target_population,
            target_households=None if target_already_filtered else target_households,
            allowed_latent_classes=allowed_latent_classes,
            outskirts_bias=context.config("outskirts_bias"),
            random_seed=random_seed,
            df_households_for_profiles=df_households_for_profiles,
        )
    else:
        df_persons, df_activities, selected_person_ids = apply_population_policy(
            df_persons,
            df_activities,
            df_locations,
            population_filter_geojson,
            target_population,
            target_households,
            allowed_latent_classes,
            context.config("outskirts_bias"),
            random_seed,
        )
        if prefilter_person_ids is not None and selected_person_ids is not None:
            df_locations = df_locations[df_locations["person_id"].isin(selected_person_ids)].copy()
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

    reuse_baseline_spatial = spatial_subset_unchanged(
        baseline_mode=baseline_run_path is not None,
        population_filter_geojson=population_filter_geojson,
        initial_person_count=initial_person_count,
        initial_activity_count=initial_activity_count,
        df_persons=df_persons,
        df_activities=df_activities,
    )
    if reuse_baseline_spatial:
        assert baseline_run_id is not None and baseline_run_path is not None
        copy_baseline_spatial_layers(
            baseline_run_path,
            baseline_run_id,
            output_path,
            output_prefix,
            output_formats,
        )
    else:
        if baseline_run_path is not None:
            assert baseline_run_id is not None and activities_gpkg_path is not None
            geometry_person_ids = selected_person_ids or prefilter_person_ids
            df_locations = _load_baseline_geometry(activities_gpkg_path, geometry_person_ids)
            df_activities = _merge_activity_geometry(
                df_activities.drop(columns=["geometry"], errors="ignore"),
                df_locations,
            )
        df_spatial = write_activity_geometries(df_activities, df_locations, output_path, output_prefix, output_formats)
        write_homes(df_spatial, output_path, output_prefix, output_formats)
        write_commutes(df_spatial, df_locations, output_path, output_prefix, output_formats)
    if context.config("export_trips"):
        write_trip_geometries(df_trips, df_locations, output_path, output_prefix, output_formats)
