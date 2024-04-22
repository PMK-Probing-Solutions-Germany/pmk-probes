import datetime
import time
from math import floor, isclose

import numpy as np
import pytest

from pmk_probes.probes import BumbleBee2kV, HSDP2010, HSDP2050, FireFly, BumbleBee400V, Hornet4kV, LED, BumbleBee200V, \
    _BumbleBee
from pmk_probes.power_supplies import PS03, Channel
from tests.config import *


def round_down(n, decimals=0):
    multiplier = 10 ** decimals
    return floor(n * multiplier) / multiplier

@pytest.fixture()
def ps():
    ps = PS03(**ps_connection_info)
    yield ps
    ps.close()


@pytest.fixture()
def bumblebee(ps):
    bb1 = BumbleBee2kV(ps, test_bumblebee_channel, verbose=True, allow_legacy=True)
    bb1.factory_reset()
    time.sleep(3)  # needs 3 seconds to reset
    yield bb1

@pytest.fixture()
def hsdp1(ps):
    yield HSDP2010(ps, test_hsdp_channel, verbose=True)


@pytest.fixture()
def firefly(ps):
    yield FireFly(ps, test_firefly_channel, verbose=True)


class TestBumbleBee:

    def test_read_metadata(self, bumblebee):
        metadata = bumblebee.metadata
        print(metadata)
        metadata.to_bytes()
        assert metadata is not None

    def test_print_offset(self, bumblebee):
        bumblebee.global_offset = 500
        print(bumblebee.global_offset)

    def test_global_offset(self, bumblebee):
        for attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = attenuation
            for offset in np.linspace(*bumblebee.properties.input_voltage_range, num=5):
                ratios_ = offset * attenuation / max(bumblebee.properties.attenuation_ratios)
                bumblebee.global_offset = ratios_
                assert isclose(bumblebee.global_offset, ratios_, rel_tol=0.01)

    @pytest.mark.parametrize(
        "offset_step_attribute,value",
        [("offset_step_small", 0.125),
         ("offset_step_large", 2),
         ("offset_step_extra_large", 200)])
    def test_offset_step(self, bumblebee, offset_step_attribute, value):
        setattr(bumblebee, offset_step_attribute, value)
        assert getattr(bumblebee, offset_step_attribute) == value

    def test_attenuation(self, bumblebee):
        for attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = attenuation
            assert bumblebee.attenuation == attenuation

    def test_led_color(self, bumblebee):
        for color in BumbleBee2kV._led_colors:
            bumblebee.led_color = color
            assert bumblebee.led_color == color

    def test_overload_positive_counter(self, bumblebee):
        bumblebee.clear_overload_counters()
        assert bumblebee.overload_positive_counter == 0

    def test_overload_negative_counter(self, bumblebee):
        bumblebee.clear_overload_counters()
        assert bumblebee.overload_negative_counter == 0

    def test_overload_main_counter(self, bumblebee):
        # shift offset to limit so overload is triggered
        bumblebee.clear_overload_counters()
        assert bumblebee.overload_main_counter == 0

    # ======================================== Tests for the executing commands ========================================

    def test_clear_overload_counter(self, bumblebee):
        bumblebee.clear_overload_counters()
        assert bumblebee.overload_positive_counter == 0
        assert bumblebee.overload_negative_counter == 0
        assert bumblebee.overload_main_counter == 0

    def test_factory_reset(self, bumblebee):
        bumblebee.factory_reset()
        time.sleep(3)  # needs 3 seconds to reset
        assert bumblebee.attenuation == 50
        assert bumblebee.global_offset == 0
        assert bumblebee.led_color == "yellow"
        assert bumblebee.overload_main_counter == 0

    @pytest.mark.parametrize(
        "step_function_name,amount",
        [("increase_attenuation", 4),
         ("decrease_attenuation", -4)])
    def test_attenuation_step(self, bumblebee, step_function_name, amount):
        """Test the attenuation step functions. The idea is that we start from a known attenuation and then step
         amount times and check if the attenuation is correct."""
        for start_attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = start_attenuation
            for _ in range(abs(amount)):
                step_function = getattr(bumblebee, step_function_name)
                step_function()
            assert bumblebee.attenuation == bumblebee.properties.attenuation_ratios.shift(amount, start_attenuation)

    @staticmethod
    def offset_step_test(bumblebee, step_function, step_size):
        """Test the offset step functions. The idea is that we start from a known offset and then step
         amount times and check if the offset is correct."""
        steps = 2
        for attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = attenuation
            bumblebee.global_offset = 0
            for _ in range(steps):
                step_function()
            print(bumblebee.global_offset, steps * step_size, bumblebee.global_offset == steps * step_size)
            assert bumblebee.global_offset == steps * step_size

    def test_increase_offset_small(self, bumblebee):
        self.offset_step_test(bumblebee, bumblebee.increase_offset_small, bumblebee.offset_step_small)

    def test_decrease_offset_small(self, bumblebee):
        self.offset_step_test(bumblebee, bumblebee.decrease_offset_small, -bumblebee.offset_step_small)

    def test_increase_offset_large(self, bumblebee):
        bumblebee.offset_step_large = -2
        self.offset_step_test(bumblebee, bumblebee.increase_offset_large, bumblebee.offset_step_large)

    def test_decrease_offset_large(self, bumblebee):
        self.offset_step_test(bumblebee, bumblebee.decrease_offset_large, -bumblebee.offset_step_large)

    def test_increase_offset_extra_large(self, bumblebee):
        print(bumblebee.offset_step_extra_large)
        bumblebee.offset_step_extra_large = -7
        self.offset_step_test(bumblebee, bumblebee.increase_offset_extra_large, bumblebee.offset_step_extra_large)

    def test_decrease_offset_extra_large(self, bumblebee):
        self.offset_step_test(bumblebee, bumblebee.decrease_offset_extra_large, -bumblebee.offset_step_extra_large)

    def test_read_attenuation(self, bumblebee):
        for attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = attenuation
            assert bumblebee.attenuation == attenuation


