import glob
import json
import math
import os
import re
import sqlite3
import statistics
import zipfile
import hashlib
import unicodedata

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

OCCITANIE_DEPARTMENTS = {"09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"}


def clean_gpkg(path):
    """
    Make GPKG files time and OS independent.
    """
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    for table_name, min_x, min_y, max_x, max_y in cur.execute(
        "SELECT table_name, min_x, min_y, max_x, max_y FROM gpkg_contents"
    ):
        if None in (min_x, min_y, max_x, max_y):
            cur.execute(
                "UPDATE gpkg_contents "
                + "SET last_change='2000-01-01T00:00:00Z' "
                + "WHERE table_name=?",
                (table_name,),
            )
            continue
        cur.execute(
            "UPDATE gpkg_contents "
            + "SET last_change='2000-01-01T00:00:00Z', min_x=?, min_y=?, max_x=?, max_y=? "
            + "WHERE table_name=?",
            (math.floor(min_x), math.floor(min_y), math.ceil(max_x), math.ceil(max_y), table_name),
        )
    conn.commit()
    conn.close()


def _normalize_gbfs_localized_text(value, preferred_languages=("fr", "en")):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        return None
    if isinstance(value, (list, tuple)):
        by_lang = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            lang = str(item.get("language") or "").lower()
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                by_lang[lang] = text.strip()
        for lang in preferred_languages:
            candidate = by_lang.get(str(lang).lower())
            if candidate:
                return candidate
        if by_lang:
            return next(iter(by_lang.values()))
        return None
    text = str(value).strip()
    return text or None


