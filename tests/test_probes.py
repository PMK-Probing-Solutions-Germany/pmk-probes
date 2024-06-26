import time
from collections import deque
from math import isclose

import numpy as np
import pytest

from pmk_probes._devices import Channel
from pmk_probes._errors import ProbeTypeError
from pmk_probes.probes import BumbleBee2kV, FireFly, LED, BumbleBee200V

parameter_list = lambda prefix: [(f"{prefix}crease_offset_{func_name}", f"offset_step_{func_name}")
                                 for func_name in ["small", "large", "extra_large"]]


def test_create_bumblebee_at_ps_ch(ps):
    with pytest.raises(ProbeTypeError):
        _ = BumbleBee2kV(ps, channel=Channel.PS_CH)


def test_create_bumblebee200v(ps, get_config):
    with pytest.raises(ProbeTypeError):
        _ = BumbleBee200V(ps, channel=Channel.CH1)


@pytest.mark.usefixtures("mockable")
class TestBumbleBeeMockable:
    def test_read_metadata(self, bumblebee):
        metadata = bumblebee.metadata
        print(metadata)
        metadata.to_bytes()
        assert metadata is not None

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
    def test_set_offset_step(self, bumblebee, offset_step_attribute, value):
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


class TestBumbleBee:

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
        bumblebee.global_offset = 0
        bumblebee.attenuation = 100
        bumblebee.led_color = "red"
        bumblebee.factory_reset()
        time.sleep(3)  # needs 3 seconds to reset
        assert bumblebee.led_color == "yellow"
        assert bumblebee.overload_main_counter == 0

    @pytest.mark.parametrize(
        "step_function_name,amount",
        [("increase_attenuation", 1),
         ("decrease_attenuation", -1)])
    def test_attenuation_step(self, bumblebee, step_function_name, amount):
        """Test the attenuation step functions. The idea is that we start from a known attenuation and then step
         amount times and check if the attenuation is correct."""
        for start_attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = start_attenuation
            for _ in range(abs(amount)):
                step_function = getattr(bumblebee, step_function_name)
                step_function()
                time.sleep(0.1)
            rotatable = deque(bumblebee.properties.attenuation_ratios.user_to_internal)
            start_index = rotatable.index(start_attenuation)
            rotatable.rotate(-amount)
            assert bumblebee.attenuation == rotatable[start_index]

    @pytest.mark.parametrize(
        "step_function_name,step_size_name",
        parameter_list("in") + parameter_list("de")
    )
    def test_offset_step(self, bumblebee, step_function_name, step_size_name):
        """Test the offset step functions. The idea is that we start from a known offset and then step
         amount times and check if the offset is correct."""
        step_function = getattr(bumblebee, step_function_name)
        step_size = getattr(bumblebee, step_size_name)
        if step_function_name.startswith("de"):
            step_size = -step_size
        steps = 2
        for attenuation in bumblebee.properties.attenuation_ratios:
            bumblebee.attenuation = attenuation
            bumblebee.global_offset = 0
            for _ in range(steps):
                step_function()
                time.sleep(0.1)
            print(bumblebee.global_offset, steps * step_size, bumblebee.offset_step_small)
            assert bumblebee.global_offset == steps * step_size

    def test_read_temperature(self, bumblebee):
        print(bumblebee.temperature)


class TestHSDP:
    def test_read_metadata(self, hsdp):
        _ = hsdp.metadata

    def test_set_offset(self, hsdp):
        # assert setting the offset raises no error, however values can only be confirmed using a DMM as there is no
        # get-method
        hsdp.offset = -10
        hsdp.offset = 0

    def test_get_offset(self, hsdp):
        # assert getting the offset raises an error
        with pytest.raises(NotImplementedError):
            _ = hsdp.offset


class TestFireFly:
    def test_read_metadata(self, firefly: FireFly):
        assert firefly.metadata is not None
        print(firefly.metadata)

    def test_auto_zero(self, firefly: FireFly):
        firefly.probe_head_on = True  # probe head must be on to perform auto zero
        firefly.auto_zero()

    def test_probe_head_on(self, firefly: FireFly):
        firefly.probe_head_on = False
        assert firefly.probe_head_on is False

    @pytest.mark.parametrize("setting", [False, True])
    def test_probe_head_off(self, firefly: FireFly, setting: bool):
        firefly.probe_head_on = setting
        assert firefly.probe_head_on is setting

    def test_status(self, firefly: FireFly):
        print(firefly.probe_status_led)

    def test_probe_status_led(self, firefly: FireFly):
        assert firefly.probe_status_led == firefly.ProbeStates.PROBE_HEAD_OFF
        firefly.probe_head_on = True  # turn on probe head
        assert firefly.probe_status_led == firefly.ProbeStates.WARMING_UP

    def test_battery_level(self, firefly: FireFly):
        assert firefly.battery_indicator == (LED.OFF,) * 4  # battery is assumed to be empty
        firefly.probe_head_on = True
        battery_fresh = ((LED.GREEN,) * (i + 1) + (LED.OFF,) * (3 - i) for i in range(4))  # tuples of 1-4 green LEDs
        print(firefly.battery_indicator)
        assert firefly.battery_indicator in battery_fresh  # battery is assumed to be fresh

    def test_battery_voltage(self, firefly: FireFly):
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
