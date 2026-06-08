# Data layout (Occitanie)

This page lists the **data files and folders** expected under `data/` for the
Occitanie setup used with `config_occitanie.yml` and the MaaS UI. Paths match the
keys in that config (`ban_path`, `bdtopo_path`, `gtfs_path`, `gbfs_path`,
`bikesharing_path`, and so on).

Download instructions are in [Gathering the data](gathering-the-data.md)
(national inputs, Occitanie BAN/BDTOPO/GTFS, and MaaS feeds).

The MATSim simulation stack (`matsim/`, Java, `mode_choice`) has been removed from
this project. Only population synthesis and MaaS resource export are supported.

The `data/` tree also contains **eqasim Python modules** (for example `data/ban/`,
`data/spatial/`). Those are processing code, not datasets; they are omitted below.

## Overview

After setup, you should have at least the following **dataset** paths.

### Population synthesis

National inputs (whole France; the pipeline filters by `departments` in config):

- `data/rp_2022/RP2022_indcvi.parquet`
- `data/rp_2022/RP2022_mobpro.parquet`
- `data/rp_2022/RP2022_mobsco.parquet`
- `data/rp_2022/base-ic-evol-struct-pop-2022_csv.zip`
- `data/filosofi_2021/indic-struct-distrib-revenu-2021-COMMUNES_XLSX.zip`
- `data/filosofi_2021/indic-struct-distrib-revenu-2021-SUPRA_XLSX.zip`
- `data/bpe_2024/BPE24.parquet`
- `data/entd_2008/K_deploc.csv`
- `data/entd_2008/Q_ind_lieu_teg.csv`
- `data/entd_2008/Q_individu.csv`
- `data/entd_2008/Q_menage.csv`
- `data/entd_2008/Q_tcm_individu.csv`
- `data/entd_2008/Q_tcm_menage_0.csv`
- `data/emp_2019/emp_2019_donnees_individuelles_anonymisees_novembre2024.zip`
- `data/iris_2024/CONTOURS-IRIS_3-0__GPKG_LAMB93_FXX_2024-01-01.7z`
- `data/codes_2024/reference_IRIS_geo2024.zip`
- `data/sirene/StockEtablissement_utf8.parquet`
- `data/sirene/StockUniteLegale_utf8.parquet`
- `data/sirene/GeolocalisationEtablissement_Sirene_pour_etudes_statistiques_utf8.parquet`

Occitanie region (`ban_path`, `bdtopo_path`):