def _extract_bikesharing_operator(system_path):
    if not os.path.exists(system_path):
        return None

    with open(system_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    data = payload.get("data", payload)
    if not isinstance(data, dict):
        return None

    for key in ("name", "operator", "short_name", "system_id"):
        value = data.get(key)
        normalized = _normalize_gbfs_localized_text(value)
        if normalized:
            return normalized
    return None


def _extract_lat_lon(properties):
    if isinstance(properties, dict):
        gp = properties.get("geo_point_2d")
        if isinstance(gp, dict) and "lat" in gp and "lon" in gp:
            return gp.get("lat"), gp.get("lon")
        if "coord_y" in properties and "coord_x" in properties:
            return properties.get("coord_y"), properties.get("coord_x")
    return None, None


def _read_gtfs_table_from_zip(zip_path, table_name):
    with zipfile.ZipFile(zip_path) as zf:
        if table_name not in zf.namelist():
            return None
        with zf.open(table_name) as f:
            try:
                return pd.read_csv(f)
            except UnicodeDecodeError:
                f.close()
                with zf.open(table_name) as f2:
                    return pd.read_csv(f2, encoding="latin-1")


def _map_gtfs_route_type(route_type):
    mapping = {
        0: "tram",
        1: "metro",
        2: "train",
        3: "bus",
        4: "ferry",
        5: "cable_tram",
        6: "aerial_lift",
        7: "funicular",
        11: "trolleybus",
        12: "monorail",
    }
    try:
        return mapping.get(int(route_type), "other")
    except (ValueError, TypeError):
        return "other"


def _ascii_operator_name(value):
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
    return ascii_text


def _parse_operator_labels(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [_ascii_operator_name(v) for v in parsed if _ascii_operator_name(v)]
    name = _ascii_operator_name(text)
    return [name] if name else []


def _format_operator_label(values) -> str:
    names = sorted({v for v in map(_ascii_operator_name, values) if v})
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return json.dumps(names, ensure_ascii=True)


def _feed_default_operator(df_agency, agency_name_by_id, feed_id):
    if len(agency_name_by_id) == 1:
        return next(iter(agency_name_by_id.values()))
    if df_agency is not None and len(df_agency) == 1 and "agency_name" in df_agency.columns:
        name = _ascii_operator_name(df_agency["agency_name"].iloc[0])
        if name:
            return name
    return _ascii_operator_name(feed_id) or "gtfs"


def _inherit_parent_station_operators(df_stops, df_stops_meta, operator_by_stop, default_operator):
    if df_stops_meta is None or len(df_stops_meta) == 0 or "parent_station" not in df_stops_meta.columns:
        return df_stops

    meta = df_stops_meta[["stop_id", "parent_station"]].copy()
    meta["stop_id"] = meta["stop_id"].astype(str)
    parent_series = meta["parent_station"].astype(str)
    children = meta[parent_series.notna() & (parent_series != "") & (parent_series != "nan")]
    if len(children) == 0:
        return df_stops

    df_stops = df_stops.copy()
    for parent_id, group in children.groupby("parent_station", observed=False):
        labels = []
        for child_id in group["stop_id"].astype(str):
            labels.extend(_parse_operator_labels(operator_by_stop.get(child_id, "")))
        if not labels:
            labels = _parse_operator_labels(default_operator)
        parent_label = _format_operator_label(labels)
        if not parent_label:
            continue
        mask = df_stops["stop_id"].astype(str) == str(parent_id)
        if mask.any():
            df_stops.loc[mask, "operator"] = parent_label
            operator_by_stop[str(parent_id)] = parent_label
    return df_stops


def _parse_parking_coordinates(value):
    if pd.isna(value):
        return None, None

    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and "'lat'" in text and "'lon'" in text:
            try:
                lat_part = text.split("'lat':", 1)[1].split("}", 1)[0]
                lon_part = text.split("'lon':", 1)[1].split(",", 1)[0]
                return float(lat_part.strip()), float(lon_part.strip())
            except (ValueError, IndexError):
                return None, None
        if "," in text:
            parts = [p.strip() for p in text.split(",")]
            if len(parts) >= 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    return None, None
    return None, None


def _snapshot_bikes_from_station_dict(station):
    if not isinstance(station, dict):
        return None
    nb = station.get("num_bikes_available")
    if nb is not None and nb != "":
        try:
            return max(0, int(round(float(nb))))
        except (TypeError, ValueError):
            pass
    vtc = station.get("vehicle_type_capacity")
    if isinstance(vtc, dict):
        vals = []
        for raw in vtc.values():
            try:
                iv = int(round(float(raw)))
            except (TypeError, ValueError):
                continue
            if iv > 0:
                vals.append(iv)
        if vals:
            return max(vals)
    return None


def _resolve_gbfs_json(gbfs_dir, prefix, city_slug):
    exact = os.path.join(gbfs_dir, "%s_%s.json" % (prefix, city_slug))
    if os.path.exists(exact):
        return exact
    want = "%s_%s" % (prefix, city_slug)
    want = want.lower()
    for path in sorted(glob.glob(os.path.join(gbfs_dir, "%s_*.json" % prefix))):
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        if stem == want:
            return path
    return exact


def _mean_num_bikes_from_collected_station_status(data_path, bikesharing_path):
    status_root = os.path.join(data_path, bikesharing_path, "station_status_data")
    if not os.path.isdir(status_root):
        return None
    paths = sorted(glob.glob(os.path.join(status_root, "*", "flat", "station_status_history.csv")))
    parts = []
    for csv_path in paths:
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if "num_bikes_available" not in df.columns:
            continue
        col = pd.to_numeric(df["num_bikes_available"], errors="coerce").dropna()
        if len(col) > 0:
            parts.append(col)
    if not parts:
        return None
    return float(pd.concat(parts, ignore_index=True).mean())


def _per_station_mean_num_bikes_from_histories(data_path, bikesharing_path):
    status_root = os.path.join(data_path, bikesharing_path, "station_status_data")
    out = {}
    if not os.path.isdir(status_root):
        return out
    pattern = os.path.join(status_root, "*", "flat", "station_status_history.csv")
    for csv_path in sorted(glob.glob(pattern)):
        city_folder = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(csv_path))))
        city_key = city_folder.lower()
        try:
            df = pd.read_csv(csv_path)
        except Exception:
            continue
        if "station_id" not in df.columns or "num_bikes_available" not in df.columns:
            continue
        work = df.copy()
        work["station_id"] = work["station_id"].astype(str)
        work["num_bikes_available"] = pd.to_numeric(work["num_bikes_available"], errors="coerce")
        work = work.dropna(subset=["num_bikes_available"])
        if len(work) == 0:
            continue
        grouped = work.groupby("station_id", as_index=True)["num_bikes_available"].mean()
        for sid, val in grouped.items():
            out[(city_key, str(sid))] = float(val)
    return out


def _parse_station_capacity(raw):
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    try:
        cap = int(round(float(raw)))
    except (TypeError, ValueError):
        return None
    return max(0, cap)


