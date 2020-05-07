"""
Module containing all encapsulated functionality for a working serial-port ⇒
influxdb path
"""

# pylint: disable=bare-except,broad-except,too-few-public-methods,no-self-use

import logging
import struct
from glob import glob
import time
from binascii import crc32
from threading import Thread
from queue import Queue
from datetime import datetime
from serial import Serial, EIGHTBITS, PARITY_NONE, STOPBITS_ONE
from cobs import cobs
from influxdb import InfluxDBClient

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.INFO)


class SerialListener:
    """
    Interface to be implemented when someone wants to receive serial packets
    """

    def add_data(self, raw_data):
        """
        Receive new raw data from SerialReader
        """
        raise NotImplementedError()


class SerialReader:
    """
    Finds and Maintains connection to a serial-port, as well as reads from it,
    notifying a SerialListener of new data when available
    """

    def __init__(self):
        self.device = None
        self.port = None
        self.listener = None

    def _try_device(self, device):
        """
        Attempts to open and read from a serial device, returning whether the
        device yielded data. This is a good metric since a running controller
        should always yield data … often.
        """
        try:
            port = Serial(
                device, 115200, EIGHTBITS, PARITY_NONE, STOPBITS_ONE, timeout=4
            )
            data = port.read(4)  # read more than the typical first 2-byte glitches
        except Exception:
            logging.debug(
                "Couldn’t probe serial port %s, see stacktrace:", device, exc_info=True
            )
            try:
                port.close()
            except:
                pass
            return False

        try:
            port.close()
        except:
            return False

        return len(data) == 4

    def _find_serialport(self):
        """
        Searches and attempts to open a usable serial port until one is found
        """
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
                        self.port = Serial(
                            self.device,
                            115200,
                            EIGHTBITS,
                            PARITY_NONE,
                            STOPBITS_ONE,
                            timeout=1,
                        )
                        logging.info("Using serial port %s", self.device)
                        break
                    except Exception:
                        self.port = None
                        self.device = None
                        logging.debug(
                            "Could not open tested-good serial port %s, see stacktrace:",
                            exc_info=True,
                        )
                        time.sleep(1)
                        continue

            if self.port and self.device:
                break

            time.sleep(1)

    def _clear_serialport(self):
        """
        Attempts to close and remove a currently used serial-port
        """
        try:
            self.port.close()
        except Exception:
            pass

        self.port = None
        self.device = None

    def _read_from_serialport(self):
        """
        Read from current serial port until something goes wrong. This chunks
        into packets delimited by \x00
        """
        if not self.port:
            return

        while True:
            try:
                data = self.port.read_until(b"\x00")
            except:
                logging.debug(
                    "Could not read data from serial port, see stacktrace:",
                    exc_info=True,
                )
                self._clear_serialport()
                return

            self._notify(data)

    def _notify(self, data):
        """
        Notifies a SerialListener of new data, if set
        """
        if not self.listener:
            return

        if not isinstance(self.listener, SerialListener):
            logging.warning(
                "Registered SerialListener is not a SerialListener ... not forwarding data"
            )

        try:
            self.listener.add_data(data)
        except Exception:
            logging.info(
                "SerialListener could not process data, see stacktrace:", exc_info=True
            )

    def run(self):
        """
        runner around serial reading, which should run as long as the program
        needs to operate
        """
        while True:
            self._find_serialport()
            self._read_from_serialport()


class ProtocolListener:
    """
    Interface to be implemented if someone wants to received parsed protocol
    packets
    """

    def add_packet(self, packet):
        """
        Implement to receive a parsed packet from ProtocolParser
        """
        raise NotImplementedError()


class ProtocolParser(SerialListener):
    """
    decodes protocol: cobs decode, struct unpack and crc32 check
    """

    def __init__(self):
        self.buffer = b""
        self.listener = None

    def add_data(self, raw_data):
        """
        Buffers received data as a SerialListener. Parses data as soon as it
        looks like a complete packet is received
        """
        self.buffer += raw_data
        if b"\x00" in self.buffer:
            self._parse_data()

    def _unpack_data(self, data):
        """
        Attempts to unpack the packed/serialized struct
        """
        try:
            name, value, crc = struct.unpack("<6sfI", data)
            ascii_name = name.decode("ASCII")
        except struct.error:
            logging.debug("Received data was not well-formed")
            raise ValueError("Received data was not well-formed")
        except Exception as exc:
            logging.error(
                "Unexpected exception occurred, see stacktrace:", exc_info=True
            )
            raise exc

        return {"name": ascii_name, "value": value, "crc": crc}

    def _check_crc(self, packed_data, parsed_data):
        """
        Checks the checksum of a parsed packet against its name and value
        """
        return parsed_data["crc"] == crc32(packed_data[:10])

    def _parse_data(self):
        """
        Complete parsing run of current buffer, including cobs, unpack, crc-check
        """
        if b"\x00" not in self.buffer:
            return

        packet, self.buffer = self.buffer.split(b"\x00")

        try:
            data = cobs.decode(packet)
        except cobs.DecodeError:
            logging.debug("Received data was not COBS-decodable")
            return
        except Exception:
            logging.error(
                "Unexpected exception occurred, see stacktrace", exc_info=True
            )
            return

        try:
            parsed_data = self._unpack_data(data)
        except Exception:
            logging.error(
                "Unexpected exception occurred, see stacktrace", exc_info=True
            )
            return

        if not parsed_data:
            return

        if not self._check_crc(data, parsed_data):
            logging.debug("crc for received packet did not match — discarding")
            return

        self._notify(parsed_data)

    def _notify(self, data):
        """
        Notifies a ProtocolListener of a new packet if available
        """
        if not self.listener:
            return

        if not isinstance(self.listener, ProtocolListener):
            logging.warnin(
                "Registered ProtocolListener is not a ProtocolListener ... not forwarding data"
            )

        try:
            self.listener.add_packet(data)
        except Exception:
            logging.info(
                "ProtocolListener could not process packet, see stacktrace:",
                exc_info=True,
            )


class InfluxWriter(ProtocolListener):
    """
    Maintain a steady connection to influx and write received packets up there
    """

    def __init__(self):
        self.client = None
        self.queue = Queue(100)

        self.connect = True
        self._reconnect_thread = None

        self.write = True
        self._writer_thread = Thread(target=self._write)
        self._writer_thread.start()

    def run(self):
        """
        Start the initial- and reconnction maintaining thread
        """
        if self._reconnect_thread and self._reconnect_thread.isAlive():
            return

        self.connect = True
        self._reconnect_thread = Thread(target=self._maintain_connection)
        self._reconnect_thread.start()

    def _try_connect(self):
        """
        Attempts to close and reconnect the influx client
        """
        try:
            self.client.close()
        except Exception:
            pass

        try:
            self.client = InfluxDBClient(database="hdvent_data")
        except:
            logging.warning("Could not connect to infux …")

    def _maintain_connection(self):
        """
        method running in the _reconnect_thread, running until !self.connect,
        always pinging the DB and reconnecting f something goes wrong
        """
        while self.connect:
            try:
                self.client.ping()
            except Exception:
                self._try_connect()
            time.sleep(1)

    def _write(self):
        """
        manages the queue, running in the write-thread. read points from the
        queue until a local buffer is sufficiently full to issue an efficient
        batched write to influx.
        """
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
        """
        adds data from a packet to the queue, which is the n consumed by _write in its thread …
        """
        try:
            self.queue.put_nowait(
                {
                    "measurement": packet["name"],
                    "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                    "fields": {"value": packet["value"]},
                }
            )
        except Exception:
            logging.warning("Couldnt add packet to queue")
