import logging
import struct
from dataclasses import dataclass, fields
import datetime
from enum import Enum, auto
from typing import ClassVar, Any, Union, NamedTuple, TypeVar

DATE_FORMAT = "%Y%m%d"

# dictionary of UUIDs and their corresponding probe models
# the key has to be the class name of the probe and the value is the UUID of the probe
UUIDs = {
    "BumbleBee2kV": "886-102-504",
    "BumbleBee400V": "886-122-504",
    "HSDP4010": "88T-400-008",
    "HSDP2010": "88T-200-003",
    "HSDP2010L": "88T-200-004",
    "HSDP2025": "88T-200-005",
    "HSDP2025L": "88T-200-006",
    "HSDP2050": "88T-200-007",
    "FireFly": "886-102-505"
}


def _batched_string(string: bytes, batch_size: int):
    """Return a generator that yields batches of size batch_size of the string."""
    for i in range(0, len(string), batch_size):
        yield string[i:i + batch_size]


class UserMapping:

    def __init__(self, user_to_integer: dict[Any, int]):
        self.user_to_integer = user_to_integer

    @property
    def integer_to_user(self) -> dict:
        """
        Inverts a bijective dictionary.

        Returns:
            The inverted dictionary.
        """
        return {v: k for k, v in self.user_to_integer.items()}

    def get_user_value(self, integer: int):
        return self.integer_to_user[integer]

    def get_integer_value(self, user_value: Any):
        return self.user_to_integer[user_value]

    def shift(self, shift: int, start: Any):
        """
        Returns the user value that is shift steps away from start. E.g. for shift=1 and start="red" the method
        returns "green".
        """
        as_list = list(self.user_to_integer)
        restricted_index = (as_list.index(start) + shift) % len(as_list)
        return as_list[restricted_index]

    def keys(self):
        return self.user_to_integer.keys()

    def values(self):
        return self.user_to_integer.values()

    def __iter__(self):
        return iter(self.user_to_integer)


class PMKProbeProperties(NamedTuple):
    input_voltage_range: tuple[float, float]  # (lower, upper)
    attenuation_ratios: UserMapping  # tuple of all selectable attenuation ratios, descending order
    scaling_factor: float | None  # factor used when interpreting 2-byte short values as decimal values


@dataclass
class PMKMetadata:
    eeprom_layout_revision: str
    serial_number: str
    manufacturer: str
    model: str
    description: str
    production_date: datetime.datetime
    calibration_due_date: datetime.datetime
    calibration_instance: str
    hardware_revision: str
    software_revision: str
    uuid: str
    page_size: ClassVar[int] = 16
    num_pages: ClassVar[int] = 16

    def __post_init__(self):
        if self.uuid not in UUIDs.values():
            self.uuid = ""

    def __eq__(self, other):
        """ Metadata is equal if byte representation is equal """
        return self.to_bytes() == other.to_bytes()

    @classmethod
    def from_bytes(cls, metadata: bytes) -> Union["PMKMetadata", None]:
        metadata = metadata.replace(b"\xFF", b"").replace(b"?", b"")
        values = {}
        try:
            for i, field in enumerate(fields(cls)):
                field_value = metadata.split(b"\n")[i].decode("utf-8")
                values[field.name] = cls._parse_field(field, field_value)
            return cls(**values)
        except TypeError as exc:
            logging.warning("Metadata present in the probe could not be parsed.")
            logging.error(exc)
            return None

    @classmethod
    def _parse_field(cls, field, field_value: str):
        # check if type of field is float:
        if field.type == float:
            return struct.unpack('f', field_value.encode())[0]
        match field_value, field.type:
            case "", _:
                return None
            case _, datetime.datetime:
                return datetime.datetime.strptime(field_value, DATE_FORMAT)
            case _, _:
                return field.type(field_value)

    def to_bytes(self):
        values = []
        for field in fields(self):
            field_value = getattr(self, field.name)
            values.append(self._unparse_field(field, field_value))
        str_values = [str(value) for value in values]
        metadata_str = ("\n".join(str_values) + "\n").encode()
        # fill the rest with 0x3F
        metadata_str += b"\x3F" * (self.page_size * self.num_pages - len(metadata_str))
        return metadata_str

    @classmethod
    def _unparse_field(cls, field, field_value):
        match field_value, field.type:
            case None, _:
                return b''  # append nothing to the metadata
            case _, datetime.datetime:
                return field_value.strftime(DATE_FORMAT)
            case _, _:
                return field_value

    def as_pages(self):
        metadata_bytes = self.to_bytes()
        return list(_batched_string(metadata_bytes, self.page_size))


@dataclass
class FireFlyMetadata(PMKMetadata):
    """ FireFly has special metadata because it has at least one more field than all other PMK probes. """

    propagation_delay: float

    metadata_map = {
        "eeprom_layout_revision": (0x04, 3),
        "serial_number": (0x07, 4),
        "manufacturer": (0x0B, 17),
        "model": (0x2B, 7),
        "description": (0x3B, 37),
        "production_date": (0x61, 8),
        "calibration_due_date": (0x69, 8),
        "calibration_instance": (0x71, 3),
        "hardware_revision": (0x75, 22),
        "software_revision": (0x8E, 13),
        "uuid": (0xA7, 11),
        "propagation_delay": (0xBB, 4)
    }

    @classmethod
    def from_bytes(cls, metadata: bytes) -> Union["FireFlyMetadata", None]:
        # TODO: this is very similar to the method in PMKMetadata, maybe refactor
        values = {}
        for field in fields(cls):
            address, length = cls.metadata_map[field.name]
            field_value = metadata[address:address + length].decode("utf-8")
            values[field.name] = cls._parse_field(field, field_value)
        return cls(**values)


class LED(Enum):
    GREEN = auto()
    YELLOW = auto()
    BLINKING_RED = auto()
    OFF = auto()
