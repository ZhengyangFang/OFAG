"""The single OFAG-to-SimPEG unit boundary."""

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.units import NumberOrArray, convert_from_engine_units, convert_to_engine_units


def density_to_simpeg(value_g_cc: NumberOrArray) -> float | np.ndarray:
    """Convert project density contrast (g/cc) to SimPEG g/cc."""
    return convert_to_engine_units(value_g_cc, QuantityType.DENSITY_CONTRAST, "simpeg")


def density_from_simpeg(value_g_cc: NumberOrArray) -> float | np.ndarray:
    """Convert SimPEG density contrast (g/cc) to project g/cc."""
    return convert_from_engine_units(value_g_cc, QuantityType.DENSITY_CONTRAST, "simpeg")


def gravity_to_simpeg(value_mgal: NumberOrArray) -> float | np.ndarray:
    """Convert project gravity acceleration (mGal) to SimPEG mGal."""
    return convert_to_engine_units(value_mgal, QuantityType.GRAVITY_ACCELERATION, "simpeg")


#: There is deliberately no plain `gravity_from_simpeg` beside these.
GRAVITY_ANOMALY_SIGN = -1.0


def gravity_anomaly_to_simpeg(value_mgal: NumberOrArray) -> float | np.ndarray:
    """Convert a project gravity anomaly (mGal, positive over excess mass) to SimPEG "gz"."""
    return GRAVITY_ANOMALY_SIGN * np.asarray(
        convert_to_engine_units(value_mgal, QuantityType.GRAVITY_ACCELERATION, "simpeg")
    )


def gravity_anomaly_from_simpeg(value_mgal: NumberOrArray) -> float | np.ndarray:
    """Convert SimPEG "gz" back to a project gravity anomaly (mGal)."""
    return GRAVITY_ANOMALY_SIGN * np.asarray(
        convert_from_engine_units(value_mgal, QuantityType.GRAVITY_ACCELERATION, "simpeg")
    )
