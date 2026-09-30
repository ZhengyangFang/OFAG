"""Fetch the land surface under case 3, from USGS 3DEP 1 m lidar."""

from pathlib import Path

import numpy as np

CASE = Path("data/case3_Llano")
DEM = CASE / "dem/llano_3dep_1m.tif"
CRS = "EPSG:26914"

TILE = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/"
    "TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA/TIFF/"
    "USGS_1M_14_x55y340_TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA.tif"
)
SCIENCEBASE = "https://www.sciencebase.gov/catalog/item/619c3717d34eb622f6931b2b"
CITATION = (
    "U.S. Geological Survey, 20211120, USGS 1 Meter 14 x55y340 "
    "TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA: U.S. Geological Survey."
)

#: How far past the outermost station the surface is kept.
MARGIN_M = 400.0

#: Every file in the release that carries a position, so the window is drawn round the
#: survey rather than round the lines that happen to be modelled.
STATIONS = ("ert/electrodes_xyz.txt", "srt/geometry.txt", "sp/survey.txt")


def _survey_bounds() -> tuple[float, float, float, float]:
    """The survey's extent in UTM, from every station the release places."""
    from pyproj import Transformer

    latitude: list[float] = []
    longitude: list[float] = []
    for name in STATIONS:
        table = np.genfromtxt(CASE / name, delimiter="\t", names=True, encoding="utf-8")
        latitude += list(table["Latitude"])
        longitude += list(table["Longitude"])
    east, north = Transformer.from_crs("EPSG:4326", CRS, always_xy=True).transform(
        np.array(longitude), np.array(latitude)
    )
    return (
        east.min() - MARGIN_M,
        north.min() - MARGIN_M,
        east.max() + MARGIN_M,
        north.max() + MARGIN_M,
    )


def fetch() -> None:
    import rasterio
    from rasterio.windows import from_bounds

    bounds = _survey_bounds()
    DEM.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(f"/vsicurl/{TILE}") as source:
        if source.crs.to_string() != CRS:
            raise SystemExit(f"tile is {source.crs}, expected {CRS}")
        window = from_bounds(*bounds, transform=source.transform)
        band = source.read(1, window=window)
        profile = source.profile | {
            "driver": "GTiff",
            "height": band.shape[0],
            "width": band.shape[1],
            "transform": source.window_transform(window),
            "compress": "deflate",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
        }
        with rasterio.open(DEM, "w", **profile) as destination:
            destination.write(band, 1)
            destination.update_tags(
                source=TILE.rsplit("/", 1)[-1],
                sciencebase=SCIENCEBASE,
                object_key=TILE,
                citation=CITATION,
                cropped_by="scripts/fetch_llano_dem.py",
            )

    ground = band[band > -1e4]
    if ground.size != band.size:
        raise SystemExit(f"{band.size - ground.size} cells have no elevation in the window")
    print(
        f"dem       {band.shape[1]} by {band.shape[0]} m at 1 m, {DEM.stat().st_size / 1e6:.1f} MB"
    )
    print(f"          {ground.min():.2f} to {ground.max():.2f} m NAVD88 over the window")
    print(f"          {DEM.as_posix()}, from {SCIENCEBASE}")


if __name__ == "__main__":
    fetch()
