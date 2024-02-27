import socket
import time
from abc import ABCMeta

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
