import configparser
import datetime
import re
import sys

import pytest

from pmk_probes._data_structures import PMKMetadata
from pmk_probes.power_supplies import PS03, _PMKPowerSupply
from pmk_probes.probes import *

config = configparser.ConfigParser()
config.read("config.ini")
MOCK_ONLY = config.getboolean("general", "mock_only")


def probe_class_from_name(name: str) -> type:
    return getattr(sys.modules[__name__], name)


def probe_class_from_config(section: str) -> type:
    return probe_class_from_name(config.get(section, "type"))


def probe_factory(section: str, ps: _PMKPowerSupply) -> ProbeType:
    return probe_class_from_config(section)(
        ps,
        Channel(config.getint(section, "channel")),
        verbose=True,
        allow_legacy=config.getboolean(section, "allow_legacy")
    )


@pytest.fixture
def get_config():
    return probe_class_from_config("devices.BumbleBee")


@pytest.fixture(params=config.items(section="devices.PS.connection"))
def ps(request):
    ps = PS03(**dict((request.param,)))
    yield ps
    ps.close()


@pytest.fixture(params=["devices.BumbleBee", "devices.BumbleBeeLegacy"])
def bumblebee(request, ps):
    bb: BumbleBeeType = probe_factory(request.param, ps)
    yield bb
    bb.global_offset = 0
    bb.attenuation = bb.properties.attenuation_ratios.get_user_value(1)


@pytest.fixture
def simulated_bumblebee():
    yield BumbleBee2kV(power_supply=None, simulated=True)

@pytest.fixture
def mock_bumblebee(request, mock_response, ps):
    bb: BumbleBeeType = probe_factory(request.param, ps)
    yield bb
    bb.global_offset = 0
    bb.attenuation = bb.properties.attenuation_ratios.get_user_value(1)


@pytest.fixture
def hsdp(ps):
    hsdp: HSDPType = probe_factory("devices.HSDP", ps)
    yield hsdp
    hsdp.global_offset = 0


@pytest.fixture
def firefly(ps):
    ff: FireFly = probe_factory("devices.FireFly", ps)
    # ff.probe_head_on = False
    yield ff
    #ff.probe_head_on = False


@pytest.fixture(autouse=False)
def mock_communication(monkeypatch):
    sent = []
    return_buffer = bytearray()

    def mock_write(self, data: bytes):
        nonlocal return_buffer
        print(data)
        string = data.decode('utf-8')

        # Use regex to find the desired substring
        match = re.search(r'(\x02)(WR|RD)(\d)\d{2}[WB](.*?)(\x03)', string)
        return_buffer.extend(b'\x02\x06' + (match.group(3) + match.group(4)).encode('utf-8') + b'\x03')
        return None

    def mock_read(self, data_length: int) -> bytes:
        ans = return_buffer[:data_length]
        return_buffer[:] = return_buffer[data_length:]
        return ans

    monkeypatch.setattr(HardwareInterface, "write", mock_write)
    monkeypatch.setattr(HardwareInterface, "read", mock_read)


def metadata_factory(probe_model: str, old_variant: bool) -> bytes:
    if old_variant:
        sw_rev = "1.0"
    else:
        sw_rev = "1.2"  # something other than 1.0
    mock_probe_metadata = PMKMetadata(
        eeprom_layout_revision="1.2",
        serial_number="0000",
        manufacturer="http://www.pmk.de",
        model="MockProbe",
        description="probe for unit tests",
        production_date=datetime.datetime.now().date(),
        calibration_due_date=(datetime.datetime.now() + datetime.timedelta(days=365)).date(),
        calibration_instance="PMK",
        hardware_revision="M1.0 K0.7",
        software_revision=f"M{sw_rev} K2.4",
        uuid=UUIDs.get_internal_value(probe_model)
    )
    return mock_probe_metadata.to_bytes()


if MOCK_ONLY:
    mock_params = [True]
else:
    mock_params = [True, False]  # run tests with and without mock query


@pytest.fixture(params=mock_params)
def mockable(request, monkeypatch):
    registers = {}

    def mock_query(self, wr_rd: Literal["WR", "RD"], i2c_address: int, command: int, payload: bytes = None,
                   length: int = 0xFF) -> bytes | None:
        nonlocal registers
        match wr_rd, i2c_address, command, payload:
            case "RD", 0x04, 0x00, _:
                return metadata_factory(self.probe_model, old_variant=True)
            case "WR", 0x04, command, payload:
                registers[command] = payload
                return None
            case "RD", 0x04, command, _:
                return registers.get(command)

    if request.param:
        monkeypatch.setattr(PMKDevice, "_query", mock_query)
    else:
        pass
