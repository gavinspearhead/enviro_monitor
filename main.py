#!/usr/bin/env python3
import logging
import argparse
import subprocess
import os
import threading
import time
import numpy
import colorsys
import datetime
import pytz
import pymongo.errors
import ST7735

from enviroplus.noise import Noise
from bme280 import BME280
from enviroplus import gas
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pms5003 import PMS5003, ReadTimeoutError as pmsReadTimeoutError, ChecksumMismatchError, SerialTimeoutError
from fonts.ttf import RobotoMedium as UserFont
from astral.geocoder import database, lookup
from astral.sun import sun

from fifo import fifo
from mongo_connector import MongoConnector
from config import config
from summarise import summarise_data

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
path = os.path.dirname(os.path.realpath(__file__))


def create_summary(months_retained=2):
    while True:
        summarise_data(months_retained)
        time.sleep(24 * 60 * 60)  # 1day


def str_to_bool(value):
    if value.lower() in {'false', 'f', '0', 'no', 'n', 'on'}:
        return False
    elif value.lower() in {'true', 't', '1', 'yes', 'y', 'off'}:
        return True
    raise ValueError('{} is not a valid boolean value'.format(value))


def calculate_y_pos(x, centre=80):
    """Calculates the y-coordinate on a parabolic curve, given x."""
    y = 1 / centre * (x - centre) ** 2
    return int(y)


def circle_coordinates(x, y, radius):
    """Calculates the bounds of a circle, given centre and radius."""
    x1 = x - radius  # Left
    x2 = x + radius  # Right
    y1 = y - radius  # Bottom
    y2 = y + radius  # Top
    return x1, y1, x2, y2


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


def sun_moon_time(city, time_zone):
    """Calculate the progress through the current sun/moon period (i.e day or
       night) from the last sunrise or sunset, given a datetime object 't'."""
    # Datetime objects for yesterday, today, tomorrow
    utc = pytz.utc
    utc_dt = datetime.datetime.now(tz=utc)
    local_dt = utc_dt.astimezone(pytz.timezone(time_zone))
    today = local_dt.date()
    yesterday = today - datetime.timedelta(days=1)
    tomorrow = today + datetime.timedelta(days=1)

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
        progress = local_dt - sunrise_today

    elif local_dt > sunset_today:
        day = False
        period = sunrise_tomorrow - sunset_today
        progress = local_dt - sunset_today

    else:
        day = False
        period = sunrise_today - sunset_yesterday
        progress = local_dt - sunset_yesterday

    # Convert time deltas to seconds
    progress = progress.total_seconds()
    period = period.total_seconds()

    return progress, period, day, local_dt


class EnviroCollector:
    def __init__(self, size=5):
        bus = SMBus(1)
        self._last_proximity = 0
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
    @staticmethod
    def reset_i2c():
        subprocess.run(['i2cdetect', '-y', '1'])
        time.sleep(2)

    # Get the temperature of the CPU for compensation
    @staticmethod
    def get_cpu_temperature():
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp = f.read()
            temp = int(temp) / 1000.0
        return temp

    def get_temperature(self, factor=None):
        """Get temperature from the weather sensor"""
        # Tuning factor for compensation. Decrease this number to adjust the
        # temperature down, and increase to adjust up
        try:
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
        except IOError:
            logging.error("Could not get pressure readings. Resetting i2c.")
            self.reset_i2c()

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
            self._last_proximity = _prox
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
            logging.warning("Failed to read PMS5003 {}".format(e))
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
        self.get_humidity(),
        self.get_pressure(),
        self.get_light(),
        self.get_gas(),
        self.get_noise(),
        self.get_particulates(),

    def get_last_proximity(self):
        return self._last_proximity


