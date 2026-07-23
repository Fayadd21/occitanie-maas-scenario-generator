(occitanie-maas)=
# Occitanie MaaS Scenario Generator

The following pages describe how to run the Occitanie map UI and API on top of
[eqasim-france](https://github.com/eqasim-org/eqasim-france): baseline population,
scenario jobs with latent classes from `profiles.yml`, and export to `scenario.json`.

Population synthesis and data download:

- [Gathering the data](gathering-the-data.md) - national inputs plus Occitanie and MaaS feeds
- [Data layout](data-layout.md) - expected file names
- [Quickstart](quickstart.md) - running the pipeline

Scenario jobs run `synthesis.output` against a stored baseline.

```{toctree}
:titlesonly:
:maxdepth: 1

overview.md
prerequisites.md
gathering-the-data.md
data-layout.md
quickstart.md
profiles-and-latent-classes.md
constraints.md
baseline-and-scenarios.md
timetables.md
taxi-fleet.md
api-and-outputs.md
unit-tests.md
```
