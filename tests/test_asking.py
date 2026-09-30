"""The order a decision has to go through before it reaches a person."""

import pytest

from ofag.agent.asking import (
    MEASURE_RATHER_THAN_ASK_SECONDS,
    AskedWhatCouldBeMeasured,
    Finding,
    Next,
    Probe,
    Question,
    classify,
    pose,
    settle,
)
from ofag.agent.decisions import Option, Settlement

TOPOGRAPHY = (
    Option(
        name="invert at elevation",
        cost="carries the release's own surface into the section, wherever that surface is",
    ),
    Option(
        name="invert flat",
        cost="the section cannot be compared with a hole or a crossing line at real elevations",
    ),
)

REVERSAL = "a surface measured to better than the 2.44 m the release's two lists differ by appears"


def _question(*probes: Probe) -> Question:
    return Question(
        question="Invert case 3's resistivity profiles at elevation, or flat?",
        options=TOPOGRAPHY,
        at="scripts/case3_llano.py::USE_TOPOGRAPHY",
        probes=probes,
    )


def _probe(seconds: float, timing: str = "measured", favours: str = "", result: str = "") -> Probe:
    return Probe(
        what="invert both profiles flat and at elevation and compare chi-squared",
        seconds=seconds,
        timing=timing,  # type: ignore[arg-type]
        run=lambda: Finding(favours=favours, result=result or "3.074 flat against 3.090"),
    )


class TestClassifying:
    def test_something_cheap_that_separates_them_is_run_not_asked(self) -> None:
        verdict = classify(_question(_probe(1.0)).probes)

        assert verdict.next is Next.MEASURE
        assert "on a clock" in verdict.because

    def test_a_question_with_nothing_runnable_behind_it_is_a_question(self) -> None:
        verdict = classify(_question().probes)

        assert verdict.next is Next.ASK
        assert verdict.probe is None
        assert "nothing runnable" in verdict.because

    def test_an_expensive_measurement_a_clock_has_seen_earns_the_question(self) -> None:
        """Case 2's airborne inversion is 1,762 s."""
        verdict = classify(_question(_probe(1762.0)).probes)

        assert verdict.next is Next.ASK
        assert "1762 s" in verdict.because

    def test_an_expensive_estimate_is_timed_rather_than_believed(self) -> None:
        """F055: the gravity plugin estimates 3,576,586 s for a run that takes minutes."""
        verdict = classify(_question(_probe(3_576_586.0, timing="estimated")).probes)

        assert verdict.next is Next.TIME_IT_FIRST
        assert "F055" in verdict.because

    def test_a_cheap_estimate_is_just_run(self) -> None:
        """Being wrong about a two-minute estimate costs two minutes."""
        verdict = classify(_question(_probe(30.0, timing="estimated")).probes)

        assert verdict.next is Next.MEASURE
        assert "even if the estimate is optimistic" in verdict.because

    def test_the_cheapest_probe_is_the_one_chosen(self) -> None:
        cheap, dear = _probe(1.0), _probe(90.0)
        verdict = classify(_question(dear, cheap).probes)

        assert verdict.probe is cheap

    def test_a_timed_probe_is_preferred_to_a_cheaper_guess(self) -> None:
        """Both are under the bar, so both get run; the one with a clock behind it is the one
        whose cost the reason can quote."""
        guess, timed = _probe(1.0, timing="estimated"), _probe(60.0)
        verdict = classify(_question(guess, timed).probes)

        assert verdict.probe is timed

    def test_one_option_is_not_a_question(self) -> None:
        with pytest.raises(ValueError, match="at least two options"):
            Question(question="?" * 30, options=TOPOGRAPHY[:1], at="x.py::Y")


class TestMeasuringFirst:
    def test_a_measurement_that_separates_them_settles_it(self) -> None:
        settled = settle(
            _question(_probe(1.0, favours="invert flat", result="3.074 flat against 3.090")),
            reverses_if=REVERSAL,
        )

        assert settled is not None
        assert settled.record.settlement is Settlement.MEASURED
        assert settled.record.chose == "invert flat"
        assert settled.record.measurement is not None
        assert "3.074" in settled.record.measurement

    def test_a_measurement_that_does_not_separate_them_is_a_result(self) -> None:
        """The commonest outcome on real data, and the one the first draft of this project
        got wrong: 3.074 against 3.090 is a tie, and a tie means the question survives
        rather than that the measurement failed."""
        assert settle(_question(_probe(1.0)), reverses_if=REVERSAL) is None

    def test_a_probe_cannot_favour_an_option_that_was_not_offered(self) -> None:
        with pytest.raises(ValueError, match="not one of"):
            settle(_question(_probe(1.0, favours="invert on lidar")), reverses_if=REVERSAL)

    def test_nothing_to_run_is_an_error_rather_than_a_silent_pass(self) -> None:
        with pytest.raises(ValueError, match="nothing to run"):
            settle(_question(), reverses_if=REVERSAL)


