(occitanie-maas)=
# Occitanie MaaS Scenario Generator

The following pages describe how to run the Occitanie map UI and API on top of
[eqasim-france](https://github.com/eqasim-org/eqasim-france): baseline population,
scenario jobs with latent classes from `profiles.yml`, and export to `scenario.json`.

Population synthesis and data download:

- [Gathering the data](gathering-the-data.md) - national inputs plus Occitanie and MaaS feeds
- [Data layout](data-layout.md) - expected file names
- [Quickstart](quickstart.md) - running the pipeline

The usual job runs only `synthesis.output` against a stored baseline. This project
does not use MATSim

```{toctree}
:titlesonly:
:maxdepth: 1

overview.md
prerequisites.md
gathering-the-data.md
data-layout.md
quickstart.md
profiles-and-latent-classes.md
baseline-and-scenarios.md
api-and-outputs.md
unit-tests.md
```
