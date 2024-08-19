"""This module contains the classes for the PMK power supplies."""
import http.client
import re
import socket
from typing import TypeVar, Any

import serial
import serial.tools.list_ports

from ._devices import PMKDevice, Channel
from ._errors import ProbeReadError, ProbeConnectionError
from ._hardware_interfaces import HardwareInterface, SerialInterface

PowerSupplyType = TypeVar("PowerSupplyType", bound="_PMKPowerSupply")


class _PMKPowerSupply(PMKDevice):
    """The class that controls access to the serial resource of the PMK power supply."""
    _i2c_addresses: dict[str, int] = {"metadata": 0x04}
    _addressing = "W"
    _num_channels = None

    def __init__(self, com_port: str = None, ip_address: str = None, verbose: bool = False):
        if com_port:
            interface = SerialInterface(com_port)
        elif ip_address:
            interface = SerialInterface(f"socket://{ip_address}:10001")
        else:
            raise ValueError("No connection information provided")
        super().__init__(channel=Channel.PS_CH, verbose=verbose)
        from .probes import _ALL_PMK_PROBES  # to avoid circular imports
        self.supported_probe_types = _ALL_PMK_PROBES
        self.interface = interface

    def __repr__(self):
        if self._serial_number:
            sn_part = f"serial_number={self._serial_number}, "
        else:
            sn_part = ""
        return f"{self.__class__.__name__}({sn_part}{next(iter(self._interface.connection_info))}={self._interface.connection_info})"

    @property
    def _interface(self) -> "HardwareInterface":
        if self._simulated:
            return self._simulated_interface
        else:
            return self.interface

    @property
    def connected_probes(self) -> tuple[Any, ...]:
        """Show all connected probes for this power supply."""
        from .probes import BumbleBee2kV, HSDP2010, FireFly
        to_try = [BumbleBee2kV, HSDP2010, FireFly]
        connected_probes = []
        for channel in [Channel(i) for i in range(1, self._num_channels + 1)]:
            # for every channel, query the probe for its metadata
            for ProbeType in to_try:
                try:
                    detected_probe = ProbeType(self, channel, allow_legacy=True)
                    connected_probes.append(detected_probe)
                    break
                except (ProbeReadError, ProbeConnectionError):
                    continue
        return tuple(connected_probes)

    # def device_at_channel(self, channel: Channel) -> PMKDevice:
    #     """
    #     Returns:
    #         The probe connected to the specified channel.
    #     """
    #     if channel == Channel.PS_CH:
    #         return self
    #     else:
    #         for ProbeType in self.supported_probe_types:
    #             try:
    #                 probe_to_try = ProbeType(self, channel, legacy_mode=True)
    #             except ValueError:
    #                 continue

    def close(self):
        """Disconnects the power supply to free the serial connection."""
        self._interface.close()


class PS02(_PMKPowerSupply):
    """Class to control a PS02 power supply."""
    _num_channels = 2  # the PS02 has 2 channels


class PS03(_PMKPowerSupply):
    """Class to control a PS03 power supply."""
    _num_channels = 4  # the PS03 has 4 channels


def _auto_ps(model=None, **kwargs) -> PowerSupplyType:
    """Automatically find a power supply and return it."""
    if not model:
        model_getter_ps = PS03(**kwargs)
        model = model_getter_ps.metadata.model
        model_getter_ps.close()
    match model:
        case "PS-02":
            return PS02(**kwargs)
        case "PS-03":
            return PS03(**kwargs)
        case _:
            raise ValueError("Unknown model")


def _find_power_supplies_usb() -> list[PowerSupplyType]:
    devices = serial.tools.list_ports.comports()
    power_supplies = []
    for device in devices:
        match device.vid, device.pid:
            case 1027, 24577:
                power_supplies.append(_auto_ps(com_port=device.device))
            case _:
                pass
    return power_supplies


def _find_power_supplies_lan() -> list[PowerSupplyType]:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind((socket.gethostbyname(socket.gethostname()), 30718))
        sock.settimeout(1)
        sock.sendto(b'\x00\x00\x00\xf6', ('<broadcast>', 30718))
        ps_ips = []
        # Receive response
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data.startswith(b'\x00\x00\x00\xf7'):
                    ps_ips.append(addr[0])
            except socket.timeout:
                break
    full_info_list = []
    # read XML metadata from the power supplies' IP addresses by creating an HTTP request
    for ip in ps_ips:
        try:
            conn = http.client.HTTPConnection(ip)
            conn.request("GET", "/PowerSupplyMetadata.xml")
            text = conn.getresponse().read().decode()
            patterns = {"model": r"<Model>([\w-]{5})</Model>", "serial_number": r"<SerialNumber>(\d{4})</SerialNumber>"}
            metadata = {key: re.search(pattern, text).group(1) for key, pattern in patterns.items()}
            full_info_list.append(_auto_ps(model=metadata["model"], ip_address=ip))
        except (OSError, AttributeError):
            pass
    return full_info_list


def find_power_supplies() -> dict[str, list[PowerSupplyType]]:
    return {'USB': _find_power_supplies_usb(), 'LAN': _find_power_supplies_lan()}


if __name__ == "__main__":
    print(find_power_supplies())

