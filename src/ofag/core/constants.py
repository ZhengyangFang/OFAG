from enum import StrEnum


class QuantityType(StrEnum):
    LENGTH = "length"
    TIME = "time"
    ANGLE = "angle"
    FREQUENCY = "frequency"
    CONDUCTIVITY = "conductivity"
    ELECTRIC_CURRENT = "electric_current"
    MAGNETIC_DIPOLE_MOMENT = "magnetic_dipole_moment"
    DENSITY_CONTRAST = "density_contrast"
    GRAVITY_ACCELERATION = "gravity_acceleration"
    MAGNETIC_ANOMALY = "magnetic_anomaly"
    MAGNETIC_FLUX_DENSITY = "magnetic_flux_density"
    MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE = "magnetic_flux_density_time_derivative"
    SUSCEPTIBILITY = "susceptibility"
    CROSS_GRADIENT = "cross_gradient"

    # Electrical resistivity and induced polarisation.
    ELECTRIC_POTENTIAL = "electric_potential"
    TRANSFER_RESISTANCE = "transfer_resistance"
    APPARENT_RESISTIVITY = "apparent_resistivity"
    RESISTIVITY = "resistivity"
    CHARGEABILITY = "chargeability"

    # Magnetotellurics.
    MAGNETOTELLURIC_IMPEDANCE = "magnetotelluric_impedance"

    # Seismic.
    P_WAVE_VELOCITY = "p_wave_velocity"
    S_WAVE_VELOCITY = "s_wave_velocity"
    PARTICLE_VELOCITY = "particle_velocity"
    BULK_DENSITY = "bulk_density"
    PRESSURE = "pressure"
    TRAVELTIME = "traveltime"
    QUALITY_FACTOR = "quality_factor"
    THOMSEN_PARAMETER = "thomsen_parameter"

    DIMENSIONLESS = "dimensionless"


class ProjectMethod(StrEnum):
    GRAVITY = "gravity"
    MAGNETICS = "magnetics"
    AEM = "aem"
    MT = "mt"
    ERT = "ert"
    SEISMIC = "seismic"


CANONICAL_UNITS: dict[QuantityType, str] = {
    QuantityType.LENGTH: "meter",
    QuantityType.TIME: "second",
    QuantityType.ANGLE: "radian",
    QuantityType.FREQUENCY: "hertz",
    QuantityType.CONDUCTIVITY: "siemens / meter",
    QuantityType.ELECTRIC_CURRENT: "ampere",
    QuantityType.MAGNETIC_DIPOLE_MOMENT: "ampere * meter ** 2",
    QuantityType.DENSITY_CONTRAST: "gram / centimeter ** 3",
    QuantityType.GRAVITY_ACCELERATION: "mGal",
    QuantityType.MAGNETIC_ANOMALY: "nanotesla",
    QuantityType.MAGNETIC_FLUX_DENSITY: "tesla",
    QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE: "tesla / second",
    QuantityType.SUSCEPTIBILITY: "dimensionless",
    QuantityType.CROSS_GRADIENT: "1 / meter ** 2",
    QuantityType.ELECTRIC_POTENTIAL: "volt",
    QuantityType.TRANSFER_RESISTANCE: "ohm",
    QuantityType.APPARENT_RESISTIVITY: "ohm * meter",
    QuantityType.RESISTIVITY: "ohm * meter",
    QuantityType.CHARGEABILITY: "dimensionless",
    QuantityType.MAGNETOTELLURIC_IMPEDANCE: "ohm",
    QuantityType.P_WAVE_VELOCITY: "meter / second",
    QuantityType.S_WAVE_VELOCITY: "meter / second",
    QuantityType.PARTICLE_VELOCITY: "meter / second",
    QuantityType.BULK_DENSITY: "kilogram / meter ** 3",
    QuantityType.PRESSURE: "pascal",
    QuantityType.TRAVELTIME: "second",
    QuantityType.QUALITY_FACTOR: "dimensionless",
    QuantityType.THOMSEN_PARAMETER: "dimensionless",
    QuantityType.DIMENSIONLESS: "dimensionless",
}
