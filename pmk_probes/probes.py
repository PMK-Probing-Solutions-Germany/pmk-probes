""" This module contains classes for controlling PMK probes. The classes are designed to be used with PMK power
supplies"""
import io
import math
import time
from _datetime import timedelta
from abc import ABCMeta, abstractmethod
from enum import Enum
from functools import lru_cache
from inspect import isabstract
from pathlib import Path
from typing import Literal, TypeVar, cast, Callable

from ._data_structures import UUIDs, UserMapping, FireFlyMetadata, PMKProbeProperties, LED, PowerOverFiberMetadata
from ._devices import PMKDevice, Channel, DUMMY
from ._errors import ProbeTypeError, UUIDReadError
from ._hardware_interfaces import HardwareInterface
from .power_supplies import _PMKPowerSupply


def _unsigned_to_bytes(command: int, length: int) -> bytes:
    return command.to_bytes(signed=False, byteorder="big", length=length)


def _bytes_to_decimal(scale: float, word: bytes) -> float:
    return int.from_bytes(word, byteorder="big", signed=True) / scale


def _to_two_bytes_unsigned(command: int) -> bytes:
    return _unsigned_to_bytes(command, 2)


def _decimal_to_byte(scale: float, decimal: float, length: int) -> bytes:
    integer = int(decimal * scale)
    return integer.to_bytes(signed=True, byteorder="big", length=length)


