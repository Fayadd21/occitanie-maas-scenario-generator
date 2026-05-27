from __future__ import annotations

import geopandas as gpd
import numpy as np
import pandas as pd

from synthesis.output_resources import _load_population_filter_area


def _clamp_outskirts_bias(outskirts_bias: float) -> float:
    return max(0.0, min(1.0, float(outskirts_bias)))


def _household_visit_order(
    household_ids: list,
    dist: pd.Series,
    size_ranking: pd.Series | None,
    *,
    edge: bool,
    random_seed: int | None,
    prefer_size_on_edge: bool = False,
) -> list:
    if not household_ids:
        return []
    frame = pd.DataFrame(
        {
            "dist": dist.reindex(household_ids).astype(float),
            "size_rank": size_ranking.reindex(household_ids).fillna(0.0).astype(float)
            if size_ranking is not None
            else 0.0,
        },
        index=household_ids,
    )
    if edge:
        if prefer_size_on_edge:
            return frame.sort_values(by=["size_rank", "dist"], ascending=[False, True]).index.tolist()
        return frame.sort_values(by=["dist", "size_rank"], ascending=[True, False]).index.tolist()
    if random_seed is not None:
        rng = np.random.default_rng(random_seed)
        frame["noise"] = rng.random(len(frame))
        return frame.sort_values(by=["size_rank", "noise"], ascending=[False, False]).index.tolist()
    return frame.sort_values(by="size_rank", ascending=False).index.tolist()


def _select_households_edge_then_random(
    household_sizes: pd.Series,
    *,
    target_households: int | None,
    target_population: int | None,
    household_scores: pd.Series,
    outskirts_bias: float,
    random_seed: int,
    random_visit_order: list | None = None,
    size_ranking: pd.Series | None = None,
) -> set:
    sizes = household_sizes.astype(int)
    if len(sizes) == 0:
        return set()

    bias = _clamp_outskirts_bias(outskirts_bias)
    max_population = int(target_population) if target_population is not None and target_population > 0 else None
    max_households = int(target_households) if target_households is not None and target_households > 0 else None

    pool_population = int(sizes.sum())
    if max_households is None and (max_population is None or pool_population <= max_population):
        return set(sizes.index.tolist())
    if max_population is None and len(sizes) <= max_households:
        return set(sizes.index.tolist())
    if (
        max_households is not None
        and max_population is not None
        and len(sizes) <= max_households
        and pool_population <= max_population
    ):
        return set(sizes.index.tolist())

    edge_pop_goal = int(round(max_population * bias)) if max_population is not None else None
    if edge_pop_goal is not None and max_population is not None:
        edge_pop_goal = min(edge_pop_goal, max_population)
    edge_household_goal = None
    if max_population is None and max_households is not None:
        edge_household_goal = int(round(max_households * bias))
        edge_household_goal = min(edge_household_goal, max_households)

    dist = household_scores.reindex(sizes.index).fillna(float("inf")).astype(float)
    prefer_size_on_edge = False
    if (
        size_ranking is not None
        and max_population is not None
        and max_households is not None
        and max_households > 0
        and (max_population / max_households) <= 1.25
    ):
        prefer_size_on_edge = True
    edge_visit = _household_visit_order(
        sizes.index.tolist(),
        dist,
        size_ranking,
        edge=True,
        random_seed=None,
        prefer_size_on_edge=prefer_size_on_edge,
    )

    selected: list = []
    current_population = 0
    edge_population = 0

    def overall_caps_reached() -> bool:
        if max_households is not None and len(selected) >= max_households:
            return True
        if max_population is not None and current_population >= max_population:
            return True
        return False

    def edge_goals_reached() -> bool:
        if edge_pop_goal is not None:
            return edge_population >= edge_pop_goal
        if edge_household_goal is not None:
            return len(selected) >= edge_household_goal
        return False

    for household_id in edge_visit:
        if edge_goals_reached() or overall_caps_reached():
            break
        household_size = int(sizes[household_id])
        if max_population is not None and current_population + household_size > max_population:
            continue
        if max_households is not None and len(selected) >= max_households:
            break
        selected.append(household_id)
        current_population += household_size
        edge_population += household_size

    remaining = [household_id for household_id in sizes.index if household_id not in selected]
    if random_visit_order is not None:
        remaining_set = set(remaining)
        visit_rest = [household_id for household_id in random_visit_order if household_id in remaining_set]
        for household_id in remaining:
            if household_id not in visit_rest:
                visit_rest.append(household_id)
    else:
        visit_rest = _household_visit_order(
            remaining,
            dist,
            size_ranking,
            edge=False,
            random_seed=random_seed,
        )

    for household_id in visit_rest:
        if overall_caps_reached():
            break
        household_size = int(sizes[household_id])
        if max_population is not None and current_population + household_size > max_population:
            continue
        if max_households is not None and len(selected) >= max_households:
            break
        selected.append(household_id)
        current_population += household_size

    if not selected and len(sizes) > 0:
        return {sizes.sort_values().index[0]}
    return set(selected)


