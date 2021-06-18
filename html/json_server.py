import datetime
import json
import os
import sys
import traceback
import tzlocal
import dateutil.parser

import pytz

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
    "pm": "Particles",
    "pm1": "Particles 1μm (μg/m3)",
    "pm25": "Particles 2.5μm (μg/m3)",
    "pm10": "Particles 10μm (μg/m3)",
    'noise_low': "Noise Low",
    'noise_mid': "Noise Mid",
    'noise_high': "Noise High",
    'noise': "Noise (Combined)",
    "particles": "Particles (Combined)"
}


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
        return render_template("main.html", types=titles, selected=session['selected'])
    except Exception as e:
        traceback.print_exc()
        return json.dumps({'success': False, "message": str(e)}), 200, {'ContentType': 'application/json'}


@app.route("/latest/", methods=['POST', 'GET'])
def latest_data():
    res = mc.find().skip(mc.find().count() - 1)
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
    res = mc.aggregate(query)
    data = []
    for x in res:
        data = x
        break
    return json.dumps({"data": data})


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
    res = mc.find().skip(mc.count() - count)
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
