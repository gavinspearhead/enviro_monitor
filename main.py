#!/usr/bin/env python3
import datetime
import os
import time
import logging
import argparse
import subprocess

import pymongo
import pytz as pytz

from fifo import fifo
from enviroplus.noise import Noise
from bme280 import BME280
from enviroplus import gas
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError, ChecksumMismatchError, SerialTimeoutError
from mongo_connector import MongoConnector
from config import config
import ST7735
from fonts.ttf import RobotoMedium as UserFont
import pytz
from pytz import timezone
from astral.geocoder import database, lookup
from astral.sun import sun

import os
import time
import numpy
import colorsys
import datetime

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


def calculate_y_pos(x, centre):
    """Calculates the y-coordinate on a parabolic curve, given x."""
    centre = 80
    y = 1 / centre * (x - centre) ** 2

    return int(y)


def circle_coordinates(x, y, radius):
    """Calculates the bounds of a circle, given centre and radius."""

    x1 = x - radius  # Left
    x2 = x + radius  # Right
    y1 = y - radius  # Bottom
    y2 = y + radius  # Top

    return (x1, y1, x2, y2)


def map_colour(x, centre, start_hue, end_hue, day):
    """Given an x coordinate and a centre point, a start and end hue (in degrees),
       and a Boolean for day or night (day is True, night False), calculate a colour
       hue representing the 'colour' of that time of day."""

    start_hue /= 360  # Rescale to between 0 and 1
    end_hue /= 360

    sat = 1.0

    # Dim the brightness as you move from the centre to the edges
    val = 1 - (abs(centre - x) / (2 * centre))

    # Ramp up towards centre, then back down
    if x > centre:
        x = (2 * centre) - x

    # Calculate the hue
    hue = start_hue + ((x / centre) * (end_hue - start_hue))

    # At night, move towards purple/blue hues and reverse dimming
    if not day:
        hue = 1 - hue
        val = 1 - val

    r, g, b = [int(c * 255) for c in colorsys.hsv_to_rgb(hue, sat, val)]

    return r, g, b


def x_from_sun_moon_time(progress, period, x_range):
    """Recalculate/rescale an amount of progress through a time period."""
    x = int((progress / period) * x_range)
    return x


def sun_moon_time(city_name, time_zone):
    """Calculate the progress through the current sun/moon period (i.e day or
       night) from the last sunrise or sunset, given a datetime object 't'."""

    city = lookup(city_name, database())

    # Datetime objects for yesterday, today, tomorrow
    utc = pytz.utc
    utc_dt = datetime.datetime.now(tz=utc)
    local_dt = utc_dt.astimezone(pytz.timezone(time_zone))
    today = local_dt.date()
    yesterday = today - datetime.timedelta(1)
    tomorrow = today + datetime.timedelta(1)

    # Sun objects for yesterday, today, tomorrow
    sun_yesterday = sun(city.observer, date=yesterday)
    sun_today = sun(city.observer, date=today)
    sun_tomorrow = sun(city.observer, date=tomorrow)

    # Work out sunset yesterday, sunrise/sunset today, and sunrise tomorrow
    sunset_yesterday = sun_yesterday["sunset"]
    sunrise_today = sun_today["sunrise"]
    sunset_today = sun_today["sunset"]
    sunrise_tomorrow = sun_tomorrow["sunrise"]

    # Work out lengths of day or night period and progress through period
    if sunrise_today < local_dt < sunset_today:
        day = True
        period = sunset_today - sunrise_today
        # mid = sunrise_today + (period / 2)
        progress = local_dt - sunrise_today

    elif local_dt > sunset_today:
        day = False
        period = sunrise_tomorrow - sunset_today
        # mid = sunset_today + (period / 2)
        progress = local_dt - sunset_today

    else:
        day = False
        period = sunrise_today - sunset_yesterday
        # mid = sunset_yesterday + (period / 2)
        progress = local_dt - sunset_yesterday

    # Convert time deltas to seconds
    progress = progress.total_seconds()
    period = period.total_seconds()

    return progress, period, day, local_dt


def overlay_text(img, position, text, font, align_right=False, rectangle=False):
    draw = ImageDraw.Draw(img)
    w, h = font.getsize(text)
    if align_right:
        x, y = position
        x -= w
        position = (x, y)
    if rectangle:
        x += 1
        y += 1
        position = (x, y)
        border = 1
        rect = (x - border, y, x + w, y + h + border)
        rect_img = Image.new('RGBA', (WIDTH, HEIGHT), color=(0, 0, 0, 0))
        rect_draw = ImageDraw.Draw(rect_img)
        rect_draw.rectangle(rect, (255, 255, 255))
        rect_draw.text(position, text, font=font, fill=(0, 0, 0, 0))
        img = Image.alpha_composite(img, rect_img)
    else:
        draw.text(position, text, font=font, fill=(255, 255, 255))
    return img


