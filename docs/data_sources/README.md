# Case data source manifests

These text manifests record filenames and source identifiers for inputs used
in the three field cases. They contain no survey measurements. They were
compiled from the local data folders so a reader can match renamed case inputs
to a public release without access to the authors' checkout.

- `cedar_rapids.tsv`: ERT and AEM releases, including original filenames and DOIs.
- `llano.tsv`: the USGS case release and the separately sourced terrain tile.
- `forge/gravity.tsv`, `forge/seismic.tsv`, `forge/wells.tsv`: the renamed
  files in those three FORGE input groups.
- `forge/tem.tsv`, `forge/mt.tsv`, `forge/terrain.tsv`: the local soundings,
  MT sites and cropped model, and derived terrain raster. See the
  [FORGE case note](../case1_forge.md#the-data) for source identifiers and
  exclusions.

The manifests describe provenance and intended local paths. They do not
download data, assert redistribution rights, or certify checksums. The
[reproduction guide](../reproducibility.md) records what is still needed for a
fresh clone to rerun the paper.
