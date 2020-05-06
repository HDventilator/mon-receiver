from cobs import cobs
from influxdb import InfluxDBClient
import struct
import logging
from glob import glob
from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE
import time
from enum import Enum

class SerialListener:
    def add_data(self, raw_data):
        raise NotImplementedError()

class SerialReader:
    def __init__(self):
        self.device = None
        self.port = None
        self.listener = None

    def _try_device(self, device):
        try:
            port = Serial(device, 115200, EIGHTBITS, PARITY_NONE, STOPBITS_ONE, timeout=1)
            data = port.read(4)  # read more than the typical first 2-byte glitches
        except Exception:
            logging.debug("Couldn’t probe serial port %s, see stacktrace:", device, exc_info=True)
        finally:
            try:
                port.close()
            except:
                logging.debug("Couldn’t close port %s after probing, see stacktrace:", device, exc_info=True)

        return len(data) == 4

    def _find_serialport(self):
        while self.device is None:
            devices = glob("/dev/ttyUSB*")
            # try in order of biggest port-number
            devices.sort(reverse=True)

            if not devices:
                time.sleep(1)
                continue

            for device in devices:
                if self._try_device(device):
                    try:
                        self.port = Serial(self.device, 115200, EIGHTBITS, PARITY_NONE, STOPBITS_ONE, timeout=1)
                        self.device = device
                        break
                    except Exception:
                        self.port = None
                        self.device = None
                        logging.debug("Could not open tested-good serial port %s, see stacktrace:", exc_info=True)
                        time.sleep(1)
                        continue

            if self.port and self.device:
                break

            time.sleep(1)

    def _read_from_serialport(self):
        if not self.port:
            return

        while True:
            try:
                data = self.port.read_until(expected=b"\x00")
            except:
                logging.debug("Could not read data from serial port, see stacktrace:", exc_info=True)
                break

            try:
                self._notify(data)

    def _notify(self, data):
        if not self.listener:
            return

        if not isinstance(self.listener, SerialListener):
            logging.warn("Registered SerialListener is not a SerialListener ... not forwarding data")

        try:
            self.listener.add_data(data)
        except Exception:
            logging.info("SerialListener could not process data, see stacktrace:", exc_info=True)

class ProtocolListener:
    def add_packet(self, packet):
        raise NotImplementedError()

class MonProtocol(SerialListener):
    def __init__(self):
        self.buffer = b""
        self.listener = None

    def add_data(self, raw_data):
        self.buffer += raw_data
        if b"\x00" in self.buffer:
            self._parse()

    def unpack_data(self, data):
        try:
            name, value, crc = struct.unpack("4sfI", data)
        except struct.error:
            logging.debug("Received data was not well-formed")
        except Exception:
            logging.error("Unexpected exception occurred, see stacktrace:", exc_info=True)

        return {
            'name': name.decode('ASCII'),
            'value': value,
            'crc': crc
        }

    def _parse_data(self):
        if not b"\x00" in self.buffer:
            return

        packet, self.buffer = self.buffer.split("\x00")

        try:
            data = cobs.decode(packet)
        except cobs.DecodeError:
            logging.debug("Received data was not COBS-decodable")
        except Exception:
            logging.error("Unexpected exception occurred, see stacktrace", exc_info=True)

        try:
            parsed_data = self.unpack_data(data)
        except Exception:
            logging.error("Unexpected exception occurred, see stacktrace", exc_info=True)

        self._notify(parsed_data)

    def _notify(self, data):
        if not self.listener:
            return

        if not isinstance(self.listener, ProtocolListener):
            logging.warn("Registered ProtocolListener is not a ProtocolListener ... not forwarding data")

        try:
            self.listener.add_packet(data)
        except Exception:
            logging.info("ProtocolListener could not process packet, see stacktrace:", exc_info=True)
