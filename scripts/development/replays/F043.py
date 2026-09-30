"""The situation F043 was decided in, regenerated from the release."""

import pathlib
import sys

import numpy as np

CASE = pathlib.Path("data/case3_Llano/srt")


def main() -> None:
    sys.path.insert(0, "src")
    from ofag.formats.seisimager import read_first_arrivals

    print("Two first-arrival pick files. Some traveltimes repeat to the last decimal.")
    print()
    for profile in (1, 2):
        arrivals = read_first_arrivals(CASE / f"srt{profile}_first_arrivals.txt")
        repeated = sorted(arrivals.repeated_traveltimes.items(), key=lambda pair: -pair[1])
        print(
            f"SRT{profile}: {arrivals.traveltime_s.size} picks over {arrivals.parsed_shots} shots, "
            f"t {1e3 * arrivals.traveltime_s.min():.3f} to "
            f"{1e3 * arrivals.traveltime_s.max():.1f} ms"
        )
        print(f"   {'value (ms)':>12s} {'picks':>6s} {'offsets they sit at (m)':>26s}")
        for value, count in repeated[:4]:
            at = arrivals.offset_m[np.isclose(arrivals.traveltime_s, value, atol=1e-12)]
            print(f"   {1e3 * value:12.6f} {count:6d} {f'{at.min():.0f} to {at.max():.0f}':>26s}")
        # What the repeated value would imply if it were a measurement.
        floor = repeated[0][0] if repeated else None
        if floor is not None:
            at = arrivals.offset_m[np.isclose(arrivals.traveltime_s, floor, atol=1e-12)]
            moving = at[at > 0]
            if moving.size:
                print(
                    f"   read as a measurement, the most repeated value implies "
                    f"{moving.min() / floor:.0f} to {moving.max() / floor:.0f} m/s "
                    f"across its offsets"
                )
        others = [v for v, _ in repeated[1:]] if len(repeated) > 1 else []
        if others:
            print(
                "   other picks near it: "
                + ", ".join(f"{1e3 * v:.6f}" for v in sorted(others)[:3])
                + " ms"
            )
        print(
            f"   the whole file's picks carry "
            f"{len({f'{v:.9f}' for v in arrivals.traveltime_s})} distinct values"
        )
        print()
    print("The release's metadata says first arrivals 'were edited when necessary to")
    print("remove obvious errors'. It does not say what an unpicked trace was written as.")


if __name__ == "__main__":
    main()