def _load_bikesharing_stations(data_path, bikesharing_path, gbfs_path):
    gbfs_dir = os.path.join(data_path, gbfs_path)
    station_files = sorted(glob.glob(os.path.join(gbfs_dir, "station_information_*.json")))
    if not station_files:
        return pd.DataFrame()

    frames = []
    snapshot_samples = []
    for station_file in station_files:
        city = os.path.basename(station_file).replace("station_information_", "").replace(".json", "")
        system_file = _resolve_gbfs_json(gbfs_dir, "system_information", city)
        operator = _extract_bikesharing_operator(system_file)

        with open(station_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        stations = payload.get("data", {}).get("stations", payload.get("stations", []))
        if not stations:
            continue

        for st in stations:
            est = _snapshot_bikes_from_station_dict(st)
            if est is not None:
                snapshot_samples.append(est)

        df = pd.DataFrame(stations)
        if not {"station_id", "lat", "lon"}.issubset(df.columns):
            continue

        keep_cols = [c for c in ("station_id", "name", "lat", "lon", "capacity", "num_bikes_available", "available_bikes") if c in df.columns]
        df = df[keep_cols].copy()
        if "name" in df.columns:
            df["name"] = df["name"].map(_normalize_gbfs_localized_text)
        df["city_id"] = city
        df["operator"] = operator
        df["station_id"] = df["station_id"].astype(str)
        df["city_station_id"] = df["city_id"] + ":" + df["station_id"]
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    out = pd.concat(frames, ignore_index=True)
    per_station_hist = _per_station_mean_num_bikes_from_histories(data_path, bikesharing_path)
    history_mean = _mean_num_bikes_from_collected_station_status(data_path, bikesharing_path)
    if history_mean is not None:
        global_default = max(0, int(round(history_mean)))
    elif snapshot_samples:
        global_default = max(0, int(round(statistics.mean(snapshot_samples))))
    else:
        global_default = 0

    def _row_available_bikes(row):
        key = (str(row["city_id"]).lower(), str(row["station_id"]))
        if key in per_station_hist:
            bikes = max(0, int(round(per_station_hist[key])))
        else:
            bikes = global_default
            for col in ("num_bikes_available", "available_bikes"):
                if col in row.index:
                    raw = row.get(col)
                    if raw is not None and not (isinstance(raw, float) and pd.isna(raw)):
                        try:
                            bikes = max(0, int(round(float(raw))))
                            break
                        except (TypeError, ValueError):
                            pass
        if "capacity" in row.index:
            cap = _parse_station_capacity(row.get("capacity"))
            if cap is not None:
                bikes = min(bikes, cap)
        return bikes

    out["available_bikes"] = out.apply(_row_available_bikes, axis=1)

    return out


def _load_gtfs_resources(gtfs_zip_paths):
    if not gtfs_zip_paths:
        return pd.DataFrame(), pd.DataFrame()

    stops_frames = []
    routes_frames = []

    for zip_path in gtfs_zip_paths:
        feed_id = os.path.basename(zip_path).replace(".zip", "")

        df_agency = _read_gtfs_table_from_zip(zip_path, "agency.txt")
        agency_name_by_id = {}
        fallback_operator = _ascii_operator_name(feed_id) or "gtfs"
        if df_agency is not None and len(df_agency) > 0:
            if {"agency_id", "agency_name"}.issubset(df_agency.columns):
                agency_name_by_id = {
                    str(row["agency_id"]): (_ascii_operator_name(row["agency_name"]) or fallback_operator)
                    for _, row in df_agency[["agency_id", "agency_name"]].dropna().iterrows()
                }
        default_operator = _feed_default_operator(df_agency, agency_name_by_id, feed_id)

        route_operator_by_route_id = {}
        df_routes = _read_gtfs_table_from_zip(zip_path, "routes.txt")
        if df_routes is not None and "route_id" in df_routes.columns:
            keep_route_cols = [c for c in ("route_id", "route_short_name", "route_long_name", "route_type", "agency_id") if c in df_routes.columns]
            df_routes = df_routes[keep_route_cols].copy()
            df_routes["feed_id"] = feed_id
            df_routes["route_id"] = df_routes["route_id"].astype(str)
            df_routes["feed_route_id"] = df_routes["feed_id"] + ":" + df_routes["route_id"]
            if "route_type" in df_routes.columns:
                df_routes["mode"] = df_routes["route_type"].map(_map_gtfs_route_type)
            if "agency_id" in df_routes.columns and agency_name_by_id:
                df_routes["operator"] = (
                    df_routes["agency_id"].astype(str).map(agency_name_by_id).fillna(default_operator).map(_ascii_operator_name)
                )
            else:
                df_routes["operator"] = default_operator
            route_operator_by_route_id = {
                str(row["route_id"]): str(row["operator"]) for _, row in df_routes[["route_id", "operator"]].iterrows()
            }
            routes_frames.append(df_routes)

        df_stops_meta = _read_gtfs_table_from_zip(zip_path, "stops.txt")
        if df_stops_meta is not None and {"stop_id", "stop_lat", "stop_lon"}.issubset(df_stops_meta.columns):
            keep_stop_cols = [c for c in ("stop_id", "stop_name", "stop_lat", "stop_lon") if c in df_stops_meta.columns]
            df_stops = df_stops_meta[keep_stop_cols].copy()
            df_stops["feed_id"] = feed_id
            df_stops["stop_id"] = df_stops["stop_id"].astype(str)
            df_stops["feed_stop_id"] = df_stops["feed_id"] + ":" + df_stops["stop_id"]
            df_stops["operator"] = default_operator

            df_trips = _read_gtfs_table_from_zip(zip_path, "trips.txt")
            df_stop_times = _read_gtfs_table_from_zip(zip_path, "stop_times.txt")
            if (
                df_trips is not None
                and df_stop_times is not None
                and {"trip_id", "route_id"}.issubset(df_trips.columns)
                and {"trip_id", "stop_id"}.issubset(df_stop_times.columns)
                and route_operator_by_route_id
            ):
                trip_routes = df_trips[["trip_id", "route_id"]].copy()
                trip_routes["trip_id"] = trip_routes["trip_id"].astype(str)
                trip_routes["route_id"] = trip_routes["route_id"].astype(str)
                stop_trips = df_stop_times[["trip_id", "stop_id"]].copy()
                stop_trips["trip_id"] = stop_trips["trip_id"].astype(str)
                stop_trips["stop_id"] = stop_trips["stop_id"].astype(str)
                stop_ops = stop_trips.merge(trip_routes, on="trip_id", how="left")
                stop_ops["operator"] = (
                    stop_ops["route_id"].map(route_operator_by_route_id).fillna(default_operator).map(_ascii_operator_name)
                )
                operator_per_stop = stop_ops.groupby("stop_id", observed=False)["operator"].agg(_format_operator_label)
                df_stops["operator"] = df_stops["stop_id"].map(operator_per_stop).fillna(default_operator)

            operator_by_stop = dict(zip(df_stops["stop_id"].astype(str), df_stops["operator"].astype(str)))
            df_stops = _inherit_parent_station_operators(df_stops, df_stops_meta, operator_by_stop, default_operator)

            stops_frames.append(df_stops)

    df_stops_all = pd.concat(stops_frames, ignore_index=True) if stops_frames else pd.DataFrame()
    df_routes_all = pd.concat(routes_frames, ignore_index=True) if routes_frames else pd.DataFrame()
    return df_stops_all, df_routes_all


def _load_carsharing_stations(data_path, relative_json_path):
    path = os.path.join(data_path, relative_json_path)
    if not os.path.exists(path):
        return pd.DataFrame()
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    stations = payload.get("data", {}).get("stations", payload.get("stations", []))
    if not stations:
        return pd.DataFrame()
    df = pd.json_normalize(stations)
    if not {"station_id", "lat", "lon"}.issubset(df.columns):
        return pd.DataFrame()
    if "name" in df.columns:
        df["name"] = df["name"].apply(
            lambda x: x[0].get("text") if isinstance(x, list) and len(x) and isinstance(x[0], dict) else x
        )
    keep = [c for c in ("station_id", "name", "lat", "lon", "address", "capacity", "parking_type", "is_virtual_station") if c in df.columns]
    df = df[keep].copy()
    df["station_id"] = df["station_id"].astype(str)
    return df


def _load_carpooling_stops(data_path, relative_csv_path):
    path = os.path.join(data_path, relative_csv_path)
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, sep=";", low_memory=False)
    if len(df) == 0:
        return df
    keep = [c for c in ("id_local", "nom_lieu", "com_lieu", "insee", "type", "type_infra", "nbre_pl", "nbre_pmr", "Ylat", "Xlong", "gratuit") if c in df.columns]
    df = df[keep].copy()
    return df.rename(columns={"Ylat": "lat", "Xlong": "lon"})


