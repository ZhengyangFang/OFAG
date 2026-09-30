"""The situation F015 was decided in, regenerated from the release."""

import pathlib
import sys

import numpy as np

CASE = pathlib.Path("data/case1_Utah FORGE/mt/edi")

#: Periods to print, in seconds.
_PERIODS = (0.01, 1.0, 100.0)


def main() -> None:
    sys.path.insert(0, "src")
    from ofag.formats.edi import apparent_resistivity_ohm_m, read_edi

    files = sorted(p for p in CASE.glob("*.edi") if "_bvv" not in p.name)
    print(f"{len(files)} magnetotelluric sites, each a 2 by 2 impedance tensor per period.")
    print("A layered inversion takes one impedance. These are the four it has to")
    print("come from, at three sites and three periods:")
    print()
    for path in files[:3]:
        station = read_edi(path)
        tensor = station.impedance()
        periods = 1.0 / station.frequencies_hz
        print(f"{path.stem}  {tensor.shape[0]} periods")
        header = f"   {'period (s)':>11s} " + " ".join(
            f"{name:>13s}" for name in "xx xy yx yy".split()
        )
        print(header)
        for target in _PERIODS:
            index = int(np.argmin(np.abs(periods - target)))
            row = tensor[index]
            print(
                f"   {periods[index]:11.4g} "
                + " ".join(f"{abs(row[i, j]):13.4g}" for i, j in ((0, 0), (0, 1), (1, 0), (1, 1)))
            )
        # What the candidate reductions give, at the middle period.
        index = int(np.argmin(np.abs(periods - 1.0)))
        row, period = tensor[index], periods[index]
        candidates = {
            "Zxy": row[0, 1],
            "Zyx": row[1, 0],
            "(Zxy - Zyx) / 2": (row[0, 1] - row[1, 0]) / 2.0,
            "-Zyx": -row[1, 0],
            "sqrt(Zxy * -Zyx)": np.sqrt(row[0, 1] * -row[1, 0]),
            "determinant": np.sqrt(row[0, 0] * row[1, 1] - row[0, 1] * row[1, 0]),
        }
        print(f"   at {period:.4g} s, apparent resistivity from each reduction:")
        for name, value in candidates.items():
            rho = apparent_resistivity_ohm_m(np.array([value]), np.array([period]))[0]
            print(f"      {name:18s} |Z| {abs(value):10.4g}   rho_a {rho:9.1f} ohm.m")
        print()
    print("Nothing in the release states a reduction. The two off-diagonals differ,")
    print("the diagonals are not zero, and a one-dimensional earth would have")
    print("Zxy = -Zyx with the diagonals at zero.")


if __name__ == "__main__":
    main()
