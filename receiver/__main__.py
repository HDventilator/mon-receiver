import logging
logging.basicConfig(level=logging.DEBUG)

from receiver import receiver

class Printer(receiver.ProtocolListener):
    def add_packet(self, packet):
        print("Received packet", packet)

serial_reader = receiver.SerialReader()
proto_parser = receiver.ProtocolParser()

printer = Printer()

serial_reader.listener = proto_parser
proto_parser.listener = printer

serial_reader._find_serialport()
serial_reader._read_from_serialport()