class TestHSDP:
    def test_read_metadata(self, hsdp1):
        _ = hsdp1.metadata

    def test_set_offset(self, hsdp1):
        # assert setting the offset raises no error, however values can only be confirmed using a DMM as there is no
        # get-method
        hsdp1.offset = -10
        time.sleep(1)
        hsdp1.offset = 0

    def test_get_offset(self, hsdp1):
        # assert getting the offset raises an error
        with pytest.raises(NotImplementedError):
            _ = hsdp1.offset


class TestFireFly:
    def test_read_metadata(self, firefly: FireFly):
        assert firefly.metadata is not None
        print(firefly.metadata)

    def test_auto_zero(self, firefly: FireFly):
        firefly.probe_head_on = True  # probe head must be on to perform auto zero
        firefly.auto_zero()

    def test_probe_head_on(self, firefly: FireFly):
        firefly.probe_head_on = True
        assert firefly.probe_head_on is True

    def test_probe_head_off(self, firefly: FireFly):
        firefly.probe_head_on = False
        assert firefly.probe_head_on is False

    def test_status(self, firefly: FireFly):
        print(firefly.probe_status_led)

    def test_probe_status_led(self, firefly: FireFly):
        firefly.probe_head_on = False  # turn off probe head
        assert firefly.probe_status_led == firefly.ProbeStates.PROBE_HEAD_OFF
        firefly.probe_head_on = True  # turn on probe head
        assert firefly.probe_status_led == firefly.ProbeStates.WARMING_UP

    def test_battery_level(self, firefly: FireFly):
        firefly.probe_head_on = False  # turn off probe head
        assert firefly.battery_indicator == (LED.OFF,) * 4  # battery is assumed to be empty
        firefly.probe_head_on = True
        battery_fresh = ((LED.GREEN,) * (i + 1) + (LED.OFF,) * (3 - i) for i in range(4))  # tuples of 1-4 green LEDs
        print(firefly.battery_indicator)
        assert firefly.battery_indicator in battery_fresh  # battery is assumed to be fresh

    def test_battery_voltage(self, firefly: FireFly):
        firefly.probe_head_on = False  # turn off probe head
        slept = 0
        for i in range(100):  # battery voltage is not available for ~200 ms after turning off probe head
            if firefly.battery_voltage != 0.0:
                break
            slept += 0.01
            time.sleep(0.01)
        print(f"Slept for {slept * 1000} ms")
        off_voltage = firefly.battery_voltage
        firefly.probe_head_on = True
        on_voltage = firefly.battery_voltage
        assert on_voltage < off_voltage  # battery voltage should drop when probe head is on
        print(f"Off voltage: {off_voltage} V, On voltage: {on_voltage} V")
