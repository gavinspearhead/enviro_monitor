import datetime
import json
import os
import sys
import traceback

import numpy
import tzlocal
import dateutil.parser

import pytz
from astral.geocoder import lookup, database
from astral.sun import sun

from flask import Flask, render_template, request, session

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import config
from mongo_connector import MongoConnector

mc = MongoConnector(config).get_collection()
app = Flask(__name__)
app.secret_key = 'dummy stuff!'

types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux", "proximity", "pm1", "pm25",
         "pm10", 'noise_low', 'noise_mid', 'noise_high']

titles = {
    "temperature": "Temperature (°C)",
    'humidity': "Humidity (%)",
    'pressure': "Pressure (HPa)",
    'oxidising': "Oxidising Gas (Nitrogen) (kO)",
    'reducing': "Reducing Gas (CO) (kO)",
    'nh3': "Ammonia (NH3) (kO)",
    "lux": "Light (Lux)",
    "proximity": "Proximity",
    "pm1": "Particles 1μm (μg/m3)",
    "pm25": "Particles 2.5μm (μg/m3)",
    "pm10": "Particles 10μm (μg/m3)",
    'noise_low': "Noise Low",
    'noise_mid': "Noise Mid",
    'noise_high': "Noise High",
    'noise': "Noise (Combined)",
    "particles": "Particles (Combined)"
}

city = "Amsterdam"
time_zone = "CET"


@app.route('/update_session/', methods=['POST', 'GET'])
def update_session():
    selected = request.json.get('selected')
    tmp = {}
    for x, v in selected.items():
        if x in session['selected']:
            tmp[x] = v
    session['selected'] = tmp
    return json.dumps({'success': True}), 200, {'ContentType': 'application/json'}


@app.route('/')
def home_page():
    try:
        if 'selected' not in session:
            session['selected'] = {k: 1 for k in titles.keys()}
            session['selected']['noise_low'] = 0
            session['selected']['noise_high'] = 0
            session['selected']['noise_mid'] = 0
            session['selected']['pm1'] = 0
            session['selected']['pm25'] = 0
            session['selected']['pm10'] = 0
        return render_template("main.html", types=titles, selected=session['selected'], keys=titles.keys())
    except Exception as e:
        traceback.print_exc()
        return json.dumps({'success': False, "message": str(e)}), 200, {'ContentType': 'application/json'}


@app.route("/latest/", methods=['POST', 'GET'])
def latest_data():
    res = mc.find().skip(mc.count_documents({}) - 1)
    data = dict()
    for i in types:
        data[i] = res[0][i]
    return json.dumps({"data": data})


def get_periods(interval, period):
    end_time = datetime.datetime.now(pytz.UTC)
    if period == 'hour':
        start_time = end_time - datetime.timedelta(hours=1)
    elif period == '4hour':
        start_time = end_time - datetime.timedelta(hours=4)
    elif period == '12hour':
        start_time = end_time - datetime.timedelta(hours=12)
    elif period == 'day':
        start_time = end_time - datetime.timedelta(hours=24)
    elif period == 'week':
        start_time = end_time - datetime.timedelta(hours=24 * 7)
    elif period == 'month':
        start_time = end_time - datetime.timedelta(hours=24 * 31)
    elif period == 'custom':
        start_time = (dateutil.parser.isoparse(interval[0])).astimezone(pytz.UTC)
        end_time = (dateutil.parser.isoparse(interval[1]).astimezone(pytz.UTC))
        t_delta = end_time - start_time
        interval = int(t_delta.total_seconds() / 25)
    else:
        raise ValueError("Invalid period {}".format(period))
    return start_time, end_time, interval


def analyse_trend(rtype, value_count=1000):
    res = mc.find({}, {"_id": 0, rtype: 1, "timestamp": 1}).skip(mc.count_documents({}) - value_count)
    data = []
    ts = []
    epoch = datetime.datetime.utcfromtimestamp(0)

    for x in res:
        data.append(x[rtype])
        ts.append((x['timestamp'] - epoch).total_seconds())
    # print(data, ts)
    line = numpy.polyfit(ts, data, 1, full=True)
    slope = line[0][0]
    intercept = line[0][1]
    variance = numpy.var(data)
    residuals = numpy.var([(slope * x + intercept - y) for x, y in zip(ts, data)])
    r_squared = 1 - residuals / variance

    # Calculate change in pressure per hour
    change_per_hour = slope * 60 * 60
    # variance_per_hour = variance * 60 * 60

    # mean_pressure = numpy.mean(data)
    trend = '-'
    # Calculate trend
    if r_squared > 0.5:
        if change_per_hour > 0.5:
            trend = ">"
        elif change_per_hour < -0.5:
            trend = "<"
        elif -0.5 <= change_per_hour <= 0.5:
            trend = "-"

        if trend != "-":
            if abs(change_per_hour) > 3:
                trend *= 2
    # print(change_per_hour, trend, r_squared)
    return change_per_hour, trend


