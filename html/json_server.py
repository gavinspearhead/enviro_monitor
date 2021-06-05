import datetime
import json
import os
import sys
import traceback
import tzlocal

import pytz

from flask import Flask, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import config
from mongo_connector import MongoConnector

mc = MongoConnector(config).get_collection()
app = Flask(__name__)


@app.route('/')
def home_page():
    try:
        return render_template("main.html")
    except Exception as e:
        traceback.print_exception(e)
        return json.dumps({'success': False, "message": str(e)}), 200, {'ContentType': 'application/json'}


@app.route("/latest/", methods=['POST', 'GET'])
def latest_data():
    res = mc.find().skip(mc.find().count() - 1)
    types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux", "proximity", "pm1", "pm25",
             "pm10", 'noise_low', 'noise_mid', 'noise_high']
    data = dict()
    for i in types:
        data[i] = res[0][i]
    return json.dumps({"data": data})


@app.route("/data/", methods=["POST", "GET"])
def data_load():
    types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux", "proximity", "pm1", "pm25",
             "pm10", 'noise_low', 'noise_mid', 'noise_high']
    rtype = request.json.get('type', '').strip()
    # print(type)
    interval = request.json.get('interval', 1)
    if rtype not in types:
        raise ValueError("Invalid type {}".format(rtype))
    rtype = "${}".format(rtype)
    period = request.json.get('period', '').strip()
    now = datetime.datetime.now(pytz.UTC)
    if period == 'hour':
        start_time = now - datetime.timedelta(hours=1)
    elif period == '4hour':
        start_time = now - datetime.timedelta(hours=4)
    elif period == '12hour':
        start_time = now - datetime.timedelta(hours=12)
    elif period == 'day':
        start_time = now - datetime.timedelta(hours=24)
    elif period == 'week':
        start_time = now - datetime.timedelta(hours=24 * 7)
    elif period == 'month':
        start_time = now - datetime.timedelta(hours=24 * 31)
    else:
        raise ValueError("Invalid period {}".format(period))
    mask = {"$and": [{"timestamp": {"$gte": start_time}}, {"timestamp": {"$lte": now}}]}

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
    # print(query)
    # print('foo')
    # print(res)

    data = []
    labels = []
    t_format = "%H:%M"
    if interval > 3600:
        t_format = "%Y-%m-%d %H:%M"

    # print(rtype)
    for x in res:
        # print(x)
        # print(x['time'].replace(tzinfo=pytz.UTC))
        t = x['time'].replace(tzinfo=pytz.UTC).astimezone(tzlocal.get_localzone())
        ts = t.strftime(t_format)
        # labels.append(x['_id'] / (1000 * interval))
        if x['avg'] is not None:
            labels.append(ts)
            data.append(round(x['avg'], 2))

    # print(rtype, len(data))
    return json.dumps({"data": data, "labels": labels})


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
    print(data)
    return json.dumps(data)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=4444, debug=True)
