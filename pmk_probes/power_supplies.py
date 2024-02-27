"""This module contains the classes for the PMK power supplies."""

from abc import abstractmethod
from enum import Enum
from typing import Literal

import serial

from ._data_structures import PMKMetadata
from ._devices import PMKDevice, Channel
from ._hardware_interfaces import LANInterface, USBInterface
from ._errors import ProbeReadError


class _PMKPowerSupply(PMKDevice):
    """
    The class that controls access to the serial resource of the PMK power supply.

    """
    _num_channels = None

    def __init__(self, com_port: str = None, ip_address: str = None):
        super().__init__(channel=Channel.PS_CH)
        from .probes import _ALL_PMK_PROBES  # to avoid circular imports
        self.supported_probe_types = _ALL_PMK_PROBES
        match com_port, ip_address:
            case com_port, None:
                self.interface = USBInterface(com_port)
            case None, ip_address:
                self.interface = LANInterface(ip_address)
            case None, None:
                raise ValueError("Either com_port or ip_address must be specified.")
            case _:
                raise ValueError("Only one of com_port or ip_address can be specified.")

    @property
    def metadata(self) -> PMKMetadata:
        """
        The metadata of the power supply. Not yet implemented.

        Returns:
            PMKMetadata: The metadata of the power supply.
        """
        raise NotImplementedError

    # @property
    # def connected_probes(self):
    #     """
    #
    #     """
    #     connected_probes = {channel: None for channel in Channel}
    #     for channel in Channel:
    #         # for every channel, query the probe for its metadata
    #         for ProbeType in self.supported_probe_types:
    #             try:
    #                 probe_to_try = ProbeType(self, channel)
    #                 connected_probes[channel] = probe_to_try
    #                 break
    #             except ProbeReadError:
    #                 continue
    #     return connected_probes

    # def device_at_channel(self, channel: Channel) -> PMKDevice:
    #     """
    #     Returns:
    #         The probe connected to the specified channel.
    #     """
    #     if channel == Channel.PS_CH:
    #         return self
    #     else:
    #         for ProbeType in self.supported_probe_types:
    #             try:
    #                 probe_to_try = ProbeType(self, channel, legacy_mode=True)
    #             except ValueError:
    #                 continue

    def close(self):
        """Disconnects the power supply to free the serial connection."""
        self.interface.close()


class PS02(_PMKPowerSupply):
    """Class to control a PS02 power supply."""
    _num_channels = 2  # the PS02 has 2 channels


class PS03(_PMKPowerSupply):
    """Class to control a PS03 power supply."""
    _num_channels = 4  # the PS03 has 4 channels
