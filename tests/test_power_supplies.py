from pmk_probes.power_supplies import find_power_supplies


class TestPMKPowerSupply:
    def test_num_channels(self, ps):
        assert ps._num_channels in (2, 4)

    def test_close(self, ps):
        ps.close()
        assert ps.interface.is_open is False

    def test_connected_probes(self, ps):
        connected_probes = ps.connected_probes
        print(connected_probes)

    def test_power_supply_repr(self, ps):
        assert repr(ps) == f"{ps.__class__.__name__}({next(iter(ps.interface.connection_info))}={ps.interface})"


def test_find_power_supplies():
    print(find_power_supplies())
    assert len(find_power_supplies()) > 0