class _PMKProbe(PMKDevice, metaclass=ABCMeta):
    _legacy_model_name = None  # model name of the probe in legacy mode

    def __init__(self, power_supply: _PMKPowerSupply, channel: Channel, verbose: bool = False,
                 allow_legacy: bool = False,
                 simulated=None, skip_metadata=False):
        super().__init__(channel, verbose=verbose)
        self.probe_model = self.__class__.__name__
        self.power_supply = power_supply
        self.channel = channel
        self._simulated = simulated
        if not simulated and not skip_metadata:
            self._validate_probe(power_supply, channel, allow_legacy)

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __repr__(self):
        return f"{self.probe_model} at {self.channel.name} of {self.power_supply}"

    def _validate_probe(self, power_supply: _PMKPowerSupply, channel: Channel, allow_legacy: bool):
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
    def _interface(self) -> HardwareInterface:
        if self._simulated:
            return self._simulated_interface
        else:
            return self.power_supply.interface

    @property
    def _uuid(self):
        uuid = UUIDs.get_internal_value(self.probe_model)
        if uuid is not None:
            return uuid
        else:
            raise ProbeTypeError("Probe model has no UUID assigned.")

    def _setting_write(self, setting_address: int, setting_value: bytes):
        self._wr_command(setting_address, setting_value)

    def _setting_read_raw(self, setting_address: int, setting_byte_count: int) -> bytes:
        return self._rd_command(setting_address, setting_byte_count)

    def _setting_read_int(self, setting_address: int, setting_byte_count: int, signed: bool = False) -> int:
        return int.from_bytes(self._setting_read_raw(setting_address, setting_byte_count), "big", signed=signed)

    def _setting_read_bool(self, setting_address: int, setting_position: int = 0):
        setting = self._setting_read_int(setting_address, 1)
        return bool(setting & (1 << setting_position))

    def _wr_command(self, command: int, payload: bytes) -> None:
        """
        The WR command is used to write data to the probe. The payload is a bytes object that is written to the
        probe. Its length also needs to be supplied to the query command.
        """
        _ = self._query("WR", self._i2c_addresses["unified"], command, payload, length=len(payload))

    def _rd_command(self, command: int, bytes_to_read: int) -> bytes:
        """
        The RD command is used to read data from the probe. In contrast to the WR command, the length of the data is
        not the length of the payload, but the number of bytes to read.
        """
        return self._query("RD", self._i2c_addresses["unified"], command, length=bytes_to_read)


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.metadata.software_revision == "M1.0 K0.0":
            self._scaling_factor = 16  # BumbleBee firmware 1.0 uses a different scaling factor

    def __init_subclass__(cls, scaling_factor, **kwargs):
        cls._scaling_factor = scaling_factor
        super().__init_subclass__(**kwargs)

    def _read_float(self, setting_address: int):
        return _bytes_to_decimal(self._scaling_factor, self._setting_read_raw(setting_address, 2))

    def _write_float(self, value, setting_address, executing_command_address=None):
        def min_max_signed_int(n):
            """Return the minimum and maximum signed integer values that can be represented with n bytes."""
            val = 2 ** (n * 8 - 1)
            return math.ceil(-val / self._scaling_factor), (val - 1) // self._scaling_factor

        try:
            byte = _decimal_to_byte(self._scaling_factor, value, 2)
            self._setting_write(setting_address, byte)
        except OverflowError as e:
            raise ValueError(f"Value {value} is out of range for this setting. Value must be in range"
                             f" {min_max_signed_int(2)}.") from e
        if executing_command_address:
            self._executing_command(executing_command_address)

    def _executing_command(self, command: int):
        self._wr_command(self._command_address, _to_two_bytes_unsigned(command))

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
        self._write_float(value, 0x0135, None)

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
        self._write_float(value, 0x0137, None)

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
        self._write_float(value, 0x0139, None)

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
    def leds_off(self):
        """
        Attribute that determines whether the probe's LEDs (status, attenuation and overload LEDs) are off,
        for example in photosensitive environments.

        :getter: Returns the current 'LEDs off' state.
        :setter: Sets the 'LEDs off' state.
        """
        return self._setting_read_bool(0x0130, 1)

    @property
    def keylock(self):
        """
        Attribute that determines whether the probe's keyboard is locked.

        :getter: Returns the current keylock state.
        :setter: Sets the keylock state. (True means ON, False means OFF)
        """
        return self._setting_read_bool(0x0130, 0)

    @leds_off.setter
    def leds_off(self, value: bool):
        self._setting_write_bool(0x0130, 1, value)
        self._executing_command(0x0B05)

    @keylock.setter
    def keylock(self, value: bool):
        self._setting_write_bool(0x0130, 0, value)
        self._executing_command(0x0B05)

    @property
    def overload_buzzer(self):
        """
        Read or write the overload buzzer setting. If set to True, the buzzer will sound whenever an overload is
        active, otherwise buzzer is disabled.

        :getter: Returns the overload buzzer setting.
        :setter: Sets the overload buzzer setting.
        """
        return self._setting_read_bool(0x012D, 0)

    @property
    def hold_overload(self):
        """
        Read or write the hold overload setting. If set to True, overload will be held until hold overload is
        disabled. If set to False, overload is only shown as long as the probe is overloaded.

        :getter: Returns the hold overload setting.
        :setter: Sets the hold overload setting.
        """
        return self._setting_read_bool(0x012D, 1)

    @overload_buzzer.setter
    def overload_buzzer(self, value: bool):
        self._setting_write_bool(0x012D, 0, value)
        self._executing_command(0x0A05)

    @hold_overload.setter
    def hold_overload(self, value: bool):
        self._setting_write_bool(0x012D, 1, value)
        self._executing_command(0x0A05)

    def _setting_write_bool(self, address, bit_position, value):
        setting = self._setting_read_int(address, 1)
        mask = 1 << bit_position
        if value:
            setting |= mask
        else:
            setting &= ~mask
        self._setting_write(address, _unsigned_to_bytes(setting, 1))

    @property
    def offset_sync(self) -> bool:
        """
        Read or write the offset synchronization setting. If set to True, the offset will be synchronized for all
        attenuation settings, otherwise it is scaled proportionally when switching the attenuation ratio.

        :getter: Returns the offset synchronization setting.
        :setter: Sets the offset synchronization setting.
        """
        return self._setting_read_bool(0x012F)

    @offset_sync.setter
    def offset_sync(self, value: bool) -> None:
        self._setting_write(0x012F, _unsigned_to_bytes(int(value), 1))
        self._executing_command(0x0A05)

    # @property
    # def overload_buzzer_enabled(self):
    #     return self._setting_read_bool(0x012D)
    #
    # @property
    # def hold_overload(self):
    #     return self._setting_read_bool(0x012D, 0)

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

    @property
    def metadata_write_protection_password(self):
        return self._setting_read_raw(0x01AD, 2)

    def unlock_eeprom(self):
        self._setting_write(0x01AD, b"\x19\x93")

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
        Decreases the offset setting of the BumbleBee by :py:attr:`~offset_step_extra_large`.

        :return: None
        """
        self._executing_command(0x0403)


class BumbleBee2kV(_BumbleBee, scaling_factor=16):
    """
    Class for controlling PMK BumbleBee probes with ±2000 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-2000, +2000),
                                  attenuation_ratios=UserMapping({500: 1, 250: 2, 100: 3, 50: 4}))


