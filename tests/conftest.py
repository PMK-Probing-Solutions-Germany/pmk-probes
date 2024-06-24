import configparser
import re
import sys

import pytest

from pmk_probes._hardware_interfaces import HardwareInterface
from pmk_probes.power_supplies import PS03, _PMKPowerSupply
from pmk_probes.probes import *

config = configparser.ConfigParser()
config.read("config.ini")
USE_MOCK = config.getboolean("general", "use_mock")


def probe_class_from_config(section: str) -> type:
    return getattr(sys.modules[__name__], config.get(section, "type"))


def probe_factory(section: str, ps: _PMKPowerSupply) -> ProbeType:
    return probe_class_from_config(section)(
        ps,
        Channel(config.getint(section, "channel")),
        verbose=True,
        allow_legacy=config.getboolean(section, "allow_legacy")
    )


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
    ff.probe_head_on = False
    yield ff
    ff.probe_head_on = False


@pytest.fixture(autouse=USE_MOCK)
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


@pytest.fixture(autouse=USE_MOCK)
def mock_response(monkeypatch):
    registers = {}

    def mock_query(self, wr_rd: Literal["WR", "RD"], i2c_address: int, command: int, payload: bytes = None,
                   length: int = 0xFF) -> bytes | None:
        sw_revision = "1.0"
        match wr_rd, i2c_address, command, payload:
            case "RD", 0x04, 0x00, _:
                a = ((b'1.2\n'
                      b'0008\n'
                      b'http://www.pmk.de\n'
                      b'MockProbe\n'
                      b'High voltage probe system\n'
                      b'20240620\n'
                      b'20250620\n'
                      b'PMK\n'
                      b'M7.2 K5.0\n') +
                     f"M{sw_revision} K0.0\n".encode() +
                     f"{UUIDs.get_internal_value(self.probe_model):?<20}\n".encode() +
                     b'\n\n???????????????????????????????????????????????????????????????????????????????????????????'
                     b'???????????????????????????????????')
                print(a)
                return a
            case "WR", 0x04, command, payload:
                registers[command] = payload
                return None
            case "RD", 0x04, command, _:
                return registers.get(command)

    monkeypatch.setattr(PMKDevice, "_query", mock_query)
