"""The situation F014 was decided in, regenerated from the release."""

import pathlib
import sys

import numpy as np

CASE = pathlib.Path("data/case1_Utah FORGE/mt/edi")

#: The band a layered inversion of this survey would be run over, in seconds.
_BAND = (0.01, 100.0)


def measures(tensor: np.ndarray, periods: np.ndarray) -> dict[str, float]:
    """Three things a tensor says about its own dimensionality."""
    keep = (periods >= _BAND[0]) & (periods <= _BAND[1])
    zxx, zxy, zyx, zyy = (tensor[keep, i, j] for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "diagonal leakage": float(
                np.nanmedian((np.abs(zxx) + np.abs(zyy)) / (np.abs(zxy) + np.abs(zyx)))
            ),
            "off-diagonal asymmetry": float(np.nanmedian(np.abs(zxy + zyx) / np.abs(zxy - zyx))),
            "off-diagonal ratio": float(np.nanmedian(np.abs(zxy) / np.abs(zyx))),
        }


def main() -> None:
    sys.path.insert(0, "src")
    from ofag.formats.edi import read_edi

    files = sorted(p for p in CASE.glob("*.edi") if "_bvv" not in p.name)
    rows = []
    for path in files:
        station = read_edi(path)
        rows.append((path.stem, measures(station.impedance(), 1.0 / station.frequencies_hz)))

    names = list(rows[0][1])
    print(f"{len(rows)} sites. A layered inversion will accept all of them.")
    print()
    print(
        "How far each tensor is from one-dimensional, over "
        f"{_BAND[0]} to {_BAND[1]} s. Zero is layered:"
    )
    print()
    print(f"   {'measure':24s} {'min':>8s} {'median':>8s} {'p90':>8s} {'max':>8s}")
    for name in names:
        values = np.array([row[1][name] for row in rows])
        print(
            f"   {name:24s} {np.nanmin(values):8.3f} {np.nanmedian(values):8.3f} "
            f"{np.nanpercentile(values, 90):8.3f} {np.nanmax(values):8.3f}"
        )
    print()
    print("The three do not rank the sites the same way:")
    order = {name: [r[0] for r in sorted(rows, key=lambda r: -r[1][name])][:5] for name in names}
    for name in names:
        print(f"   worst five by {name:24s} {', '.join(order[name])}")
    print()
    shared = set.intersection(*(set(order[name]) for name in names))
    print(f"   sites in all three worst-fives: {sorted(shared) or 'none'}")
    print()
    print("Nothing in the release marks a site as one-dimensional or not.")


if __name__ == "__main__":
    main()