def _choose_households_for_targets(
    household_sizes: pd.Series,
    target_households: int,
    target_population: int | None,
    household_scores: pd.Series | None = None,
    outskirts_bias: float = 0.0,
    random_seed: int = 42,
) -> set:
    if target_households <= 0 or len(household_sizes) == 0:
        return set()
    if len(household_sizes) <= target_households and (
        target_population is None or int(household_sizes.sum()) <= int(target_population)
    ):
        return set(household_sizes.index.tolist())

    size_ranking = None
    if target_population is not None and target_population > 0:
        target_avg = float(target_population) / float(target_households)
        size_ranking = -((household_sizes.astype(float) - target_avg).abs())

    if household_scores is not None and outskirts_bias > 0.0:
        return _select_households_edge_then_random(
            household_sizes,
            target_households=target_households,
            target_population=target_population,
            household_scores=household_scores,
            outskirts_bias=outskirts_bias,
            random_seed=random_seed,
            size_ranking=size_ranking,
        )

    rng = np.random.default_rng(random_seed)
    if target_population is not None and target_population > 0:
        return _select_households_edge_then_random(
            household_sizes,
            target_households=target_households,
            target_population=target_population,
            household_scores=pd.Series(0.0, index=household_sizes.index),
            outskirts_bias=0.0,
            random_seed=random_seed,
            size_ranking=size_ranking,
        )

    selected_idx = rng.choice(len(household_sizes), size=target_households, replace=False)
    return set(household_sizes.index[selected_idx].tolist())


def _choose_households_for_dual_targets(
    household_sizes: pd.Series,
    target_households: int,
    target_population: int,
    household_scores: pd.Series | None = None,
    outskirts_bias: float = 0.0,
    random_seed: int = 42,
) -> set:
    if target_households <= 0 or target_population <= 0 or len(household_sizes) == 0:
        return set()

    sizes = household_sizes.astype(int)
    target_avg = float(target_population) / float(target_households)
    size_fit = -((sizes.astype(float) - target_avg).abs())

    if household_scores is not None and outskirts_bias > 0.0:
        return _select_households_edge_then_random(
            household_sizes,
            target_households=target_households,
            target_population=target_population,
            household_scores=household_scores,
            outskirts_bias=outskirts_bias,
            random_seed=random_seed,
            size_ranking=size_fit,
        )

    visit_order = _household_visit_order(
        sizes.index.tolist(),
        pd.Series(0.0, index=sizes.index),
        size_fit,
        edge=False,
        random_seed=random_seed,
    )

    selected: list = []
    current_population = 0
    for household_id in visit_order:
        if len(selected) >= target_households:
            break
        household_size = int(sizes[household_id])
        if current_population + household_size > target_population:
            continue
        selected.append(household_id)
        current_population += household_size

    return set(selected)


def _choose_households_for_population_target(
    household_sizes: pd.Series,
    target_population: int,
    household_scores: pd.Series | None = None,
    outskirts_bias: float = 0.0,
    random_seed: int = 42,
) -> set:
    if target_population <= 0 or len(household_sizes) == 0:
        return set()

    sizes = household_sizes.astype(int)
    total_population = int(sizes.sum())
    if total_population <= target_population:
        return set(sizes.index.tolist())

    if household_scores is not None and outskirts_bias > 0.0:
        return _select_households_edge_then_random(
            household_sizes,
            target_households=None,
            target_population=target_population,
            household_scores=household_scores,
            outskirts_bias=outskirts_bias,
            random_seed=random_seed,
        )

    rng = np.random.default_rng(random_seed)
    visit_order = sizes.index.tolist()
    rng.shuffle(visit_order)

    selected: list = []
    current_population = 0
    for household_id in visit_order:
        household_size = int(sizes[household_id])
        if current_population + household_size > target_population:
            continue
        selected.append(household_id)
        current_population += household_size

    if not selected:
        return {sizes.sort_values().index[0]}
    return set(selected)


