"""The single OFAG-to-pyGIMLi unit boundary."""

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.units import NumberOrArray, convert_from_engine_units, convert_to_engine_units

ENGINE = "pygimli"


def resistivity_to_pygimli(value_ohm_m: NumberOrArray) -> float | np.ndarray:
    """Convert project resistivity (ohm.m) to pyGIMLi ohm.m."""
    return convert_to_engine_units(value_ohm_m, QuantityType.RESISTIVITY, ENGINE)


def resistivity_from_pygimli(value_ohm_m: NumberOrArray) -> float | np.ndarray:
    """Convert a pyGIMLi resistivity model (ohm.m) to project ohm.m."""
    return convert_from_engine_units(value_ohm_m, QuantityType.RESISTIVITY, ENGINE)


def transfer_resistance_to_pygimli(value_ohm: NumberOrArray) -> float | np.ndarray:
    """Convert project transfer resistance (ohm) to pyGIMLi ohm."""
    return convert_to_engine_units(value_ohm, QuantityType.TRANSFER_RESISTANCE, ENGINE)


def transfer_resistance_from_pygimli(value_ohm: NumberOrArray) -> float | np.ndarray:
    """Convert a pyGIMLi transfer resistance (ohm) to project ohm."""
    return convert_from_engine_units(value_ohm, QuantityType.TRANSFER_RESISTANCE, ENGINE)


def chargeability_to_pygimli(value: NumberOrArray) -> float | np.ndarray:
    """Convert project chargeability (dimensionless) to pyGIMLi's."""
    return convert_to_engine_units(value, QuantityType.CHARGEABILITY, ENGINE)


def chargeability_from_pygimli(value: NumberOrArray) -> float | np.ndarray:
    """Convert a pyGIMLi chargeability model to project dimensionless."""
    return convert_from_engine_units(value, QuantityType.CHARGEABILITY, ENGINE)
