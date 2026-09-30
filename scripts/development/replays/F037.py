"""The situation F037 was decided in, regenerated from the release."""

import pathlib
import sys

import numpy as np

CASE = pathlib.Path("data/case3_Llano/ert")


def elevation_lists(profile: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Both of the release's statements of where the ground is, on one profile."""
    sys.path.insert(0, "src")
    from ofag.formats.res2dinv import read_res2dinv

    survey = read_res2dinv(CASE / f"ert{profile}_input.dat")
    block = survey.topography_m
    if block is None:
        raise SystemExit(f"ert{profile}_input.dat carries no topography block")

    table = np.genfromtxt(CASE / "electrodes_xyz.txt", delimiter="\t", names=True, encoding="utf-8")
    keep = table["ERT_Profile_ID"] == profile
    along = table["Profile_x_Coordinate_meters"][keep]
    separate = table["Surface_Elevation_meters_above_NAVD88"][keep]
    order = np.argsort(along)
    return block[:, 0], block[:, 1], separate[order]


def main() -> None:
    print("A resistivity release states the elevation of its electrodes twice.")
    print("One statement is a topography block inside each .dat; the other is a")
    print("separate table, electrodes_xyz.txt. Both cover the same 48 positions.")
    print()
    for profile in (1, 2):
        x, embedded, separate = elevation_lists(profile)
        difference = embedded - separate
        print(f"ERT{profile}: {x.size} positions, x {x.min():.0f} to {x.max():.0f} m")
        print(
            f"   embedded block   relief {np.ptp(embedded):5.2f} m   "
            f"mean {embedded.mean():8.3f}   "
            f"{len(np.unique(np.round(embedded, 2))):2d} distinct values"
        )
        print(
            f"   separate table   relief {np.ptp(separate):5.2f} m   "
            f"mean {separate.mean():8.3f}   "
            f"{len(np.unique(np.round(separate, 2))):2d} distinct values"
        )
        print(
            f"   they differ by up to {np.abs(difference).max():.2f} m, "
            f"mean difference {difference.mean():+.3f} m"
        )
        print(
            f"   same 48 values in a different order: "
            f"{np.allclose(np.sort(embedded), np.sort(separate), atol=0.011)}"
        )
        print(
            f"   scatter of the second difference along the line: "
            f"embedded {np.sqrt((np.diff(embedded, 2) ** 2).mean()):.3f} m, "
            f"table {np.sqrt((np.diff(separate, 2) ** 2).mean()):.3f} m"
        )
        print("   first eight, embedded: " + " ".join(f"{v:.2f}" for v in embedded[:8]))
        print("   first eight, table   : " + " ".join(f"{v:.2f}" for v in separate[:8]))
        print()
    print("Nothing in the release marks the disagreement or says which is authoritative.")


if __name__ == "__main__":
    main()