class TestPosing:
    def test_a_question_something_cheap_would_close_is_refused(self) -> None:
        with pytest.raises(AskedWhatCouldBeMeasured, match="not a question yet"):
            pose(
                _question(_probe(1.0)),
                recommend="invert flat",
                because="it is simpler",
                reverses_if=REVERSAL,
            )

    def test_an_expensive_estimate_is_refused_too_until_it_is_timed(self) -> None:
        with pytest.raises(AskedWhatCouldBeMeasured, match="time it first"):
            pose(
                _question(_probe(3_576_586.0, timing="estimated")),
                recommend="invert flat",
                because="forty-one days is too long to wait",
                reverses_if=REVERSAL,
            )

    def test_what_is_posed_says_why_it_was_not_measured(self) -> None:
        """The field that is usually missing."""
        posed = pose(
            _question(),
            recommend="invert at elevation",
            because="the section has to be compared with a hole and a crossing line",
            reverses_if=REVERSAL,
            informed_by=("inverting both ways gives 3.074 flat against 3.090, a tie",),
        )
        prompt = posed.as_prompt()

        assert "Not measured because nothing runnable" in prompt
        assert "-> invert at elevation" in prompt
        assert "cannot be compared with a hole" in prompt
        assert "Measured first, and it did not separate them" in prompt
        assert "scripts/case3_llano.py::USE_TOPOGRAPHY" in prompt

    def test_recommending_something_that_is_not_on_the_list_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not one of"):
            pose(
                _question(),
                recommend="invert on lidar",
                because="a third surface would settle it",
                reverses_if=REVERSAL,
            )


def test_the_whole_loop_ends_in_a_block_the_audit_reads_back(tmp_path) -> None:
    """Check that the audit reads a recorded decision."""
    from ofag.agent.audit import audit_script

    posed = pose(
        _question(),
        recommend="invert at elevation",
        because="the section has to be compared with a hole that refuses at 2.3 m and with a "
        "seismic line that crosses it, and both of those are at real elevations",
        reverses_if=REVERSAL,
        informed_by=("inverting both ways gives 3.074 flat against 3.090, which is a tie",),
    )
    record = posed.accept("invert at elevation")

    script = tmp_path / "case_example.py"
    script.write_text(record.as_comment() + "\nUSE_TOPOGRAPHY = True\n", encoding="utf-8")
    (found,) = audit_script(script)

    assert found.constant == "USE_TOPOGRAPHY"
    assert found.reads_as_choice
    assert found.states_reversal
    assert record.settlement is Settlement.JUDGED
    assert record.measurement is None
    assert "does not settle this" in record.as_comment()


def test_the_bar_is_the_one_the_run_history_measured() -> None:
    """Asserted so it moves on purpose."""
    assert MEASURE_RATHER_THAN_ASK_SECONDS == 120.0


class TestPlacingItInTheCode:
    """The last step, and the one `ofag.record_decision` refuses to take."""

    def _record(self, at: str = "case_example.py::USE_TOPOGRAPHY"):
        return pose(
            Question(
                question="Invert case 3's resistivity profiles at elevation, or flat?",
                options=TOPOGRAPHY,
                at=at,
            ),
            recommend="invert at elevation",
            because="the section has to be compared with a hole that refuses at 2.3 m and a "
            "seismic line that crosses it, both at real elevations",
            reverses_if=REVERSAL,
        ).accept("invert at elevation")

    def test_the_block_lands_above_the_constant_and_the_audit_finds_it(self, tmp_path) -> None:
        from ofag.agent.asking import place
        from ofag.agent.audit import audit_script

        script = tmp_path / "case_example.py"
        script.write_text("LAMBDA = 20.0\nUSE_TOPOGRAPHY = True\n", encoding="utf-8")

        place(self._record(), root=tmp_path, apply=True)
        found = {choice.constant: choice for choice in audit_script(script)}

        assert set(found) == {"USE_TOPOGRAPHY"}
        assert found["USE_TOPOGRAPHY"].reads_as_choice
        assert found["USE_TOPOGRAPHY"].states_reversal
        assert script.read_text(encoding="utf-8").startswith("LAMBDA = 20.0\n#:")

    def test_nothing_is_written_unless_it_is_asked_for(self, tmp_path) -> None:
        from ofag.agent.asking import place

        script = tmp_path / "case_example.py"
        script.write_text("USE_TOPOGRAPHY = True\n", encoding="utf-8")

        assert "#:" in place(self._record(), root=tmp_path)
        assert script.read_text(encoding="utf-8") == "USE_TOPOGRAPHY = True\n"

    def test_a_constant_that_already_has_a_record_is_not_overwritten(self, tmp_path) -> None:
        """Two decisions about one constant means one of them was reversed, and case 3's
        elevation source is what that looks like: the reversal is the thing to write down,
        not the thing to erase."""
        from ofag.agent.asking import AlreadyRecorded, place

        script = tmp_path / "case_example.py"
        script.write_text("#: chosen deliberately\nUSE_TOPOGRAPHY = True\n", encoding="utf-8")

        with pytest.raises(AlreadyRecorded, match="already has a"):
            place(self._record(), root=tmp_path)

    def test_a_location_that_names_no_constant_is_refused(self, tmp_path) -> None:
        from ofag.agent.asking import place

        (tmp_path / "case_example.py").write_text("LAMBDA = 20.0\n", encoding="utf-8")

        with pytest.raises(ValueError, match="no constant or function"):
            place(self._record(), root=tmp_path)

    def test_a_recorded_at_with_no_constant_in_it_is_refused(self, tmp_path) -> None:
        from ofag.agent.asking import place

        with pytest.raises(ValueError, match="path/to/file.py::CONSTANT_NAME"):
            place(self._record(at="case_example.py"), root=tmp_path)