class BumbleBee1kV(_BumbleBee, scaling_factor=32):
    """
    Class for controlling PMK BumbleBee probes with ±1000 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-1000, +1000),
                                  attenuation_ratios=UserMapping({250: 1, 125: 2, 50: 3, 25: 4}))


class BumbleBee400V(_BumbleBee, scaling_factor=80):
    """
    Class for controlling PMK BumbleBee probes with ±400 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-400, +400),
                                  attenuation_ratios=UserMapping({100: 1, 50: 2, 20: 3, 10: 4}))


class BumbleBee200V(_BumbleBee, scaling_factor=160):
    """
    Class for controlling PMK BumbleBee probes with ±200 V input voltage. See http://www.pmk.de/en/en/bumblebee for
    specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-200, +200),
                                  attenuation_ratios=UserMapping({50: 1, 25: 2, 10: 3, 5: 4}))


class Hornet4kV(_BumbleBee, scaling_factor=8):
    """
    Class for controlling PMK Hornet probes with ±4000 V. See http://www.pmk.de/en/home for specifications.
    """

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-4000, +4000),
                                  attenuation_ratios=UserMapping({1000: 1, 500: 2, 200: 3, 100: 4}))


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
                                  attenuation_ratios=UserMapping({10: 1}))


class HSDP2010L(HSDP2010):
    """Class for controlling the HSDP2010L probe. See http://www.pmk.de/en/products/hsdp for specifications."""


class HSDP2025(_HSDP):
    """Class for controlling the HSDP2025 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-25, +25),
                                  attenuation_ratios=UserMapping({25: 1}))


class HSDP2025L(HSDP2025):
    """Class for controlling the HSDP2025L probe. See http://www.pmk.de/en/products/hsdp for specifications."""


class HSDP2050(_HSDP):
    """Class for controlling the HSDP2050 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-50, +50),
                                  attenuation_ratios=UserMapping({50: 1}))


class HSDP4010(_HSDP):
    """Class for controlling the HSDP4010 probe. See http://www.pmk.de/en/products/hsdp for specifications."""

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(-10, +10),
                                  attenuation_ratios=UserMapping({10: 1}))


