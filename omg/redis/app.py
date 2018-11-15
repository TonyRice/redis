# -*- coding: utf-8 -*-
import json
import os
from typing import Dict

from .RLPopThread import RLPopThread

from flask import Flask, make_response, request

import redis


class Handler:
    app = Flask(__name__)

    listeners: Dict[str, RLPopThread] = {}

    r = redis.StrictRedis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', '6379')),
        password=os.getenv('REDIS_PASSWORD', None),
        db=os.getenv('REDIS_DB', None),
    )

    command_methods = {
        'del': 'delete',
        'rpop': 'pop_generic',
        'lpop': 'pop_generic',
        'brpop': 'pop_generic',
        'blpop': 'pop_generic',
        'rpush': 'push_generic',
        'lpush': 'push_generic',
    }

    def execute(self, command):
        req = request.get_json()
        method = self.command_methods.get(command, command)
        return getattr(self, method)(command, req)

    def ok(self, result=None, null=False):
        res = {'status': 'ok'}

        if result is not None:
            if isinstance(result, bytes):
                result = result.decode('utf-8')

            res['result'] = result
        elif null:
            res['result'] = None

        resp = make_response(json.dumps(res))
        resp.headers['Content-Type'] = 'application/json; charset=utf-8'
        return resp

    def set(self, command, json_req):
        self.r.set(json_req['key'], json_req['value'])
        return self.ok()

    def get(self, command, json_req):
        val = self.r.get(json_req['key'])
        return self.ok(result=val, null=True)

    def push_generic(self, command, json_req):
        """
        Handles LPUSH, RPUSH.
        """
        c = getattr(self.r, command)
        c(json_req['key'], json_req['value'])
        return self.ok()

    def pop_generic(self, command, json_req):
        """
        Handles LPOP, RPOP, BLPOP, BRPOP.
        """
        c = getattr(self.r, command)
        val = c(json_req['key'])
        if val:
            if isinstance(val, tuple):  # True if blocking pop.
                return self.ok(val[1])
            else:
                return self.ok(val)
        else:
            return self.ok(null=True)

    def delete(self, command, json_req):
        """
        Pretty command - actual command is del.
        """
        self.r.delete(json_req['key'])
        return self.ok()

    def expire(self, command, json_req):
        self.r.expire(json_req['key'], json_req['seconds'])
        return self.ok()

    def listener(self, action):
        req = request.get_json()
        sub_id = req['id']

        if action == 'remove':
            old_thread = self.listeners.get(sub_id)

            if old_thread is not None:
                old_thread.shutdown = True
                return 'ok\n'

            return 'already_inactive\n'

        assert action == 'add'

        # We only support r/lpop for now.
        assert req['event'] == 'rpop' or req['event'] == 'lpop'

        key = req['data']['key']

        old_thread = self.listeners.get(sub_id)
        if old_thread is not None:
            if old_thread.is_alive():
                return 'already_active\n'

        t = RLPopThread(sub_id, req['event'], self.r, key, req['endpoint'])
        t.start()
        self.listeners[sub_id] = t
        return 'ok\n'


if __name__ == '__main__':
    handler = Handler()
    handler.app.add_url_rule('/listener/<string:action>',
                             # action=add/remove.
                             'listener', handler.listener, methods=['post'])
    handler.app.add_url_rule('/<string:command>', 'execute', handler.execute,
                             methods=['post'])
    handler.app.run(host='0.0.0.0', port=8000)
