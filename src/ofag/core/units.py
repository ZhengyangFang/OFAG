"""Project-unit conversion at OFAG import and engine boundaries."""

from collections.abc import Sequence
from typing import Any, TypeAlias

import numpy as np
from pint import UnitRegistry
from pint.errors import DimensionalityError, UndefinedUnitError

from ofag.core.constants import CANONICAL_UNITS, QuantityType

NumberOrArray: TypeAlias = float | Sequence[float] | np.ndarray


class UnitValidationError(ValueError):
    """A quantity is missing a unit or does not match its declared physics."""


ureg: UnitRegistry[Any] = UnitRegistry(autoconvert_offset_to_baseunit=True)
ureg.define("mGal = 1e-5 * meter / second ** 2")
ureg.define("Eotvos = 1e-9 / second ** 2")


def _quantity(value: NumberOrArray, source_unit: str) -> Any:
    if not source_unit.strip():
        raise UnitValidationError("unit is required; provide an explicit source unit")
    try:
        return ureg.Quantity(value, source_unit)
    except UndefinedUnitError as error:
        raise UnitValidationError(f"unknown unit {source_unit!r}") from error


def _normalize_magnitude(value: object) -> float | np.ndarray:
    magnitude = np.asarray(value)
    if magnitude.ndim == 0:
        return float(magnitude)
    return magnitude


def validate_unit_dimension(unit: str, quantity_type: QuantityType) -> None:
    """Reject a unit whose dimensionality differs from the named physics quantity."""
    expected = ureg.Quantity(1, CANONICAL_UNITS[quantity_type])
    candidate = _quantity(1, unit)
    try:
        candidate.to(expected.units)
    except DimensionalityError as error:
        raise UnitValidationError(
            f"unit {unit!r} is invalid for {quantity_type.value}; "
            f"expected dimensionality compatible with {expected.units}"
        ) from error


def canonicalize_quantity(
    value: NumberOrArray, source_unit: str, quantity_type: QuantityType
) -> float | np.ndarray:
    """Convert an explicitly labelled value into OFAG's project standard unit."""
    validate_unit_dimension(source_unit, quantity_type)
    try:
        converted = _quantity(value, source_unit).to(CANONICAL_UNITS[quantity_type])
    except DimensionalityError as error:  # defensive; validation above provides the clearer error
        raise UnitValidationError(str(error)) from error
    return _normalize_magnitude(converted.magnitude)


_SIMPEG_UNITS: dict[QuantityType, str] = {
    QuantityType.DENSITY_CONTRAST: "gram / centimeter ** 3",
    QuantityType.GRAVITY_ACCELERATION: "mGal",
    QuantityType.MAGNETIC_ANOMALY: "nanotesla",
    QuantityType.MAGNETIC_FLUX_DENSITY: "nanotesla",
    QuantityType.ANGLE: "degree",
}

# pyGIMLi works in SI throughout its resistivity stack: ohm.m for resistivity, ohm for
# transfer resistance, dimensionless chargeability.
_PYGIMLI_UNITS: dict[QuantityType, str] = {}

_ENGINE_UNITS: dict[str, dict[QuantityType, str]] = {
    "simpeg": _SIMPEG_UNITS,
    "pygimli": _PYGIMLI_UNITS,
}


def _engine_unit(quantity_type: QuantityType, engine: str) -> str:
    try:
        overrides = _ENGINE_UNITS[engine]
    except KeyError as error:
        known = ", ".join(sorted(_ENGINE_UNITS))
        raise UnitValidationError(
            f"unsupported engine {engine!r}; known engines: {known}"
        ) from error
    return overrides.get(quantity_type, CANONICAL_UNITS[quantity_type])


def convert_to_engine_units(
    value: NumberOrArray, quantity_type: QuantityType, engine: str
) -> float | np.ndarray:
    """Convert project-standard values at an engine adapter boundary only."""
    target = _engine_unit(quantity_type, engine)
    converted = ureg.Quantity(value, CANONICAL_UNITS[quantity_type]).to(target)
    return _normalize_magnitude(converted.magnitude)


def convert_from_engine_units(
    value: NumberOrArray, quantity_type: QuantityType, engine: str
) -> float | np.ndarray:
    """Convert an engine result immediately back into its project standard unit."""
    source = _engine_unit(quantity_type, engine)
    return canonicalize_quantity(value, source, quantity_type)
