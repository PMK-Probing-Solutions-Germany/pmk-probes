import http.client
import re
import socket
import time
from abc import ABCMeta
from collections import namedtuple

import serial
import serial.tools.list_ports

from pmk_probes._errors import ProbeConnectionError


class HardwareInterface(metaclass=ABCMeta):

    def __init__(self, connection_info: str):
        self.connection_info = connection_info

    def write(self, data: bytes):
        raise NotImplementedError

    def read(self, length: int) -> bytes:
        raise NotImplementedError

    def query(self, data: bytes) -> bytes:
        raise NotImplementedError

    def reset_input_buffer(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


class LANInterface(HardwareInterface):
    def __init__(self, ip_address: str):
        super().__init__(ip_address)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((ip_address, 10001))

    def write(self, data: bytes):
        self.sock.send(data)

    def read(self, length: int) -> bytes:
        time.sleep(0.05)
        return self.sock.recv(length)

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        self.sock.close()


class USBInterface(HardwareInterface):

    def __init__(self, com_port: str):
        super().__init__(com_port)
        try:
            self.ser = serial.Serial(com_port, baudrate=115200, timeout=1, rtscts=False, dsrdtr=False)
        except serial.SerialException:
            raise ProbeConnectionError(f"Could not open {com_port}. Is the power supply connected?")

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def read(self, length: int) -> bytes:
        return self.ser.read(length)

    def reset_input_buffer(self) -> None:
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()


PSConnectionInformation = namedtuple("PSConnectionInformation", ["ip_address", "model", "serial_number"])

def _scan_serial_ports() -> list[PSConnectionInformation]:

    devices = serial.tools.list_ports.comports()
    power_supplies = []
    for device in devices:
        match device.vid, device.pid:
            case 1027, 24577:
                print("Found PMK power supply at", device.device)
                from pmk_probes.power_supplies import PS03
                ps = PS03(device.device, verbose=True)
                power_supplies.append(PSConnectionInformation(device.device, ps.metadata.model, ps.metadata.serial_number))
                ps.close()
            case _:
                pass
    return power_supplies

def _find_power_supplies() -> list[PSConnectionInformation]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
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
    sock.close()
    full_info_list = []
    # read XML metadata from the power supplies' IP addresses by creating an HTTP request
    for ip in ps_ips:
        try:
            conn = http.client.HTTPConnection(ip)
            conn.request("GET", "/PowerSupplyMetadata.xml")
            text = conn.getresponse().read().decode()
            patterns = {"model": r"<Model>([\w-]{5})</Model>", "serial_number": r"<SerialNumber>(\d{4})</SerialNumber>"}
            metadata = {key: re.search(pattern, text).group(1) for key, pattern in patterns.items()}
            full_info_list.append(PSConnectionInformation(ip, **metadata))
        except OSError:
            pass
    return full_info_list

if __name__ == "__main__":
    print(_scan_serial_ports())
