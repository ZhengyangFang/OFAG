"""What the workbench is divided into, and why it is divided that way."""

from dataclasses import dataclass
from enum import StrEnum


class Stage(StrEnum):
    """The six places a project can be worked on."""

    DATA = "data"
    SETUP = "setup"
    INVERSION = "inversion"
    RESULTS = "results"
    INTERPRETATION = "interpretation"
    LINEAGE = "lineage"


@dataclass(frozen=True)
class StageInfo:
    """What the sidebar shows and what the stage is for."""

    stage: Stage
    title: str
    purpose: str
    #: True when the stage needs a project open. Only the launcher does not.
    needs_project: bool = True


STAGES: tuple[StageInfo, ...] = (
    StageInfo(Stage.DATA, "Data", "Import and manage surveys."),
    StageInfo(Stage.SETUP, "Setup", "Review data and prepare models."),
    StageInfo(Stage.INVERSION, "Inversion", "Configure, check and run."),
    StageInfo(Stage.RESULTS, "Results", "Review quality and select results."),
    StageInfo(Stage.INTERPRETATION, "Interpretation", "Build and review geological models."),
    StageInfo(Stage.LINEAGE, "Lineage", "Trace data, runs and models."),
)


def stage_info(stage: Stage) -> StageInfo:
    """The entry for a stage, or a failure naming the stage that has none."""
    for info in STAGES:
        if info.stage is stage:
            return info
    raise KeyError(f"{stage} is missing from STAGES")
