"""A1's second half: a column checked against what the ground holds."""

import numpy as np
import pytest

from ofag.agent.domains import (
    DOMAINS,
    Domain,
    OutOfDomain,
    domain_for,
    inspect,
    refuse_out_of_domain,
)
from ofag.core.constants import QuantityType

RESISTIVITY = DOMAINS[QuantityType.RESISTIVITY]
ANOMALY = DOMAINS[QuantityType.MAGNETIC_ANOMALY]


class TestTheDefectsItCatches:
    def test_an_impedance_that_lost_mu_nought(self) -> None:
        """The phase stays at a perfect 45 degrees and the resistivity does not."""
        with pytest.raises(OutOfDomain, match="5.2e\\+12"):
            refuse_out_of_domain(DOMAINS[QuantityType.APPARENT_RESISTIVITY], np.full(200, 5.2e12))

    def test_a_sentinel_that_is_a_number(self) -> None:
        """F031. Ten per cent of the column is -99999 and ninety is ordinary; the mean comes
        back plausible, low, and wrong."""
        column = np.r_[np.full(180, 120.0), np.full(20, -99999.0)]

        with pytest.raises(OutOfDomain, match="20 of 200"):
            refuse_out_of_domain(RESISTIVITY, column)

    def test_a_total_field_wearing_an_anomaly_s_name(self) -> None:
        """F058. Every reading is a perfectly ordinary magnetic flux density and the set of
        them is not an anomaly, so no bound on the extremes reaches it -- the median does."""
        rng = np.random.default_rng(0)
        unreduced = 55_762e-9 + rng.normal(0, 907e-9, 5_000)

        with pytest.raises(OutOfDomain, match="every magnetic anomaly is possible"):
            refuse_out_of_domain(ANOMALY, unreduced)

    def test_a_column_of_milliseconds_read_as_seconds(self) -> None:
        """A factor of a thousand that an inversion absorbs into the velocity scale and
        reports a healthy misfit for."""
        with pytest.raises(OutOfDomain, match="traveltime"):
            refuse_out_of_domain(DOMAINS[QuantityType.TRAVELTIME], np.linspace(5, 60, 24))


class TestWhatHasToPass:
    def test_a_real_anomaly(self) -> None:
        """Comfortably inside rather than barely: the bound is two orders above where a
        residual's median lands, which is the margin that keeps it from firing on sampling
        noise."""
        rng = np.random.default_rng(1)
        seen = refuse_out_of_domain(ANOMALY, rng.normal(0, 2_000e-9, 5_000))

        assert seen.inside
        assert ANOMALY.median is not None
        assert abs(seen.median) < ANOMALY.median[1] / 10

    def test_a_real_resistivity_section_spanning_five_decades(self) -> None:
        """Llano runs 30 to 1,400 ohm-metres and FORGE's granite is higher still."""
        assert refuse_out_of_domain(RESISTIVITY, np.geomspace(0.5, 20_000, 400)).inside

    def test_a_spread_of_first_arrivals_in_seconds(self) -> None:
        picks = np.linspace(0.004, 0.061, 24)

        assert refuse_out_of_domain(DOMAINS[QuantityType.TRAVELTIME], picks).inside


class TestReadingWithoutJudging:
    def test_the_non_finite_are_counted_rather_than_dropped(self) -> None:
        """A column that is nine per cent NaN gives a plausible mean, and the count is the
        only thing that says so."""
        seen = inspect(RESISTIVITY, np.r_[np.full(91, 120.0), np.full(9, np.nan)])

        assert seen.non_finite == 9
        assert seen.count == 100
        assert seen.inside

    def test_a_column_with_nothing_finite_in_it_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="no finite value"):
            inspect(RESISTIVITY, np.full(10, np.nan))

    def test_the_summary_says_the_span_and_flags_the_bad(self) -> None:
        summary = inspect(RESISTIVITY, np.r_[np.full(9, 120.0), [-99999.0]]).summary

        assert "resistivity: 10 values" in summary
        assert "outside what the ground holds" in summary


class TestTheTable:
    def test_a_quantity_with_no_defensible_bound_has_none(self) -> None:
        """Nine of twenty-nine. A domain nobody can justify is one that gets widened the
        first time it fires rather than consulted."""
        assert domain_for(QuantityType.CHARGEABILITY) is None
        assert len(DOMAINS) == 9

    def test_every_bound_names_the_rock_at_each_end(self) -> None:
        """An arithmetic reason -- "it should be positive" -- is a reason that loses the
        argument the first time somebody wants it widened."""
        for domain in DOMAINS.values():
            assert len(domain.because) > 40, domain.what
            assert domain.low < domain.high

    def test_the_median_bound_sits_inside_the_extremes(self) -> None:
        for domain in DOMAINS.values():
            if domain.median is None:
                continue
            low, high = domain.median
            assert domain.low <= low < high <= domain.high, domain.what

    def test_conductivity_and_resistivity_describe_the_same_rocks(self) -> None:
        """Reciprocals, so the bounds have to be reciprocals too or one of them admits a rock
        the other refuses."""
        resistivity = DOMAINS[QuantityType.RESISTIVITY]
        conductivity = DOMAINS[QuantityType.CONDUCTIVITY]

        assert conductivity.low == pytest.approx(1 / resistivity.high)
        assert conductivity.high == pytest.approx(1 / resistivity.low)

    def test_an_ad_hoc_bound_works_the_same_way(self) -> None:
        """F005: an export carrying an easting of 3.35e15, which is not a place."""
        easting = Domain(
            what="UTM easting",
            unit="m",
            low=166_000.0,
            high=834_000.0,
            because="a UTM zone is six degrees wide and its easting is bounded by the "
            "projection itself, whatever the ground is",
        )

        with pytest.raises(OutOfDomain, match="UTM easting"):
            refuse_out_of_domain(easting, np.r_[np.full(99, 600_000.0), [3.35e15]])
