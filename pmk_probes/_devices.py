from abc import abstractmethod
from collections import namedtuple
from enum import Enum

from ._data_structures import PMKMetadata, PMKProbeProperties


class Channel(Enum):
    """
    Enumeration of the power supply channels.

    Use this to declare which device you want to target when sending commands.
    """
    CH1 = 1  # the first channel
    CH2 = 2  # the second channel
    CH3 = 3  # the third channel (PS03 only)
    CH4 = 4  # the fourth channel (PS03 only)
    PS_CH = 0  # the PS's channel (internal use only)


class PMKDevice:
    """
    Base class for all PMK devices.

    Defines the methods that are common to all PMK devices.
    """

    def __init__(self, channel: Channel):
        self.channel = channel

    @property
    def metadata(self) -> PMKMetadata:
        """The metadata of the device."""
        raise NotImplementedError
