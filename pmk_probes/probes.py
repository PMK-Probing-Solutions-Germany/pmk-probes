""" This module contains classes for controlling PMK probes. The classes are designed to be used with PMK power
supplies"""

import math
import time
from abc import ABCMeta, abstractmethod
from enum import Enum
from functools import lru_cache
from typing import Literal, TypeVar, cast

from .power_supplies import _PMKPowerSupply
from ._data_structures import UUIDs, UserMapping, FireFlyMetadata, PMKProbeProperties, LED
from ._devices import PMKDevice, Channel, DUMMY
from ._errors import ProbeTypeError, UUIDReadError


def _unsigned_to_bytes(command: int, length: int) -> bytes:
    return command.to_bytes(signed=False, byteorder="big", length=length)


def _bytes_to_decimal(scale: float, byte_pair: bytes) -> float:
    return int.from_bytes(byte_pair, byteorder="big", signed=True) / scale


def _decimal_to_byte(scale: float, decimal: float, length: int) -> bytes:
    integer = int(decimal * scale)
    return integer.to_bytes(signed=True, byteorder="big", length=length)


class _PMKProbe(PMKDevice, metaclass=ABCMeta):
    _legacy_model_name = None  # model name of the probe in legacy mode

    def __init__(self, power_supply: _PMKPowerSupply, channel: Channel, verbose: bool = False,
                 allow_legacy: bool = False):
        super().__init__(channel, verbose=verbose)
        self.probe_model = self.__class__.__name__
        self.power_supply = power_supply
        self.channel = channel
        self._validate_probe(power_supply, channel, allow_legacy)

    def __repr__(self):
        return f"{self.probe_model} at {self.channel.name} of {self.power_supply}"

    def _validate_probe(self, power_supply, channel, allow_legacy):
        if self.__class__ not in power_supply.supported_probe_types:
            raise ValueError(f"Probe {self.probe_model} is not supported by this power supply.")
        if channel.value >= power_supply._num_channels + 1:
            raise ValueError(f"Channel {channel.name} is not available on power supply {self.probe_model}.")
        self._check_uuid(allow_legacy)

    def _check_uuid(self, allow_legacy):
        try:
            read_uuid = self.metadata.uuid
        except UUIDReadError:
            read_uuid = None
        uuids_match = read_uuid == self._uuid
        legacy_names_match = self.metadata.model == self._legacy_model_name
        if not uuids_match and not (legacy_names_match and allow_legacy):
            if read_uuid != "":
                raise ProbeTypeError(f"Probe is of type {UUIDs.get_user_value(read_uuid)}, not {self.probe_model}.")
            else:
                raise ProbeTypeError(
                    f"Could not read probe's UUID, use allow_legacy=True if you are sure it is a {self.probe_model}.")

    @property
    @abstractmethod
    def properties(self) -> PMKProbeProperties:
        """Properties of the specific probe model, similar to metadata but stored in the Python package instead of
        the probe's flash."""
        raise NotImplementedError

    @staticmethod
    def _init_using(metadata_value, expected_value) -> bool:
        return metadata_value == expected_value

    @property
    def interface(self):
        return self.power_supply.interface

    @property
    def _uuid(self):
        uuid = UUIDs.get_internal_value(self.probe_model)
        if uuid is not None:
            return uuid
        else:
            raise NotImplementedError("Probe model has no UUID assigned. Please add it to the UUIDs dictionary.")

    def _write_float(self, value, setting_address, executing_command_address):
        raise NotImplementedError

    def _setting_write(self, setting_address: int, setting_value: bytes):
        self._wr_command(setting_address, self._i2c_addresses['unified'], setting_value)

    def _setting_read_raw(self, setting_address: int, setting_byte_count: Literal[1, 2, 4]):
        return self._rd_command(setting_address, self._i2c_addresses['unified'], setting_byte_count)

    def _setting_read_int(self, setting_address: int, setting_byte_count: Literal[1, 2, 4], signed: bool = False):
        return int.from_bytes(self._setting_read_raw(setting_address, setting_byte_count), "big", signed=signed)

    def _wr_command(self, command: int, i2c_address, payload: bytes) -> None:
        """
        The WR command is used to write data to the probe. The payload is a bytes object that is written to the
        probe. Its length also needs to be supplied to the query command.
        """
        _ = self._query("WR", i2c_address, command, payload, length=len(payload))

    def _rd_command(self, command: int, i2c_address, bytes_to_read: int) -> bytes:
        """
        The RD command is used to read data from the probe. In contrast to the WR command, the length of the data is
        not the length of the payload, but the number of bytes to read.
        """
        return self._query("RD", i2c_address, command, length=bytes_to_read)


