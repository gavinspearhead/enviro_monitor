#!/usr/bin/env python3
import datetime
import os
import time
import logging
import argparse
import subprocess

import pytz as pytz

from fifo import fifo
from enviroplus.noise import Noise
from bme280 import BME280
from enviroplus import gas

from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError
from mongo_connector import MongoConnector

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
    'hostname': '192.168.178.21',
    'port': 27017,
    "database": "enviro",
    "collection": "enviro",
    "username": "enviro",
    "password": "S2ytTULCBmEQYZrxF0sC",
    "auth_db": "enviro"
}

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
noise = Noise()

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
noise_high = fifo()
noise_mid = fifo()
noise_low = fifo()


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

        reducing.add(readings.reducing)

        nh3.add(readings.nh3)
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


def get_noise():
    try:
        low, mid, high, amp = noise.get_noise_profile()
        noise_high.add(high)
        noise_mid.add(mid)
        noise_low.add(low)
    except Exception:
        logging.error("Could not get noise readings.")


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
    sensor_data['noise_low'] = noise_low.avg()
    sensor_data['noise_mid'] = noise_mid.avg()
    sensor_data['noise_high'] = noise_high.avg()
    sensor_data['timestamp'] = datetime.datetime.now(pytz.UTC)
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
    parser.add_argument("-f", "--factor", metavar='FACTOR', type=float, default=None,
                        help="The compensation factor to get better temperature results when the Enviro+ pHAT is too close to the Raspberry Pi board")
    parser.add_argument('-t', '--timeout', metavar="TIMOUT", type=int, default=1, help='timeout between readings')
    args = parser.parse_args()

    # Start up the server to expose the metrics.
    # start_http_server(addr=args.bind, port=args.port)
    # Generate some requests.

    if args.debug:
        DEBUG = True

    if args.timeout:
        logging.info("Logging every {} seconds".format(args.timeout))

    if args.factor:
        logging.info(
            "Using compensating algorithm (factor={}) to account for heat leakage from Raspberry Pi board".format(
                args.factor))

    mc = MongoConnector(config).get_collection()

    while True:
        now1 = datetime.datetime.now(pytz.UTC)
        get_temperature(args.factor)
        get_pressure()
        get_humidity()
        get_light()
        # if not args.enviro:
        get_gas()
        get_noise()
        get_particulates()
        if DEBUG:
            logging.info('Sensor data: {}'.format(collect_all_data()))
        mc.insert_one(collect_all_data())
        now2 = datetime.datetime.now(pytz.UTC) - now1
        remaining_time = args.timeout - (now2.seconds + (now2.microseconds / 1000000))

        if remaining_time > 0:
            logging.debug("sleeping :{}".format(remaining_time))
            time.sleep(remaining_time)
