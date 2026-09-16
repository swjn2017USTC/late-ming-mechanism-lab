# Third-party data and attribution notice

The MIT License in this repository applies to the project's original software and original
documentation. It does not grant rights to third-party datasets, publications, names, geographic
records, quotations, or other materials from external sources.

## CHGIS

The historical core uses derived selections from CHGIS V6:

> CHGIS, Version 6. Fairbank Center for Chinese Studies at Harvard University and the Center for
> Historical Geographical Studies at Fudan University, 2016.

The source manifests record the CHGIS terms as academic-only and prohibit redistribution of the
source layers. This repository does not contain those layers. Small derived tables record selected
node identities, coordinates, dates, links and distances, with changes and omissions documented in
`sources/snapshots/chgis-v6.yaml` and `docs/v2/coverage-historical-core-v1.md`. Obtain the source
layers from CHGIS and follow its current terms if you rebuild or extend the historical core.

## REACHES

The climate input is an aggregate derived from the REACHES Chinese Historical Climate Database,
distributed through NOAA/WDS for Paleoclimatology. The raw record and coding files are absent from
Git. The repository records the upstream licence as unknown and publishes only aggregated event
counts used by the model. See `sources/snapshots/climate-and-literature.yaml` and
`docs/v2/data-rights-notice.md`.

## Literature and runtime fixtures

Paywalled literature is cited or summarized and is not redistributed. Runtime decision fixtures in
`tests/fixtures/llm/` are sanitized test records; they contain no account identifiers or credentials.

## No relicensing of external material

External material and derived facts retain any restrictions imposed by their sources. Inclusion in
this repository does not relicense them under MIT. Users are responsible for checking the current
terms that apply to their use. This notice records the project's provenance boundary and is not legal
advice.
