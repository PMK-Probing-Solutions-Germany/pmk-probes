import pytest

from pmk_probes.power_supplies import PS03, find_power_supplies
from tests.config import *


@pytest.fixture()
def ps():
    ps = PS03(**ps_connection_info)
    yield ps
    ps.close()


class TestPMKPowerSupply:
    def test_num_channels(self, ps):
        assert ps._num_channels in (2, 4)

    def test_close(self, ps):
        ps.close()


def test_find_power_supplies():
    print("PSs: ", find_power_supplies())
