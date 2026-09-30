"""What an inversion will solve over, prepared before it is configured."""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ofag.core.schemas import DatasetKind
from ofag.desktop.navigation import Stage
from ofag.desktop.plotting import PlotPanel
from ofag.desktop.specform import SpecForm
from ofag.desktop.stages.base import StagePanel


class SetupStage(StagePanel):
    """Select the part of a survey to invert, and state what to start from."""

    def __init__(self) -> None:
        super().__init__(Stage.SETUP)

        self._dataset = QComboBox()
        self._dataset.currentIndexChanged.connect(self._dataset_changed)

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Survey"))
        chooser.addWidget(self._dataset, 2)

        self._extract_form: SpecForm | None = None
        self._model_form: SpecForm | None = None
        self._extract_host = QGroupBox("Select what to invert")
        self._extract_host.setLayout(QVBoxLayout())
        self._model_host = QGroupBox("Starting model")
        self._model_host.setLayout(QVBoxLayout())

        prepare = QPushButton("Prepare the line")
        prepare.clicked.connect(self._prepare)
        build = QPushButton("Build the starting model")
        build.clicked.connect(self._build_model)
        self._prepare_button = prepare
        self._build_button = build
        show_map = QPushButton("Show the survey in plan")
        show_map.clicked.connect(self._show_map)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(prepare)
        buttons.addWidget(build)

        left = QVBoxLayout()
        left.addWidget(self._extract_host)
        left.addWidget(self._model_host)
        left.addLayout(buttons)
        left.addStretch(1)
        left_holder = QWidget()
        left_holder.setLayout(left)
        # Shown only for a SEG-Y line, the one survey with a selection step and a
        # starting model to build here.
        self._left_holder = left_holder
        chooser.addWidget(show_map)
        chooser.addStretch(1)

        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._plot = PlotPanel()
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self._plot)
        right.addWidget(self._report)
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_holder)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self._body.addLayout(chooser)
        self._body.addWidget(splitter, 1)

    # -- what there is to prepare ------------------------------------------

    def refresh(self) -> None:
        session = self.session
        if session is None:
            return
        same = getattr(self, "_catalog_session", None) is session
        selected = self._dataset.currentData() if same else None
        self._catalog_session = session
        self._dataset.blockSignals(True)
        self._dataset.clear()
        for dataset in session.workspace().datasets:
            self._dataset.addItem(f"{dataset.name} ({dataset.kind.value})", dataset.dataset_id)
        from ofag.desktop.selection import find_data

        self._dataset.setCurrentIndex(max(0, find_data(self._dataset, selected)))
        self._dataset.blockSignals(False)
        if not same or self._dataset.currentData() != selected:
            self._dataset_changed()

    def _selected(self) -> Any:
        session = self.session
        dataset_id = self._dataset.currentData()
        if session is None or dataset_id is None:
            return None
        for dataset in session.workspace().datasets:
            if dataset.dataset_id == dataset_id:
                return dataset
        return None

    def _dataset_changed(self) -> None:
        dataset = self._selected()
        if self.session is not None and dataset is not None:
            self.session.selected_dataset_id = dataset.dataset_id
        _replace(self._extract_host, None)
        _replace(self._model_host, None)
        self._extract_form = None
        self._model_form = None
        segy = (
            dataset is not None
            and dataset.kind is DatasetKind.SEISMIC
            and "pairs_path" not in dataset.payload
        )
        self._left_holder.setVisible(segy)
        self._report.setVisible(segy)
        # The two steps are the SEG-Y line's; offered for anything else they were
        # buttons that did nothing when pressed.
        self._prepare_button.setVisible(segy)
        self._build_button.setVisible(segy)
        if dataset is None:
            self._plot.clear("Select a survey.")
            return
        self._preview(dataset)
        if segy:
            from ofag.services.seismic_prepare import SegyExtractRequest, StartingModelRequest

            self._extract_form = SpecForm(SegyExtractRequest)
            self._extract_form.set_value(_seed_from_dataset(dataset.payload))
            _replace(self._extract_host, self._extract_form)
            self._model_form = SpecForm(StartingModelRequest)
            _replace(self._model_host, self._model_form)
        else:
            _replace(
                self._extract_host,
                _wrapped(
                    f"A {dataset.kind.value} survey needs no selection step: the whole survey "
                    "is inverted, and the mesh is part of the run's own configuration."
                ),
            )
            _replace(
                self._model_host,
                _wrapped(
                    "Set in the Inversion stage, with the rest of the run: this survey has no "
                    "separate starting-model step."
                ),
            )

    def _preview(self, dataset: Any) -> None:
        """Draw the selected survey as its method is read: data, not a blank panel."""
        from ofag.services.data_preview import (
            pseudosection,
            sounding_directory,
            station_values,
            traveltime_curves,
        )

        payload = dataset.payload
        paths = {
            key: payload.get(key)
            for key in (
                "electrodes_path",
                "quadrupoles_path",
                "observations_path",
                "sensors_path",
                "pairs_path",
            )
        }
        try:
            if dataset.kind is DatasetKind.ERT and all(
                isinstance(paths[k], str)
                for k in ("electrodes_path", "quadrupoles_path", "observations_path")
            ):
                section = pseudosection(
                    paths["electrodes_path"], paths["quadrupoles_path"], paths["observations_path"]
                )
                dropped = (
                    f", {section.dropped} with no positive apparent resistivity"
                    if section.dropped
                    else ""
                )
                self._plot.pseudosection(
                    section,
                    title=f"{dataset.name}: {section.midpoint_m.size} readings{dropped}",
                )
                return
            if dataset.kind is DatasetKind.SEISMIC and all(
                isinstance(paths[k], str)
                for k in ("sensors_path", "pairs_path", "observations_path")
            ):
                curves = traveltime_curves(
                    paths["sensors_path"], paths["pairs_path"], paths["observations_path"]
                )
                self._plot.traveltime_curves(
                    curves, title=f"{dataset.name}: first arrivals of {len(curves.shots)} shots"
                )
                return
            observations = payload.get("canonical_observations_path")
            if dataset.kind in (
                DatasetKind.GRAVITY,
                DatasetKind.TOPOGRAPHY,
                DatasetKind.MAGNETICS,
            ) and isinstance(observations, str):
                stations = station_values(observations)
                self._plot.station_map(
                    stations, title=f"{dataset.name}: {stations.values.size} stations"
                )
                return
            folder = payload.get("import_directory")
            if dataset.kind in (DatasetKind.MT, DatasetKind.AEM) and isinstance(folder, str):
                soundings = sounding_directory(folder)
                if soundings is not None:
                    self._plot.sounding_curves(soundings, title=dataset.name)
                    return
        except (OSError, ValueError) as unreadable:
            self._plot.clear(f"{dataset.name} could not be drawn: {unreadable}")
            return
        self._show_map()

    # -- doing it -----------------------------------------------------------

    def _prepare(self) -> None:
        session = self.session
        form = self._extract_form
        if session is None or form is None:
            return
        issues = form.errors()
        if issues:
            self._report.setPlainText("Not ready:\n  " + "\n  ".join(issues))
            return
        from ofag.services.seismic_prepare import SegyExtractRequest

        request = SegyExtractRequest.model_validate(form.value())
        try:
            line = session.seismic.extract(request)
        except (ValueError, OSError) as error:
            self._report.setPlainText(str(error))
            return
        self._report.setPlainText(
            "\n".join(
                [
                    f"{line.shot_count} shots of {line.shots_available} available",
                    f"{line.receiver_count} channels used, {line.channels_shared} shared by "
                    f"every shot, {line.channels_available} offered by the richest",
                    f"{line.sample_count} samples of {line.samples_available}",
                    f"{line.line_length_m:.0f} m at {line.line_azimuth_degrees:.1f} degrees",
                    f"offline deviation {line.maximum_offline_deviation_m:.0f} m",
                    "",
                    "Preprocessing: "
                    + ("; ".join(line.preprocessing_applied) or "none, as recorded"),
                    "",
                    f"observations  {line.observations_path}",
                    f"sources       {line.sources_path}",
                    f"receivers     {line.receivers_path}",
                    f"receipt       {line.preparation_path}",
                    f"digest        {line.observations_sha256[:16]}…",
                ]
            )
        )
        self._draw_prepared(line)

    def _build_model(self) -> None:
        session = self.session
        form = self._model_form
        if session is None or form is None:
            return
        issues = form.errors()
        if issues:
            self._report.setPlainText("Not ready:\n  " + "\n  ".join(issues))
            return
        from ofag.services.seismic_prepare import StartingModelRequest

        try:
            model = session.seismic.starting_model(
                StartingModelRequest.model_validate(form.value())
            )
        except (ValueError, OSError) as error:
            self._report.setPlainText(str(error))
            return
        self._report.setPlainText(
            "\n".join(
                [
                    f"{model.shape[0]} by {model.shape[1]} cells",
                    f"Vp {model.p_velocity_min_m_s:.0f}–{model.p_velocity_max_m_s:.0f} m/s",
                    f"Vs {model.s_velocity_min_m_s:.0f}–{model.s_velocity_max_m_s:.0f} m/s",
                    f"density {model.density_kg_m3:.0f} kg/m^3",
                    "",
                    f"vp       {model.initial_vp_path}",
                    f"vs       {model.initial_vs_path}",
                    f"density  {model.density_path}",
                ]
            )
        )

    def _draw_prepared(self, line: Any) -> None:
        import numpy as np

        try:
            receivers = np.load(line.receivers_path, allow_pickle=False)
            sources = np.load(line.sources_path, allow_pickle=False)
        except (OSError, ValueError):
            return
        self._plot.stations(
            receivers[:, 0],
            np.zeros(len(receivers)),
            title=f"{line.source_filename}: the line as it will be inverted",
            second=(sources[:, 0], np.zeros(len(sources)), "shots"),
        )

    def _show_map(self) -> None:
        """The survey in plan, from whatever geometry its importer recorded."""
        dataset = self._selected()
        if dataset is None:
            self._plot.clear("Select a survey.")
            return
        import numpy as np

        payload = dataset.payload
        path = payload.get("geometry_path") or payload.get("electrodes_path")
        if not isinstance(path, str):
            self._plot.clear(
                f"The {dataset.kind.value} importer records no station geometry to draw."
            )
            return
        try:
            geometry = np.load(path, allow_pickle=False)
        except (OSError, ValueError) as error:
            self._plot.clear(str(error))
            return
        if geometry.shape[1] >= 4:
            self._plot.stations(
                geometry[:, 2],
                geometry[:, 3],
                title=f"{dataset.name}: receivers and sources",
                second=(geometry[:, 0], geometry[:, 1], "sources"),
            )
        else:
            self._plot.stations(geometry[:, 0], geometry[:, 1], title=f"{dataset.name}: stations")


def _seed_from_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    """Carry the import's own declaration into the selection step."""
    carried = (
        "source_path",
        "source_x_byte",
        "source_y_byte",
        "receiver_x_byte",
        "receiver_y_byte",
        "coordinate_unit",
    )
    seed = {key: payload[key] for key in carried if key in payload}
    if "coordinate_scalar_applied" in payload:
        seed["coordinate_scalar"] = payload["coordinate_scalar_applied"]
    if "traces_per_station" in payload and payload["traces_per_station"]:
        seed["components"] = payload["traces_per_station"]
    return seed


def _wrapped(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


def _replace(box: QGroupBox, widget: QWidget | None) -> None:
    layout = box.layout()
    assert isinstance(layout, QVBoxLayout)
    while layout.count():
        item = layout.takeAt(0)
        existing = None if item is None else item.widget()
        if existing is not None:
            # Hidden and unparented first: out of the layout, a widget stays drawn where
            # it was until the event loop deletes it, and two explanations sat on top of
            # each other in the box.
            existing.hide()
            existing.setParent(None)
            existing.deleteLater()
    if widget is not None:
        layout.addWidget(widget)
