import datetime
import json
import traceback

import pytz

from flask import Flask, render_template, request

from mongo_connector import MongoConnector

config = {
    'hostname': '192.168.178.21',
    'port': 27017,
    "database": "enviro",
    "collection": "enviro",
    "username": "enviro",
    "password": "S2ytTULCBmEQYZrxF0sC",
    "auth_db": "enviro"
}

mc = MongoConnector(config).get_collection()
app = Flask(__name__)


@app.route('/')
def home_page():
    print("main")
    try:
        return render_template("main.html")
    except Exception as e:
        traceback.print_exception(e)
        return json.dumps({'success': False, "message": str(e)}), 200, {'ContentType': 'application/json'}


@app.route("/data/", methods=["POST", "GET"])
def data():
    types = ["temperature", 'humidity', 'pressure', 'oxidising', 'reducing', 'nh3', "lux", "proximity", "pm1", "pm25",
             "pm10"]
    type = request.json.get('type', '').strip()
    # print(type)
    interval = request.json.get('interval', 1)
    if type not in types:
        raise ValueError("Invalid type {}".format(type))
    type = "${}".format(type)
    period = request.json.get('period', '').strip()
    now = datetime.datetime.now(pytz.UTC)
    if period == 'hour':
        start_time = now - datetime.timedelta(hours=1)
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
            "avg": {"$avg": type}
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
    for x in res:
        # print(x)
        print(x)
        labels.append(x['_id']/ (1000 * interval))
        data.append(x['avg'])

    print(type , len(data))
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
