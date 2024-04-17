"""This module contains the classes for the PMK power supplies."""
import http.client
import re
import socket
import time

import serial
import serial.tools.list_ports

from ._devices import PMKDevice, Channel
from ._errors import ProbeReadError
from ._hardware_interfaces import LANInterface, USBInterface


class _PMKPowerSupply(PMKDevice):
    """
    The class that controls access to the serial resource of the PMK power supply.

    """
    _i2c_addresses: dict[str, int] = {"metadata": 0x04}
    _addressing = "W"
    _num_channels = None

    def __init__(self, com_port: str = None, ip_address: str = None, verbose: bool = False):
        super().__init__(channel=Channel.PS_CH, verbose=verbose)
        from .probes import _ALL_PMK_PROBES  # to avoid circular imports
        self.supported_probe_types = _ALL_PMK_PROBES
        match com_port, ip_address:
            case com_port, None:
                self.interface = USBInterface(com_port)
            case None, ip_address:
                self.interface = LANInterface(ip_address)
            case None, None:
                raise ValueError("Either com_port or ip_address must be specified.")
            case _:
                raise ValueError("Only one of com_port or ip_address can be specified.")

    def __repr__(self):
        if isinstance(self.interface, USBInterface):
            connection_info_name = "com_port"
        else:
            connection_info_name = "ip_address"
        return (f"{self.__class__.__name__}(serial_number={self.metadata.serial_number}, "
                f"{connection_info_name}={self.interface.connection_info})")

    @property
    def _interface(self):
        return self.interface

    @property
    def connected_probes(self):
        """

        """
        from .probes import _BumbleBee, _HSDP, FireFly
        to_try = [_BumbleBee, _HSDP, FireFly]
        connected_probes = {channel: None for channel in Channel}
        for channel in Channel:
            # for every channel, query the probe for its metadata
            for ProbeType in to_try:
                try:
                    detected_probe = ProbeType(self, channel, allow_legacy=True)
                    connected_probes[channel] = detected_probe
                    break
                except ProbeReadError:
                    continue
        return connected_probes

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
        self.interface.close()


class PS02(_PMKPowerSupply):
    """Class to control a PS02 power supply."""
    _num_channels = 2  # the PS02 has 2 channels


class PS03(_PMKPowerSupply):
    """Class to control a PS03 power supply."""
    _num_channels = 4  # the PS03 has 4 channels


def get_closed_ps_with_metadata(model=None, **connection_info) -> _PMKPowerSupply:
    if not model:
        ps = PS03(**connection_info)  # works for detecting both PS02 and PS03
        model = ps.metadata.model
        ps.close()
    if model == "PS-02":
        ps = PS02(**connection_info)
    elif model == "PS-03":
        ps = PS03(**connection_info)
    else:
        raise ValueError(f"Unknown model: {model}")
    return ps

def _find_power_supplies_usb() -> list[_PMKPowerSupply]:
    devices = serial.tools.list_ports.comports()
    power_supplies = []
    for device in devices:
        match device.vid, device.pid:
            case 1027, 24577:
                power_supplies.append(get_closed_ps_with_metadata(com_port=device.device))
            case _:
                pass
    return power_supplies

def _find_power_supplies_lan() -> list[_PMKPowerSupply]:
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
            full_info_list.append(get_closed_ps_with_metadata(metadata["model"], ip_address=ip))
        except (OSError, AttributeError):
            pass
    return full_info_list


def find_power_supplies() -> dict[str, list[_PMKPowerSupply]]:
    return {'usb': _find_power_supplies_usb(), 'lan': _find_power_supplies_lan()}
