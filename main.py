#!/usr/bin/env python3
import os
import time
import logging
import argparse
import subprocess
from fifo import fifo

from bme280 import BME280
from enviroplus import gas
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError
from pymongo import MongoClient

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

try:
    # Transitional fix for breaking change in LTR559
    from ltr559 import LTR559

    ltr559 = LTR559()
except ImportError:
    import ltr559

config = {
    'hostname': '192.168.1788.21',
    'port': 27017,
    "database": "enviro",
    "collection": "enviro",
    "username": "enviro",
    "password": "S2ytTULCBmEQYZrxF0sC",
    "auth_db": "enviro"
}


class MongoConnector:
    def __init__(self, config):
        self._config = config
        hostname = self._config['hostname'] if self._config['hostname'] != "" else None
        port = self._config['port'] if self._config['port'] != "" else None
        if 'username' in self._config and 'password' in self._config and \
                (self._config['username'] != '' and self._config['password'] != ''):
            self._mongo = MongoClient(username=self._config['username'], password=self._config['password'],
                                      authSource=self._config['auth_db'], host=hostname, port=port)
        else:
            self._mongo = MongoClient(host=hostname, port=port)
        self._db = self._mongo[self._config['database']]
        self._collection = self._db[self._config['collection']]

    def get_collection(self):
        return self._collection


logging.basicConfig(
    format='%(asctime)s.%(msecs)03d %(levelname)-8s %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("enviroplus_exporter.log"),
              logging.StreamHandler()],
    datefmt='%Y-%m-%d %H:%M:%S')

logging.info("""enviroplus_exporter.py - Expose readings from the Enviro+ sensor by Pimoroni in Prometheus format

Press Ctrl+C to exit!

""")

DEBUG = os.getenv('DEBUG', 'false') == 'true'

bus = SMBus(1)
bme280 = BME280(i2c_dev=bus)
pms5003 = PMS5003()

temperature = fifo()
pressure = fifo()
humidity = fifo()
oxidising = fifo()
reducing = fifo()
nh3 = fifo()
lux = fifo()
proximity = fifo()
pm1 = fifo()
pm25 = fifo()
pm10 = fifo()


#
#
# TEMPERATURE = Gauge('temperature', 'Temperature measured (*C)')
# PRESSURE = Gauge('pressure', 'Pressure measured (hPa)')
# HUMIDITY = Gauge('humidity', 'Relative humidity measured (%)')
# OXIDISING = Gauge('oxidising', 'Mostly nitrogen dioxide but could include NO and Hydrogen (Ohms)')
# REDUCING = Gauge('reducing',
#                  'Mostly carbon monoxide but could include H2S, Ammonia, Ethanol, Hydrogen, Methane, Propane, Iso-butane (Ohms)')
# NH3 = Gauge('NH3', 'mostly Ammonia but could also include Hydrogen, Ethanol, Propane, Iso-butane (Ohms)')
# LUX = Gauge('lux', 'current ambient light level (lux)')
# PROXIMITY = Gauge('proximity', 'proximity, with larger numbers being closer proximity and vice versa')
# PM1 = Gauge('PM1', 'Particulate Matter of diameter less than 1 micron. Measured in micrograms per cubic metre (ug/m3)')
# PM25 = Gauge('PM25',
#              'Particulate Matter of diameter less than 2.5 microns. Measured in micrograms per cubic metre (ug/m3)')
# PM10 = Gauge('PM10',
#              'Particulate Matter of diameter less than 10 microns. Measured in micrograms per cubic metre (ug/m3)')
# #
# OXIDISING_HIST = Histogram('oxidising_measurements', 'Histogram of oxidising measurements', buckets=(
# 0, 10000, 15000, 20000, 25000, 30000, 35000, 40000, 45000, 50000, 55000, 60000, 65000, 70000, 75000, 80000, 85000,
# 90000, 100000))
# REDUCING_HIST = Histogram('reducing_measurements', 'Histogram of reducing measurements', buckets=(
# 0, 100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000, 900000, 1000000, 1100000, 1200000, 1300000, 1400000,
# 1500000))
# NH3_HIST = Histogram('nh3_measurements', 'Histogram of nh3 measurements', buckets=(
# 0, 10000, 110000, 210000, 310000, 410000, 510000, 610000, 710000, 810000, 910000, 1010000, 1110000, 1210000, 1310000,
# 1410000, 1510000, 1610000, 1710000, 1810000, 1910000, 2000000))
#
# PM1_HIST = Histogram('pm1_measurements', 'Histogram of Particulate Matter of diameter less than 1 micron measurements',
#                      buckets=(0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100))
# PM25_HIST = Histogram('pm25_measurements',
#                       'Histogram of Particulate Matter of diameter less than 2.5 micron measurements',
#                       buckets=(0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100))
# PM10_HIST = Histogram('pm10_measurements',
#                       'Histogram of Particulate Matter of diameter less than 10 micron measurements',
#                       buckets=(0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100))


# Sometimes the sensors can't be read. Resetting the i2c
def reset_i2c():
    subprocess.run(['i2cdetect', '-y', '1'])
    time.sleep(2)