def apply_population_policy(
    df_persons: pd.DataFrame,
    df_activities: pd.DataFrame,
    df_locations: pd.DataFrame,
    population_filter_geojson: str | None,
    target_population: int | None,
    target_households: int | None,
    allowed_latent_classes: list[str] | None = None,
    outskirts_bias: float = 0.0,
    random_seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, set | None]:
    selected_person_ids = None
    filter_area = _load_population_filter_area(population_filter_geojson)
    household_dist_to_edge: pd.Series | None = None
    if filter_area is not None:
        gdf_home_activities = gpd.GeoDataFrame(
            df_activities[df_activities["purpose"] == "home"][["person_id", "household_id", "geometry"]].copy(),
            geometry="geometry",
            crs=df_locations.crs,
        )
        if gdf_home_activities.crs != filter_area.crs:
            filter_area = filter_area.to_crs(gdf_home_activities.crs)
        gdf_selected = gpd.sjoin(gdf_home_activities, filter_area[["geometry"]], predicate="within", how="inner")
        if len(gdf_selected) > 0:
            filtered_geom = filter_area.unary_union
            dist_to_edge = gdf_selected.geometry.distance(filtered_geom.boundary)
            gdf_selected = gdf_selected.copy()
            gdf_selected["dist_to_edge"] = dist_to_edge.astype(float)
            household_dist_to_edge = (
                gdf_selected.groupby("household_id", observed=False)["dist_to_edge"].mean().astype(float)
            )
        selected_person_ids = set(gdf_selected["person_id"].unique())
        df_persons = df_persons[df_persons["person_id"].isin(selected_person_ids)].copy()
        df_activities = df_activities[df_activities["person_id"].isin(selected_person_ids)].copy()

    if allowed_latent_classes and "latent_class" in df_persons.columns:
        allowed = {str(c).strip() for c in allowed_latent_classes if str(c).strip()}
        if allowed:
            df_persons = df_persons[df_persons["latent_class"].astype(str).isin(allowed)].copy()
            selected_person_ids = set(df_persons["person_id"].unique())
            df_activities = df_activities[df_activities["person_id"].isin(selected_person_ids)].copy()

    selected_household_ids: set | None = None

    if target_households is not None and "household_id" in df_persons.columns:
        target_households = int(target_households)
        household_sizes = (
            df_persons[["household_id", "person_id"]]
            .dropna(subset=["household_id"])
            .groupby("household_id")["person_id"]
            .nunique()
        )
        if target_population is not None and int(target_population) > 0:
            selected_household_ids = _choose_households_for_dual_targets(
                household_sizes,
                target_households=target_households,
                target_population=int(target_population),
                household_scores=household_dist_to_edge,
                outskirts_bias=max(0.0, min(1.0, float(outskirts_bias))),
                random_seed=int(random_seed),
            )
        else:
            selected_household_ids = _choose_households_for_targets(
                household_sizes,
                target_households=target_households,
                target_population=None,
                household_scores=household_dist_to_edge,
                outskirts_bias=max(0.0, min(1.0, float(outskirts_bias))),
                random_seed=int(random_seed),
            )
        if selected_household_ids:
            df_persons = df_persons[df_persons["household_id"].isin(selected_household_ids)].copy()

    if target_population is not None and "household_id" in df_persons.columns and target_households is None:
        target_population = int(target_population)
        household_sizes = (
            df_persons[["household_id", "person_id"]]
            .dropna(subset=["household_id"])
            .groupby("household_id")["person_id"]
            .nunique()
        )
        selected_household_ids = _choose_households_for_population_target(
            household_sizes,
            target_population=target_population,
            household_scores=household_dist_to_edge,
            outskirts_bias=max(0.0, min(1.0, float(outskirts_bias))),
            random_seed=int(random_seed),
        )
        if selected_household_ids:
            df_persons = df_persons[df_persons["household_id"].isin(selected_household_ids)].copy()

    if "person_id" in df_activities.columns and "person_id" in df_persons.columns:
        selected_person_ids = set(df_persons["person_id"].unique())
        df_activities = df_activities[df_activities["person_id"].isin(selected_person_ids)].copy()

    return df_persons, df_activities, selected_person_ids
