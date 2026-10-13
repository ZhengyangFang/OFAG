"""What came from what. Read from the runs and the workspace rather than recorded alongside
them, so the graph cannot drift from what was actually computed."""

from typing import Any
from uuid import UUID

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem

from ofag.desktop.navigation import Stage
from ofag.desktop.stages.base import StagePanel


class LineageStage(StagePanel):
    """Surveys, the runs built on them, and what was read out of those."""

    def __init__(self) -> None:
        super().__init__(Stage.LINEAGE)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["What", "Detail"])
        self._tree.setColumnWidth(0, 420)

        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.refresh)
        self._counts = QLabel("")
        controls = QHBoxLayout()
        controls.addWidget(reload_button)
        controls.addStretch(1)
        controls.addWidget(self._counts)

        self._body.addLayout(controls)
        self._body.addWidget(self._tree, 1)

    def refresh(self) -> None:
        session = self.session
        if session is None:
            return
        self._tree.clear()
        workspace = session.workspace()
        runs = session.runs.list_runs()

        by_dataset: dict[str, list[Any]] = {}
        unattached: list[Any] = []
        for record in runs:
            sources = _source_datasets(record, workspace.datasets)
            if not sources:
                unattached.append(record)
            else:
                for dataset in sources:
                    by_dataset.setdefault(str(dataset.dataset_id), []).append(record)

        for dataset in workspace.datasets:
            node = QTreeWidgetItem(
                [f"{dataset.name}", f"{dataset.kind.value} · {dataset.source_filename}"]
            )
            for record in by_dataset.get(str(dataset.dataset_id), ()):
                node.addChild(self._run_node(session, record, workspace))
            self._tree.addTopLevelItem(node)
            node.setExpanded(True)

        if unattached:
            orphans = QTreeWidgetItem(
                [
                    "Runs not tied to a registered survey",
                    "their spec names a dataset this project does not hold",
                ]
            )
            for record in unattached:
                orphans.addChild(self._run_node(session, record, workspace))
            self._tree.addTopLevelItem(orphans)
            orphans.setExpanded(True)

        geology = workspace.geology[0] if workspace.geology else None
        if geology is not None:
            node = QTreeWidgetItem(
                [
                    f"Geological model: {geology.name}",
                    f"{len(geology.units)} units · {len(geology.boreholes)} holes · "
                    f"{len(geology.borehole_points())} logged contacts · "
                    f"{len(geology.surface_points)} picked points",
                ]
            )
            for hole in geology.boreholes:
                node.addChild(
                    QTreeWidgetItem(
                        [
                            f"Borehole {hole.name}",
                            f"{hole.total_depth_m:.0f} m, "
                            f"{'vertical' if hole.vertical else 'surveyed'}, "
                            f"{len(hole.intervals)} intervals",
                        ]
                    )
                )
            for run_id in geology.interpreted_from_run_ids:
                node.addChild(QTreeWidgetItem(["Digitised on run", str(run_id)]))
            self._tree.addTopLevelItem(node)
            node.setExpanded(True)

        self._counts.setText(
            f"{len(workspace.datasets)} surveys · {len(runs)} runs · "
            f"{len(workspace.models)} site models · {len(workspace.geology)} geological models"
        )

    def _run_node(self, session: Any, record: Any, workspace: Any) -> QTreeWidgetItem:
        run_id: UUID = record.spec.run_id
        node = QTreeWidgetItem([f"Run {record.spec.plugin_id}", f"{record.state} · {run_id}"])
        try:
            result = session.runs.result(run_id)
        except (KeyError, ValueError, OSError):
            result = None
        if result is not None:
            for artifact in result.artifacts:
                node.addChild(
                    QTreeWidgetItem(
                        [
                            f"  {artifact.artifact_type}",
                            f"{artifact.physical_quantity} ({artifact.units})",
                        ]
                    )
                )
        for site in workspace.models:
            for source in site.sources:
                if source.run_id == run_id:
                    node.addChild(
                        QTreeWidgetItem(
                            [
                                f"  Site model: {site.name}",
                                f"{len(source.classes)} units classified from "
                                f"{source.physical_quantity}",
                            ]
                        )
                    )
        return node


def _source_datasets(record: Any, datasets: tuple[Any, ...]) -> tuple[Any, ...]:
    """Use stable channel IDs; resolve old name-only specs only if unambiguous."""
    by_id = {item.dataset_id: item for item in datasets}
    channels = record.spec.datasets
    explicit = set(record.spec.source_dataset_ids)
    explicit.update(channel.source_dataset_id for channel in channels if channel.source_dataset_id)
    if explicit:
        if any(identifier not in by_id for identifier in explicit):
            return ()
        return tuple(by_id[identifier] for identifier in explicit)
    names = {channel.dataset.name for channel in channels}
    if not names and record.spec.dataset is not None:
        names.add(record.spec.dataset.name)
    matched: list[Any] = []
    for name in names:
        candidates = [item for item in datasets if item.name == name]
        if len(candidates) != 1:
            return ()
        matched.append(candidates[0])
    return tuple(matched)
