import time
from abc import abstractmethod
from collections import namedtuple
from enum import Enum
from functools import lru_cache
from typing import Literal

from ._data_structures import PMKMetadata, PMKProbeProperties
from ._errors import ProbeReadError, ProbeConnectionError
from ._hardware_interfaces import HardwareInterface

# Constants for communication
DUMMY = b'\x00'
STX = b'\x02'
ACK = b'\x06'
NACK = b'\x15'
ETX = b'\x03'
CR = b'\r'


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
    _i2c_addresses: dict[str, int] = None  # addresses of the metadata and offset registers
    _addressing: str = None  # word- or byte-addressing

    def __init__(self, channel: Channel, verbose: bool = False):
        self.channel = channel
        self.verbose = verbose
        self._serial_number = None

    @property
    @abstractmethod
    def interface(self) -> "HardwareInterface":
        """
        The _interface to the device.
        """
        raise NotImplementedError

    @lru_cache
    def _read_metadata(self) -> PMKMetadata:
        """
        Helper function to read the metadata of the probe and cache it for later use. Cache can be cleared using
        _read_metadata.cache_clear() to force a re-read."""
        query = self._query("RD", i2c_address=self._i2c_addresses['metadata'], command=0x00, length=0xFF)
        return PMKMetadata.from_bytes(query)

    @property
    def metadata(self) -> PMKMetadata:
        """
        Read the probe's metadata.

        :getter: Returns the probe's metadata.
        """
        try:
            metadata = self._read_metadata()
            self._serial_number = metadata.serial_number
            return metadata
        except Exception as e:
            raise ProbeConnectionError(f"{e.args[0]}. Could not read metadata from {repr(self)}.") \
                from e

    def _expect(self, expected: list[bytes]) -> None:
        """
        For every entry expected[i] in expected reads len(expected[i]) bytes from the serial port and compares them
        to expected[i].

        :param expected: A list of bytes objects that are expected to be read from the serial port.
        :return: None
        :raises ProbeReadError: If the bytes read from the serial port do not match the expected bytes.
        """
        for expected_byte in expected:
            answer = self.interface.read(len(expected_byte))
            if answer != expected_byte:
                raise ProbeReadError(f"Got {answer} instead of {expected_byte}.")
        return None

    def _query(self, wr_rd: Literal["WR", "RD"], i2c_address: int, command: int, payload: bytes = None,
               length: int = 0xFF) -> bytes:
        """
        Query the probe for the metadata of the current channel. This method is used for all WR/RD commands.
        Returns:
            The response as a bytes object.
        """
        self.interface.reset_input_buffer()  # Clear input buffer in case it wasn't empty
        cmd = f"{command:04X}{length:02X}"
        string = f"\x02{wr_rd}{self.channel.value}{i2c_address:02X}{self._addressing}{cmd}"
        if payload is not None:
            string += payload.hex().upper()  # 2 hex digits per byte
        string += "\x03"
        # write the command
        self.interface.write(string.encode())
        if self.verbose:
            print(f"Sent: {string}")
        # read the response and ensure it's correct: (STX, ACK, echo, read_payload, ETX, CR)
        self._expect([STX, ACK, f"{self.channel.value}{cmd}".encode()])
        # read the payload
        if wr_rd == "RD":
            # length here means number of bytes, not number of characters
            # decoding (decode()) and creating new bytes (fromhex) is required to get rid of doubly encoded characters
            read_payload = bytes.fromhex(self.interface.read(length * 2).decode())
        else:
            # no payload is returned for WR commands
            read_payload = None
        if self.verbose:
            print(f"Received: {read_payload}")
        self._expect([ETX, CR])
        return read_payload