class _BumbleBee(_PMKProbe, metaclass=ABCMeta):
    """Abstract base class for the BumbleBee probes."""
    _i2c_addresses: dict[str, int] = {"unified": 0x04, "metadata": 0x04}  # BumbleBee only has one I2C address
    _addressing: str = "W"
    _command_address: int = 0x0118
    _led_colors = UserMapping({"red": 0, "green": 1, "blue": 2, "magenta": 3, "cyan": 4, "yellow": 5, "white": 6,
                               "black": 7})
    _overload_flags = UserMapping(
        {"no overload": 0, "positive overload": 1, "negative overload": 2, "main overload": 4})
    _legacy_model_name = "BumbleBee"

    def _read_float(self, setting_address: int):
        return _bytes_to_decimal(self.properties.scaling_factor, self._setting_read_raw(setting_address, 2))

    def _write_float(self, value, setting_address, executing_command_address):
        def min_max_signed_int(n):
            val = 2 ** (n * 8 - 1)
            return math.ceil(-val / self.properties.scaling_factor), (val - 1) // self.properties.scaling_factor

        try:
            byte = _decimal_to_byte(self.properties.scaling_factor, value, 2)
            self._setting_write(setting_address, byte)
            print(f"Writing {byte} to setting address {setting_address}.")
        except OverflowError as e:
            raise ValueError(f"Value {value} is out of range for this setting. Value must be in range"
                             f" {min_max_signed_int(2)}.") from e
        self._executing_command(executing_command_address)

    def _executing_command(self, command: int):
        self._wr_command(self._command_address, self._i2c_addresses['unified'], _unsigned_to_bytes(command, 2))

    @property
    def global_offset(self):
        """
        Return the global offset in V.

        :getter: Read the global offset from the probe.
        :setter: Write the global offset to the probe.
        """
        return self._read_float(0x0133)

    @global_offset.setter
    def global_offset(self, value: float):
        self._write_float(value, 0x0133, 0x0605)

    @property
    def offset_step_small(self):
        """
        Read or write the small offset step size in V. This step size is used when the user presses the small offset
        step button (one arrow) or when the :py:meth:`~increase_offset_small` or :py:meth:`~decrease_offset_small`
        methods are called.

        :setter: Write the small offset step size to the probe.
        :getter: Read the small offset step size from the probe.
        """
        return self._read_float(0x0135)

    @offset_step_small.setter
    def offset_step_small(self, value: int):
        self._write_float(value, 0x0135, 0x0A05)

    @property
    def offset_step_large(self):
        """
        Read or write the large offset step size in V. This step size is used when the user presses the large offset
        step button (two arrows) or when the :py:meth:`~increase_offset_large` or :py:meth:`~decrease_offset_large`
        methods are called.

        :getter: Read the large offset step size from the probe.
        :setter: Write the large offset step size to the probe.
        """
        return self._read_float(0x0137)

    @offset_step_large.setter
    def offset_step_large(self, value: int):
        self._write_float(value, 0x0137, 0x0A05)

    @property
    def offset_step_extra_large(self):
        """
        Read or write the extra large offset step size in V. This step size is used when the user presses the extra
        large offset step button combination (one arrow + two arrows at once) or when the
        :py:meth:`~increase_offset_extra_large` or :py:meth:`~decrease_offset_extra_large` methods are called.

        :getter: Read the extra large offset step size from the probe.
        :setter: Write the extra large offset step size to the probe.
        """
        return self._read_float(0x0139)

    @offset_step_extra_large.setter
    def offset_step_extra_large(self, value: int):
        self._write_float(value, 0x0139, 0x0A05)

    @property
    def attenuation(self) -> int:
        """
        Read or write the current attenuation setting of the probe.

        :getter: Returns the current attenuation setting.
        :setter: Sets the attenuation setting.
        """
        return self.properties.attenuation_ratios.get_user_value(self._setting_read_int(0x0131, 1))

    @attenuation.setter
    def attenuation(self, value) -> None:
        if value not in self.properties.attenuation_ratios:
            raise ValueError(f"Attenuation {value} is not supported by this probe.")
        self._setting_write(0x0131, _unsigned_to_bytes(self.properties.attenuation_ratios.get_internal_value(value), 1))
        self._executing_command(0x0105)

    @property
    def led_color(self):
        """
        Attribute that determines the probe's status LED color. Allowed colors are red, green, blue, magenta, cyan,
        yellow, white, black (off).

        :getter: Returns the current LED color.
        :setter: Sets the LED color.
        """
        return self._led_colors.get_user_value(self._setting_read_int(0x012C, 1))

    @led_color.setter
    def led_color(self, value: Literal["red", "green", "blue", "magenta", "cyan", "yellow", "white", "black"]):
        if value not in self._led_colors:
            raise ValueError(
                f"LED color {value} is not supported by this probe. List of available colors: "
                f"{list(self._led_colors.keys())}.")
        self._setting_write(0x012C, _unsigned_to_bytes(self._led_colors.get_internal_value(value), 1))
        self._executing_command(0x0305)

    @property
    def overload_positive_counter(self) -> int:
        """
        Returns the number of times the probe has been overloaded in the positive direction since the last call of
        :py:meth:`~clear_overload_counters`.

        :return: The number of times the probe has been overloaded on the positive path.
        """
        return self._setting_read_int(0x013B, 2)

    @property
    def overload_negative_counter(self) -> int:
        """
        Returns the number of times the probe has been overloaded in the negative direction since the last call of
        :py:meth:`~clear_overload_counters`.

        :return: The number of times the probe has been overloaded on the negative path.
        """
        return self._setting_read_int(0x013D, 2)

    @property
    def overload_main_counter(self) -> int:
        """
        Returns the number of times the probe has been overloaded in the main path since the last call of
        :py:meth:`~clear_overload_counters`.

        :return: The number of times the probe has been overloaded on the main path.
        """
        return self._setting_read_int(0x013F, 2)

    @property
    def temperature(self) -> float:
        """
        Get the temperature of the probe in °C.

        :return: The temperature of the probe in °C.
        """
        return self._setting_read_int(0x0142, 2) / 5 - 50

    # All the following methods represent keys on the BumbleBee keyboard

    def clear_overload_counters(self) -> None:
        """
        Clears the BumbleBee's overload counters :py:attr:`~overload_positive_counter`,
        :py:attr:`~overload_negative_counter` and :py:attr:`~overload_main_counter`.

        :return: None
        """
        self._executing_command(0x0C05)

    def factory_reset(self) -> None:
        """
        Resets the BumbleBee to factory settings.

        :return: None
        """
        self._executing_command(0x0E05)

    def increase_attenuation(self) -> None:
        """
        Increases the attenuation setting of the BumbleBee by one step relative to :py:attr:`~attenuation`.

        :return: None
        """
        self._executing_command(0x0002)

    def decrease_attenuation(self) -> None:
        """
        Decreases the attenuation setting of the BumbleBee by one step relative to :py:attr:`~attenuation`.

        :return: None
        """
        self._executing_command(0x0102)

    def increase_offset_small(self) -> None:
        """
        Increases the offset setting of the BumbleBee by :py:attr:`~offset_step_small`.

        :return: None
        """
        self._executing_command(0x0103)

    def decrease_offset_small(self) -> None:
        """
        Decreases the offset setting of the BumbleBee by :py:attr:`~offset_step_small`.

        :return: None
        """
        self._executing_command(0x0603)

    def increase_offset_large(self) -> None:
        """
        Increases the offset setting of the BumbleBee by :py:attr:`~offset_step_large`.

        :return: None
        """
        self._executing_command(0x0203)

    def decrease_offset_large(self) -> None:
        """
        Decreases the offset setting of the BumbleBee by :py:attr:`~offset_step_large`.

        :return: None
        """
        self._executing_command(0x0503)

    def increase_offset_extra_large(self) -> None:
        """
        Increases the offset setting of the BumbleBee by :py:attr:`~offset_step_extra_large`.

        :return: None
        """
        self._executing_command(0x0303)

    def decrease_offset_extra_large(self) -> None:
        """
        Increases the offset setting of the BumbleBee by :py:attr:`~offset_step_extra_large`.

        :return: None
        """
        self._executing_command(0x0403)