def _load_taxi_stands(data_path, relative_paths, target_cities=None):
    from synthesis.output_resources.taxi.stands_loader import load_taxi_stands_dataframe

    return load_taxi_stands_dataframe(
        data_path,
        relative_paths,
        target_cities=target_cities,
    )


def _load_pmr_stands(data_path, relative_paths):
    rows = []
    for rel_path in relative_paths:
        path = os.path.join(data_path, rel_path)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        records = payload if isinstance(payload, list) else payload.get("features", [])
        for item in records:
            if isinstance(item, dict) and "properties" in item:
                props = item.get("properties", {})
                lat, lon = _extract_lat_lon(props)
                geometry = item.get("geometry", {})
                if (lat is None or lon is None) and isinstance(geometry, dict):
                    coordinates = geometry.get("coordinates", [])
                    if isinstance(coordinates, list) and len(coordinates) >= 2:
                        lon, lat = coordinates[0], coordinates[1]
            else:
                props = item if isinstance(item, dict) else {}
                lat = props.get("lat") or props.get("coord_y")
                lon = props.get("lon") or props.get("coord_x")

            if lat is None or lon is None:
                continue

            rows.append({
                "name": props.get("lib_voie") or props.get("nom") or props.get("name"),
                "commune": props.get("commune"),
                "nb_places": props.get("nb_places") or props.get("nbr_emplacement"),
                "pmr_type": props.get("tipe", "PMR"),
                "lat": lat,
                "lon": lon,
                "source_file": os.path.basename(path),
            })
    return pd.DataFrame(rows)


