"""Every way data gets into a project, declared so an agent can reach it."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ofag.core.schemas import (
    CsvPreviewRequest,
    GravityCsvImportRequest,
    MagneticCsvImportRequest,
    TDEMCsvImportRequest,
    TopographyCsvImportRequest,
)
from ofag.services.aeromagnetic_import import AeromagneticImportRequest
from ofag.services.borehole_import import DrillLogImportRequest
from ofag.services.ert_import import ERTFieldImportRequest
from ofag.services.line_data_import import (
    LayeredLineImportRequest,
    LayeredLineInventoryRequest,
)
from ofag.services.model_import import ExternalModelImportRequest
from ofag.services.mt_import import MtImportRequest
from ofag.services.segy_import import SegyImportRequest
from ofag.services.tem_import import TemImportRequest

__all__ = ["Importer", "IMPORTERS", "importer", "importer_ids"]


@dataclass(frozen=True)
class Importer:
    """One reader, what it is for, and what it needs before it will run."""

    importer_id: str
    what: str
    #: The service's own request type.
    request_model: type[Any]
    #: Which service attribute holds it, and the method that reads.
    service: str
    method: str
    #: What this refuses before it returns anything, in the agent's terms.
    refuses: str = ""
    #: The optional dependency this reader needs, where it needs one.
    needs_extra: str = ""
    #: True where reading produces a run that `RunService` must adopt, rather than a
    #: dataset under the import root.
    adopts_a_run: bool = False
    #: True where the call only looks, so it belongs in the read tier.
    reads_only: bool = False


IMPORTERS: tuple[Importer, ...] = (
    Importer(
        importer_id="ofag.import.csv_preview",
        what="The columns and the first rows of a delimited file, before any mapping.",
        request_model=CsvPreviewRequest,
        service="data",
        method="preview_csv",
        reads_only=True,
    ),
    Importer(
        importer_id="ofag.import.gravity_csv",
        what="Gravity stations from a delimited file, with the anomaly column named.",
        request_model=GravityCsvImportRequest,
        service="data",
        method="import_gravity_csv",
    ),
    Importer(
        importer_id="ofag.import.magnetic_csv",
        what="A magnetic survey from a delimited file.",
        request_model=MagneticCsvImportRequest,
        service="data",
        method="import_magnetic_csv",
        refuses=(
            "A total field read as an anomaly is refused by the domain check: a magnetometer "
            "measures the whole field and a release that calls that column TMI is the normal "
            "case, not the exception (F058)."
        ),
    ),
    Importer(
        importer_id="ofag.import.tdem_csv",
        what="Transient soundings from a delimited file.",
        request_model=TDEMCsvImportRequest,
        service="data",
        method="import_tdem_csv",
    ),
    Importer(
        importer_id="ofag.import.topography_csv",
        what="Ground elevations from a delimited file.",
        request_model=TopographyCsvImportRequest,
        service="data",
        method="import_topography_csv",
    ),
    Importer(
        importer_id="ofag.import.ert_field",
        what="One resistivity acquisition file, in the instrument's own format.",
        request_model=ERTFieldImportRequest,
        service="ert",
        method="import_field_file",
        refuses=(
            "The geometric factor is recomputed from the electrode coordinates and compared "
            "with the instrument's own apparent resistivity, so A, B, M and N read in the "
            "wrong order is refused rather than inverted."
        ),
        needs_extra="ert-formats",
    ),
    Importer(
        importer_id="ofag.import.tem_usf",
        what="A directory of transient soundings in Universal Sounding Format.",
        request_model=TemImportRequest,
        service="tem",
        method="import_usf_directory",
        refuses=(
            "A declared turn-off ramp no transmitter could produce is refused against the "
            "loop and the current the file itself declares (F054). A file that declares no "
            "location or no z direction is refused unless the caller supplies them (F029, F001)."
        ),
    ),
    Importer(
        importer_id="ofag.import.mt_edi",
        what="A directory of magnetotelluric sites as EDIs.",
        request_model=MtImportRequest,
        service="mt",
        method="import_edi_directory",
        refuses=(
            "A site whose phase-tensor skew exceeds the stated maximum is refused, because a "
            "layered inversion accepts a three-dimensional site and returns a model and a "
            "misfit for it (F014)."
        ),
    ),
    Importer(
        importer_id="ofag.import.drill_logs",
        what="Logged drill holes, with their collars and their intervals.",
        request_model=DrillLogImportRequest,
        service="borehole",
        method="import_drill_logs",
        refuses=(
            "A hole with no elevation source is refused, and a log that crosses a unit twice "
            "will not construct as a pile -- its interval tops are rock changes and not "
            "points on one surface (F071)."
        ),
    ),
    Importer(
        importer_id="ofag.import.aeromagnetic",
        what="An airborne magnetic survey, line by line.",
        request_model=AeromagneticImportRequest,
        service="aeromagnetic",
        method="import_survey",
    ),
    Importer(
        importer_id="ofag.import.segy",
        what="A seismic line in SEG-Y.",
        request_model=SegyImportRequest,
        service="segy",
        method="import_file",
        needs_extra="seismic",
    ),
    Importer(
        importer_id="ofag.import.line_inventory",
        what="What a layered-line delivery holds, before importing any of it.",
        request_model=LayeredLineInventoryRequest,
        service="line",
        method="inventory",
        reads_only=True,
    ),
    Importer(
        importer_id="ofag.import.layered_line",
        what="One line of layered soundings, written as OFAG's batch artifacts.",
        request_model=LayeredLineImportRequest,
        service="line",
        method="import_line",
        adopts_a_run=True,
    ),
    Importer(
        importer_id="ofag.import.external_model",
        what="A model somebody else inverted, read in for comparison.",
        request_model=ExternalModelImportRequest,
        service="model",
        method="import_model",
        adopts_a_run=True,
        needs_extra="simpeg",
    ),
)


def importer_ids() -> tuple[str, ...]:
    return tuple(item.importer_id for item in IMPORTERS)


#: The kind each reader's output is registered as in an open project.
REGISTERS_AS: dict[str, str] = {
    "ofag.import.gravity_csv": "gravity",
    "ofag.import.magnetic_csv": "magnetics",
    "ofag.import.aeromagnetic": "magnetics",
    "ofag.import.tdem_csv": "aem",
    "ofag.import.tem_usf": "aem",
    "ofag.import.topography_csv": "topography",
    "ofag.import.ert_field": "ert",
    "ofag.import.mt_edi": "mt",
    "ofag.import.segy": "seismic",
}

#: Where a request names the file or folder it read, in the order looked for.
SOURCE_FIELDS = ("source_path", "path", "data_path", "source_directory", "directory", "filename")


def importer(importer_id: str) -> Importer:
    """One importer by name, or a refusal that says what there is."""
    for item in IMPORTERS:
        if item.importer_id == importer_id:
            return item
    raise KeyError(
        f"no importer named {importer_id!r}. The readers are exactly: " + ", ".join(importer_ids())
    )


#: Kept beside the registry so a caller can check the shape of every entry without
#: importing the services.
def request_schema(item: Importer) -> dict[str, Any]:
    """The reader's own request schema, from the service's own model."""
    model_schema: Callable[[], dict[str, Any]] = item.request_model.model_json_schema
    return dict(model_schema())
