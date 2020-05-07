from receiver import receiver

class Printer(receiver.ProtocolListener):
    def add_packet(self, packet):
        print(packet)

serial_reader = receiver.SerialReader()
proto_parser = receiver.ProtocolParser()

printer = Printer()

serial_reader.listener = proto_parser
proto_parser.listener = printer

serial_reader.run()