@app.route("/details/", methods=["POST", "GET"])
def get_details():
    orig_type = rtype = request.json.get('type', '')
    interval = request.json.get('interval', 1)
    if rtype not in types:
        raise ValueError("Invalid type {}".format(rtype))
    rtype = "${}".format(rtype)
    period = request.json.get('period', '').strip()
    start_time, end_time, interval = get_periods(interval, period)
    mask = {"$and": [{"timestamp": {"$gte": start_time}}, {"timestamp": {"$lte": end_time}}]}
    query = [
        {"$match": {'$and': [mask]}},
        {"$group": {
            "_id": None,
            "max": {"$max": rtype},
            "min": {"$min": rtype},
            "avg": {"$avg": rtype},
            "std": {"$stdDevPop": rtype},
        }
        }
    ]
    # print(query)
    change_per_hour, trend = analyse_trend(orig_type)
    res = mc.aggregate(query)
    data = []
    for x in res:
        data = x
        break
    # print(data)
    data['trend'] = trend
    data['change_per_hour'] = change_per_hour
    return json.dumps({"data": data})


def calculate_next_sun(cityname, time_zone_name="UTC"):
    city = lookup(cityname, database())
    timezone = pytz.timezone(time_zone_name)
    now = datetime.datetime.now(timezone)
    local_now = now.astimezone(timezone)
    yesterday = now - datetime.timedelta(days=1)
    tomorrow = now + datetime.timedelta(days=1)
    sun_today = sun(city.observer, date=local_now)
    sun_yesterday = sun(city.observer, date=yesterday)
    sun_tomorrow = sun(city.observer, date=tomorrow)
    sunset_yesterday = sun_yesterday["sunset"]
    sunrise_today = sun_today["sunrise"]
    sunset_today = sun_today["sunset"]
    sunrise_tomorrow = sun_tomorrow["sunrise"]
    sunset_tomorrow = sun_tomorrow["sunset"]
    if sunrise_today <= local_now:
        next_sunrise = sunrise_tomorrow
    else:
        next_sunrise = sunrise_today

    if sunset_today <= local_now:
        next_sunset = sunset_tomorrow
    else:
        next_sunset = sunset_yesterday
    return next_sunset.astimezone(timezone), next_sunrise.astimezone(timezone)


@app.route("/sun/", methods=["POST", "GET"])
def sun_info():
    sun_down, sun_up = calculate_next_sun(city, time_zone)
    return json.dumps({'sun_up': sun_up.strftime("%X"), "sun_down": sun_down.strftime("%X")})


@app.route("/data/", methods=["POST", "GET"])
def data_load():
    orig_type = rtype = request.json.get('type', '')
    interval = request.json.get('interval', 1)
    if rtype not in types:
        raise ValueError("Invalid type {}".format(rtype))
    rtype = "${}".format(rtype)
    period = request.json.get('period', '').strip()
    start_time, end_time, interval = get_periods(interval, period)

    mask = {"$and": [{"timestamp": {"$gte": start_time}}, {"timestamp": {"$lte": end_time}}]}
    query = [
        {"$match": {'$and': [mask]}},
        {"$group": {
            "_id": {
                "$subtract": [
                    {"$subtract": ["$timestamp", start_time]},
                    {"$mod": [
                        {"$subtract": ["$timestamp", start_time]},
                        1000 * interval
                    ]}
                ]
            },
            'time': {'$min': "$timestamp"},
            'time2': {'$max': "$timestamp"},
            "avg": {"$avg": rtype}
        }
        },
        {"$sort": {"_id": 1}}
    ]

    res = mc.aggregate(query)

    data = []
    labels = []
    t_format = "%H:%M"
    if interval > 3600:
        t_format = "%Y-%m-%d %H:%M"

    for x in res:
        t = x['time'].replace(tzinfo=pytz.UTC).astimezone(tzlocal.get_localzone())
        ts = t.strftime(t_format)
        if x['avg'] is not None:
            labels.append(ts)
            data.append(round(x['avg'], 2))

    title = titles[orig_type] if orig_type in titles else ""
    return json.dumps({"data": data, "labels": labels, "title": title})


@app.route('/all/<int:count>')
@app.route('/all/<name>/<int:count>')
def all_data(name='', count=1):
    res = mc.find().skip(mc.count_documents({}) - count)
    data = []
    for i in res:
        if name == '':
            row = {
                'temperature': i['temperature'],
                'humidity': i['humidity'],
                'pressure': i['pressure'],
                'oxidising': i['oxidising'],
                'reducing': i['reducing'],
                'nh3': i['nh3'],
                'lux': i['lux'],
                'proximity': i['proximity'],
                'pm1': i['pm1'],
                'pm25': i['pm25'],
                'pm10': i['pm10'],
                'timestamp': i['timestamp'].isoformat()
            }
        else:
            try:
                row = {
                    'timestamp': i['timestamp'].isoformat(),
                    name: i[name]}
            except KeyError:
                row = {}
        data.append(row)
    return json.dumps(data)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=4444, debug=True)
