from __future__ import annotations

import typing

from homeassistant.components import number
from homeassistant.const import PERCENTAGE, UnitOfTemperature

from . import meross_entity as me
from .helpers import schedule_async_callback
from .merossclient import const as mc

if typing.TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .climate import MtsClimate
    from .helpers.manager import EntityManager
    from .meross_device import MerossDevice


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_devices
):
    me.platform_setup_entry(hass, config_entry, async_add_devices, number.DOMAIN)


class MLConfigNumber(me.MerossEntity, number.NumberEntity):
    PLATFORM = number.DOMAIN
    DeviceClass = number.NumberDeviceClass
    DEVICECLASS_TO_UNIT_MAP = {
        DeviceClass.HUMIDITY: PERCENTAGE,
        DeviceClass.TEMPERATURE: UnitOfTemperature.CELSIUS,
    }

    DEBOUNCE_DELAY = 1

    manager: MerossDevice

    # customize the request payload for different
    # devices api. see 'async_set_native_value' to see how
    namespace: str
    key_namespace: str
    key_channel: str = mc.KEY_CHANNEL
    key_value: str

    device_scale: float = 1
    """used to scale the device value when converting to/from native value"""
    device_value: float | None
    """the 'native' device value carried in protocol messages"""

    # HA core entity attributes:
    entity_category = me.EntityCategory.CONFIG
    mode: number.NumberMode = number.NumberMode.BOX
    native_max_value: float
    native_min_value: float
    native_step: float
    native_unit_of_measurement: str | None = None
    _attr_state: int | float | None

    __slots__ = (
        "device_value",
        "_unsub_request",
    )

    def __init__(
        self,
        manager: EntityManager,
        channel: object | None,
        entitykey: str | None = None,
        device_class: DeviceClass | None = None,
    ):
        self.device_value = None
        self._unsub_request = None
        super().__init__(manager, channel, entitykey, device_class)

    async def async_shutdown(self):
        self._cancel_request()
        await super().async_shutdown()

    def set_unavailable(self):
        self.device_value = None
        self._cancel_request()
        super().set_unavailable()

    # interface: number.NumberEntity
    """REMOVE(attr)
    @property
    def mode(self) -> number.NumberMode:
        return NUMBERMODE_BOX  # type: ignore

    @property
    def native_max_value(self):
        return self._attr_native_max_value

    @property
    def native_min_value(self):
        return self._attr_native_min_value

    @property
    def native_step(self):
        return self._attr_native_step

    @property
    def native_unit_of_measurement(self):
        return self._attr_native_unit_of_measurement
    """

    @property
    def native_value(self):
        return self._attr_state

    async def async_set_native_value(self, value: float):
        device_value = round(value * self.device_scale)
        device_step = round(self.native_step * self.device_scale)
        device_value = round(device_value / device_step) * device_step
        # since the async_set_native_value might be triggered back-to-back
        # especially when using the BOXED UI we're debouncing the device
        # request and provide 'temporaneous' optimistic updates
        self.update_state(device_value / self.device_scale)
        if self._unsub_request:
            self._unsub_request.cancel()
        self._unsub_request = schedule_async_callback(
            self.hass, self.DEBOUNCE_DELAY, self._async_request_debounce, device_value
        )

    # interface: self
    def update_native_value(self, device_value):
        self.device_value = device_value
        self.update_state(device_value / self.device_scale)

    async def async_request(self, device_value):
        """sends the actual request to the device. this is likely to be overloaded"""
        return await self.manager.async_request_ack(
            self.namespace,
            mc.METHOD_SET,
            {
                self.key_namespace: [
                    {self.key_channel: self.channel, self.key_value: device_value}
                ]
            },
        )

    async def _async_request_debounce(self, device_value):
        self._unsub_request = None
        if await self.async_request(device_value):
            self.update_native_value(device_value)
        else:
            # restore the last good known device value
            device_value = self.device_value
            if device_value is not None:
                self.update_state(device_value / self.device_scale)

    def _cancel_request(self):
        if self._unsub_request:
            self._unsub_request.cancel()
            self._unsub_request = None


class MtsTemperatureNumber(MLConfigNumber):
    """
    Common number entity for representing MTS temperatures configuration
    """

    __slots__ = (
        "climate",
        "device_scale",
    )

    def __init__(self, climate: MtsClimate, entitykey: str):
        self.climate = climate
        self.device_scale = climate.device_scale
        super().__init__(
            climate.manager,
            climate.channel,
            entitykey,
            MLConfigNumber.DeviceClass.TEMPERATURE,
        )

    @property
    def native_unit_of_measurement(self):
        # the climate.temperature_unit is actually fixed to CELSIUS
        # but I see a probable change in device features (change of device unit)
        # so we're using a property here to be more future-proof
        return self.climate.temperature_unit

    """REMOVE(attr)
    @property
    def device_scale(self):
        return self.climate.device_scale
    """


