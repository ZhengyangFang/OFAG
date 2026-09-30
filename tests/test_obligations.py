"""What a run owes, and what happens when it does not pay."""

from pathlib import Path

import pytest

from ofag.agent.obligations import (
    LEDGER_FILENAME,
    Discharge,
    Ledger,
    NotIndependent,
    ObligationError,
    Stage,
    Vetoed,
)

#: Two specifications that differ.
SPEC = "a" * 64
EDITED = "b" * 64


def test_existing_ledger_observes_another_readers_veto(tmp_path):
    path = tmp_path / LEDGER_FILENAME
    first = Ledger(path)
    discharged_through(first, Stage.ADOPTED, Stage.DIAGNOSED, by="producer")
    other = Ledger(path)
    other.discharge(Stage.VETOED, SPEC, "the evidence does not support this result", by="auditor")
    with pytest.raises(Vetoed):
        first.discharge(Stage.AUDITED, SPEC, "independent review of all evidence", by="reader")
    assert first.entries() == other.entries()


def test_failed_write_does_not_discharge_in_memory(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path / LEDGER_FILENAME)

    def fail_open(*args, **kwargs):
        raise OSError("disk write failed")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", fail_open)
        with pytest.raises(OSError, match="disk write failed"):
            ledger.discharge(Stage.SPECIFIED, SPEC, "specification checked and recorded")
    assert not ledger.has(Stage.SPECIFIED, SPEC)


def discharged_through(ledger: Ledger, *stages: Stage, spec: str = SPEC, by: str = "") -> None:
    for stage in stages:
        ledger.discharge(stage, spec, f"{stage.value} discharged, with something checked", by=by)


def test_a_stage_entered_owing_something_says_what(tmp_path) -> None:
    ledger = Ledger(tmp_path / LEDGER_FILENAME)
    ledger.discharge(Stage.SPECIFIED, SPEC, "a RunSpec exists and was fingerprinted")

    with pytest.raises(ObligationError) as raised:
        ledger.require(Stage.EXECUTED, SPEC)

    assert raised.value.missing == (
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
    )
    assert "conventions_checked" in str(raised.value)


def test_an_obligation_cannot_be_discharged_out_of_order(tmp_path) -> None:
    """Recording "executed" before "validated" would make the ledger a log of what happened
    rather than a record of what was owed."""
    ledger = Ledger(tmp_path / LEDGER_FILENAME)

    with pytest.raises(ObligationError, match="specified"):
        ledger.discharge(Stage.VALIDATED, SPEC, "validate returned no issues")


def test_evidence_has_to_say_what_was_checked(tmp_path) -> None:
    ledger = Ledger(tmp_path / LEDGER_FILENAME)

    with pytest.raises(ValueError, match="what was done and checked"):
        ledger.discharge(Stage.SPECIFIED, SPEC, "ok")


def test_an_obligation_belongs_to_a_specification_and_not_to_a_run(tmp_path) -> None:
    """The part that does the work."""
    ledger = Ledger(tmp_path / LEDGER_FILENAME)
    discharged_through(
        ledger, Stage.SPECIFIED, Stage.VALIDATED, Stage.CONVENTIONS_CHECKED, Stage.ESTIMATED
    )
    ledger.require(Stage.EXECUTED, SPEC)

    with pytest.raises(ObligationError) as raised:
        ledger.require(Stage.EXECUTED, EDITED)
    assert set(raised.value.missing) == {
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
    }


def test_a_walk_on_five_samples_is_owed_when_the_caller_says_it_is(tmp_path) -> None:
    """C4 (F084), and the one conditional obligation."""
    ledger = Ledger(tmp_path / LEDGER_FILENAME)
    discharged_through(
        ledger, Stage.SPECIFIED, Stage.VALIDATED, Stage.CONVENTIONS_CHECKED, Stage.ESTIMATED
    )

    ledger.require(Stage.EXECUTED, SPEC)
    with pytest.raises(ObligationError) as raised:
        ledger.require(Stage.EXECUTED, SPEC, also=[Stage.SAMPLED])
    assert raised.value.missing == (Stage.SAMPLED,)

    ledger.discharge(Stage.SAMPLED, SPEC, "5 soundings ran; progress.jsonl read back, 3 events")
    ledger.require(Stage.EXECUTED, SPEC, also=[Stage.SAMPLED])