# Get the temperature of the CPU for compensation
def get_cpu_temperature():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = f.read()
        temp = int(temp) / 1000.0
    return temp


def get_temperature(factor):
    """Get temperature from the weather sensor"""
    # Tuning factor for compensation. Decrease this number to adjust the
    # temperature down, and increase to adjust up
    raw_temp = bme280.get_temperature()

    if factor:
        cpu_temps = [get_cpu_temperature()] * 5
        cpu_temp = get_cpu_temperature()
        # Smooth out with some averaging to decrease jitter
        cpu_temps = cpu_temps[1:] + [cpu_temp]
        avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
        _temperature = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
    else:
        _temperature = raw_temp

    temperature.add(_temperature)  # Set to a given value


def get_pressure():
    """Get pressure from the weather sensor"""
    try:
        _pressure = bme280.get_pressure()
        pressure.add(_pressure)
    except IOError:
        logging.error("Could not get pressure readings. Resetting i2c.")
        reset_i2c()


def get_humidity():
    """Get humidity from the weather sensor"""
    try:
        _humidity = bme280.get_humidity()
        humidity.add(_humidity)
    except IOError:
        logging.error("Could not get humidity readings. Resetting i2c.")
        reset_i2c()


def get_gas():
    """Get all gas readings"""
    try:
        readings = gas.read_all()

        oxidising.add(readings.oxidising)
        # OXIDISING_HIST.observe(readings.oxidising)

        reducing.add(readings.reducing)
        # REDUCING_HIST.observe(readings.reducing)

        nh3.add(readings.nh3)
        # NH3_HIST.observe(readings.nh3)
    except IOError:
        logging.error("Could not get gas readings. Resetting i2c.")
        reset_i2c()


def get_light():
    """Get all light readings"""
    try:
        _lux = ltr559.get_lux()
        _prox = ltr559.get_proximity()

        lux.add(_lux)
        proximity.add(_prox)
    except IOError:
        logging.error("Could not get lux and proximity readings. Resetting i2c.")
        reset_i2c()


def get_particulates():
    """Get the particulate matter readings"""
    try:
        pms_data = pms5003.read()
    except pmsReadTimeoutError:
        logging.warning("Failed to read PMS5003")
    except IOError:
        logging.error("Could not get particulate matter readings. Resetting i2c.")
        reset_i2c()
    else:
        pm1.add(pms_data.pm_ug_per_m3(1.0))
        pm25.add(pms_data.pm_ug_per_m3(2.5))
        pm10.add(pms_data.pm_ug_per_m3(10))

        # PM1_HIST.observe(pms_data.pm_ug_per_m3(1.0))
        # PM25_HIST.observe(pms_data.pm_ug_per_m3(2.5) - pms_data.pm_ug_per_m3(1.0))
        # PM10_HIST.observe(pms_data.pm_ug_per_m3(10) - pms_data.pm_ug_per_m3(2.5))


def collect_all_data():
    """Collects all the data currently set"""
    sensor_data = {}
    sensor_data['temperature'] = temperature.avg()
    sensor_data['humidity'] = humidity.avg()
    sensor_data['pressure'] = pressure.avg()
    sensor_data['oxidising'] = oxidising.avg()
    sensor_data['reducing'] = reducing.avg()
    sensor_data['nh3'] = nh3.avg()
    sensor_data['lux'] = lux.avg()
    sensor_data['proximity'] = proximity.avg()
    sensor_data['pm1'] = pm1.avg()
    sensor_data['pm25'] = pm25.avg()
    sensor_data['pm10'] = pm10.avg()
    return sensor_data


def get_serial_number():
    """Get Raspberry Pi serial number to use as LUFTDATEN_SENSOR_UID"""
    with open('/proc/cpuinfo', 'r') as f:
        for line in f:
            if line[0:6] == 'Serial':
                return str(line.split(":")[1].strip())


def str_to_bool(value):
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", metavar='DEBUG', type=str_to_bool,
                        help="Turns on more verbose logging, showing sensor output and post responses [default: false]")
    parser.add_argument("-f", "--factor", metavar='FACTOR', type=float, default=1.0,
                        help="The compensation factor to get better temperature results when the Enviro+ pHAT is too close to the Raspberry Pi board")

    args = parser.parse_args()

    # Start up the server to expose the metrics.
    # start_http_server(addr=args.bind, port=args.port)
    # Generate some requests.

    if args.debug:
        DEBUG = True

    if args.factor:
        logging.info(
            "Using compensating algorithm (factor={}) to account for heat leakage from Raspberry Pi board".format(
                args.factor))

    # logging.info("Listening on http://{}:{}".format(args.bind, args.port))

    mc = MongoConnector(config).get_collection()

    while True:
        get_temperature(args.factor)
        get_pressure()
        get_humidity()
        get_light()
        # if not args.enviro:
        get_gas()
        get_particulates()
        if DEBUG:
            logging.info('Sensor data: {}'.format(collect_all_data()))
        mc.insert_one(collect_all_data())
