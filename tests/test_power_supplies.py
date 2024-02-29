import pytest

from pmk_probes._hardware_interfaces import USBInterface, LANInterface, find_power_supplies
from pmk_probes.power_supplies import PS03
from tests.config import *


@pytest.fixture()
def ps():
    ps = PS03(**ps_connection_info)
    yield ps
    ps.close()


class TestPMKPowerSupply:
    def test_init_with_usb(self, ps):
        assert isinstance(ps.interface, USBInterface)

    def test_init_with_lan(self, ps):
        assert isinstance(ps.interface, LANInterface)

    def test_init_with_no_preferred_interface(self, ps):
        assert isinstance(ps.interface, USBInterface)

    def test_ps02_num_channels(self, ps):
        assert ps._num_channels == 2

    def test_ps03_num_channels(self, ps):
        assert ps._num_channels == 4

    def test_close(self, ps):
        ps.close()
        assert ps.interface.is_open == False

    def test_connected_probes(self, ps):
        print(ps.connected_probes)
        assert 1 == 0


def test_find_power_supplies():
    find_power_supplies()