def test_the_ledger_survives_the_process_that_wrote_it(tmp_path) -> None:
    """Numerical work runs in a child process."""
    path = tmp_path / LEDGER_FILENAME
    discharged_through(Ledger(path), Stage.SPECIFIED, Stage.VALIDATED)

    reopened = Ledger(path)
    assert reopened.has(Stage.VALIDATED, SPEC)
    assert not reopened.has(Stage.EXECUTED, SPEC)
    assert len(reopened.entries(SPEC)) == 2


def test_the_ledger_is_append_only(tmp_path) -> None:
    """Retracting an obligation is indistinguishable from never having had it, and the
    difference matters when reading back why a run proceeded."""
    path = tmp_path / LEDGER_FILENAME
    ledger = Ledger(path)
    discharged_through(ledger, Stage.SPECIFIED)
    ledger.discharge(Stage.SPECIFIED, SPEC, "specified again, for a different reason")

    assert len(Ledger(path).entries(SPEC)) == 2


def test_the_whole_sequence_can_be_walked(tmp_path) -> None:
    ledger = Ledger(tmp_path / LEDGER_FILENAME)
    discharged_through(
        ledger,
        Stage.SPECIFIED,
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
        Stage.SAMPLED,
        Stage.EXECUTED,
        Stage.DIAGNOSED,
        by="inversion",
    )
    ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")
    ledger.discharge(Stage.READ_INTO_MODEL, SPEC, "two units, 12% unclaimed")

    assert all(
        ledger.has(stage, SPEC) for stage in Stage if stage not in {Stage.ADOPTED, Stage.VETOED}
    )
    assert "read_into_model        done" in ledger.report(SPEC)


def test_a_ledger_with_no_path_still_gates(tmp_path) -> None:
    """Useful in a test or a dry run; the gating is the same."""
    ledger = Ledger()
    discharged_through(ledger, Stage.SPECIFIED)

    assert ledger.has(Stage.SPECIFIED, SPEC)
    with pytest.raises(ObligationError):
        ledger.require(Stage.EXECUTED, SPEC)


def test_what_a_report_says_about_a_run_that_stopped_halfway(tmp_path) -> None:
    ledger = Ledger(tmp_path / LEDGER_FILENAME)
    discharged_through(ledger, Stage.SPECIFIED, Stage.VALIDATED)

    report = ledger.report(SPEC)
    assert "validated              done" in report
    assert "conventions_checked    owed" in report
    assert "executed               owed" in report


def test_a_discharge_records_when_as_well_as_what() -> None:
    entry = Discharge(Stage.SPECIFIED, SPEC, "a RunSpec exists and was fingerprinted")

    assert entry.at.endswith("+00:00")
    assert Path(LEDGER_FILENAME).suffix == ".jsonl"


