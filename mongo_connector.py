from pymongo import MongoClient


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
        self._hourly_collection = self._db[self._config['aggregate_collection']]

    def get_aggregate_collection(self):
        return self._hourly_collection

    def get_collection(self):
        return self._collection

    def get_db(self):
        return self._db