def _expand_relative_resource_paths(data_path, relative_paths, extensions):
    resolved_paths = []
    seen = set()
    if relative_paths is None:
        return resolved_paths
    if isinstance(relative_paths, str):
        paths = [relative_paths]
    else:
        paths = list(relative_paths)

    for rel_path in paths:
        candidate = os.path.join(data_path, rel_path)
        if not os.path.exists(candidate):
            continue

        if os.path.isdir(candidate):
            for extension in extensions:
                pattern = os.path.join(candidate, f"*{extension}")
                for matched in sorted(glob.glob(pattern)):
                    if matched in seen:
                        continue
                    seen.add(matched)
                    resolved_paths.append(matched)
            continue

        if candidate in seen:
            continue
        seen.add(candidate)
        resolved_paths.append(candidate)
    return resolved_paths


def _load_public_parking(data_path, relative_paths):
    frames = []
    for path in _expand_relative_resource_paths(data_path, relative_paths, extensions=(".csv",)):

        if "nimes" in os.path.basename(path).lower():
            df = pd.read_csv(path, sep=";", low_memory=False)
            if len(df) == 0:
                continue
            df = df.rename(columns={
                "Identifiant du parking": "parking_id",
                "Nom du parking": "name",
                "Ville": "city",
                "Code postal": "postal_code",
                "totalParkingSpaces": "total_spaces",
                "freespots": "free_spaces",
                "Statut": "status",
                "updatedat": "updated_at",
            })
            coordinate_column = next(
                (
                    column
                    for column in df.columns
                    if str(column).strip().lower().startswith("coordonn")
                ),
                None,
            )
            if coordinate_column is not None and coordinate_column != "coordinates":
                df = df.rename(columns={coordinate_column: "coordinates"})
            df["lat"], df["lon"] = zip(*df["coordinates"].map(_parse_parking_coordinates))
            df["source_file"] = os.path.basename(path)
            keep = [c for c in ("parking_id", "name", "city", "postal_code", "total_spaces", "free_spaces", "status", "updated_at", "lat", "lon", "source_file") if c in df.columns]
            frames.append(df[keep].copy())
        else:
            df = pd.read_csv(path, sep=None, engine="python")
            if len(df) == 0:
                continue
            df = df.rename(columns={
                "id": "parking_id",
                "nom": "name",
                "commune": "city",
                "insee": "city_insee",
                "adresse": "address",
                "nb_places": "total_spaces",
                "nb_pr": "park_and_ride_spaces",
                "nb_pmr": "pmr_spaces",
                "Xlong": "lon",
                "xlong": "lon",
                "Ylat": "lat",
                "ylat": "lat",
                "gratuit": "free_access",
                "type_ouvrage": "parking_type",
                "type_fonct": "function_type",
                "proprietaire": "owner",
            })
            df["source_file"] = os.path.basename(path)
            keep = [c for c in ("parking_id", "name", "city_insee", "address", "total_spaces", "park_and_ride_spaces", "pmr_spaces", "free_access", "parking_type", "function_type", "owner", "lat", "lon", "source_file") if c in df.columns]
            frames.append(df[keep].copy())

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    return _filter_occitanie_public_parking(df)


