# PMK Probes

pmk-probes is a Python package to control active oscilloscope probes by [PMK](http://www.pmk.de/).

## Installation

Use the package manager [pip](https://pip.pypa.io/en/stable/) to install pmk-probes.

```bash
pip install pmk-probes
```

## Requirements

- Python 3.10 or higher
- pyserial

## Usage

```python
from pmk_probes.probes import BumbleBee2kV
from pmk_probes.power_supplies import PS03, Channel

ps = PS03('<YOUR_COM_PORT>')  # replace with the COM port of your power supply or specify ip_address parameter 
bumblebee1 = BumbleBee2kV(ps, Channel.CH1)  # use the BumbleBee probe on channel 1
print(bumblebee1.metadata.serial_number)  # print the serial number of the probe
bumblebee1.attenuation = 500  # set the attenuation to 500x
```

## Documentation

The documentation is available at [https://pmk-probes.readthedocs.io](https://pmk-probes.readthedocs.io).

## License

[BSD-3-Clause](https://opensource.org/licenses/BSD-3-Clause)