"""Configuring a run, and finding out what is wrong with it before paying."""

from typing import Any
from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    DataChannelSpec,
    DatasetKind,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    RunState,
)
from ofag.desktop.navigation import Stage
from ofag.desktop.selection import find_data
from ofag.desktop.specform import SpecForm
from ofag.desktop.stages.base import StagePanel
from ofag.desktop.tasks import BackgroundTask, probe_sensitivity
from ofag.plugins.protocol import SensitivityCapable
from ofag.services.method_catalog import method_info
from ofag.services.run_configuration import RunInputs, reuse_spec, uses_dataset
from ofag.services.run_start_policy import RunStartPolicy


class InversionStage(StagePanel):
    """One page for every method, because the form comes from the plugin."""

    def __init__(self) -> None:
        super().__init__(Stage.INVERSION)

        self._plugin = QComboBox()
        self._plugin.setMinimumContentsLength(20)
        self._plugin.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._plugin.currentIndexChanged.connect(self._rebuild_form)
        self._dataset = QComboBox()
        self._dataset.setMinimumContentsLength(14)
        self._dataset.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._dataset.currentIndexChanged.connect(self._dataset_changed)
        self._second_dataset = QComboBox()
        self._second_dataset.currentIndexChanged.connect(self._invalidate)
        self._source_spec: RunSpec | None = None
        self._inputs: SpecForm | None = None
        self._second_dataset_label = QLabel("Second data")
        self._second_dataset.setToolTip("Second observation channel for a joint inversion.")

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Method"))
        chooser.addWidget(self._plugin, 2)
        chooser.addWidget(QLabel("Data"))
        chooser.addWidget(self._dataset, 2)
        chooser.addWidget(self._second_dataset_label)
        chooser.addWidget(self._second_dataset, 2)
        chooser.addStretch(1)

        self._form_host = QScrollArea()
        self._form_host.setWidgetResizable(True)
        self._form: SpecForm | None = None

        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._report.setObjectName("preRunReport")

        self._sample = QComboBox()
        self._sample.addItem("No trial run selected", None)
        self._sample.setToolTip("A completed smaller run using this numerical method.")
        self._allow_unchecked = QCheckBox("Skip trial (recorded)")
        trial_row = QHBoxLayout()
        trial_row.addWidget(QLabel("Smaller trial"))
        trial_row.addWidget(self._sample, 1)

        check = QPushButton("Check")
        check.setToolTip("Validate the configuration and estimate what it will cost.")
        check.clicked.connect(self._check)
        probe = QPushButton("Sensitivity")
        probe.setToolTip(
            "One forward and one adjoint pass at the starting model. It says "
            "whether what is being inverted for is in the data at all, which "
            "is a different question from whether the run will converge."
        )
        probe.clicked.connect(self._probe)
        self._probe_button = probe
        self._probe_task = BackgroundTask(self)
        self._probe_task.status.connect(self._report.setPlainText)
        self._probe_task.failed.connect(self._report.setPlainText)
        self._probe_task.succeeded.connect(self._show_probe)
        self._probe_task.busy_changed.connect(lambda busy: probe.setEnabled(not busy))
        cancel_probe = QPushButton("Cancel analysis")
        cancel_probe.setEnabled(False)
        cancel_probe.clicked.connect(self._probe_task.cancel)
        self._probe_task.busy_changed.connect(cancel_probe.setEnabled)
        start = QPushButton("Create and start")
        start.clicked.connect(self._start)
        for control in (
            self._plugin,
            self._dataset,
            self._second_dataset,
            self._form_host,
            check,
            start,
        ):
            self._probe_task.busy_changed.connect(
                lambda busy, widget=control: widget.setEnabled(not busy)
            )

        buttons = QGridLayout()
        buttons.addWidget(check, 0, 0)
        buttons.addWidget(probe, 0, 1)
        buttons.addWidget(cancel_probe, 1, 0)
        buttons.addWidget(start, 1, 1)

        right = QVBoxLayout()
        right.addWidget(QLabel("Checks"))
        right.addWidget(self._report, 1)
        right.addLayout(trial_row)
        right.addWidget(self._allow_unchecked)
        right.addLayout(buttons)
        right_box = QGroupBox()
        right_box.setLayout(right)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._form_host)
        splitter.addWidget(right_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._body.addLayout(chooser)
        self._body.addWidget(splitter, 1)

    # -- what is on offer ---------------------------------------------------

    def _invalidate(self, *_: Any) -> None:
        self._report.setPlainText("Configuration changed. Check again.")

    def follow_selection(self) -> None:
        if self.session and self.session.selected_dataset_id:
            index = find_data(self._dataset, self.session.selected_dataset_id)
            if index >= 0 and index != self._dataset.currentIndex():
                self._dataset.setCurrentIndex(index)

    def _dataset_changed(self) -> None:
        dataset = self._selected_dataset()
        if self.session and dataset:
            self.session.selected_dataset_id = dataset.dataset_id
            if dataset.kind.value not in method_info(self._plugin.currentData()).kinds:
                for index in range(self._plugin.count()):
                    if dataset.kind.value in method_info(self._plugin.itemData(index)).kinds:
                        self._plugin.setCurrentIndex(index)
                        return
        self._rebuild_form()

    def refresh(self) -> None:
        session = self.session
        if session is None:
            return
        same_project = getattr(self, "_form_session", None) is session
        self._form_session = session
        current = self._plugin.currentData() if same_project else None
        selected = self._dataset.currentData() if same_project else None
        second = self._second_dataset.currentData() if same_project else None
        draft = self._form.value() if same_project and self._form is not None else None
        input_draft = self._inputs.value() if same_project and self._inputs is not None else None
        source = self._source_spec if same_project else None
        if not same_project:
            self._probe_task.cancel()
            self._report.clear()
            selected = session.selected_dataset_id
        datasets = session.workspace().datasets
        kinds = {d.kind.value for d in datasets}
        self._plugin.blockSignals(True)
        self._plugin.clear()
        manifests = sorted(
            session.runs.list_plugins(),
            key=lambda m: (
                m.plugin_id.startswith("ofag.fixture"),
                not set(method_info(m.plugin_id).kinds).issubset(kinds),
            ),
        )
        for manifest in manifests:
            info = method_info(manifest.plugin_id)
            self._plugin.addItem(
                info.name,
                manifest.plugin_id,
            )
            self._plugin.setItemData(
                self._plugin.count() - 1, info.readiness(kinds), Qt.ItemDataRole.ToolTipRole
            )
        index = self._plugin.findData(current)
        self._plugin.setCurrentIndex(max(index, 0))
        self._plugin.blockSignals(False)

        self._dataset.blockSignals(True)
        self._second_dataset.blockSignals(True)
        self._dataset.clear()
        self._second_dataset.clear()
        self._second_dataset.addItem("— none —", None)
        self._dataset.addItem("— none —", None)
        for dataset in session.workspace().datasets:
            self._dataset.addItem(f"{dataset.name} ({dataset.kind.value})", dataset.dataset_id)
            self._second_dataset.addItem(
                f"{dataset.name} ({dataset.kind.value})", dataset.dataset_id
            )
        self._dataset.setCurrentIndex(max(1 if datasets else 0, find_data(self._dataset, selected)))
        self._second_dataset.setCurrentIndex(max(0, find_data(self._second_dataset, second)))
        self._dataset.blockSignals(False)
        self._second_dataset.blockSignals(False)
        if same_project:
            self._rebuild_form()
        else:
            self._dataset_changed()
        if self._dataset.currentData() == selected:
            self._source_spec = source
            if draft is not None and self._form is not None:
                self._form.set_value(draft)
            if input_draft is not None and self._inputs is not None:
                self._inputs.set_value(input_draft)

    def focus_record(self, identifier: str) -> None:
        """Open an Agent draft for inspection and editing without executing it."""
        if self.session is None:
            return
        try:
            run_id = UUID(identifier)
            path = self.session.folder.runs_root / "drafts" / f"{run_id}.json"
            spec = RunSpec.model_validate_json(path.read_text("utf-8"))
            if spec.project_id not in (None, self.session.record.project_id):
                raise ValueError("This draft belongs to another project.")
            index = self._plugin.findData(spec.plugin_id)
            if index < 0:
                raise ValueError(f"Method unavailable: {spec.plugin_id}")
            datasets = [d for d in self.session.workspace().datasets if uses_dataset(spec, d)]
            ids = list(spec.source_dataset_ids) or [d.dataset_id for d in datasets]
            if any(find_data(self._dataset, item) < 0 for item in ids):
                raise ValueError("A draft dataset is no longer registered.")
            for combo in (self._plugin, self._dataset, self._second_dataset):
                combo.blockSignals(True)
            self._plugin.setCurrentIndex(index)
            self._dataset.setCurrentIndex(find_data(self._dataset, ids[0]) if ids else 0)
            self._second_dataset.setCurrentIndex(
                find_data(self._second_dataset, ids[1]) if len(ids) > 1 else 0
            )
            for combo in (self._plugin, self._dataset, self._second_dataset):
                combo.blockSignals(False)
            self.session.selected_dataset_id = ids[0] if ids else None
            self._rebuild_form()
            self._load_spec(spec)
            self._report.setPlainText(f"Draft: {spec.label or spec.run_id}\nCheck before starting.")
            self._report.setToolTip(f"Saved draft: {path}")
        except (OSError, ValueError, KeyError) as error:
            self._report.setPlainText(f"Could not open draft: {error}")

    def _load_spec(self, spec: RunSpec) -> None:
        self._source_spec = spec
        if self._form is not None:
            model = self._form._model
            physics = spec.physics
            if physics is None:
                physics = next(
                    (
                        value.model_dump(mode="json")
                        for value in spec.__dict__.values()
                        if isinstance(value, model)
                    ),
                    None,
                )
            if physics is not None:
                self._form.set_value(model.model_validate(physics).model_dump(mode="json"))
        if self._inputs is not None:
            payload = spec.model_dump(mode="json")
            self._inputs.set_value({key: payload[key] for key in RunInputs.model_fields})

    def _rebuild_form(self) -> None:
        session = self.session
        plugin_id = self._plugin.currentData()
        if session is None or plugin_id is None:
            return
        self._source_spec = None
        self._inputs = None
        self._report.setPlainText("Select data and check the configuration.")
        joint = plugin_id == "simpeg.joint.gravmag.cross_gradient"
        self._refresh_samples()
        self._second_dataset_label.setVisible(joint)
        self._second_dataset.setVisible(joint)
        plugin = session.runs.plugin(plugin_id)
        model = plugin.physics_model()
        if model is None:
            placeholder = QLabel("Diagnostic run inputs")
            placeholder.setWordWrap(True)
            host = QWidget()
            column = QVBoxLayout()
            column.addWidget(placeholder)
            self._inputs = SpecForm(RunInputs)
            self._inputs.changed.connect(self._invalidate)
            column.addWidget(self._inputs, 1)
            host.setLayout(column)
            self._form = None
            self._form_host.setWidget(host)
            return
        self._form = SpecForm(model, grouped=True)
        host = QWidget()
        column = QVBoxLayout(host)
        column.addWidget(self._form)
        inputs = QGroupBox("Mesh and run inputs")
        inputs.setCheckable(True)
        inputs.setChecked(False)
        self._inputs = SpecForm(RunInputs)
        QVBoxLayout(inputs).addWidget(self._inputs)
        self._inputs.hide()
        inputs.toggled.connect(self._inputs.setVisible)
        column.addWidget(inputs)
        column.addStretch(1)
        self._form_host.setWidget(host)
        self._seed_selected_sites()
        self._seed_from_dataset()
        self._form.changed.connect(self._invalidate)
        self._inputs.changed.connect(self._invalidate)

    def _refresh_samples(self) -> None:
        session = self.session
        if session is None:
            return
        selected = self._sample.currentData()
        self._sample.clear()
        self._sample.addItem("No trial run selected", None)
        for record in session.runs.list_runs():
            if (
                record.state is RunState.SUCCEEDED
                and record.spec.plugin_id == self._plugin.currentData()
            ):
                self._sample.addItem(
                    record.spec.label or str(record.spec.run_id), record.spec.run_id
                )
        self._sample.setCurrentIndex(max(0, find_data(self._sample, selected)))

    def _seed_from_dataset(self) -> None:
        """Fill the form from what this survey was last inverted with, or from its files."""
        session = self.session
        form = self._form
        plugin_id = self._plugin.currentData()
        dataset = self._selected_dataset()
        if session is None or form is None or dataset is None or plugin_id is None:
            return
        runs = [
            record
            for record in session.runs.list_runs()
            if record.state is RunState.SUCCEEDED and uses_dataset(record.spec, dataset)
        ]
        same = sorted(
            (r for r in runs if r.spec.plugin_id == plugin_id), key=lambda r: r.created_at
        )
        if same:
            source = same[-1]
            self._load_spec(source.spec)
            self._report.setPlainText(
                f"Based on: {source.spec.label or source.spec.run_id}\nCheck before starting."
            )
            self._report.setToolTip(f"Source run: {source.spec.run_id}")
            return
        seeded = _fill_paths(form.value(), dataset.payload)
        form.set_value(seeded)
        others = sorted({r.spec.plugin_id for r in runs} - {plugin_id})
        hint = (
            f" This survey was inverted with {', '.join(others)}; choose that plugin to start "
            "from that run's configuration."
            if others
            else ""
        )
        self._report.setPlainText("Data paths loaded. Set parameters, then check." + hint)

    def _selected_dataset(self) -> Any:
        session = self.session
        selected = self._dataset.currentData()
        if session is None or selected is None:
            return None
        return next((d for d in session.workspace().datasets if d.dataset_id == selected), None)

    def _seed_selected_sites(self) -> None:
        """Carry imported MT site files into the method form without guessing a 2D line."""
        if self._form is None or self.session is None:
            return
        plugin_id = self._plugin.currentData()
        if plugin_id not in {"simpeg.nsem.mt1d_batch", "simpeg.nsem.mt2d"}:
            return
        selected = self._dataset.currentData()
        dataset = next(
            (item for item in self.session.workspace().datasets if item.dataset_id == selected),
            None,
        )
        if dataset is None or dataset.kind is not DatasetKind.MT:
            return
        soundings = dataset.payload.get("soundings")
        if not isinstance(soundings, list):
            return
        sites: list[dict[str, Any]] = []
        for site in soundings:
            if not isinstance(site, dict):
                continue
            if plugin_id == "simpeg.nsem.mt1d_batch":
                sites.append(dict(site))
            else:
                sites.append(
                    {
                        "site_id": site.get("site_id"),
                        "observations_path": site.get("observations_path"),
                        "elevation_m": site.get("elevation_m", 0.0),
                        "distance_m": None,
                        "mode": None,
                    }
                )
        self._form.set_value({"sites": sites})
        if plugin_id == "simpeg.nsem.mt2d":
            self._report.setPlainText(
                "MT site files are filled in. Enter each site's distance along the chosen "
                "profile and TE/TM mode in the sites list; these cannot be inferred from "
                "map coordinates."
            )

    # -- the spec -----------------------------------------------------------

    def _spec(self) -> RunSpec | None:
        session = self.session
        plugin_id = self._plugin.currentData()
        if session is None or plugin_id is None:
            return None
        physics: dict[str, Any] | None = None
        if self._form is not None:
            issues = self._form.errors()
            if issues:
                self._report.setPlainText(
                    "This configuration is not yet a valid one:\n\n  " + "\n  ".join(issues)
                )
                return None
            physics = self._form.value()
        manifest = session.runs.plugin(plugin_id).manifest()
        channels = self._channels(session)
        if self._source_spec and plugin_id != "simpeg.joint.gravmag.cross_gradient":
            channels = self._source_spec.datasets
        selected_ids = tuple(
            dict.fromkeys(
                identifier
                for identifier in (
                    self._dataset.currentData(),
                    self._second_dataset.currentData()
                    if plugin_id == "simpeg.joint.gravmag.cross_gradient"
                    else None,
                )
                if identifier is not None
            )
        )
        try:
            inputs = RunInputs.model_validate(self._inputs.value() if self._inputs else {})
            if self._source_spec is not None:
                source = self._source_spec
                # Keep uncertainties and channel declarations when editing the same pair.
                if set(selected_ids) == set(source.source_dataset_ids):
                    channels = source.datasets
                return reuse_spec(
                    source,
                    schema_version="1.1" if physics is not None else source.schema_version,
                    physics=physics,
                    source_dataset_ids=selected_ids or source.source_dataset_ids,
                    datasets=channels,
                    **inputs.model_dump(),
                )
            if channels and plugin_id in {"simpeg.pf.gravity3d", "simpeg.pf.magnetics3d"}:
                inputs.parameters.setdefault("observations_path", channels[0].observations_path)
                inputs.parameters.setdefault("data_uncertainty", channels[0].data_uncertainty)
            return RunSpec(
                schema_version="1.1" if physics is not None else "1.0",
                plugin_id=plugin_id,
                plugin_version=manifest.plugin_version,
                # Use the engine declared by the plugin.
                engine=_engine_of(plugin_id),
                project_id=session.record.project_id,
                dataset=self._dataset_spec(session, channels, self._dataset.currentData()),
                source_dataset_ids=selected_ids,
                datasets=channels,
                physics=physics,
                **inputs.model_dump(),
            )
        except Exception as error:  # noqa: BLE001 - reported, not swallowed
            self._report.setPlainText(str(error))
            return None

    def _channels(self, session: Any) -> tuple[DataChannelSpec, ...]:
        """The chosen survey, declared as the channel a plugin resolves by name."""
        first = self._channel_for(session, self._dataset.currentData())
        if self._plugin.currentData() != "simpeg.joint.gravmag.cross_gradient":
            return (first,) if first is not None else ()
        second = self._channel_for(session, self._second_dataset.currentData())
        return tuple(channel for channel in (first, second) if channel is not None)

    @staticmethod
    def _channel_for(session: Any, dataset_id: Any) -> DataChannelSpec | None:
        if dataset_id is None:
            return None
        for dataset in session.workspace().datasets:
            if dataset.dataset_id != dataset_id:
                continue
            channel = _CHANNELS.get(dataset.kind)
            if channel is None:
                return None
            channel_id, quantity, units, path_key, uncertainty = channel
            path = dataset.payload.get(path_key)
            if not isinstance(path, str):
                return None
            return DataChannelSpec(
                channel_id=channel_id,
                source_dataset_id=dataset.dataset_id,
                dataset=DatasetSpec(
                    name=dataset.name,
                    coordinate_convention=session.record.coordinate_convention,
                    physical_quantity=quantity,
                    units=units,
                ),
                observations_path=path,
                data_uncertainty=QuantitySpec(
                    value=uncertainty, quantity_type=quantity, unit=units
                ),
            )
        return None

    @staticmethod
    def _dataset_spec(
        session: Any, channels: tuple[DataChannelSpec, ...], dataset_id: Any
    ) -> DatasetSpec:
        """What the run says it is inverting."""
        if channels:
            return channels[0].dataset
        for dataset in session.workspace().datasets:
            if dataset.dataset_id == dataset_id and dataset.kind is DatasetKind.MT:
                return DatasetSpec(
                    name=dataset.name,
                    coordinate_convention=session.record.coordinate_convention,
                    physical_quantity=QuantityType.MAGNETOTELLURIC_IMPEDANCE,
                    units="ohm",
                )
        return DatasetSpec(
            name=session.record.name,
            coordinate_convention=session.record.coordinate_convention,
            physical_quantity=QuantityType.DIMENSIONLESS,
            units="dimensionless",
        )

    # -- the three questions ------------------------------------------------

    def _check(self) -> None:
        session = self.session
        spec = self._spec()
        if session is None or spec is None:
            return
        lines: list[str] = []
        report = session.runs.validate(spec)
        if report.valid:
            lines.append("Valid.")
        else:
            lines.append("Not runnable yet:")
            for issue in report.issues:
                lines.append(f"  {issue.field}")
                lines.append(f"    {issue.message}")
                lines.append(f"    → {issue.remediation}")
        if report.valid:
            estimate = session.runs.estimate_resources(spec)
            lines += [
                "",
                "Rough resource estimate (not calibrated to this machine)",
                f"  cores    {estimate.cpu_cores}",
                f"  memory   {estimate.memory_mb} MB",
                f"  time     {estimate.estimated_seconds} s estimated; measure a small run first",
            ]
        self._report.setPlainText("\n".join(lines))

    def _probe(self) -> None:
        session = self.session
        spec = self._spec()
        if session is None or spec is None:
            return
        plugin = session.runs.plugin(spec.plugin_id)
        if not isinstance(plugin, SensitivityCapable):
            self._report.setPlainText(
                f"{spec.plugin_id} cannot report what its data sees. A number that did not "
                "come from the method's own adjoint would be a guess with a plausible shape."
            )
            return
        self._probe_task.start(
            "Computing parameter sensitivity...", probe_sensitivity, session.folder.runs_root, spec
        )

    def _show_probe(self, seen: Any) -> None:
        ratios = seen.ratios()
        best = max(ratios, key=lambda name: ratios[name], default="")
        lines = ["What the data can see, against the parameter it sees best:", ""]
        for name, ratio in sorted(ratios.items(), key=lambda item: -item[1]):
            held = "" if name in seen.inverted else "   (held fixed)"
            lines.append(f"  {name:10s} {ratio:7.1%}{held}")
        weak = [name for name in seen.inverted if ratios.get(name, 0.0) < 0.1 and name != best]
        if weak:
            lines += [
                "",
                f"This run updates {' and '.join(weak)}, which the data sees less than a",
                f"tenth as well as it sees {best}. A parameter moved on a gradient that weak",
                "is being carried by the others rather than resolved: hold it fixed, or",
                "select data that shows it.",
            ]
        lines += [
            "",
            "Only these ratios mean anything. The underlying numbers are in the misfit's",
            "own units, and a preprocessing choice such as trace normalisation moves them",
            "by orders of magnitude -- compare configurations by probing again.",
        ]
        self._report.setPlainText("\n".join(lines))

    def _start(self) -> None:
        session = self.session
        spec = self._spec()
        if session is None or spec is None:
            return
        report = session.runs.validate(spec)
        if not report.valid:
            self._check()
            QMessageBox.warning(
                self, "Not runnable", "The configuration has to be valid before it can start."
            )
            return
        try:
            self._refresh_samples()
            policy = RunStartPolicy(session.runs)
            assessment = policy.check(
                spec,
                sample_run_id=self._sample.currentData(),
                allow_unchecked_large_run=self._allow_unchecked.isChecked(),
            )
            record = session.runs.create(spec)
            policy.record(spec, assessment)
            session.runs.start(record.spec.run_id)
        except (ValueError, KeyError) as error:
            QMessageBox.warning(self, "Could not start", str(error))
            return
        session.events.changed.emit("runs")
        session.events.navigate.emit(Stage.RESULTS.value)
        self._report.setPlainText(
            f"Started {record.spec.run_id}.\n\n"
            f"Writing to {session.folder.runs_root / str(record.spec.run_id)}\n\n"
            "Results lists it, with its progress and what it produced."
        )


#: What a survey of each kind is called when a plugin looks for it, the quantity the
#: importer wrote, and where it wrote it.
_PATH_ALIASES = {"shot_receiver_path": "pairs_path"}


def _fill_paths(value: Any, payload: dict[str, Any]) -> Any:
    """Every empty `*_path` field the register has a file for, filled; nothing else."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key.endswith("_path") and not item:
                found = payload.get(key) or payload.get(_PATH_ALIASES.get(key, ""))
                out[key] = found if isinstance(found, str) else item
            else:
                out[key] = _fill_paths(item, payload)
        return out
    return value


_CHANNELS: dict[DatasetKind, tuple[str, QuantityType, str, str, float]] = {
    DatasetKind.ERT: ("dc", QuantityType.TRANSFER_RESISTANCE, "ohm", "observations_path", 0.02),
    DatasetKind.GRAVITY: (
        "gravity",
        QuantityType.GRAVITY_ACCELERATION,
        "mGal",
        "canonical_observations_path",
        0.02,
    ),
    DatasetKind.MAGNETICS: (
        "tmi",
        QuantityType.MAGNETIC_ANOMALY,
        "nT",
        "canonical_observations_path",
        2.0,
    ),
    DatasetKind.AEM: (
        "tdem",
        QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
        "V/m^2",
        "canonical_observations_path",
        0.05,
    ),
}


def _engine_of(plugin_id: str) -> str:
    """The engine a plugin runs on, from the first word of its identifier."""
    head = plugin_id.split(".", 1)[0]
    return "simpeg" if head == "ofag" else head