class Display:
    _font_sm = ImageFont.truetype(UserFont, 12)
    _font_lg = ImageFont.truetype(UserFont, 14)
    _blur = 50
    _opacity = 125
    _margin = 3
    _mid_hue = 0
    _day_hue = 25
    _sun_radius = 50
    _num_vals = 1000

    def __init__(self, city, timezone, path):
        self._city = lookup(city, database())
        self._timezone = timezone
        self._disp = ST7735.ST7735(port=0, cs=1, dc=9, backlight=12, rotation=270, spi_speed_hz=10000000)
        self._disp.begin()
        self._WIDTH = self._disp.width
        self._HEIGHT = self._disp.height
        self._path = path
        self._temp_icon = Image.open(f"{path}/icons/temperature.png")
        self._min_temp = None
        self._max_temp = None
        self._pressure_values = []
        self._time_values = []
        self._trend = "-"
        self.start_time = time.time()
        self._backlight = False
        self._black_img = Image.new('RGBA', (self._WIDTH, self._HEIGHT), color=(0, 0, 0, 0))

    @staticmethod
    def describe_pressure(pressure):
        """Convert pressure into barometer-type description."""
        if pressure < 970:
            description = "storm"
        elif 970 <= pressure < 990:
            description = "rain"
        elif 990 <= pressure < 1010:
            description = "change"
        elif 1010 <= pressure < 1030:
            description = "fair"
        elif pressure >= 1030:
            description = "dry"
        else:
            description = ""
        return description

    @staticmethod
    def describe_humidity(humidity):
        """Convert relative humidity into good/bad description."""
        if 40 < humidity < 60:
            description = "good"
        else:
            description = "bad"
        return description

    @staticmethod
    def describe_light(light):
        """Convert light level in lux to descriptive value."""
        if light < 50:
            description = "dark"
        elif 50 <= light < 100:
            description = "dim"
        elif 100 <= light < 500:
            description = "light"
        elif light >= 500:
            description = "bright"
        return description

    def analyse_pressure(self, pressure, t):
        if len(self._pressure_values) > self._num_vals:
            self._pressure_values = self._pressure_values[1:] + [pressure]
            self._time_values = self._time_values[1:] + [t]

            # Calculate line of best fit
            line = numpy.polyfit(self._time_values, self._pressure_values, 1, full=True)

            # Calculate slope, variance, and confidence
            slope = line[0][0]
            intercept = line[0][1]
            variance = numpy.var(self._pressure_values)
            residuals = numpy.var(
                [(slope * x + intercept - y) for x, y in zip(self._time_values, self._pressure_values)])
            r_squared = 1 - residuals / variance

            # Calculate change in pressure per hour
            change_per_hour = slope * 60 * 60
            # variance_per_hour = variance * 60 * 60

            mean_pressure = numpy.mean(self._pressure_values)

            # Calculate trend
            if r_squared > 0.5:
                if change_per_hour > 0.5:
                    self._trend = ">"
                elif change_per_hour < -0.5:
                    self._trend = "<"
                elif -0.5 <= change_per_hour <= 0.5:
                    self._trend = "-"

                if self._trend != "-":
                    if abs(change_per_hour) > 3:
                        self._trend *= 2
        else:
            self._pressure_values.append(pressure)
            self._time_values.append(t)
            mean_pressure = numpy.mean(self._pressure_values)
            change_per_hour = 0
            self._trend = "-"
        return mean_pressure, change_per_hour, self._trend

    def overlay_text(self, img, position, text, font, align_right=False, rectangle=False):
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
            rect_img = Image.new('RGBA', (self._WIDTH, self._HEIGHT), color=(0, 0, 0, 0))
            rect_draw = ImageDraw.Draw(rect_img)
            rect_draw.rectangle(rect, (255, 255, 255))
            rect_draw.text(position, text, font=font, fill=(0, 0, 0, 0))
            img = Image.alpha_composite(img, rect_img)
        else:
            draw.text(position, text, font=font, fill=(255, 255, 255))
        return img

    def draw_background(self, progress, period, day):
        """Given an amount of progress through the day or night, draw the
           background colour and overlay a blurred sun/moon."""

        # x-coordinate for sun/moon
        x = x_from_sun_moon_time(progress, period, self._WIDTH)

        # If it's day, then move right to left
        if day:
            x = self._WIDTH - x

        # Calculate position on sun/moon's curve
        centre = self._WIDTH / 2
        y = calculate_y_pos(x, centre)

        # Background colour
        background = map_colour(x, 80, self._mid_hue, self._day_hue, day)

        # New image for background colour
        img = Image.new('RGBA', (self._WIDTH, self._HEIGHT), color=background)
        # draw = ImageDraw.Draw(img)

        # New image for sun/moon overlay
        overlay = Image.new('RGBA', (self._WIDTH, self._HEIGHT), color=(0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Draw the sun/moon
        circle = circle_coordinates(x, y, self._sun_radius)
        overlay_draw.ellipse(circle, fill=(200, 200, 50, self._opacity))

        # Overlay the sun/moon on the background as an alpha matte
        composite = Image.alpha_composite(img, overlay).filter(ImageFilter.GaussianBlur(radius=self._blur))

        return composite

    def update_display(self, data_set):
        self.enable()
        progress, period, day, local_dt = sun_moon_time(self._city, self._timezone)
        time_string = local_dt.strftime("%H:%M")
        date_string = local_dt.strftime("%d %b %y").lstrip('0')
        temp_string = "{:.0f}°C".format(data_set['temperature'])
        humidity_string = "{:.0f}%".format(data_set['humidity'])
        mean_pressure, change_per_hour, trend = self.analyse_pressure(data_set['pressure'], time.time())
        light_string = "{}".format(int(data_set['lux']))
        light_desc = self.describe_light(data_set['lux']).upper()
        humidity_desc = self.describe_humidity(data_set['humidity']).upper()
        pressure_desc = self.describe_pressure(data_set['pressure']).upper()
        pressure_string = f"{int(mean_pressure):,} {trend}"

        light_icon = Image.open(f"{self._path}/icons/bulb-{light_desc.lower()}.png")
        humidity_icon = Image.open(f"{self._path}/icons/humidity-{humidity_desc.lower()}.png")
        pressure_icon = Image.open(f"{path}/icons/weather-{pressure_desc.lower()}.png")
        time_elapsed = time.time() - self.start_time

        if time_elapsed > 30:
            if self._min_temp is not None and self._max_temp is not None:
                if data_set['temperature'] < self._min_temp:
                    self._min_temp = data_set['temperature']
                elif data_set['temperature'] > self._max_temp:
                    self._max_temp = data_set['temperature']
            else:
                self._min_temp = data_set['temperature']
                self._max_temp = data_set['temperature']

        if self._min_temp is not None and self._max_temp is not None:
            range_string = f"{self._min_temp:.0f}-{self._max_temp:.0f}"
        else:
            range_string = "------"
        background = self.draw_background(progress, period, day)
        img = self.overlay_text(background, (0 + self._margin, 0 + self._margin), time_string, self._font_lg)
        img = self.overlay_text(img, (self._WIDTH - self._margin, 0 + self._margin), date_string, self._font_lg,
                                align_right=True)
        img = self.overlay_text(img, (68, 18), temp_string, self._font_lg, align_right=True)
        img = self.overlay_text(img, (self._WIDTH - self._margin, 18), light_string, self._font_lg, align_right=True)
        spacing = self._font_lg.getsize(light_string.replace(",", ""))[1] + 1
        img = self.overlay_text(img, (self._WIDTH - self._margin - 1, 18 + spacing), light_desc, self._font_sm,
                                align_right=True, rectangle=True)
        img.paste(self._temp_icon, (self._margin, 18), mask=self._temp_icon)
        img.paste(humidity_icon, (80, 18), mask=light_icon)
        img.paste(pressure_icon, (80, 48), mask=pressure_icon)
        img.paste(humidity_icon, (self._margin, 48), mask=humidity_icon)
        spacing = self._font_lg.getsize(temp_string)[1] + 1
        img = self.overlay_text(img, (68, 48), humidity_string, self._font_lg, align_right=True)
        img = self.overlay_text(img, (68, 48 + spacing), humidity_desc, self._font_sm, align_right=True, rectangle=True)
        img = self.overlay_text(img, (self._WIDTH - self._margin, 48), pressure_string, self._font_lg, align_right=True)
        img = self.overlay_text(img, (68, 18 + spacing), range_string, self._font_sm, align_right=True, rectangle=True)
        img = self.overlay_text(img, (self._WIDTH - self._margin - 1, 48 + spacing), pressure_desc, self._font_sm,
                                align_right=True, rectangle=True)
        self._disp.display(img)

    def disable(self, force=False):
        if self._backlight or force:
            self._disp.display(self._black_img)
            self._backlight = False
            self._disp.set_backlight(0)

    def enable(self):
        if not self._backlight:
            self._backlight = True
            self._disp.set_backlight(1)


if __name__ == '__main__':
    try:
        timeout = 1
        parser = argparse.ArgumentParser()
        parser.add_argument("-C", '--city', metavar="CITY", type=str, help="City")
        parser.add_argument("-D", '--display', metavar="DISPLAY", type=str_to_bool, help="Show the display")
        parser.add_argument("-O", '--display_on_duration', metavar="DISPLAY_ON_DURATION", type=int, default=30,
                            help="How long to show the display")
        parser.add_argument("-p", '--display_proximity', metavar="DISPLAY_PROXIMITY", type=int, default=1000,
                            help="The value indicating the proximity to turn on the display")
        parser.add_argument("-T", '--timezone', metavar="TIMEZONE", type=str, help="Timezone")
        parser.add_argument("-d", "--debug", metavar='DEBUG', type=str_to_bool,
                            help="Turns on more verbose logging, showing sensor output and post responses [default: false]")
        parser.add_argument("-f", "--factor", metavar='FACTOR', type=float, default=None,
                            help="The compensation factor to get better temperature results when the Enviro+ pHAT is too close to the Raspberry Pi board")
        parser.add_argument('-t', '--timeout', metavar="TIMOUT", type=int, default=5, help='timeout between readings')
        args = parser.parse_args()

        # Start up the server to expose the metrics.
        # start_http_server(addr=args.bind, port=args.port)
        # Generate some requests.

        # Initialise the LCD

        city_name = "Amsterdam"
        time_zone = "Europe/Amsterdam"
        show_display = False

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)
            DEBUG = True

        if args.timezone:
            time_zone = args.timezone

        if args.display:
            show_display = True

        if args.city:
            city_name = args.city

        if args.timeout:
            timeout = args.timeout
            logging.info("Logging every {} seconds".format(args.timeout))

        if args.factor:
            logging.info(
                "Using compensating algorithm (factor={}) to account for heat leakage from Raspberry Pi board".format(
                    args.factor))

        display_on_duration = 30
        proximity_threshold = 1000
        if args.display_on_duration:
            display_on_duration = args.display_on_duration
        if args.display_proximity:
            proximity_threshold = args.display_proximity

        mc = MongoConnector(config).get_collection()
        ec = EnviroCollector(timeout * 2)
        display = Display(city_name, time_zone, path)

        x = threading.Thread(target=create_summary(), args=(2,), daemon=True)
        x.start()

        enable_display = False
        display.disable(True)
        time_display_enable = 0
        now1 = time.time()
        while True:
            now = time.time()
            ec.update_all()
            if show_display and ec.get_last_proximity() > proximity_threshold and not enable_display:
                logging.debug("Enabling display")
                enable_display = True
                time_display_enable = now
                data = ec.collect_all_data()
                display.update_display(data)

            now2 = now - now1
            remaining_time = args.timeout - now2
            if enable_display and now > (time_display_enable + display_on_duration):
                logging.debug("resetting display")
                enable_display = False
                display.disable()
            if remaining_time <= 0:
                try:
                    now1 = time.time()
                    data = ec.collect_all_data()
                    mc.insert_one(data)
                    # print(enable_display, now1, time_display_enable, display_on_duration)
                    if enable_display:
                        logging.debug("update display")
                        display.update_display(data)
                except pymongo.errors.ServerSelectionTimeoutError():
                    logging.error("Can't connect to Mongo - drop reading")
                except Exception as e:
                    logging.warning("Can't update display {}".format(e))

            time.sleep(max(0.0, 1.0 - (time.time() - now)))
            # logging.debug('Sensor data: {}'.format(ec.collect_all_data()))
    except KeyboardInterrupt:
        display.disable()