class BumbleBee2kV(_BumbleBee):
    """
    Class for controlling the BumbleBee probe with ±2000 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-2000, +2000),
                                  attenuation_ratios=UserMapping({500: 1, 250: 2, 100: 3, 50: 4}),
                                  scaling_factor=16)


class BumbleBee1kV(_BumbleBee):
    """
    Class for controlling PMK BumbleBee probes with ±1000 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-1000, +1000),
                                  attenuation_ratios=UserMapping({250: 1, 125: 2, 50: 3, 25: 4}),
                                  scaling_factor=32)


class BumbleBee400V(_BumbleBee):
    """
    Class for controlling PMK BumbleBee probes with ±400 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-400, +400),
                                  attenuation_ratios=UserMapping({100: 1, 50: 2, 20: 3, 10: 4}),
                                  scaling_factor=80)


class BumbleBee200V(_BumbleBee):
    """
    Class for controlling PMK BumbleBee probes with ±200 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-200, +200),
                                  attenuation_ratios=UserMapping({50: 1, 25: 2, 10: 3, 5: 4}),
                                  scaling_factor=160)


class Hornet4kV(_BumbleBee):
    """
    Class for controlling the upcoming PMK Hornet probe. See http://www.pmk.de/en/home for specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-4000, +4000),
                                  attenuation_ratios=UserMapping({1000: 1, 500: 2, 200: 3, 100: 4}),
                                  scaling_factor=8)


class _HSDP(_PMKProbe, metaclass=ABCMeta):
    """Base class for controlling HSDP series probes"""
    _i2c_addresses: dict[str, int] = {"metadata": 0x50, "offset": 0x52}
    _addressing: str = "B"

    @property
    def offset(self):
        """
        Set the offset of the probe in V. Reading the offset is not supported for HSDP probes.

        :setter: Change the offset of the probe.
        """
        raise NotImplementedError(f"Offset cannot be read for probe {self.probe_model}.")

    @offset.setter
    def offset(self, offset: float):
        # calculate the offset in bytes
        offset_rescaled = int(offset * 0x7FFF / (self.properties.attenuation_ratios.get_user_value(1) * 6 / 5) + 0x8000)
        self._query("WR", i2c_address=self._i2c_addresses['offset'], command=0x30,
                    payload=_unsigned_to_bytes(offset_rescaled, 2), length=2)


class HSDP2010(_HSDP):
    """Class for controlling the HSDP2010 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-10, +10),
                                  attenuation_ratios=UserMapping({10: 1}),
                                  scaling_factor=None)


