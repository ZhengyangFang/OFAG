"""A15: what a library call does, as opposed to what it is called."""

import pytest
from pydantic import ValidationError

from ofag.agent.defaults import (
    Behaviour,
    Leans,
    UnaccountedCall,
    refuse_assumed_behaviour,
    refuse_unaccounted_calls,
)

#: F021, as it should have been recorded. Three occurrences before it was.
UNSET_SMOOTHNESS = Behaviour(
    call="simpeg.regularization.Smallness.alpha_s",
    leans=Leans.UNSET,
    assumed="left at None it contributes nothing, so the model is the data's",
    observed="SimPEG scales a weight left at None by the square of the cell size, so on a "
    "graded mesh the unset weight varies by orders of magnitude across the volume",
    probe="inverted the same data twice, once at None and once at 1.0, and differenced",
    costs="three occurrences in one case before it was named (F007, F021)",
)

#: F053, which an agent found with no gate in front of it.
COVERAGE_CONVENTION = Behaviour(
    call="pygimli.physics.ert.ERTManager.coverage",
    leans=Leans.RETURN,
    assumed="the cumulative sensitivity, as summed",
    observed="log10(covTrans / paramSizes): already divided by cell area and already logged, "
    "unlike the linear covTrans / cellSizes() of the MeshMethodManager it inherits from",
    probe="read the stored array: min -2.774, max 0.422, negative and so logged",
    costs="read as raw it returns the depth of the mesh bottom, 37.0 and 41.3 m against 12.5",
)


def test_a_behaviour_established_by_reading_the_docs_is_refused() -> None:
    """The rule, and the reason for it: A15's five failures are all readings, and in two of
    them the documentation was itself wrong."""
    with pytest.raises(ValidationError, match="Name what was run"):
        Behaviour(
            call="simpeg.regularization.Smallness.alpha_s",
            leans=Leans.UNSET,
            assumed="an unset weight is a neutral weight",
            observed="the documentation says it defaults to a weight of one",
            probe="the docstring for the regularization class",
        )


@pytest.mark.parametrize(
    "probe",
    [
        "according to the SimPEG tutorial",
        "as documented in the release notes",
        "read the signature",
    ],
)
def test_every_way_of_saying_nothing_was_run_is_refused(probe: str) -> None:
    with pytest.raises(ValidationError, match="Name what was run"):
        Behaviour(
            call="a.call",
            leans=Leans.RETURN,
            assumed="it does what it says",
            observed="something long enough to be a real observation of behaviour",
            probe=probe,
        )


def test_an_observation_too_short_to_be_one_is_refused() -> None:
    with pytest.raises(ValidationError):
        Behaviour(
            call="a.call",
            leans=Leans.RETURN,
            assumed="it does what it says",
            observed="it does not",
            probe="ran it",
        )


def test_the_two_real_records_stand() -> None:
    assert refuse_assumed_behaviour([UNSET_SMOOTHNESS, COVERAGE_CONVENTION]) == (
        UNSET_SMOOTHNESS,
        COVERAGE_CONVENTION,
    )


class TestAccountingForWhatARunLeansOn:
    def test_a_call_with_no_measured_behaviour_is_refused(self) -> None:
        """The A3 shape moved from the file to the library."""
        with pytest.raises(UnaccountedCall, match="2 of 3"):
            refuse_unaccounted_calls(
                [
                    "simpeg.regularization.Smallness.alpha_s",
                    "simpeg.utils.WeightedGaussianMixture.order_clusters_GM_weight",
                    "scipy.interpolate.NearestNDInterpolator",
                ],
                [UNSET_SMOOTHNESS],
            )

    def test_the_refusal_names_the_calls_that_are_missing(self) -> None:
        with pytest.raises(UnaccountedCall) as raised:
            refuse_unaccounted_calls(["a.missing.call"], [])

        assert "a.missing.call" in str(raised.value)

    def test_a_complete_accounting_comes_back_in_the_order_asked(self) -> None:
        wanted = [
            "pygimli.physics.ert.ERTManager.coverage",
            "simpeg.regularization.Smallness.alpha_s",
        ]

        got = refuse_unaccounted_calls(wanted, [UNSET_SMOOTHNESS, COVERAGE_CONVENTION])

        assert [b.call for b in got] == wanted

    def test_leaning_on_nothing_is_accounted_for(self) -> None:
        assert refuse_unaccounted_calls([], []) == ()
