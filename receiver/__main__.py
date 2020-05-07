from receiver import receiver

serial_reader = receiver.SerialReader()
proto_parser = receiver.ProtocolParser()
influx_writer = receiver.InfluxWriter()

serial_reader.listener = proto_parser
proto_parser.listener = influx_writer

influx_writer.run()
serial_reader.run()
