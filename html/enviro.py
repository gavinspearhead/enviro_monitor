#!/usr/bin/python3
import argparse
import datetime
import json
import os.path
import re
import sys
import pytz

from flask import Flask, render_template, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mongo_connector import MongoConnector

app = Flask(__name__)

mc = MongoConnector(config)


def get_mongo_connection():
    output = Outputs()
    output.parse_outputs(os.path.join(config_path, '..', output_file_name))
    config = output.get_output('mongo')
    mc = MongoConnector(config)
    col = mc.get_collection()
    return col


@app.route('/data/', methods=['POST'])
def data():
    name = request.json.get('name', '').strip()
    rtype = request.json.get('type', '').strip()
    period = request.json.get('period', '').strip()
    search = request.json.get('search', '').strip()
    if rtype == 'ssh':
        res, keys = get_ssh_data(name, period, search)
    elif rtype == 'apache':
        res, keys = get_apache_data(name, period, search)
    else:
        raise ValueError("Unknown type: {}".format(rtype))
    res2 = []
    flags = dict()
    for x in res:

        for k, v in x.items():
            if k == 'ip_address' and k not in flags:
                try:
                    flag = geoip_db.lookup(v).country.lower()
                    flags[v] = flag
                except AttributeError:
                    flags[v] = ''

        # Force every thing to string so we can truncate stuff in the template
        res2.append({k: str(v) for k, v in x.items()})
    rhtml = render_template("data_table.html", data=res2, keys=keys, flags=flags)
    return json.dumps({'success': True, 'rhtml': rhtml}), 200, {'ContentType': 'application/json'}


@app.route('/')
def homepage():
    try:
        return render_template("main.html")
    except Exception as e:
        return json.dumps({'success': False, "message": str(e)}), 200, {'ContentType': 'application/json'}


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="RSS update daemon")
    parser.add_argument("-c", '--config', help="Config File Directory", default="", metavar="FILE")
    args = parser.parse_args()
    if args.config:
        config_path = args.config

    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    app.run(host='0.0.0.0', debug=True)
