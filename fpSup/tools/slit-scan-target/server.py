#!/usr/bin/env python3
"""LAN-only test-pattern server with remote visual controls (no camera access).

GET /api/state: desired target state and version.
POST /api/state: update selected controls.
POST /api/client: browser acknowledgement/cadence; GET /api/client reads it.
The page polls four times/second; animation timing remains entirely in rAF.
Opening index.html as a local file still works offline without polling.
"""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time

LOCK = threading.Lock()
STATE = dict(version=0, mode='bars', speed=.5, paused=False, reversed=False,
             hiddenControls=True, showReadouts=False)
CLIENT = {}


def validate(update):
    if type(update) is not dict or not update or set(update)-set(STATE) or 'version' in update:
        raise ValueError('unknown or empty controls')
    merged = dict(STATE, **update)
    if merged['mode'] not in ('fan', 'bars', 'flash'):
        raise ValueError('unknown mode')
    speed = merged['speed']
    low, high = (1, 15) if merged['mode'] == 'flash' else (.25, 4)
    if type(speed) not in (int, float) or not low <= speed <= high:
        raise ValueError('speed outside mode range')
    for k in ('paused', 'reversed', 'hiddenControls', 'showReadouts'):
        if type(merged[k]) is not bool:
            raise ValueError(f'{k} must be boolean')
    return merged


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if '/api/' not in str(args[0]):
            super().log_message(fmt, *args)

    def json_response(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ('/api/state', '/api/client'):
            with LOCK:
                value = dict(STATE if self.path == '/api/state' else CLIENT)
            return self.json_response(value)
        if self.path not in ('/', '/index.html', '/favicon.ico'):
            return self.send_error(404)
        super().do_GET()

    def do_POST(self):
        if self.path not in ('/api/state', '/api/client'):
            return self.send_error(404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('body must be 1..4096 bytes')
            value = json.loads(self.rfile.read(size))
            with LOCK:
                if self.path == '/api/state':
                    merged = validate(value)
                    merged['version'] = STATE['version']+1
                    STATE.update(merged)
                    response = dict(STATE)
                else:
                    if type(value) is not dict:
                        raise ValueError('client state must be an object')
                    CLIENT.clear()
                    CLIENT.update(value, received_at=time.time())
                    response = dict(ok=True)
        except (ValueError, TypeError) as error:
            return self.json_response(dict(error=str(error)), 400)
        self.json_response(response)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8127)
    args = p.parse_args()
    handler = partial(Handler, directory=str(Path(__file__).resolve().parent))
    ThreadingHTTPServer((args.bind, args.port), handler).serve_forever()