class TestAnAuditIsSomeoneElses:
    """The audited stage, and the one rule in the ledger about who."""

    THROUGH_DIAGNOSIS = (
        Stage.SPECIFIED,
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
        Stage.EXECUTED,
        Stage.DIAGNOSED,
    )

    def test_reading_into_a_model_owes_an_audit(self) -> None:
        ledger = Ledger()
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS, by="inversion")

        with pytest.raises(ObligationError) as raised:
            ledger.discharge(Stage.READ_INTO_MODEL, SPEC, "two units, 12% unclaimed")

        assert raised.value.missing == (Stage.AUDITED,)

    def test_the_actor_that_ran_it_may_not_audit_it(self) -> None:
        ledger = Ledger()
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS, by="inversion")

        with pytest.raises(NotIndependent, match="F056"):
            ledger.discharge(Stage.AUDITED, SPEC, "I checked my own misfit", by="inversion")

    def test_an_audit_that_names_nobody_is_refused(self) -> None:
        ledger = Ledger()
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS, by="inversion")

        with pytest.raises(NotIndependent, match="has to name who"):
            ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back")

    def test_an_audit_of_an_unnamed_execution_is_refused(self) -> None:
        """Independence that cannot be read back was not established."""
        ledger = Ledger()
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS)

        with pytest.raises(NotIndependent, match="names nobody"):
            ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")

    def test_later_named_adoption_supersedes_an_unnamed_execution(self) -> None:
        ledger = Ledger()
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS)
        ledger.discharge(
            Stage.ADOPTED,
            SPEC,
            "Saved successful run and artifacts rechecked for retrospective review",
            by="inversion",
        )
        ledger.discharge(Stage.DIAGNOSED, SPEC, "Current saved misfit was read", by="inversion")
        ledger.discharge(Stage.AUDITED, SPEC, "Current saved result independently read", by="audit")
        assert not ledger.has(Stage.EXECUTED, SPEC)
        assert ledger.has(Stage.ADOPTED, SPEC)

    def test_who_discharged_what_survives_a_reload(self, tmp_path) -> None:
        path = tmp_path / LEDGER_FILENAME
        ledger = Ledger(path)
        discharged_through(ledger, *self.THROUGH_DIAGNOSIS, by="inversion")
        ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")

        again = Ledger(path)
        assert {e.by for e in again.entries(SPEC)} == {"inversion", "audit"}
        with pytest.raises(NotIndependent):
            again.discharge(Stage.AUDITED, SPEC, "a second look by the runner", by="inversion")

    def test_an_entry_written_before_names_existed_still_loads(self, tmp_path) -> None:
        path = tmp_path / LEDGER_FILENAME
        path.write_text(
            '{"stage": "specified", "fingerprint": "' + SPEC + '", '
            '"evidence": "a RunSpec exists and was fingerprinted", "at": "2026-09-01T00:00:00"}\n',
            encoding="utf-8",
        )

        assert Ledger(path).entries(SPEC)[0].by == ""


class TestARunAdoptedRatherThanInverted:
    """Check the audit path for adopted models."""

    def test_adopted_stands_in_for_executed(self) -> None:
        ledger = Ledger()
        ledger.discharge(Stage.ADOPTED, SPEC, "adopted by ofag.import.layered_line", by="data")
        ledger.discharge(Stage.DIAGNOSED, SPEC, "published misfit column read", by="inversion")
        ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")

        assert ledger.missing_for(Stage.READ_INTO_MODEL, SPEC) == ()

    def test_the_actor_that_adopted_it_may_not_audit_it(self) -> None:
        ledger = Ledger()
        ledger.discharge(Stage.ADOPTED, SPEC, "adopted by ofag.import.layered_line", by="data")
        ledger.discharge(Stage.DIAGNOSED, SPEC, "published misfit column read", by="inversion")

        with pytest.raises(NotIndependent):
            ledger.discharge(Stage.AUDITED, SPEC, "I imported it and it looks fine", by="data")

    def test_neither_is_still_owed_as_executed(self) -> None:
        ledger = Ledger()

        assert ledger.missing_for(Stage.DIAGNOSED, SPEC) == (Stage.EXECUTED,)

    def test_the_report_shows_whichever_was_taken(self) -> None:
        adopted = Ledger()
        adopted.discharge(Stage.ADOPTED, SPEC, "adopted by ofag.import.layered_line", by="data")
        executed = Ledger()
        discharged_through(
            executed,
            Stage.SPECIFIED,
            Stage.VALIDATED,
            Stage.CONVENTIONS_CHECKED,
            Stage.ESTIMATED,
            Stage.EXECUTED,
        )

        assert "adopted" in adopted.report(SPEC) and "executed" not in adopted.report(SPEC)
        assert "executed" in executed.report(SPEC) and "adopted" not in executed.report(SPEC)
        assert "executed" in Ledger().report(SPEC) and "adopted" not in Ledger().report(SPEC)