def _load_park_and_ride(data_path, relative_paths):
    frames = []
    for path in _expand_relative_resource_paths(data_path, relative_paths, extensions=(".json", ".csv")):
        basename = os.path.basename(path)
        lower_name = basename.lower()

        if lower_name.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            if isinstance(payload, list):
                rows = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    gp = item.get("geo_point_2d", {}) if isinstance(item.get("geo_point_2d"), dict) else {}
                    lon = item.get("xlong", item.get("lon", gp.get("lon")))
                    lat = item.get("ylat", item.get("lat", gp.get("lat")))
                    rows.append(
                        {
                            "parking_id": item.get("id"),
                            "name": item.get("nom"),
                            "city": item.get("commune"),
                            "city_insee": item.get("insee"),
                            "address": item.get("adresse"),
                            "total_spaces": item.get("nb_places"),
                            "park_and_ride_spaces": item.get("nb_pr"),
                            "pmr_spaces": item.get("nb_pmr"),
                            "free_access": item.get("gratuit"),
                            "parking_type": item.get("type_ouvrage"),
                            "function_type": item.get("fonction"),
                            "owner": item.get("proprietaire"),
                            "lat": lat,
                            "lon": lon,
                            "source_file": basename,
                        }
                    )
                if rows:
                    frames.append(pd.DataFrame(rows))
            elif isinstance(payload, dict) and "features" in payload:
                rows = []
                for feature in payload.get("features", []):
                    if not isinstance(feature, dict):
                        continue
                    props = feature.get("properties", {}) if isinstance(feature.get("properties"), dict) else {}
                    geometry = feature.get("geometry", {}) if isinstance(feature.get("geometry"), dict) else {}
                    coordinates = geometry.get("coordinates", [])
                    lon, lat = (coordinates[0], coordinates[1]) if isinstance(coordinates, list) and len(coordinates) >= 2 else (None, None)

                    parking_id = props.get("id") or hashlib.sha1(
                        f"{props.get('nom', '')}|{props.get('adresse', '')}|{lat}|{lon}".encode("utf-8")
                    ).hexdigest()[:12]
                    rows.append(
                        {
                            "parking_id": parking_id,
                            "name": props.get("nom"),
                            "address": props.get("adresse"),
                            "park_and_ride_spaces": props.get("nb_pr"),
                            "pmr_spaces": props.get("acces_pmr"),
                            "parking_type": props.get("type_ouvra"),
                            "function_type": props.get("info"),
                            "lat": lat,
                            "lon": lon,
                            "source_file": basename,
                        }
                    )
                if rows:
                    frames.append(pd.DataFrame(rows))

    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "city_insee" in df.columns:
        normalized = df["city_insee"].map(_normalize_insee)
        keep = normalized.isna() | normalized.str[:2].isin(OCCITANIE_DEPARTMENTS)
        df = df.loc[keep].copy()
        df["city_insee"] = normalized.loc[keep].astype("string").to_numpy()
    return df


def _normalize_insee(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(re.findall(r"\d", text))
    if len(digits) < 5:
        return None
    return digits[:5]


def _filter_occitanie_public_parking(df):
    if len(df) == 0:
        return df
    if "city_insee" in df.columns:
        normalized = df["city_insee"].map(_normalize_insee)
        keep = normalized.notna() & normalized.str[:2].isin(OCCITANIE_DEPARTMENTS)
        if keep.any():
            filtered = df.loc[keep].copy()
            filtered["city_insee"] = normalized.loc[keep].astype(str).to_numpy()
            return filtered
    return df


def _load_population_filter_area(path):
    if path is None:
        return None
    if not os.path.exists(path):
        return None
    try:
        area = gpd.read_file(path)
    except Exception:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        features = payload.get("features", []) if isinstance(payload, dict) else []

        def _close_ring(coords):
            if isinstance(coords, list) and len(coords) > 0 and coords[0] != coords[-1]:
                return coords + [coords[0]]
            return coords

        geometries = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            gtype = geometry.get("type")
            coords = geometry.get("coordinates")
            if gtype == "Polygon" and isinstance(coords, list):
                geometry = dict(geometry)
                geometry["coordinates"] = [_close_ring(ring) for ring in coords]
            elif gtype == "MultiPolygon" and isinstance(coords, list):
                geometry = dict(geometry)
                geometry["coordinates"] = [
                    [_close_ring(ring) for ring in polygon] if isinstance(polygon, list) else polygon
                    for polygon in coords
                ]
            try:
                geometries.append(shape(geometry))
            except Exception:
                continue
        if not geometries:
            return None
        area = gpd.GeoDataFrame(geometry=geometries, crs="EPSG:4326")
    if len(area) == 0:
        return None
    return area