class HSDP2010L(HSDP2010):
    """Class for controlling the HSDP2010L probe. See http://www.pmk.de/en/products/hsdp for specifications."""


class HSDP2025(_HSDP):
    """Class for controlling the HSDP2025 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-25, +25),
                                  attenuation_ratios=UserMapping({25: 1}),
                                  scaling_factor=None)


class HSDP2025L(HSDP2025):
    """Class for controlling the HSDP2025L probe. See http://www.pmk.de/en/products/hsdp for specifications."""


class HSDP2050(_HSDP):
    """Class for controlling the HSDP2050 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-50, +50),
                                  attenuation_ratios=UserMapping({50: 1}),
                                  scaling_factor=None)


class HSDP4010(_HSDP):
    """Class for controlling the HSDP4010 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-10, +10),
                                  attenuation_ratios=UserMapping({10: 1}),
                                  scaling_factor=None)


class FireFly(_PMKProbe):
    """Class for controlling the FireFly probe. See http://www.pmk.de/en/products/firefly for specifications."""

    class ProbeStates(Enum):
        """ Enumeration of the possible states of the FireFly probe indicated by the Probe Status LED."""
        NOT_POWERED = b'\x00'
        PROBE_HEAD_OFF = b'\x01'
        WARMING_UP = b'\x02'
        READY_TO_USE = b'\x03'
        EMPTY_OR_NO_BATTERY = b'\x04'
        ERROR = b'\x05'

    _i2c_addresses: dict[str, int] = {"unified": 0x04, "metadata": 0x04}  # BumbleBee only has one I2C address
    _addressing: str = "W"
    _probe_head_on = UserMapping({True: 1, False: 0})

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-1, +1),
                                  attenuation_ratios=UserMapping({1: 1}),
                                  scaling_factor=None)

    @lru_cache
    def _read_metadata(self) -> FireFlyMetadata:
        self._query("WR", i2c_address=self._i2c_addresses['metadata'], command=0x0C01, payload=DUMMY * 2, length=0x02)
        return FireFlyMetadata.from_bytes(self._query("RD", i2c_address=self._i2c_addresses['metadata'], command=0x1000,
                                                      length=0xBF))

    @property
    def metadata(self) -> FireFlyMetadata:
        """Read the probe's metadata."""
        return cast(FireFlyMetadata, super().metadata)

    @property
    def probe_status_led(self):
        """Returns the state of the probe status LED."""
        return self.ProbeStates(self._setting_read_raw(0x080B, 1))

    def _battery_adc(self) -> int:
        """Read the battery voltage from the probe head's ADC."""
        return self._setting_read_int(0x0800, 4, signed=False)

    @property
    def battery_voltage(self) -> float:
        """Return the current battery voltage in V.

        Caution: This value is not available immediately after turning off the probe head. It takes approximately 200
        milliseconds to become available. Before that the battery voltage will read as 0.0."""
        return 2.47 / 4096 / 0.549 * self._battery_adc()

    @property
    def battery_indicator(self) -> tuple[LED, LED, LED, LED]:
        """Returns the state of the battery indicator LEDs on the _interface board.

        The tuple contains the states of the four physical LEDs from bottom to top."""
        levels = {
            2322: (LED.OFF, LED.OFF, LED.OFF, LED.OFF),
            2777: (LED.BLINKING_RED, LED.OFF, LED.OFF, LED.OFF),
            3141: (LED.YELLOW, LED.OFF, LED.OFF, LED.OFF),
            3323: (LED.GREEN, LED.OFF, LED.OFF, LED.OFF),
            3505: (LED.GREEN, LED.GREEN, LED.OFF, LED.OFF),
            3596: (LED.GREEN, LED.GREEN, LED.GREEN, LED.OFF),
            4096: (LED.GREEN, LED.GREEN, LED.GREEN, LED.GREEN)
        }
        if not self.probe_head_on:
            return levels[2322]  # if the probe head is off, the battery indicator is off
        battery_level = self._battery_adc()
        for i, limit in enumerate(levels.keys()):
            if battery_level <= limit:
                return levels[limit]
        raise ValueError(f"Invalid battery level {battery_level}.")

    @property
    def probe_head_on(self) -> bool:
        """
        Attribute that determines whether the probe head is on or off.

        :getter: Returns the current state of the probe head.
        :setter: Sets the state of the probe head and waits until the attribute change is confirmed by the probe."""
        return self._probe_head_on.get_user_value(self._setting_read_int(0x090A, 1))

    @probe_head_on.setter
    def probe_head_on(self, value: bool):
        if self.probe_head_on != value:
            self._wr_command(0x0803, self._i2c_addresses['unified'], DUMMY)
            timeout = time.time() + 5
            sleep_time = 0.1
            while self.probe_head_on != value and time.time() < timeout:
                time.sleep(sleep_time)
        else:
            pass  # no need to do anything if the probe head is already in the desired state

    def auto_zero(self):
        self._wr_command(0x0A10, self._i2c_addresses['unified'], DUMMY)


BumbleBeeType = TypeVar("BumbleBeeType", bound=_BumbleBee)
HSDPType = TypeVar("HSDPType", bound=_HSDP)
ProbeType = TypeVar("ProbeType", bound=_PMKProbe)

_ALL_PMK_PROBES = (
    BumbleBee2kV, BumbleBee1kV, BumbleBee400V, BumbleBee200V, Hornet4kV, HSDP2010, HSDP2010L, HSDP2025, HSDP2025L,
    HSDP2050, HSDP4010, FireFly)