class PowerOverFiber(_PMKProbe):
    _i2c_addresses: dict[str, int] = {"unified": 0x0E, "metadata": 0x0E}  # BumbleBee only has one I2C address
    _addressing: str = "W"
    _error_log_size = 1000
    _error_codes = {
        0: "ERROR_NOERROR",
        1: "ERROR_POWERGOOD_OUT_OF_RANGE",
        2: "ERROR_UNDEFINED_I2C_COMMAND",
        3: "ERROR_UNDEFINED_EEPROM_CONSTANT",
        # An index was provided to eeprom constant read or write function which is undefined
        4: "ERROR_PROGRAMMING_PM_TOO_FAST",
        # A new PH flash chunk of data was sent over I2c, although the last data chunk was not finished programming
        5: "ERROR_FAILED_TO_ENTER_PM_BL",  # Entering PH bootloader failed
        6: "ERROR_PM_WAS_NOT_IN_BL_MODE",  # Command to leave BL mode was received, but PM was not in BL mode
        8: "ERROR_PM_RECEIVED_INCOMPLETE_DATA",  # Incomplete auto message was received from PM.
        9: "ERROR_LASER_OVERTEMP",  # Monitored laser current has unrealistic values
        10: "ERROR_PD_OVERTEMP",  # Charge bank current too low for powering PM during system start-up
        11: "ERROR_FIBER_BREAK",
        12: "ERROR_BEAM_LOSS",

        7: "WARNING_PM_WAS_IN_BL_MODE",  # Command to enter BL mode was received, but PM was already in BL mode
        23: "WARNING_BEAM_LOSS",
        25: "WARNING_RX_BUFFER_OVERFLOW",
        26: "WARNING_WRONG_CRC",

        37: "EVENT_PM_BOOTLOADER_ENTERED",
        38: "EVENT_PM_BOOTLOADER_EXITED",
        39: "EVENT_LM_BOOTLOADER_ENTERED",
        40: "EVENT_LM_BOOTLOADER_EXITED",
    }

    class PMStatusFlag(Enum):
        CHARGING = 0
        READY = 1
        OPERATIONAL = 2
        BOOTLOADER = 3

    class OperatingTime(Enum):
        TOTAL = 0
        WITH_LOAD = 1
        WITHOUT_LOAD = 2
        LASER_OFF = 3

    _led_colors = UserMapping({"red": 0, "green": 1, "blue": 2, "magenta": 3, "cyan": 4, "yellow": 5, "white": 6,
                               "black": 7})

    @property
    def properties(self) -> PMKProbeProperties:
        return PMKProbeProperties(input_voltage_range=(0, 0),
                                  attenuation_ratios=UserMapping({}))

    @lru_cache
    def _read_metadata(self) -> PowerOverFiberMetadata:
        self._query("WR", i2c_address=self._i2c_addresses['metadata'], command=0x0C01, payload=DUMMY * 2, length=0x02)
        return PowerOverFiberMetadata.from_bytes(
            self._query("RD", i2c_address=self._i2c_addresses['metadata'], command=0x1000,
                        length=0xC1))

    @property
    def echo_value(self):
        """ Read the echo value. """
        return self._setting_read_int(0x0801, 4, signed=False)

    @property
    def status_flag(self) -> PMStatusFlag:
        """ Read the status flag. """
        read_flag = self._setting_read_int(0x0802, 1, signed=False)
        try:
            return self.PMStatusFlag(read_flag)
        except ValueError as e:
            raise ValueError(f"PoF returned unknown status flag ({read_flag}).") from e

    @property
    def firefly_on(self):
        """ Check if the attached FireFly is turned on (high load). """
        return self._setting_read_bool(0x0803, 1)

    @property
    def photodiode_voltage(self):
        """ Read the photodiode voltage. """
        return self._setting_read_int(0x0804, 4, signed=False)

    @property
    def photodiode_current(self):
        """ Read the photodiode current. """
        return self._setting_read_int(0x0805, 4, signed=False)

    @property
    def lm_temperature(self):
        """ Read the LM temperature. """
        return self._setting_read_int(0x0806, 4, signed=False)

    @property
    def pm_temperature(self):
        """ Read the PM temperature. """
        return self._setting_read_int(0x0807, 4, signed=False)

    @property
    def photodiode_temperature(self):
        """ Read the photodiode temperature. """
        return self._setting_read_int(0x0808, 4, signed=False)

    @property
    def lm_version(self):
        """ Read the LM version. """
        (major, minor, patch) = self._setting_read_raw(0x0809, 3)
        return f"LM v{major}.{minor}.{patch}"

    @property
    def pm_version(self):
        """ Read the PM version. """
        (major, minor, patch) = self._setting_read_raw(0x080A, 3)
        return f"PM v{major}.{minor}.{patch}" if (bool(major) or bool(minor) or bool(patch)) else "Unavailable"

    @property
    def lm_status_led(self):
        """ Read the LM status LED. """
        return self._setting_read_int(0x080B, 4, signed=False)

    @property
    def chargebank_voltage(self):
        """ Read the charge bank voltage. """
        return self._setting_read_int(0x080C, 4, signed=False)

    @property
    def chargebank_current(self):
        """ Read the charge bank current. """
        return self._setting_read_int(0x080D, 4, signed=False)

    @property
    def chargebank_state(self):
        """ Read the charge bank state. """
        return self._setting_read_int(0x080E, 4, signed=False)

    @chargebank_state.setter
    def chargebank_state(self, value):
        """ Set the charge bank state. """
        self._setting_write(0x080F, int.to_bytes(value))

    @property
    def output_state(self):
        """ Read the output state. """
        return self._setting_read_int(0x0811, 4, signed=False)

    @property
    def output_fault_indication(self):
        """ Read the output fault indication. """
        return self._setting_read_int(0x0813, 4, signed=False)

    @property
    def load_detect_voltage(self):
        """ Read the load detect voltage. """
        return self._setting_read_int(0x0815, 4, signed=False)

    @property
    def led_color(self):
        """
        Attribute that determines the probe's status LED color. Allowed colors are red, green, blue, magenta, cyan,
        yellow, white, black (off).

        :getter: Returns the current LED color.
        :setter: Sets the LED color.
        """
        return self._led_colors.get_user_value(self._setting_read_int(0x0A02, 1, signed=False))

    @led_color.setter
    def led_color(self, value: Literal["red", "green", "blue", "magenta", "cyan", "yellow", "white", "black"]):
        if value not in self._led_colors:
            raise ValueError(
                f"LED color {value} is not supported by PoF. List of available colors: "
                f"{list(self._led_colors.keys())}.")
        self._setting_write(0x0A00, _unsigned_to_bytes(self._led_colors.get_internal_value(value), 1))

    def force_bootloader(self):
        """ Change the state of LM to bootloader state and send BL to PM without checking its answer. """
        self._setting_write(0x0A11, int.to_bytes(0))

    @property
    def laser_enabled(self):
        """ Read if the laser is enabled. """
        return self._setting_read_int(0x0A09, 4, signed=True)

    @laser_enabled.setter
    def laser_enabled(self, value):
        """ Set the laser regulator status. """
        self._setting_write(0x0A0A, int.to_bytes(value))

    @property
    def laser_current(self):
        """ Read the laser current. """
        return self._setting_read_int(0x0A0B, 4, signed=False)

    @property
    def laser_voltage(self):
        """ Read the laser voltage. """
        return self._setting_read_int(0x0A0C, 4, signed=False)

    @property
    def laser_temperature(self):
        """ Read the laser temperature. """
        return self._setting_read_int(0x0A0E, 4, signed=False)

    @property
    def laser_ictrl(self):
        """ Read the laser ICTRL. """
        return self._setting_read_int(0x0A10, 2, signed=False)

    @laser_ictrl.setter
    def laser_ictrl(self, value):
        """ Write the laser control current. """
        self._setting_write(0x0A0F, int.to_bytes(value, length=2))

    @property
    def laser_imon(self):
        """ Read the laser IMON. """
        return self._setting_read_int(0x0A0B, 4, signed=False)

    @property
    def chargebank_powergood(self):
        """ Read the power good value. """
        return self._setting_read_int(0x0A25, 4, signed=True)

    @property
    def errorcode(self):
        """ Read the power good value. """
        return self._setting_read_int(0x0A26, 1, signed=False)

    @output_state.setter
    def output_state(self, value):
        """ Set the PM output state. """
        self._setting_write(0x0A30, int.to_bytes(value))

    @property
    def safety_shutdown_enabled(self):
        """ Check if safety shutdown is enabled. """
        return self._setting_read_int(0x0A32, 4, signed=False)

    @safety_shutdown_enabled.setter
    def safety_shutdown_enabled(self, value):
        """ Set the LM safety shutdown. """
        self._setting_write(0x0A31, int.to_bytes(value))

    def lm_enter_bootloader(self):
        """ Enter LM Bootloader Mode """
        self._setting_write(0x0AAA, int.to_bytes(0x0))

    def lm_enter_application(self):
        """ Enter LM Bootloader Mode """
        self._setting_write(0x0000, int.to_bytes(0x43))

    def pm_enter_bootloader(self):
        self._setting_write(0x0999, int.to_bytes(1))

    def pm_enter_application(self):
        self._setting_write(0x099A, int.to_bytes(1))

    def read_operating_time(self, counter: OperatingTime):  # in seconds
        return self._setting_read_int(0x0A16 + counter.value, 4, signed=False)  # add offset depending on specific field

    @property
    def pm_read_mode(self):
        return self._setting_read_int(0x0A2A, 1, False)

    @property
    def pm_poll_status(self):
        return self._setting_read_int(0x0A29, 1, False)

    def lm_flash(self, path: Path, callback_fn: Callable = None) -> None:
        data, start_address = read_hex_file(path)
        self.flash_bytes(start_address, 0x0053, 128, data, callback_fn, None)

    def pm_flash(self, path: Path, callback_fn: Callable = None) -> None:

        def wait_for_pm(address: int) -> None:
            timeout = 1  # s
            while True:
                if timeout <= 0:
                    raise TimeoutError(f"Got stuck flashing at {address}. Aborting.")
                match self.pm_poll_status:  # this polls the PM
                    case 0x01:  # chunk received, continue with next chunk
                        break
                    case 0xFE:
                        raise TimeoutError("PH hasn't answered a read command by LM. Please power cycle the LM.")
                    case 0xFF:
                        time.sleep(0.05)  # poll every 0.05 s

        data, start_address = read_hex_file(path)
        data += b"\x00" * (64 - (len(data) % 64))  # Pad data to page (64 bytes)
        self.flash_bytes(start_address, 0x0A28, 16, data, callback_fn, wait_for_fn=self.wait_for_pm)

    def flash_bytes(self, start_address: int, flash_command: int, chunk_size: int, data: bytes,
                    callback_fn: Callable[[int, int], None], wait_for_fn: Callable[[int], None] | None) -> None:
        address = start_address
        f = io.BytesIO(data)
        while chunk := f.read(chunk_size):
            self._query(
                "FL",
                self._i2c_addresses["unified"],
                flash_command,
                _to_two_bytes_unsigned(address) + chunk,
                length=len(chunk) + 2  # We need to add 2 bytes because of the address
            )
            address += len(chunk)
            if wait_for_fn:
                wait_for_fn(address)
            if callback_fn:
                callback_fn(address - start_address, len(data))

    def _parse_error_log(self, data: bytes):
        if len(data) % 5 != 0:
            raise ValueError("Error log data length must be a multiple of 5 bytes")
        entries = []
        for i in range(0, len(data), 5):
            timestamp_bytes = data[i:i + 4]
            error_code = data[i + 4]
            timestamp = timedelta(seconds=int.from_bytes(timestamp_bytes, byteorder='little'))
            entries.append((timestamp, f"{self._error_codes.get(error_code)} ({error_code})"))
        return entries

    def read_error_log(self):
        # Validate chunk size
        chunk_size = 255
        error_log_data = bytearray()
        for offset in range(0, self._error_log_size, chunk_size):
            current_chunk_size = min(chunk_size, self._error_log_size - offset)
            self._query(
                "WR",
                i2c_address=self._i2c_addresses['unified'],
                command=0x0C02,
                payload=offset.to_bytes(2, byteorder='big'),
                length=2
            )
            chunk = self._query(
                "RD",
                i2c_address=self._i2c_addresses['unified'],
                command=0x1001,
                length=current_chunk_size
            )
            error_log_data.extend(chunk)
        return self._parse_error_log(error_log_data)  # Placeholder for actual parsing logic

    def system_reset(self):
        """  """
        self._setting_write(0x0A0D, int.to_bytes(0x00))

    def factory_reset(self):
        """ Reset the probe to factory settings. """
        self._setting_write(0x0A2E, int.to_bytes(0x00))

    def developer_factory_reset(self):
        """ Reset the probe to factory settings. """
        self._setting_write(0x0A2F, int.to_bytes(0x00))
        self._read_metadata.cache_clear()


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
                                  attenuation_ratios=UserMapping({1: 1}))

    @lru_cache
    def _read_metadata(self) -> FireFlyMetadata:
        self._query("WR", i2c_address=self._i2c_addresses['metadata'], command=0x0C01, payload=b'\x00' * 2, length=0x02)
        return FireFlyMetadata.from_bytes(self._query("RD", i2c_address=self._i2c_addresses['metadata'], command=0x1000,
                                                      length=0xC5))

    @property
    def metadata(self) -> FireFlyMetadata:
        """Read the probe's metadata."""
        return cast(FireFlyMetadata, super().metadata)

    @property
    def probe_status_led(self) -> ProbeStates:
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
        for limit in levels.keys():
            if battery_level <= limit:
                return levels[limit]
        raise ValueError(f"Invalid battery level {battery_level}.")

    @property
    def probe_head_on(self) -> bool:
        """
        Attribute that determines whether the probe head is on or off.

        :getter: Returns the current state of the probe head.
        :setter: Sets the state of the probe head and waits until the attribute change is confirmed by the probe."""
        return self._setting_read_bool(0x090A)

    @probe_head_on.setter
    def probe_head_on(self, value: bool):
        if self.probe_head_on != value:
            self._wr_command(0x0803, DUMMY)
            timeout = time.time() + 5
            sleep_time = 0.1
            while self.probe_head_on != value and time.time() < timeout:
                time.sleep(sleep_time)
        else:
            pass  # no need to do anything if the probe head is already in the desired state

    def auto_zero(self):
        self._wr_command(0x0A10, DUMMY)

    def enable_expert_mode(self):
        self._wr_command(0x0A2F, b"pmk1993;")


BumbleBeeType = TypeVar("BumbleBeeType", bound=_BumbleBee)
HSDPType = TypeVar("HSDPType", bound=_HSDP)
ProbeType = TypeVar("ProbeType", bound=_PMKProbe)

_ALL_PMK_PROBES = set(
    cls for cls in globals().values() if (isinstance(cls, type) and issubclass(cls, _PMKProbe)) and not isabstract(cls))
