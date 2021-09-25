import datetime
import os
import sys
import tzlocal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "html"))

from mongo_connector import MongoConnector
from config import config
from enviro import types
from dateutil.relativedelta import relativedelta


def summarise_data(months_retained=2):
    local_tz = str(tzlocal.get_localzone())
    mc = MongoConnector(config)
    col = mc.get_collection()
    hc = mc.get_aggregate_collection()

    start_time = datetime.datetime.now() - relativedelta(months=months_retained)
    start_time = datetime.datetime(start_time.year, start_time.month, start_time.day, 0, 0, 0, 0)
    mask = {"timestamp": {"$lte": start_time}}

    match = {"$match": {'$and': [mask]}}
    group = {
        "$group": {
            "_id": {
                "hour": {"$hour": {"date": "$timestamp", "timezone": local_tz}},
                "day": {"$dayOfMonth": {"date": "$timestamp", "timezone": local_tz}},
                "month": {"$month": {"date": "$timestamp", "timezone": local_tz}},
                "year": {"$year": {"date": "$timestamp", "timezone": local_tz}}
            },
            "ids": {"$addToSet": "$_id"}
        }
    }

    for tp in types:
        group["$group"][tp] = {"$avg": "${}".format(tp)}

    query = [
        match,
        group
    ]

    res = col.aggregate(query)
    for i in res:
        ids = i['ids']
        ts = datetime.datetime(hour=i["_id"]['hour'], day=i["_id"]['day'], month=i["_id"]['month'],
                               year=i["_id"]['year'])
        y = dict(i)
        y['timestamp'] = ts
        del y['ids'], y['_id']
        hc.insert_one(y)
        col.delete_many({"_id": {"$in": ids}})

