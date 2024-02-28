Quickstart
==========

Probes are implemented as objects mirroring the physical probes. Writing to specific probe properties sets the probe's register to the corresponding value.
Reading from the probe properties reads the current value from the physical probe. Currently, no values except the probes metadata are cached.
This means that reading a property will always read the current value from the probe, which may slow down program execution so always keep this in mind when reading (or writing to) such properties inside loops.

The following example demonstrates how to use the library to set the attenuation of a probe and read the current value of the probe's attenuation:

.. code-block:: python

   from pmk_probes.probes import BumbleBee2kV
   from pmk_probes.power_supplies import PS03, Channel

   ps = PS03('COM3')  # replace 'COM3' with the actual serial port of the power supply
   bumblebee1 = BumbleBee2kV(ps, Channel.CH1)  # BumbleBee2kV probe at channel 1 of the power supply
   bumblebee1.attenuation = 500  # set the attenuation to 500
   print(bumblebee1.attenuation)  # should print 500

And this is how you would use auto zero on a FireFly probe:

.. code-block:: python

   from pmk_probes.probes import BumbleBee2kV, FireFly
   from pmk_probes.power_supplies import PS03, Channel

   ps = PS03('COM3')  # replace 'COM3' with the actual serial port of the power supply
   firefly1 = FireFly(ps, Channel.CH2)  # FireFly probe at channel 2 of the power supply
   firefly1.auto_zero()  # auto zero the probe