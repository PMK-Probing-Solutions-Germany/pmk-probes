import socket
import time
from abc import ABCMeta, abstractmethod
from collections import namedtuple

import serial
import serial.tools.list_ports

from pmk_probes._errors import ProbeConnectionError


class HardwareInterface(metaclass=ABCMeta):

    def __init__(self, connection_info: str):
        self.connection_info = connection_info  # ip_address/com_port depending on the _interface

    def __repr__(self):
        return f"{self.connection_info}"

    def write(self, data: bytes) -> None:
        self._ensure_connection()
        self._write(data)

    @abstractmethod
    def _write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, length: int) -> bytes:
        self._ensure_connection()
        return self._read(length)

    @abstractmethod
    def _read(self, length: int) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def reset_input_buffer(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

    def _ensure_connection(self) -> None:
        if not self.is_open:
            self.open()

    @property
    @abstractmethod
    def is_open(self) -> bool:
        raise NotImplementedError


class LANInterface(HardwareInterface):
    def __init__(self, ip_address: str):
        super().__init__(ip_address)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._is_open = False  # flag to check if the connection is open, not provided by socket
        self.buffer = bytearray()

    def _write(self, data: bytes):
        totalsent = 0
        while totalsent < len(data):
            sent = self.sock.send(data[totalsent:])
            if sent == 0:
                raise RuntimeError("socket connection broken")
            totalsent = totalsent + sent

    def _read_sock_into_buffer(self):
        chunks = bytearray()
        bytes_recd = 0
        chunk = b''
        while b'\r' not in chunk:
            chunk = self.sock.recv(4096)
            if chunk == b'':
                raise RuntimeError("socket connection broken")
            chunks.extend(chunk)
            bytes_recd = bytes_recd + len(chunk)
        self.buffer += chunks

    def _read(self, length: int) -> bytes:
        if len(self.buffer) < length:
            self._read_sock_into_buffer()
        data = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return bytes(data)

    def reset_input_buffer(self) -> None:
        self.buffer = bytearray()

    def open(self) -> None:
        self.sock.connect((self.connection_info, 10001))
        self._is_open = True

    def close(self) -> None:
        self.sock.close()
        self._is_open = False

    @property
    def is_open(self) -> bool:
        return self._is_open


class USBInterface(HardwareInterface):

    def __init__(self, com_port: str):
        super().__init__(com_port)
        self.ser = serial.Serial(baudrate=115200, timeout=1, rtscts=False, dsrdtr=False)
        self.ser.port = com_port

    def _write(self, data: bytes) -> None:
        self.ser.write(data)

    def _read(self, length: int) -> bytes:
        return self.ser.read(length)

    def reset_input_buffer(self) -> None:
        self._ensure_connection()
        self.ser.reset_input_buffer()

    def open(self):
        try:
            self.ser.open()
        except serial.SerialException:
            raise ProbeConnectionError(f"Could not open {self.connection_info}. Is the power supply connected?")

    def close(self) -> None:
        self.ser.close()

    @property
    def is_open(self) -> bool:
        return self.ser.is_open
