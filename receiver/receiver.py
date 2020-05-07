import logging
logging.basicConfig(level=logging.DEBUG)

from cobs import cobs
from influxdb import InfluxDBClient
import struct
from glob import glob
from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE
import time
from binascii import crc32
from threading import Thread
from queue import Queue
from datetime import datetime
logging.getLogger("urllib3").setLevel(logging.INFO)

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
            port = Serial(device, 115200, EIGHTBITS, PARITY_NONE, STOPBITS_ONE, timeout=4)
            data = port.read(4)  # read more than the typical first 2-byte glitches
        except Exception:
            logging.debug("Couldn’t probe serial port %s, see stacktrace:", device, exc_info=True)
            return
        finally:
            try:
                port.close()
            except:
                return

        return len(data) == 4

    def _find_serialport(self):
        logging.info("Searching for usable serial port")
        while self.device is None:
            devices = glob("/dev/ttyUSB*")
            # try in order of biggest port-number
            devices.sort(reverse=True)

            if not devices:
                time.sleep(1)
                continue

            for device in devices:
                logging.debug("trying device %s", device)
                if self._try_device(device):
                    try:
                        self.device = device
                        self.port = Serial(self.device, 115200, EIGHTBITS, PARITY_NONE, STOPBITS_ONE, timeout=1)
                        logging.info("Using serial port %s", self.device)
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

    def _clear_serialport(self):
        try:
            self.port.close()
        except Exception:
            pass

        self.port = None
        self.device = None

    def _read_from_serialport(self):
        if not self.port:
            return

        while True:
            try:
                data = self.port.read_until(b"\x00")
            except:
                logging.debug("Could not read data from serial port, see stacktrace:", exc_info=True)
                self._clear_serialport()
                return

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

    def run(self):
        while True:
            self._find_serialport()
            self._read_from_serialport()


class ProtocolListener:
    def add_packet(self, packet):
        raise NotImplementedError()

class ProtocolParser(SerialListener):
    def __init__(self):
        self.buffer = b""
        self.listener = None

    def add_data(self, raw_data):
        self.buffer += raw_data
        if b"\x00" in self.buffer:
            self._parse_data()

    def _unpack_data(self, data):
        try:
            name, value, crc = struct.unpack("<6sfI", data)
            ascii_name = name.decode('ASCII')
        except struct.error:
            logging.debug("Received data was not well-formed")
            raise ValueError("Received data was not well-formed")
        except Exception as exc:
            logging.error("Unexpected exception occurred, see stacktrace:", exc_info=True)
            raise exc

        return {
            'name': ascii_name,
            'value': value,
            'crc': crc
        }

    def _check_crc(self, packed_data, parsed_data):
        return parsed_data['crc'] == crc32(packed_data[:10])

    def _parse_data(self):
        if not b"\x00" in self.buffer:
            return

        packet, self.buffer = self.buffer.split(b"\x00")

        try:
            data = cobs.decode(packet)
        except cobs.DecodeError:
            logging.debug("Received data was not COBS-decodable")
            return
        except Exception:
            logging.error("Unexpected exception occurred, see stacktrace", exc_info=True)
            return

        try:
            parsed_data = self._unpack_data(data)
        except Exception:
            logging.error("Unexpected exception occurred, see stacktrace", exc_info=True)
            return

        if not parsed_data:
            return

        if not self._check_crc(data, parsed_data):
            logging.debug("crc for received packet did not match — discarding")
            return

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

class InfluxWriter(ProtocolListener):
    def __init__(self):
        self.client = None
        self.queue = Queue(100)

        self.connect = True
        self._reconnect_thread = None

        self.write = True
        self._writer_thread = Thread(target=self._write)
        self._writer_thread.start()

    def run(self):
        if self._reconnect_thread and self._reconnect_thread.isAlive():
            return

        self.connect = True
        self._reconnect_thread = Thread(target=self._maintain_connection)
        self._reconnect_thread.start()

    def _try_connect(self):
        try:
            self.client.close()
        except Exception:
            pass

        try:
            self.client = InfluxDBClient(database="hdvent_data")
        except:
            logging.warning("Could not connect to infux …")

    def _maintain_connection(self):
        while self.connect:
            try:
                self.client.ping()
            except Exception:
                self._try_connect()
            time.sleep(1)

    def _write(self):
        points = []
        while self.write:
            item = self.queue.get()
            points.append(item)
            if len(points) >= 100:
                try:
                    self.client.write_points(points)
                    points = []
                except:
                    logging.warning("Couldn’t write points to influx")

            if len(points) > 500:
                points = []
                logging.warning("point-buffer too big, dropping data-points")

    def add_packet(self, packet):
        try:
            self.queue.put_nowait({
                "measurement": packet["name"],
                "time": datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                "fields": {
                    "value": packet["value"]
                    }
                })
        except Exception as exc:
            logging.warning("Couldnt add packet to queue")