- `data/ban_occitanie/adresses-09.csv.gz`
- `data/ban_occitanie/adresses-11.csv.gz`
- `data/ban_occitanie/adresses-12.csv.gz`
- `data/ban_occitanie/adresses-30.csv.gz`
- `data/ban_occitanie/adresses-31.csv.gz`
- `data/ban_occitanie/adresses-32.csv.gz`
- `data/ban_occitanie/adresses-34.csv.gz`
- `data/ban_occitanie/adresses-46.csv.gz`
- `data/ban_occitanie/adresses-48.csv.gz`
- `data/ban_occitanie/adresses-65.csv.gz`
- `data/ban_occitanie/adresses-66.csv.gz`
- `data/ban_occitanie/adresses-81.csv.gz`
- `data/ban_occitanie/adresses-82.csv.gz`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D009_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D011_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D012_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D030_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D031_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D032_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D034_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D046_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D048_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D065_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D066_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D081_2022-03-15.7z`
- `data/bdtopo_occitanie/BDTOPO_3-0_TOUSTHEMES_GPKG_LAMB93_D082_2022-03-15.7z`

### MaaS static resources

Used when building `*_bikesharing_stations.csv`, `*_gtfs_*.csv`, parking, and related
layers (`gbfs_path`, `bikesharing_path`, and list paths in `config_occitanie.yml`):

**GBFS static feeds** (`data/gbfs/`):

- `data/gbfs/station_information_toulouse.json`
- `data/gbfs/station_information_montpellier.json`
- `data/gbfs/station_information_nimes.json`
- `data/gbfs/station_information_perpignan.json`
- `data/gbfs/station_information_Carcassonne.json`
- `data/gbfs/station_information_Argeles_sur_mer.json`
- `data/gbfs/station_information_grand_auch.json`
- `data/gbfs/station_information_gevaudan.json`
- `data/gbfs/station_information_tarbes_lourdes.json`
- `data/gbfs/system_information_toulouse.json`
- `data/gbfs/system_information_montpellier.json`
- `data/gbfs/system_information_nimes.json`
- `data/gbfs/system_information_perpignan.json`
- `data/gbfs/system_information_Carcassonne.json`
- `data/gbfs/system_information_Argeles_sur_mer.json`
- `data/gbfs/system_information_grand_auch.json`
- `data/gbfs/system_information_gevaudan.json`
- `data/gbfs/system_information_tarbes_lourdes.json`

**Bikesharing status history** (`data/bikesharing_occitanie/`):

- `data/bikesharing_occitanie/station_status_feeds.json`
- `data/bikesharing_occitanie/station_status_data/toulouse/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/montpellier/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/nimes/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/perpignan/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/carcassonne/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/argeles_sur_mer/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/grand_auch/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/gevaudan/flat/station_status_history.csv`
- `data/bikesharing_occitanie/station_status_data/tarbes_lourdes/flat/station_status_history.csv`

**Other feeds:**

- `data/carsharing_occitanie/station_information_carsharing_citiz_occitanie.json`
- `data/carsharing_occitanie/system_information_carsharing_citiz_occitanie.json`
- `data/carsharing_occitanie/station_status_carsharing_citiz_occitanie.json`
- `data/carpooling_occitanie/infrastructures-de-covoiturage-en-occitanie-v2.csv`
- `data/parking_occitanie/etat-des-parkings-en-temps-reel-ville-de-nimes.csv`
- `data/parking_occitanie/VilleMTP_MTP_ParkingOuv-montpellier.csv`
- `data/parking_occitanie/parcs-de-stationnement-toulouse.csv`
- `data/taxi_pmr_occitanie/taxis_toulouse.json`
- `data/taxi_pmr_occitanie/pmr_Toulouse.json`
- `data/taxi_pmr_occitanie/pmr_taxis_delivery_Montpellier.json`
- `data/p+r/parkings-relais_Toulouse.json`
- `data/p+r/MMM_MMM_ParkingTram_Montpellier.json`

**GTFS schedules** (`data/gtfs_occitanie/`, for `*_gtfs_stops.csv` / `*_gtfs_routes.csv`):

- `data/gtfs_occitanie/tisseo_gtfs_v2.zip`
- `data/gtfs_occitanie/TAM_MMM_GTFS.zip`
- `data/gtfs_occitanie/lio.zip`
- `data/gtfs_occitanie/sncf-tgv-intercite-ter.gtfs.zip`
- `data/gtfs_occitanie/gtfs-production.zip`
- `data/gtfs_occitanie/gtfs-sankeo.zip`

### GeoPackage outputs (UI map layers)

With `output_formats` including `gpkg`, `synthesis.output` writes geometry for the
map API, for example:

- `output/jobs/<run_id>/<run_id>_homes.gpkg`
- `output/jobs/<run_id>/<run_id>_activities.gpkg`

The backend serves these as `population.geojson` and `activities.geojson`. They are
built from **activity locations** (`synthesis.population.spatial.locations`: BAN,
BDTOPO, IRIS zoning).

MaaS resource layers (bikesharing, GTFS stops, parking, and so on) are point GeoPackages
or CSVs from `export_static_resources`.

## Config mapping

| `config_occitanie.yml` key | Folder under `data/` |
|----------------------------|----------------------|
| `ban_path` | `ban_occitanie/` |
| `bdtopo_path` | `bdtopo_occitanie/` |
| `gtfs_path` | `gtfs_occitanie/` |
| `gbfs_path` | `gbfs/` |
| `bikesharing_path` | `bikesharing_occitanie/` |
| `carsharing_path` | `carsharing_occitanie/station_information_carsharing_citiz_occitanie.json` |
| `carpooling_path` | `carpooling_occitanie/infrastructures-de-covoiturage-en-occitanie-v2.csv` |
| `taxi_data_paths` | `taxi_pmr_occitanie/` |
| `pmr_data_paths` | `taxi_pmr_occitanie/` |
| `parking_data_paths` | `parking_occitanie/` |
| `pnr_data_paths` | `p+r/` |

National paths (`rp_2022`, `entd_2008`, `sirene`, and others) are fixed in the eqasim pipeline
and are not overridden in `config_occitanie.yml`.

## Refreshing bikesharing availability

Baseline rebuild **does not** call live GBFS APIs. It reads the files above.
To refresh status history, run the collector (it loads `station_status_feeds.json` by default):

```bash
uv run python data/bikesharing_occitanie/collect_station_status.py
```

Then run **Rebuild baseline** in the UI (or `POST /baseline/rebuild`) so
`*_bikesharing_stations.csv` is regenerated from disk.
