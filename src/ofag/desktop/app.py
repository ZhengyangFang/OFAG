"""Starting the desktop workbench."""

import sys
from pathlib import Path

from ofag.services.project_folder import DEFAULT_RESULT_ROOT


def run_desktop(result_root: Path = DEFAULT_RESULT_ROOT) -> int:
    """Open the workbench on a result root, returning the process exit code."""
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError as error:  # pragma: no cover - depends on the install
        raise SystemExit(
            "The desktop workbench needs the 'desktop' extra: uv sync --extra desktop"
        ) from error

    from ofag.desktop.main_window import MainWindow

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("OFAG")
    application.setOrganizationName("OFAG")

    window = MainWindow(result_root=result_root)
    window.show()
    return int(application.exec())


def main() -> None:  # pragma: no cover - a console entry point
    raise SystemExit(run_desktop())
