"""The rubric the control arm is graded by, and whether it is a fair one."""

import pytest

from ofag.agent.arms import ELEMENTS, score_prose
from ofag.agent.replay import load_replays

#: Everything the schema would have made mandatory, said in prose and in no particular
#: order.
COMPLETE = (
    "Use electrodes_xyz.txt rather than the embedded block. The scatter of the second "
    "difference along the line is 0.225 m for the table against 1.346 for the block, so the "
    "block is implausibly rough for a surveyed profile. The alternative is to take the "
    "embedded block, and the cost of choosing wrongly is up to 2.44 m of vertical position "
    "against a borehole. The data cannot settle which is authoritative, so this is a "
    "judgement rather than a measurement. It would be wrong if a third elevation source "
    "appears and disagrees with the table."
)

#: The same conclusion with nothing behind it.
THIN = "Use the separate table. It looks cleaner and the block is noisy."


@pytest.fixture(scope="module")
def f037():
    return {replay.lesson: replay for replay in load_replays()}["F037"]


class TestTheRubricIsFair:
    def test_a_careful_answer_can_reach_full_marks(self, f037) -> None:
        """Written as prose, with no instruction about shape."""
        scored = score_prose(f037, COMPLETE)

        assert scored.absent == ()
        assert scored.named_everything

    def test_a_thin_answer_scores_nothing(self, f037) -> None:
        """And it reaches the same conclusion, which is the point: the rubric is about what
        was established, not about which option was chosen."""
        scored = score_prose(f037, THIN)

        assert scored.present == ()
        assert len(scored.missed) == 2

    def test_the_content_half_is_the_same_rule_both_arms_are_graded_by(self, f037) -> None:
        """`must_name` is matched over everything either arm says, by the same substring
        test, so the facts half of the comparison is exact and only the form half is
        generous."""
        from ofag.agent.replay import score

        assert score_prose(f037, COMPLETE).missed == ()
        assert [group for group in f037.must_name] and score.__doc__


class TestWhatEachElementCatches:
    @pytest.mark.parametrize(
        ("element", "said"),
        [
            ("an alternative", "the alternative is to take the embedded block"),
            ("what the alternative costs", "the cost is up to 2.44 m of vertical position"),
            ("measured or judged, said", "the data cannot settle which is authoritative"),
            ("a reversal condition", "it would be wrong if a third source appears"),
        ],
    )
    def test_each_is_reachable_on_its_own(self, f037, element: str, said: str) -> None:
        assert element in score_prose(f037, said).present

    def test_none_of_them_fires_on_a_bare_conclusion(self, f037) -> None:
        assert score_prose(f037, "Take the table.").present == ()

    def test_every_element_says_why_it_is_in_the_rubric(self) -> None:
        """A rubric line with no reason behind it is one that gets argued about after the
        result is in."""
        for item in ELEMENTS:
            assert len(item.why) > 30, item.name
