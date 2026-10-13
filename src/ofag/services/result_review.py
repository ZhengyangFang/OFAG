"""Persist a person's preferred result independently of the scientific audit."""

import json
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from ofag.agent.obligations import Ledger, Stage
from ofag.core.schemas import RunState, spec_fingerprint
from ofag.services.run_service import RunService


class ResultReview:
    def __init__(self, runs: RunService) -> None:
        self.runs = runs
        self.path = runs.artifact_root / "preferred_results.json"

    def audit_status(self, run_id: UUID) -> str:
        fingerprint = spec_fingerprint(self.runs.get(run_id).spec)
        ledger = Ledger(self.runs.artifact_root / "obligations.jsonl")
        adoption = ledger.current(Stage.ADOPTED, fingerprint)
        retrospective = adoption is not None and adoption.evidence.startswith(
            "Retrospective adoption"
        )
        if ledger.has(Stage.VETOED, fingerprint):
            if retrospective:
                return "Vetoed (retrospective review) - must not be used for interpretation"
            return "Vetoed - must not be used for interpretation"
        if ledger.has(Stage.AUDITED, fingerprint):
            if retrospective:
                return "Audit passed (retrospective review)"
            return "Audit passed"
        return "Not audited"

    def _read(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
            raise ValueError("Invalid preferred result register")
        migrated = {}
        for entry in data.values():
            try:
                record = self.runs.get(UUID(entry["run_id"]))
                migrated[self._scope(record.spec)] = entry
            except (KeyError, ValueError):
                continue
        return migrated

    @staticmethod
    def _scope(spec: object) -> str:
        from ofag.core.schemas import RunSpec

        assert isinstance(spec, RunSpec)
        ids = (
            spec.source_dataset_ids
            or tuple(
                channel.source_dataset_id or channel.dataset.dataset_id for channel in spec.datasets
            )
            or (spec.dataset.dataset_id,)
        )
        return spec.plugin_id + ":" + ",".join(sorted(str(identifier) for identifier in set(ids)))

    def choose(self, run_id: UUID) -> None:
        record = self.runs.get(run_id)
        if record.state is not RunState.SUCCEEDED or self.runs.result(run_id) is None:
            raise ValueError("Choose a completed result with readable artifacts.")
        if self.audit_status(run_id).startswith("Vetoed"):
            raise ValueError("A vetoed result cannot be marked for use.")
        data = self._read()
        data[self._scope(record.spec)] = {
            "run_id": str(run_id),
            "chosen_at": datetime.now(UTC).isoformat(),
            "fingerprint": spec_fingerprint(record.spec),
            "dataset": record.spec.dataset.name,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(data, handle, indent=2)
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def preferred(self, run_id: UUID) -> bool:
        record = self.runs.get(run_id)
        entry = self._read().get(self._scope(record.spec), {})
        return entry.get("run_id") == str(run_id) and entry.get(
            "fingerprint", spec_fingerprint(record.spec)
        ) == spec_fingerprint(record.spec)

    def selections(self) -> list[dict[str, str]]:
        selected = []
        for entry in self._read().values():
            try:
                run_id = UUID(entry["run_id"])
                record = self.runs.get(run_id)
                if not self.preferred(run_id):
                    continue
                selected.append(
                    {
                        **entry,
                        "plugin": record.spec.plugin_id,
                        "dataset": record.spec.dataset.name,
                        "audit": self.audit_status(run_id),
                    }
                )
            except (ValueError, KeyError):
                continue
        return selected
