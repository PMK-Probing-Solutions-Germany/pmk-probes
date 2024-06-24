import datetime
import logging
import struct
from dataclasses import dataclass, fields
from enum import Enum, auto
from typing import ClassVar, Any, Union, NamedTuple

DATE_FORMAT = "%Y%m%d"




def _batched_string(string: bytes, batch_size: int):
    """Return a generator that yields batches of size batch_size of the string."""
    for i in range(0, len(string), batch_size):
        yield string[i:i + batch_size]



class UserMapping:
    """ Maps between 'end user' display values and internal descriptors. It is defined using a dictionary that maps
    from user values to descriptors. """

    def __init__(self, user_to_internal: dict[int | str, int | str]):
        if len(set(user_to_internal.values())) != len(user_to_internal):
            logging.warning("The mapping is not bijective.")
        self.user_to_internal = user_to_internal

    @property
    def internal_to_user(self) -> dict:
        """
        Inverts a bijective dictionary.

        Returns:
            The inverted dictionary.
        """
        return {v: k for k, v in self.user_to_internal.items()}

    def get_user_value(self, internal_value: int):
        return self.internal_to_user[internal_value]

    def get_internal_value(self, user_value: Any) -> int:
        return self.user_to_internal[user_value]

    def keys(self):
        """ Returns the user values. """
        return self.user_to_internal.keys()

    @property
    def user_values(self):
        return self.user_to_internal.keys()

    @property
    def internal_values(self):
        return self.user_to_internal.values()

    def __iter__(self):
        return iter(self.user_to_internal)


# dictionary of UUIDs and their corresponding probe models
# the key has to be the class name of the probe and the value is the UUID of the probe
UUIDs = UserMapping({
    "Hornet4kV": "886-142-504",
    "BumbleBee2kV": "886-102-504",
    "BumbleBee1kV": "886-132-504",
    "BumbleBee400V": "886-122-504",
    "BumbleBee200V": "886-112-504",
    "HSDP4010": "88T-400-008",
    "HSDP2010": "88T-200-003",
    "HSDP2010L": "88T-200-004",
    "HSDP2025": "88T-200-005",
    "HSDP2025L": "88T-200-006",
    "HSDP2050": "88T-200-007",
    "FireFly": "886-102-505"
})

class PMKProbeProperties(NamedTuple):
    input_voltage_range: tuple[float, float]  # (lower, upper)
    attenuation_ratios: UserMapping  # tuple of all selectable attenuation ratios, descending order


@dataclass
class PMKMetadata:
    eeprom_layout_revision: str
    serial_number: str
    manufacturer: str
    model: str
    description: str
    production_date: datetime.date
    calibration_due_date: datetime.date
    calibration_instance: str
    hardware_revision: str
    software_revision: str
    uuid: str
    page_size: ClassVar[int] = 16
    num_pages: ClassVar[int] = 16

    def __post_init__(self):
        if self.uuid not in UUIDs.internal_values:
            self.uuid = ""

    def __eq__(self, other):
        """ Metadata is equal if byte representation is equal """
        return self.to_bytes() == other.to_bytes()

    @classmethod
    def from_bytes(cls, metadata: bytes) -> Union["PMKMetadata", None]:
        values = {}
        for i, field in enumerate(fields(cls)):
            field_value = cls._get_field_value(metadata, i, field.name)
            try:
                values[field.name] = cls._parse_field(field, field_value)
            except struct.error:
                values[field.name] = None
        return cls(**values)

    @classmethod
    def _get_field_value(cls, metadata: bytes, k: int, field_name: str) -> bytes:
        """ Get the value of a field from the metadata using the traditional sequential evaluation of fields.

        :param metadata: The metadata as a bytes object.
        :param k: The index of the field in the metadata.
        :param field_name: The name of the field.
        :return: The kth field of the metadata separated by "\n".
        """
        metadata_list = metadata.replace(b"\xFF", b"").replace(b"?", b"").split(b"\n")
        return metadata_list[k]

    @classmethod
    def _parse_field(cls, field, field_value: str | bytes):
        # check if type of field is float:
        if field.type == float:
            return struct.unpack('f', field_value)[0]
        match field_value.decode("utf-8"), field.type:
            case "", _:
                return None
            case decoded, datetime.date:
                try:
                    return datetime.datetime.strptime(decoded, DATE_FORMAT)
                except ValueError:
                    return None
            case decoded, _:
                return field.type(decoded)

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
            case _, datetime.date:
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
    # notation for metadata maps is "name: (address, length)"
    metadata_map_v11 = {
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
    metadata_map_v12 = {
        "eeprom_layout_revision": (0x04, 3),
        "serial_number": (0x07, 7),
        "manufacturer": (0x11, 17),
        "model": (0x31, 7),
        "description": (0x41, 37),
        "production_date": (0x67, 8),
        "calibration_due_date": (0x6F, 8),
        "calibration_instance": (0x77, 3),
        "hardware_revision": (0x7B, 22),
        "software_revision": (0x94, 13),
        "uuid": (0xAD, 11),
        "propagation_delay": (0xC1, 4)
    }
    # EEPROM layout revision -> metadata map
    metadata_maps = {
        b"1.1": metadata_map_v11,
        b"1.2": metadata_map_v12
    }

    @classmethod
    def _get_field_value(cls, metadata: bytes, k: int, field_name: str) -> bytes:
        """ Get the value of a field from the metadata.
        :param metadata: The metadata as a bytes object.
        :param k: The index of the field in the metadata.
        :param field_name: The name of the field.
        :return: The field value of the metadata entry with name field_name.
        """
        address, length = cls.metadata_maps[metadata[0x04:0x07]][field_name]  # layout revision is stored at 0x04-0x06
        return metadata[address:address + length]


class LED(Enum):
    """ Enum for the FireFly LED states."""
    GREEN = auto()
    YELLOW = auto()
    BLINKING_RED = auto()
    OFF = auto()
