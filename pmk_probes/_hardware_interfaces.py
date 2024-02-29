import http.client
import re
import socket
import time
from abc import ABCMeta
from collections import namedtuple

import serial

from pmk_probes._errors import ProbeConnectionError


class HardwareInterface(metaclass=ABCMeta):
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
        super().__init__()
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
        super().__init__()
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


def _find_power_supplies() -> list[PSConnectionInformation]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(2)
    sock.sendto(b'\x00\x00\x00\xf8', ('<broadcast>', 30718))
    ps_ips = []
    # Receive response
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if data.startswith(b'\x00\x00\x00\xf9'):
                ps_ips.append(addr[0])
        except socket.timeout:
            break
    sock.close()
    full_info_list = []
    # read XML metadata from the power supplies' IP addresses by creating an HTTP request
    for ip in ps_ips:
        conn = http.client.HTTPConnection(ip)
        conn.request("GET", "/PowerSupplyMetadata.xml")
        text = conn.getresponse().read().decode()
        patterns = {"model": r"<Model>([\w-]{5})</Model>", "serial_number": r"<SerialNumber>(\d{4})</SerialNumber>"}
        metadata = {key: re.search(pattern, text).group(1) for key, pattern in patterns.items()}
        full_info_list.append(PSConnectionInformation(ip, **metadata))
    return full_info_list
