import configparser
import sys
import time

import pytest

from pmk_probes.power_supplies import PS03, _PMKPowerSupply
from pmk_probes.probes import *

config = configparser.ConfigParser()
config.read("config.ini")


def probe_class_from_config(section: str) -> type:
    return getattr(sys.modules[__name__], config.get(section, "type"))


def probe_factory(section: str, ps: _PMKPowerSupply) -> ProbeType:
    return probe_class_from_config(section)(
        ps,
        Channel(config.getint(section, "channel")),
        verbose=False,
        allow_legacy=True
    )


@pytest.fixture
def conf():
    return config


@pytest.fixture(params=config.items(section="devices.PS.connection"))
def ps(request):
    ps = PS03(**dict((request.param,)))
    yield ps
    ps.close()


@pytest.fixture
def bumblebee(ps):
    bb: BumbleBeeType = probe_factory("devices.BumbleBee", ps)
    # bb1.factory_reset()
    # time.sleep(3)  # needs 3 seconds to reset
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
