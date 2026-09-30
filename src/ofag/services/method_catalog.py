"""Human-facing method descriptions shared by application adapters."""

from dataclasses import dataclass
from importlib.util import find_spec


@dataclass(frozen=True)
class MethodInfo:
    name: str
    kinds: tuple[str, ...]
    modules: tuple[str, ...] = ()
    extra: str = ""

    def readiness(self, available_kinds: set[str]) -> str:
        missing = [module for module in self.modules if find_spec(module) is None]
        if missing:
            return f"Needs {self.extra} extra"
        if not set(self.kinds).issubset(available_kinds):
            return "Needs matching data"
        return "Ready to configure"


METHODS = {
    "ofag.fixture.gravity3d": MethodInfo("Offline diagnostic fixture", (), (), ""),
    "simpeg.pf.gravity3d": MethodInfo("3D gravity inversion", ("gravity",), ("simpeg",), "simpeg"),
    "simpeg.pf.magnetics3d": MethodInfo(
        "3D magnetic inversion", ("magnetics",), ("simpeg",), "simpeg"
    ),
    "simpeg.joint.gravmag.cross_gradient": MethodInfo(
        "Joint gravity / magnetic inversion", ("gravity", "magnetics"), ("simpeg",), "simpeg"
    ),
    "simpeg.aem.tdem1d": MethodInfo("1D transient EM sounding", ("aem",), ("simpeg",), "simpeg"),
    "simpeg.aem.batch_tdem1d": MethodInfo(
        "Transient EM sounding batch", ("aem",), ("simpeg",), "simpeg"
    ),
    "simpeg.aem.tdem3d_forward": MethodInfo(
        "3D transient EM forward model", ("aem",), ("simpeg",), "simpeg"
    ),
    "simpeg.aem.fdem1d": MethodInfo("1D frequency-domain EM", ("aem",), ("simpeg",), "simpeg"),
    "simpeg.nsem.mt1d_batch": MethodInfo("1D MT sounding batch", ("mt",), ("simpeg",), "simpeg"),
    "simpeg.nsem.mt2d": MethodInfo("2D MT profile inversion", ("mt",), ("simpeg",), "simpeg"),
    "pygimli.ert.dcip": MethodInfo(
        "Resistivity / induced polarization", ("ert",), ("pygimli", "pgcore"), "pygimli"
    ),
    "pygimli.seismic.traveltime": MethodInfo(
        "Seismic travel-time inversion", ("seismic",), ("pygimli", "pgcore"), "pygimli"
    ),
    "deepwave.fwi.elastic2d": MethodInfo(
        "2D elastic waveform inversion", ("seismic",), ("deepwave", "torch"), "seismic"
    ),
}


def method_info(plugin_id: str) -> MethodInfo:
    return METHODS.get(plugin_id, MethodInfo(plugin_id, ()))


# Parameters always remain available; grouping changes presentation only.
ADVANCED_FIELDS = frozenset(
    {
        "max_iterations",
        "max_cg_iterations",
        "cg_tolerance",
        "beta",
        "beta_ratio",
        "beta_cooling_factor",
        "beta_cooling_rate",
        "alpha_s",
        "alpha_x",
        "alpha_y",
        "alpha_z",
        "irls",
        "irls_threshold",
        "sensitivity_floor",
        "optimizer",
        "regularization",
        "directives",
        "simulation",
        "solver",
        "line_search",
        "max_line_search_iterations",
        "cooling_factor",
        "cooling_rate",
        "target_chi_factor",
        "norms",
    }
)


def advanced_parameter(name: str) -> bool:
    return name in ADVANCED_FIELDS or name.startswith(("irls_", "beta_", "cg_", "alpha_"))
