# Gathering the data

The first part of this page is the usual eqasim national setup (sections 1 -> 9 adapted from
[eqasim population data documentation](https://eqasim-org.github.io/eqasim-france/population/population_data.html)). After that you will find project-specific
downloads that were added on top of the eqasim-france setup: Bikesharing, Parking, PMR, Carpooling, and Carsharing data. Use
[Data layout](data-layout.md) for where each file should sit on disk, then set the matching
`ban_path`, `gtfs_path`, and other keys in your own `config_occitanie.yml`.

To create the scenario, synthetic population, a couple of data sources must be collected. It is best to start with an empty folder that can be located anywhere in your file system. In the following, the folder will be denoted as `/data`. All downloaded data sets need to be put into specific sub-directories. The following paragraphs describe this process.

:::{tip}

**Mixing code and data:** Often, when people clone the eqasim repository, they see the `data` folder and put the data sets there. This is not the intended procedure: the cloned repository only contains the processing code that should be separated from where the data is located. See [Quickstart](quickstart.md) for a common project directory structure in this project.

:::

## 1) Census data (RP 2022)

Census data containing the socio-demographic information of people living in
France is available from INSEE:

- [Census data](https://www.insee.fr/fr/statistiques/8647104)
- Download the data set in **parquet** format by clicking the link under *Individus localises au canton-ou-ville*.
- Copy the *parquet* file into the folder `data/rp_2022`

## 2) Population totals (RP 2022)

We also make use of more aggregated population totals available from INSEE:

- [Population data](https://www.insee.fr/fr/statistiques/8647014)
- Download the data for *France hors Mayotte* in **csv** format.
- Copy the *zip* file into the folder `data/rp_2022`.

## 3) Origin-destination data (RP-MOBPRO / RP-MOBSCO 2022)

Origin-destination data is available from INSEE (at two locations):

- [Work origin-destination data](https://www.insee.fr/fr/statistiques/8589904)
- [Education origin-destination data](https://www.insee.fr/fr/statistiques/8589945)
- Download the data from the links, both in **parquet** format.
- Copy both *parquet* files into the folder `data/rp_2022`.

## 4) Income tax data (Filosofi 2021)

The tax data set is available from INSEE:

- [Income tax data](https://www.insee.fr/fr/statistiques/7756855)
- Download the munipality data (first link): *Base niveau communes en 2021* in **xlsx** format
- Copy the *zip* file into the folder `data/filosofi_2021`
- Download the administrative level data (second link): *Base niveau administratif en 2021* in **xlsx** format
- Copy the second *zip* file into `data/filosofi_2021`

## 5) Service and facility census (BPE 2024)

The census of services and facilities in France is available from INSEE:

- [Service and facility census](https://www.insee.fr/fr/statistiques/8217525)
- Download the data set in **parquet** format.
- Copy the *parquet* file into the folder `data/bpe_2024`.

## 6a) National household travel survey (ENTD 2008)

The national household travel survey is available from the Ministry of Ecology:

- [National household travel survey](https://www.statistiques.developpement-durable.gouv.fr/enquete-nationale-transports-et-deplacements-entd-2008)
- Scroll all the way down the website to the **Table des donnees** (a clickable
pop-down menu).
- You can either download all the available *csv* files in the list, but only
  a few are actually relevant for the pipeline. Those are:
  - Donnees socio-demographiques des menages (Q_tcm_menage_0.csv)
  - Donnees socio-demographiques des individus (Q_tcm_individu.csv)
  - Logement, stationnement, vehicules a disposition des menages (Q_menage.csv)
  - Donnees trajets domicile-travail, domicile-etude, accidents (Q_individu.csv)
  - Donnees mobilite contrainte, trajets vers lieu de travail (Q_ind_lieu_teg.csv)
  - Donnees mobilite deplacements locaux (K_deploc.csv)
- Put the downloaded *csv* files in to the folder `data/entd_2008`.

### 6b) National Person Mobility Survey (EMP 2019)

The National Person Mobility Survey is also available from the Ministry of Ecology:

- [National Person Mobility Survey](https://www.statistiques.developpement-durable.gouv.fr/resultats-detailles-de-lenquete-mobilite-des-personnes-de-2019)
- Scroll all the way down the website to the **Telecharger les donnees individuelles anonymisees et leurs dictionnaires** (a clickable pop-down menu).
- Download the data set in **csv** by clicking on the link **Donnees individuelles anonymisees (fichiers au format CSV) - EMP 2019**
- Copy the *zip* file into the folder `data/emp_2019`.

### 6c) *(Optional)* Regional household travel survey (EGT)

Usually, you do not have access to the regional household travel
survey, which is not available publicly. In case you have access (but we cannot
guarantee that you have exactly the correct format), you should make sure that
the following files are accessible in the folder `data/egt_2010`:
`Menages_semaine.csv`, `Personnes_semaine.csv`, `Deplacements_semaine.csv`.

## 7) IRIS zoning system (2024)

The IRIS zoning system is available from IGN:

- [IRIS data](https://geoservices.ign.fr/contoursiris)
- Scroll down to Resources and links
- Under API, Click the download button next to *Contours... IRIS&#174;* (tag: Data download)
- Search for 'CONTOURS-IRIS_3-0__GPKG_LAMB93_FXX_2024-01-01' and click on it then download the *7z* version
- Copy the *7z* file into the folder `data/iris_2024`


## 8) Zoning registry (2023)

We make use of a zoning registry by INSEE that establishes a connection between
the identifiers of IRIS, municipalities, departments and regions:

- [Zoning data](https://www.insee.fr/fr/information/7708995)
- Download the **2024** edition as a *zip* file.
- Copy the *zip* file into `data/codes_2024`.

## 9) Enterprise census (SIRENE)

The enterprise census of France is available on data.gouv.fr:

- [Enterprise census](https://www.data.gouv.fr/fr/datasets/base-sirene-des-entreprises-et-de-leurs-etablissements-siren-siret/)
- Scroll down and click on the blue download button on the right for the two following data sets:
 - **Sirene : Fichier StockUniteLegale du dd mm yyyy (format parquet)** (where "dd mm yyyy" is the
 date), the database of enterprises
 - **Sirene : Fichier StockEtablissement du dd mm yyy (format parquet)** (where "dd mm yyyy" is the
 date), the database of enterprise facilities
- The files are updated monthly and are rather large. After downloading, you should have two files:
 - `StockEtablissement_utf8.parquet`
 - `StockUniteLegale_utf8.parquet`
- Move both *parquet* files into `data/sirene`.

The geolocated enterprise census is available on data.gouv.fr:

- [Geolocated enterprise census](https://www.data.gouv.fr/fr/datasets/geolocalisation-des-etablissements-du-repertoire-sirene-pour-les-etudes-statistiques/)
- Scroll down and click on the blue download button on the right for the following data set:
 - **Sirene : Fichier GeolocalisationEtablissement_Sirene_pour_etudes_statistiques du dd mm yyyy
 (format parquet)** (where "dd mm yyyy" is the date)
- Put the downloaded *parquet* file into `data/sirene`

## Regional datasets (Occitanie)



### A) Buildings database (BD TOPO)

You need the region-specific buildings database.

- [Buildings database](https://geoservices.ign.fr/bdtopo)
- Scroll down to the Resources and links, under API, click on the download button next to
 *BD TOPO&#174; V3*  (tag: Data download).
- The data is split by department. Download the departments you list under `departments` in
 `config_occitanie.yml` (required format is GeoPackage), for example:
 - Ariege (09), Aude (11), Aveyron (12), Gard (30), Haute-Garonne (31), Gers (32),
 Herault (34), Lot (46), Lozere (48), Hautes-Pyrenees (65), Pyrenees-Orientales (66),
 Tarn (81), Tarn-et-Garonne (82)
- Copy each `*.7z` file into `data/bdtopo_occitanie/`.

### B) Adresses database (BAN)

- [Adresses database](https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/)
- Download `adresses-xx.csv.gz` for each department code listed above.
- Copy the `*.gz` files into `data/ban_occitanie/`.

### C) GTFS schedules

GTFS is required for transit stop and route layers in baseline exports (`*_gtfs_stops.csv`,
`*_gtfs_routes.csv`). There is no single consolidated GTFS for all of Occitanie; collect
feeds operator by operator on [transport.data.gouv.fr](https://transport.data.gouv.fr/).

| Save as | Source |
|---------|--------|
| `data/gtfs_occitanie/tisseo_gtfs_v2.zip` | [TISSEO (Toulouse)](https://transport.data.gouv.fr/datasets/tisseo-reseau-transport-urbain-toulousain/) |
| `data/gtfs_occitanie/TAM_MMM_GTFS.zip` | [TAM (Montpellier)](https://transport.data.gouv.fr/datasets/offre-de-transport-de-montpellier-mediterranee-metropole-tam-gtfs/) |
| `data/gtfs_occitanie/lio.zip` | [liO (Occitanie interurban)](https://transport.data.gouv.fr/datasets/reseau-lio-occitanie/) |
| `data/gtfs_occitanie/sncf-tgv-intercite-ter.gtfs.zip` | [SNCF TGV, Intercites et TER](https://transport.data.gouv.fr/datasets/horaires-sncf) |
| `data/gtfs_occitanie/gtfs-production.zip` | [Reseau urbain Tango (Nimes)](https://transport.data.gouv.fr/datasets/offre-de-transport-du-reseau-tango-de-nimes-metropole-gtfs-gtfs-rt) - download the GTFS resource named `gtfs-production.zip` |
| `data/gtfs_occitanie/gtfs-sankeo.zip` | [Sankeo (Perpignan)](https://transport.data.gouv.fr/datasets/gtfs-sankeo) |

File names on the portal may change when operators publish updates. It is best to save them as in
[Data layout](data-layout.md).


### D) Configuration

In `config_occitanie.yml`, set `departments` and the paths to match your data tree, for example:

```yaml
config:
 departments: ["09", "82", "81", "11", "31", "32", "12", "30", "34", "46", "48", "65", "66"]
 ban_path: ban_occitanie
 bdtopo_path: bdtopo_occitanie
 gtfs_path: gtfs_occitanie
```

The same file also lists MaaS paths (`bikesharing_path`, `parking_data_paths`, and so on); keep
those consistent with [Data layout](data-layout.md).

## MaaS resource datasets

These feeds are read when `export_static_resources: true` (set automatically on
**Rebuild baseline**).

### A) Bikesharing - GBFS static (`data/gbfs/`)

For each system, save **two** JSON snapshots from the live GBFS feed:

- `station_information_<city>.json`
- `system_information_<city>.json`

Use the city slug in the file name exactly as in [Data layout](data-layout.md)
(for example `station_information_Argeles_sur_mer.json`).

| City slug | GBFS `station_information` URL | Save as |
|-----------|--------------------------------|---------|
| `toulouse` | `https://api.cyclocity.fr/contracts/toulouse/gbfs/v2/station_information.json` | `data/gbfs/station_information_toulouse.json` |
| `montpellier` | `https://gbfs.theta.fifteen.eu/gbfs/2.2/montpellier/en/station_information.json` | `data/gbfs/station_information_montpellier.json` |
| `nimes` | `https://api.gbfs.v3.0.ecovelo.mobi/nemovelo/station_information.json` | `data/gbfs/station_information_nimes.json` |
| `perpignan` | `https://proxy.transport.data.gouv.fr/resource/pony-perpignan-gbfs/station_information.json` | `data/gbfs/station_information_perpignan.json` |
| `carcassonne` | `https://api.gbfs.v3.0.ecovelo.mobi/cyclolibre/station_information.json` | `data/gbfs/station_information_Carcassonne.json` |
| `argeles_sur_mer` | `https://api.gbfs.v3.0.ecovelo.mobi/velodaqui/station_information.json` | `data/gbfs/station_information_Argeles_sur_mer.json` |
| `grand_auch` | `https://api.gbfs.v3.0.ecovelo.mobi/auchveloc/station_information.json` | `data/gbfs/station_information_grand_auch.json` |
| `gevaudan` | `https://www.mobility-parc.net/gbfs/v3/GEVAUDAN/station_information.json` | `data/gbfs/station_information_gevaudan.json` |
| `tarbes_lourdes` | `https://api.gbfs.v3.0.ecovelo.mobi/tlpmobilites/station_information.json` | `data/gbfs/station_information_tarbes_lourdes.json` |

| City slug | GBFS `system_information` URL | Save as |
|-----------|------------------------------|---------|
| `toulouse` | `https://api.cyclocity.fr/contracts/toulouse/gbfs/v2/system_information.json` | `data/gbfs/system_information_toulouse.json` |
| `montpellier` | `https://gbfs.theta.fifteen.eu/gbfs/2.2/montpellier/en/system_information.json` | `data/gbfs/system_information_montpellier.json` |
| `nimes` | `https://api.gbfs.v3.0.ecovelo.mobi/nemovelo/system_information.json` | `data/gbfs/system_information_nimes.json` |
| `perpignan` | `https://proxy.transport.data.gouv.fr/resource/pony-perpignan-gbfs/system_information.json` | `data/gbfs/system_information_perpignan.json` |
| `carcassonne` | `https://api.gbfs.v3.0.ecovelo.mobi/cyclolibre/system_information.json` | `data/gbfs/system_information_Carcassonne.json` |
| `argeles_sur_mer` | `https://api.gbfs.v3.0.ecovelo.mobi/velodaqui/system_information.json` | `data/gbfs/system_information_Argeles_sur_mer.json` |
| `grand_auch` | `https://api.gbfs.v3.0.ecovelo.mobi/auchveloc/system_information.json` | `data/gbfs/system_information_grand_auch.json` |
| `gevaudan` | `https://www.mobility-parc.net/gbfs/v3/GEVAUDAN/system_information.json` | `data/gbfs/system_information_gevaudan.json` |
| `tarbes_lourdes` | `https://api.gbfs.v3.0.ecovelo.mobi/tlpmobilites/system_information.json` | `data/gbfs/system_information_tarbes_lourdes.json` |


Example one-time download for Toulouse:

```bash
curl -fsSL 'https://api.cyclocity.fr/contracts/toulouse/gbfs/v2/station_information.json' \
 -o data/gbfs/station_information_toulouse.json
curl -fsSL 'https://api.cyclocity.fr/contracts/toulouse/gbfs/v2/system_information.json' \
 -o data/gbfs/system_information_toulouse.json
```

Repeat for each city, changing URLs and output file names.

### B) Bikesharing - status history (`data/bikesharing_occitanie/`)

Baseline rebuild reads **historical** availability from CSV, not live APIs.

1. Edit `data/bikesharing_occitanie/station_status_feeds.json` (city slug → GBFS
   `station_status.json` URL; same hosts as above with `station_status` instead of
   `station_information`). `collect_station_status.py` reads this file by default.
2. Run the collector to append snapshots (default interval 900 seconds):

```bash
# One snapshot per city (smoke test)
uv run python data/bikesharing_occitanie/collect_station_status.py --once

# Continuous collection
uv run python data/bikesharing_occitanie/collect_station_status.py
```

3. After enough history is collected, each city should have:
 `data/bikesharing_occitanie/station_status_data/<city>/flat/station_status_history.csv`

Then run **Rebuild baseline** so `*_bikesharing_stations.csv` is regenerated from disk.

### C) Carsharing - Citiz GBFS (`data/carsharing_occitanie/`)

- Dataset: [Autopartage Citiz Occitanie](https://transport.data.gouv.fr/datasets/citiz-autopartage-occitanie)
- Download the GBFS resource (`gbfs-citiz-autopartage-occitanie`) and save:
 - `station_information_carsharing_citiz_occitanie.json`
 - `system_information_carsharing_citiz_occitanie.json`
 - `station_status_carsharing_citiz_occitanie.json`

### D) Carpooling (`data/carpooling_occitanie/`)

- Dataset: [Lieux de covoiturage - Region Occitanie](https://transport.data.gouv.fr/datasets/infrastructures-de-covoiturage-en-occitanie-1)
- Download and save as:
 - `infrastructures-de-covoiturage-en-occitanie-v2.csv`

### E) Parking (`data/parking_occitanie/`)

| Save as | Dataset | Download |
|---------|---------|----------|
| `parcs-de-stationnement-toulouse.csv` | [Parcs de stationnement - Toulouse Metropole](https://data.toulouse-metropole.fr/explore/dataset/parcs-de-stationnement/) | [CSV export](https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/parcs-de-stationnement/exports/csv) |
| `VilleMTP_MTP_ParkingOuv-montpellier.csv` | [Parkings en ouvrage de Montpellier](https://data.montpellier3m.fr/dataset/parkings-en-ouvrage-de-montpellier) | [CSV export](https://data.montpellier3m.fr/sites/default/files/ressources/VilleMTP_MTP_ParkingOuv.csv) |
| `etat-des-parkings-en-temps-reel-ville-de-nimes.csv` | [Etat des parkings en temps reel - Nimes Metropole](https://data.nimes-metropole.fr/explore/dataset/etat-des-parkings-en-temps-reel-ville-de-nimes/) | [CSV export](https://data.nimes-metropole.fr/api/explore/v2.1/catalog/datasets/etat-des-parkings-en-temps-reel-ville-de-nimes/exports/csv) |

Example (Toulouse):

```bash
curl -fsSL 'https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/parcs-de-stationnement/exports/csv' \
  -o data/parking_occitanie/parcs-de-stationnement-toulouse.csv
```


### F) Park-and-ride (`data/p+r/`)

| Save as | Dataset | Download |
|---------|---------|----------|
| `parkings-relais_Toulouse.json` | [Parkings relais - Toulouse Metropole](https://data.toulouse-metropole.fr/explore/dataset/parkings-relais/) | [JSON export](https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/parkings-relais/exports/json) |
| `MMM_MMM_ParkingTram_Montpellier.json` | [Parkings Tramway de Montpellier](https://data.montpellier3m.fr/dataset/parkings-tramway-de-montpellier-mediterranee-metropole) | [JSON export](https://data.montpellier3m.fr/sites/default/files/ressources/MMM_MMM_ParkingTram.json) |

Example (Toulouse):

```bash
curl -fsSL 'https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/parkings-relais/exports/json' \
  -o data/p+r/parkings-relais_Toulouse.json
```

For Montpellier, download `MMM_MMM_ParkingTram.json` and save it as
`MMM_MMM_ParkingTram_Montpellier.json`.

### G) Taxi and PMR (`data/taxi_pmr_occitanie/`)

| Save as | Dataset | Download |
|---------|---------|----------|
| `taxis_toulouse.json` | [Emplacements taxis - Toulouse Metropole](https://data.toulouse-metropole.fr/explore/dataset/emplacements-taxis/) | [JSON export](https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/emplacements-taxis/exports/json) |
| `pmr_Toulouse.json` | [Emplacements PMR - Toulouse Metropole](https://data.toulouse-metropole.fr/explore/dataset/pmr/) | [JSON export](https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/pmr/exports/json) |
| `pmr_taxis_delivery_Montpellier.json` | [Places reservees (PMR, livraison et taxi) - Montpellier](https://data.montpellier3m.fr/dataset/places-reservees-pmr-livraison-et-taxi-de-montpellier) | [JSON export](https://data.montpellier3m.fr/sites/default/files/ressources/MMM_MTP_PlacesReserv.json) |

Example (Toulouse):

```bash
curl -fsSL 'https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/emplacements-taxis/exports/json' \
  -o data/taxi_pmr_occitanie/taxis_toulouse.json
curl -fsSL 'https://data.toulouse-metropole.fr/api/explore/v2.1/catalog/datasets/pmr/exports/json' \
  -o data/taxi_pmr_occitanie/pmr_Toulouse.json
```

For Montpellier, download `MMM_MTP_PlacesReserv.json` and save it as
`pmr_taxis_delivery_Montpellier.json` (name expected by `pmr_data_paths` in
`config_occitanie.yml`).

## After download

1. Compare your tree with [Data layout](data-layout.md).
2. Copy `backend/config/example.profiles.yml` to `backend/config/profiles.yml` (see [Prerequisites](prerequisites.md)).
3. Run **Rebuild baseline** in the UI or `POST /baseline/rebuild` once national,
 regional, and MaaS files are in place.
