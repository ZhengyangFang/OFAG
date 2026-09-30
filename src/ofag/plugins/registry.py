"""Versioned, explicit plugin registration."""

from ofag.plugins.protocol import InversionPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, InversionPlugin] = {}

    def register(self, plugin: InversionPlugin) -> None:
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"plugin {plugin.plugin_id!r} is already registered")
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> InversionPlugin:
        try:
            return self._plugins[plugin_id]
        except KeyError as error:
            raise KeyError(f"unknown plugin {plugin_id!r}") from error

    def all(self) -> tuple[InversionPlugin, ...]:
        return tuple(self._plugins.values())


def default_registry() -> PluginRegistry:
    from ofag.plugins.deepwave_fwi import DeepwaveElasticFwiPlugin
    from ofag.plugins.pygimli_ert import PyGIMLiERTPlugin
    from ofag.plugins.pygimli_traveltime import PyGIMLiTravelTimePlugin
    from ofag.plugins.simpeg_fdem1d import SimPEGFDEM1DPlugin
    from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin
    from ofag.plugins.simpeg_gravmag_joint import SimPEGGravMagJointPlugin
    from ofag.plugins.simpeg_magnetics import SimPEGMagnetics3DPlugin
    from ofag.plugins.simpeg_mt1d import SimPEGMT1DPlugin
    from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin
    from ofag.plugins.simpeg_tdem1d import SimPEGTDEM1DPlugin
    from ofag.plugins.simpeg_tdem3d_forward import SimPEGTDEM3DForwardPlugin
    from ofag.plugins.simpeg_tdem_batch import SimPEGTDEMBatchPlugin
    from ofag.plugins.synthetic_gravity import SyntheticGravityPlugin

    registry = PluginRegistry()
    registry.register(SyntheticGravityPlugin())
    registry.register(SimPEGGravity3DPlugin())
    registry.register(SimPEGMagnetics3DPlugin())
    registry.register(SimPEGGravMagJointPlugin())
    registry.register(SimPEGFDEM1DPlugin())
    registry.register(SimPEGTDEM1DPlugin())
    registry.register(SimPEGTDEM3DForwardPlugin())
    registry.register(SimPEGTDEMBatchPlugin())
    registry.register(SimPEGMT1DPlugin())
    registry.register(SimPEGNSEM2DPlugin())
    registry.register(PyGIMLiERTPlugin())
    registry.register(PyGIMLiTravelTimePlugin())
    registry.register(DeepwaveElasticFwiPlugin())
    return registry