class MtsRichTemperatureNumber(MtsTemperatureNumber):
    """
    Slightly enriched MtsTemperatureNumber to generalize  a lot of Thermostat namespaces
    which usually carry a temperature value together with some added entities (typically a switch
    to enable the feature and a 'warning sensor')
    typical examples are :
    "calibration": {"channel": 0, "value": 0, "min": -80, "max": 80, "lmTime": 1697010767}
    "deadZone":
    "frost": {"channel": 0, "onoff": 1, "value": 500, "min": 500, "max": 1500, "warning": 0}
    "overheat": {"warning": 0, "value": 335, "onoff": 1, "min": 200, "max": 700,
        "lmTime": 1674121910, "currentTemp": 355, "channel": 0}
    """

    entitykey: str

    __slots__ = (
        "sensor_warning",
        "switch",
        "native_max_value",
        "native_min_value",
        "native_step",
    )

    def __init__(self, climate: MtsClimate, entitykey: str):
        super().__init__(climate, entitykey)
        manager = self.manager
        # preset entity platforms since these might be instantiated later
        from .switch import MtsConfigSwitch

        manager.platforms.setdefault(MtsConfigSwitch.PLATFORM)
        from .sensor import MLSensor

        manager.platforms.setdefault(MLSensor.PLATFORM)
        self.sensor_warning = None
        self.switch = None
        manager.register_parser(
            self.namespace,
            self,
            self._parse,
        )

    async def async_shutdown(self):
        self.switch = None
        self.sensor_warning = None
        await super().async_shutdown()

    def _parse(self, payload: dict):
        """
        {"channel": 0, "value": 0, "min": -80, "max": 80, "lmTime": 1697010767}
        """
        if mc.KEY_MIN in payload:
            self.native_min_value = payload[mc.KEY_MIN] / self.device_scale
        if mc.KEY_MAX in payload:
            self.native_max_value = payload[mc.KEY_MAX] / self.device_scale
        self.update_native_value(payload[self.key_value])
        if mc.KEY_ONOFF in payload:
            # on demand instance
            try:
                self.switch.update_onoff(payload[mc.KEY_ONOFF])  # type: ignore
            except Exception as exception:
                from .switch import MtsConfigSwitch

                self.switch = MtsConfigSwitch(
                    self.climate, f"{self.entitykey}_switch", self.namespace
                )
                self.switch.update_onoff(payload[mc.KEY_ONOFF])
        if mc.KEY_WARNING in payload:
            # on demand instance
            try:
                self.sensor_warning.update_state(payload[mc.KEY_WARNING])  # type: ignore
            except Exception as exception:
                from .sensor import MLSensor

                self.sensor_warning = sensor_warning = MLSensor(
                    self.manager,
                    self.channel,
                    f"{self.entitykey}_warning",
                    MLSensor.DeviceClass.ENUM,
                    state=payload[mc.KEY_WARNING],
                )
                sensor_warning.translation_key = f"mts_{sensor_warning.entitykey}"


class MtsCalibrationNumber(MtsRichTemperatureNumber):
    """
    Adjust temperature readings for mts200 and mts960.
    Manages Appliance.Control.Thermostat.Calibration:
    {"channel": 0, "value": 0, "min": -80, "max": 80, "lmTime": 1697010767}
    """

    namespace = mc.NS_APPLIANCE_CONTROL_THERMOSTAT_CALIBRATION
    key_namespace = mc.KEY_CALIBRATION
    key_value = mc.KEY_VALUE

    def __init__(self, climate: MtsClimate):
        self.name = "Calibration"
        self.native_max_value = 8
        self.native_min_value = -8
        self.native_step = 0.1
        super().__init__(climate, mc.KEY_CALIBRATION)

    """REMOVE(attr)
    @property
    def native_step(self):
        return 0.1
    """


class MtsSetPointNumber(MtsTemperatureNumber):
    """
    Helper entity to configure MTS100/150/200 setpoints
    AKA: Heat(comfort) - Cool(sleep) - Eco(away)
    """

    # HA core entity attributes:
    icon: str

    __slots__ = ("icon",)

    def __init__(self, climate: MtsClimate, preset_mode: str):
        self._preset_mode = preset_mode
        self.key_value = climate.PRESET_TO_TEMPERATUREKEY_MAP[preset_mode]
        self.icon = climate.PRESET_TO_ICON_MAP[preset_mode]
        self.name = f"{preset_mode} {MLConfigNumber.DeviceClass.TEMPERATURE}"
        super().__init__(
            climate,
            f"config_{mc.KEY_TEMPERATURE}_{self.key_value}",
        )

    @property
    def native_max_value(self):
        return self.climate.max_temp

    @property
    def native_min_value(self):
        return self.climate.min_temp

    @property
    def native_step(self):
        return self.climate.target_temperature_step

    async def async_request(self, device_value):
        if response := await super().async_request(device_value):
            # mts100(s) reply to the setack with the 'full' (or anyway richer) payload
            # so we'll use the _parse_temperature logic (a bit overkill sometimes) to
            # make sure the climate state is consistent and all the correct roundings
            # are processed when changing any of the presets
            # not sure about mts200 replies..but we're optimist
            key_namespace = self.key_namespace
            payload = response[mc.KEY_PAYLOAD]
            if key_namespace in payload:
                # by design key_namespace is either "temperature" (mts100) or "mode" (mts200)
                self.climate._parse(payload[key_namespace][0])

        return response
