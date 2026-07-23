# Taxi fleet generation

Taxi resources for scenario export combine **fixed stands** (waiting locations) with **mobile taxis**
(shifts and pre-existing bookings). Stands come from the baseline; fleet and bookings are generated
offline, then wired into exports via `config_occitanie.yml`.

## Prerequisites

- Baseline `*_taxi_stands.csv` (from Toulouse / Montpellier open data via `taxi_data_paths`)
- Fleet parameters in [`backend/config/taxi_fleet.yml`](../../backend/config/taxi_fleet.yml)

## Generate a run

From the repo root:

```bash
uv run scripts/generate_taxi_fleet.py --weekday monday
```

Defaults:

| Option | Default |
|--------|---------|
| `--baseline-dir` | active baseline from `config_occitanie.yml` |
| `--output-dir` | `data/taxi_occitanie/fleet/` |
| `--config` | `backend/config/taxi_fleet.yml` |
| `--weekday` | `monday` |

Output folder, e.g. `data/taxi_occitanie/fleet/20260720_143000/`:

- `Taxi.json` - full `operators/Taxi.json` payload
- `generation_stats.json` - fleet size, booking counts

## Operator shape

**Stand points** (fixed locations):

```json
{
  "id": "taxi_stand:wilson",
  "lat": 43.6047,
  "lon": 1.4477,
  "kind": "taxi_stand",
  "name": "PL DU PRESIDENT THOMAS WOODROW WILSON",
  "parking_capacity": 15,
  "zone_type": "city_center"
}
```

**Taxi resources** (mobile fleet):

```json
{
  "id": "taxi_0001",
  "mode": "Taxi",
  "operator_id": "Taxi",
  "passenger_capacity": 4,
  "wheelchair_accessible": false,
  "start_stand": "taxi_stand:wilson",
  "availability_period": {"start": 480, "end": 1200},
  "bookings": [
    {
      "pickup": {"time": 510, "lat": 43.6045, "lon": 1.4440},
      "dropoff": {"time": 535, "lat": 43.6293, "lon": 1.3676}
    }
  ]
}
```

Stands are **not** exported as taxi resources with a `capacity` field. Parking spaces use
`parking_capacity` on stand points only.

## Wire into scenarios

In `config_occitanie.yml`:

```yaml
taxi_fleet_path: taxi_occitanie/fleet/20260720_143000
```

Path is relative to `data_path`. On **Export scenario zip**, the backend loads
`{taxi_fleet_path}/Taxi.json` into `operators/Taxi.json`.

If `taxi_fleet_path` is unset, export falls back to **stand points only** (no taxis or bookings).

After changing the fleet run, start a **new scenario job** before exporting.

## Generation model

The generator follows the Occitanie taxi scenario specification:

1. Per city, sample active fleet size: `N_day ~ Binomial(n_fleet[city], p_day[weekday])`
   (`n_fleet` comes from `taxi_demand_zones.yml`)
2. Assign each taxi a shift profile (morning / day / afternoon / night)
3. Pick a start stand weighted by `parking_capacity × zone_attractiveness`
4. Fill pre-existing bookings until ~15% of shift time is occupied (configurable)
5. Bookings use an hourly demand profile; trip duration uses haversine distance × circuity / speed
6. Pickup and drop-off locations are sampled from **high-demand zones** (stations, airports,
   city centres, hospitals, entertainment areas) with a configurable chance of using an official
   taxi stand (`booking_endpoint.stand_probability` in `taxi_demand_zones.yml`). Taxis still **start** at a
   weighted taxi stand.

Per-city licensed fleet sizes and demand zones live in
[`backend/config/taxi_demand_zones.yml`](../../backend/config/taxi_demand_zones.yml).

Fleet-size sources (`n_fleet`):

- **Nîmes (45):** [Ville de Nîmes - En taxi](https://www.nimes.fr/mon-quotidien/deplacement-stationnement/se-deplacer/en-taxi) (45 ADS managed by the city)
- **Perpignan (45):** trade listing citing *45 ADS* on the commune ([CessionPME](https://www.cessionpme.com/annonce,vente-societe-societe-et-licence-de-taxi-perpignan-66000,2731893,A,offre.html))
- **Montpellier (226):** [Charte des taxis 2026](https://www.montpellier.fr/sites/default/files/2026-01/Charte%20des%20taxis%202026.pdf)
- **Toulouse (500):** [MesADS chiffres clés](https://mesads.beta.gouv.fr/chiffres-cles) (Haute-Garonne is around **913** ADS department wide); I use a subset equal to **500** but is is still configurable 

Configure probabilities, shift profiles, occupancy, and hourly demand in
[`backend/config/taxi_fleet.yml`](../../backend/config/taxi_fleet.yml).
Zone attractiveness and booking stand probability are in
[`backend/config/taxi_demand_zones.yml`](../../backend/config/taxi_demand_zones.yml).

`passenger_capacity` in `taxi_fleet.yml` is a weight map sampled once per taxi

## Baseline stand cleanup

When loading taxi stands for the baseline CSV, the pipeline:

- loads configured sources under `data/taxi_pmr_occitanie/` for `taxi_cities`
  (`toulouse`, `montpellier`, `perpignan`, `nimes`)
- keeps **taxi stands only** - PMR,
  livraison, and delivery spots are counted but not exported
- merges duplicate coordinates (sums parking spaces)
- assigns `zone_type` from stand name keywords (station, airport, city centre, multimodal hub)

Per-city source statistics:

```bash
python scripts/report_taxi_stand_stats.py
```

Perpignan and Nimes are listed in `taxi_cities` but have **no taxi stand files** in
`data/taxi_pmr_occitanie/` (nothing is invented).