def _audited(ledger: Ledger, *, by: str = "inversion") -> None:
    discharged_through(
        ledger,
        Stage.SPECIFIED,
        Stage.VALIDATED,
        Stage.CONVENTIONS_CHECKED,
        Stage.ESTIMATED,
        Stage.EXECUTED,
        Stage.DIAGNOSED,
        by=by,
    )


class TestAVetoHolds:
    """Found by the independent review: a veto was a journal note nothing checked, a later
    pass outvoted it, and the producer could clear the note."""

    def test_no_audit_passes_while_a_veto_stands(self) -> None:
        ledger = Ledger()
        _audited(ledger)
        ledger.discharge(Stage.VETOED, SPEC, "ramp read in the wrong unit (F054)", by="audit")

        with pytest.raises(Vetoed, match="F054"):
            ledger.discharge(Stage.AUDITED, SPEC, "a second reader thinks it is fine", by="audit")

    def test_a_veto_after_a_pass_withdraws_it(self) -> None:
        ledger = Ledger()
        _audited(ledger)
        ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")
        ledger.discharge(Stage.VETOED, SPEC, "a fresh reader found the ramp (F054)", by="audit")

        assert ledger.missing_for(Stage.READ_INTO_MODEL, SPEC) == (Stage.AUDITED,)

    def test_the_producer_cannot_veto_or_pass(self) -> None:
        ledger = Ledger()
        _audited(ledger)

        with pytest.raises(NotIndependent):
            ledger.discharge(Stage.VETOED, SPEC, "vetoing my own run to hide it", by="inversion")

    def test_executing_again_lifts_the_veto(self) -> None:
        ledger = Ledger()
        _audited(ledger)
        ledger.discharge(Stage.VETOED, SPEC, "ramp read in the wrong unit (F054)", by="audit")
        discharged_through(ledger, Stage.EXECUTED, Stage.DIAGNOSED, by="inversion")

        ledger.discharge(Stage.AUDITED, SPEC, "ramp now in seconds; misfit read", by="audit")
        assert ledger.missing_for(Stage.READ_INTO_MODEL, SPEC) == ()

    def test_the_report_shows_a_veto_only_while_it_stands(self) -> None:
        ledger = Ledger()
        _audited(ledger)
        assert "vetoed" not in ledger.report(SPEC)
        ledger.discharge(Stage.VETOED, SPEC, "ramp read in the wrong unit (F054)", by="audit")
        assert "vetoed" in ledger.report(SPEC)


class TestAnEntryBelongsToTheExecutionItFollowed:
    """Found by the independent review: after delete_run and a re-execution of the same
    specification, the old diagnosis and audit still counted, so build_model read a result
    nobody had looked at."""

    def test_executing_again_owes_a_new_diagnosis_and_audit(self) -> None:
        ledger = Ledger()
        _audited(ledger)
        ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")
        assert ledger.missing_for(Stage.READ_INTO_MODEL, SPEC) == ()

        discharged_through(ledger, Stage.EXECUTED, by="inversion")

        assert ledger.missing_for(Stage.READ_INTO_MODEL, SPEC) == (Stage.AUDITED,)
        assert ledger.missing_for(Stage.AUDITED, SPEC) == (Stage.DIAGNOSED,)

    def test_an_unnamed_old_execution_does_not_bar_auditing_a_named_new_one(self) -> None:
        """Every ledger written before names existed has unnamed executions."""
        ledger = Ledger()
        _audited(ledger, by="")
        discharged_through(ledger, Stage.EXECUTED, Stage.DIAGNOSED, by="inversion")

        ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")
        assert ledger.has(Stage.AUDITED, SPEC)

    def test_the_refusal_for_an_unnamed_execution_says_how_to_get_out(self) -> None:
        ledger = Ledger()
        _audited(ledger, by="")

        with pytest.raises(NotIndependent, match="Execute or adopt it again"):
            ledger.discharge(Stage.AUDITED, SPEC, "misfit and depth band read back", by="audit")
