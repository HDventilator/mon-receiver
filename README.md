# HDVent - Monitor - Receiver
This is the component that runs on the monitoring-raspeberrypi to receive data
from the arduino-controller, to feed it into influxdb for later display.

The receiver will:
* look for a usable serial port and open it
* try to maintain a readable serial port at all times
* read from the port and attempt to parse the data passed
* attempt to maintain a connection to the systems influxdb-server
* feed the data received from serial-port into influx.

For details on the protocol, look at the rough ![spec](https://github.com/HDventilator/mon-protocol/).

## Installing and running

### Development
For development, a `virtualenv`, and running from the source is probably easiest:
```
python3 -m venv venv/
source venv/bin/activate
pip install -r requirements.txt
python3 -m receiver # to start receiver/__main__.py
```

### Installing
The package also contains a `setup.py` to install the package using pip:
```
pip install git+https://github.com/HDventilator/mon-receiver.git@master
python3 -m receiver
```
A systemd-service file can be found in the ![OS](https://github.com/HDventilator/mon-os-image) repo.

## Development tasks
### Update dependencies
Dependencies are declared in `requirements.in` and locked to `requirements.txt` (which can be used by `pip`) using `pip-tools`. Add all dependencies you need to `requirements.in`, then use `pip-compile requirements.in` to compile it to a new `requirements.txt`. To update all dependencies, use `pip-compile -U requirements.in`