def draw_background(progress, period, day):
    """Given an amount of progress through the day or night, draw the
       background colour and overlay a blurred sun/moon."""

    # x-coordinate for sun/moon
    x = x_from_sun_moon_time(progress, period, WIDTH)

    # If it's day, then move right to left
    if day:
        x = WIDTH - x

    # Calculate position on sun/moon's curve
    centre = WIDTH / 2
    y = calculate_y_pos(x, centre)

    # Background colour
    background = map_colour(x, 80, mid_hue, day_hue, day)

    # New image for background colour
    img = Image.new('RGBA', (WIDTH, HEIGHT), color=background)
    # draw = ImageDraw.Draw(img)

    # New image for sun/moon overlay
    overlay = Image.new('RGBA', (WIDTH, HEIGHT), color=(0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)

    # Draw the sun/moon
    circle = circle_coordinates(x, y, sun_radius)
    overlay_draw.ellipse(circle, fill=(200, 200, 50, opacity))

    # Overlay the sun/moon on the background as an alpha matte
    composite = Image.alpha_composite(img, overlay).filter(ImageFilter.GaussianBlur(radius=blur))

    return composite


class EnviroCollector:
    def __init__(self, size=5):
        bus = SMBus(1)
        self._bme280 = BME280(i2c_dev=bus)
        self._pms5003 = PMS5003()
        self._noise = Noise()

        self.temperature = fifo(size)
        self.pressure = fifo(size)
        self.humidity = fifo(size)
        self.oxidising = fifo(size)
        self.reducing = fifo(size)
        self.nh3 = fifo(size)
        self.lux = fifo(size)
        self.proximity = fifo(size)
        self.pm1 = fifo(size)
        self.pm25 = fifo(size)
        self.pm10 = fifo(size)
        self.noise_high = fifo(size)
        self.noise_mid = fifo(size)
        self.noise_low = fifo(size)

    # Sometimes the sensors can't be read. Resetting the i2c
    def reset_i2c(self):
        subprocess.run(['i2cdetect', '-y', '1'])
        time.sleep(2)

    # Get the temperature of the CPU for compensation
    def get_cpu_temperature(self):
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = f.read()
            temp = int(temp) / 1000.0
        return temp

    def get_temperature(self, factor):
        """Get temperature from the weather sensor"""
        # Tuning factor for compensation. Decrease this number to adjust the
        # temperature down, and increase to adjust up
        raw_temp = self._bme280.get_temperature()

        if factor:
            cpu_temps = [self.get_cpu_temperature()] * 5
            cpu_temp = self.get_cpu_temperature()
            # Smooth out with some averaging to decrease jitter
            cpu_temps = cpu_temps[1:] + [cpu_temp]
            avg_cpu_temp = sum(cpu_temps) / float(len(cpu_temps))
            _temperature = raw_temp - ((avg_cpu_temp - raw_temp) / factor)
        else:
            _temperature = raw_temp

        self.temperature.add(_temperature)  # Set to a given value

    def get_pressure(self):
        """Get pressure from the weather sensor"""
        try:
            _pressure = self._bme280.get_pressure()
            self.pressure.add(_pressure)
        except IOError:
            logging.error("Could not get pressure readings. Resetting i2c.")
            self.reset_i2c()

    def get_humidity(self):
        """Get humidity from the weather sensor"""
        try:
            _humidity = self._bme280.get_humidity()
            self.humidity.add(_humidity)
        except IOError:
            logging.error("Could not get humidity readings. Resetting i2c.")
            self.reset_i2c()

    def get_gas(self):
        """Get all gas readings"""
        try:
            readings = gas.read_all()
            self.oxidising.add(readings.oxidising)
            self.reducing.add(readings.reducing)
            self.nh3.add(readings.nh3)
        except IOError:
            logging.error("Could not get gas readings. Resetting i2c.")
            self.reset_i2c()

    def get_light(self):
        """Get all light readings"""
        try:
            _lux = ltr559.get_lux()
            _prox = ltr559.get_proximity()

            self.lux.add(_lux)
            self.proximity.add(_prox)
        except IOError:
            logging.error("Could not get lux and proximity readings. Resetting i2c.")
            self.reset_i2c()

    def get_particulates(self):
        """Get the particulate matter readings"""
        try:
            pms_data = self._pms5003.read()
        except (pmsReadTimeoutError, SerialTimeoutError) as e:
            logging.warning("Failed to read PMS5003 {}").format(e)
            self.reset_i2c()
        except ChecksumMismatchError as e:
            logging.warning("Failed to read PMS5003 {}".format(e))
            self.reset_i2c()
        except IOError:
            logging.error("Could not get particulate matter readings. Resetting i2c.")
            self.reset_i2c()
        else:
            self.pm1.add(pms_data.pm_ug_per_m3(1.0))
            self.pm25.add(pms_data.pm_ug_per_m3(2.5))
            self.pm10.add(pms_data.pm_ug_per_m3(10))

    def get_noise(self):
        try:
            low, mid, high, amp = self._noise.get_noise_profile()
            self.noise_high.add(high)
            self.noise_mid.add(mid)
            self.noise_low.add(low)
        except Exception:
            logging.error("Could not get noise readings.")

    def collect_all_data(self):
        """Collects all the data currently set"""
        sensor_data = dict()
        sensor_data['temperature'] = self.temperature.avg()
        sensor_data['humidity'] = self.humidity.avg()
        sensor_data['pressure'] = self.pressure.avg()
        sensor_data['oxidising'] = self.oxidising.avg()
        sensor_data['reducing'] = self.reducing.avg()
        sensor_data['nh3'] = self.nh3.avg()
        sensor_data['lux'] = self.lux.avg()
        sensor_data['proximity'] = self.proximity.avg()
        sensor_data['pm1'] = self.pm1.avg()
        sensor_data['pm25'] = self.pm25.avg()
        sensor_data['pm10'] = self.pm10.avg()
        sensor_data['noise_low'] = self.noise_low.avg()
        sensor_data['noise_mid'] = self.noise_mid.avg()
        sensor_data['noise_high'] = self.noise_high.avg()
        sensor_data['timestamp'] = datetime.datetime.now(pytz.UTC)
        return sensor_data

    def update_all(self):
        self.get_temperature(args.factor)
        self.get_pressure()
        self.get_humidity()
        self.get_light()
        self.get_gas()
        self.get_noise()
        self.get_particulates()


#
# def get_serial_number():
#     """Get Raspberry Pi serial number to use as LUFTDATEN_SENSOR_UID"""
#     with open('/proc/cpuinfo', 'r') as f:
#         for line in f:
#             if line[0:6] == 'Serial':
#                 return str(line.split(":")[1].strip())
#
# #
def str_to_bool(value):
    if value.lower() in {'false', 'f', '0', 'no', 'n'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y'}:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))


if __name__ == '__main__':
    timeout = 1
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

    # Initialise the LCD
    disp = ST7735.ST7735(
        port=0,
        cs=1,
        dc=9,
        backlight=12,
        rotation=270,
        spi_speed_hz=10000000
    )

    city_name = "Amsterdam"
    time_zone = "Europe/Amsterdam"
    font_sm = ImageFont.truetype(UserFont, 12)
    font_lg = ImageFont.truetype(UserFont, 14)

    disp.begin()
    margin = 3

    WIDTH = disp.width
    HEIGHT = disp.height
    blur = 50
    opacity = 125

    mid_hue = 0
    day_hue = 25

    sun_radius = 50

    if args.debug:
        DEBUG = True

    if args.timeout:
        timeout = args.timeout
        logging.info("Logging every {} seconds".format(args.timeout))

    if args.factor:
        logging.info(
            "Using compensating algorithm (factor={}) to account for heat leakage from Raspberry Pi board".format(
                args.factor))

    mc = MongoConnector(config).get_collection()
    ec = EnviroCollector(timeout * 2)
    now1 = datetime.datetime.now(pytz.UTC)

    while True:
        ec.update_all()

        now2 = datetime.datetime.now(pytz.UTC) - now1
        remaining_time = args.timeout - (now2.seconds + (now2.microseconds / 1000000))
        if remaining_time <= 0:
            try:
                now1 = datetime.datetime.now(pytz.UTC)
                data = ec.collect_all_data()
                mc.insert_one(data)
                progress, period, day, local_dt = sun_moon_time(city_name, time_zone)
                time_string = local_dt.strftime("%H:%M")

                temp_string = "{:.0f}°C".format(data['temperature'])
                humidity_string = "{:.0f}%".format(data['humidity'])
                pressure_string = "{}".format(int(data['pressure']))
                background = draw_background(progress, period, day)

                img = overlay_text(background, (0 + margin, 0 + margin), time_string, font_lg)
                img = overlay_text(img, (WIDTH - margin, 0 + margin), date_string, font_lg, align_right=True)
                img = overlay_text(img, (68, 18), temp_string, font_lg, align_right=True)
                img = overlay_text(img, (68, 48), humidity_string, font_lg, align_right=True)
                img = overlay_text(img, (WIDTH - margin, 48), pressure_string, font_lg, align_right=True)

                disp.display(img)


            except pymongo.errors.ServerSelectionTimeoutError():
                logging.error("Can't connect to Mongo - drop reading")
        time.sleep(.98)
        if DEBUG:
            logging.info('Sensor data: {}'.format(ec.collect_all_data()))

        # if remaining_time > 0:
        #     logging.debug("sleeping :{}".format(remaining_time))
        #     time.sleep(remaining_time)
