import re
from abc import ABCMeta, abstractmethod

import serial
import serial.tools.list_ports

from pmk_probes._errors import ProbeConnectionError


class HardwareInterface(metaclass=ABCMeta):

    def __init__(self, connection_info: dict[str, str]):
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



class SerialInterface(HardwareInterface):

    def __init__(self, port: str):
        pattern = re.compile(r'://([^:/]+):')
        match = pattern.search(port)
        super().__init__({"ip_address": match.group(1)}) if match else super().__init__({"com_port": port})
        kwargs = {"baudrate": 115200, "timeout": 1, "rtscts": False, "dsrdtr": False, "do_not_open": True}
        self.ser = serial.serial_for_url(url=port, **kwargs)

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
            raise ProbeConnectionError(f"Could not open power supply at {self.connection_info}. Is the power supply connected?")

    def close(self) -> None:
        self.ser.close()

    @property
    def is_open(self) -> bool:
        return self.ser.is_open

class EchoInterface(HardwareInterface):

    def _write(self, data: bytes) -> None:
        pass

    def _read(self, length: int) -> bytes:
        pass

    def reset_input_buffer(self) -> None:
        pass

    @property
    def is_open(self) -> bool:
        return True
