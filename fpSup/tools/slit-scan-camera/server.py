#!/usr/bin/env python3
"""Local browser controls for fpl_slit_scan.py. Run with analysis-venv Python.

Uses the existing FPSHD_SOCKET owner. One capture job at a time; controls only
invoke the validated capture CLI. Outputs live outside the source tree.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
CAPTURE = HERE.parents[1]/'fp_usb_shell/fpl_slit_scan.py'
LOCK = threading.Lock()
JOB = {}
PROCESS = None
OUTPUT = None


def finish(process, directory):
    global PROCESS
    code = process.wait()
    preview_error = None
    try:
        files = sorted((directory/'images').glob('*.DNG'))
        if files:
            import rawpy
            from PIL import Image
            with rawpy.imread(str(files[len(files)//2])) as raw:
                rgb = raw.postprocess(use_camera_wb=True, half_size=True)
            image = Image.fromarray(rgb)
            image.thumbnail((1280, 720))
            image.save(directory/'preview.jpg', quality=90)
    except Exception as error:
        preview_error = str(error)
    with LOCK:
        JOB.update(running=False, returncode=code, preview_error=preview_error)
        PROCESS = None


def start(value):
    global PROCESS
    if type(value) is not dict or set(value)-{'action', 'fps', 'seconds', 'shutter', 'iso'}:
        raise ValueError('invalid controls')
    action = value.get('action')
    if action not in ('check', 'photo', 'video'):
        raise ValueError('unknown action')
    for key, allowed in [('fps', (4,6,8,12)), ('shutter', (250,500,1000)),
                         ('iso', (100,200,400,800,1600,3200))]:
        if type(value.get(key)) is not int or value[key] not in allowed:
            raise ValueError('invalid '+key)
    seconds = value.get('seconds')
    if type(seconds) is not int or not 1 <= seconds <= 30:
        raise ValueError('duration must be 1..30 seconds')
    with LOCK:
        if PROCESS is not None:
            raise ValueError('a capture is already running')
        name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'-'+action
        directory = OUTPUT/name
        logfile = OUTPUT/(name+'.log')
        command = [sys.executable, '-B', str(CAPTURE), action, '--out', str(directory),
                   '--fps', str(value['fps']), '--frames', str(value['fps']*seconds),
                   '--shutter', str(value['shutter']), '--iso', str(value['iso'])]
        with logfile.open('xb') as log:
            PROCESS = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                       cwd=CAPTURE.parent)
        JOB.clear()
        JOB.update(id=name, action=action, running=True, returncode=None)
        threading.Thread(target=finish, args=(PROCESS, directory), daemon=True).start()
        return dict(JOB)


def status():
    with LOCK:
        result = dict(JOB)
    if 'id' in result:
        name = result['id']
        directory = OUTPUT/name
        log = OUTPUT/(name+'.log')
        if log.exists():
            with log.open('rb') as f:
                f.seek(max(0, log.stat().st_size-6000))
                result['log'] = f.read().decode(errors='replace')
        result['files'] = [str(p.relative_to(OUTPUT)) for p in sorted(directory.rglob('*'))
                           if p.is_file() and p.suffix.lower() in ('.dng', '.jpg', '.json')]
        result['output'] = str(directory)
        capture = directory/'capture.json'
        if capture.exists():
            try:
                result['capture'] = json.loads(capture.read_text())
            except json.JSONDecodeError:
                pass
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, body, kind='application/json', code=200):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/':
            return self.reply((HERE/'index.html').read_bytes(), 'text/html; charset=utf-8')
        if path == '/api/status':
            return self.reply(status())
        if path.startswith('/files/'):
            file = (OUTPUT/path[len('/files/'):]).resolve()
            if not file.is_relative_to(OUTPUT) or not file.is_file() or file.suffix.lower() not in ('.dng', '.jpg', '.json'):
                return self.send_error(404)
            kind = {'.jpg':'image/jpeg', '.json':'application/json', '.dng':'image/x-adobe-dng'}[file.suffix.lower()]
            return self.reply(file.read_bytes(), kind)
        self.send_error(404)

    def do_POST(self):
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send_error(403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 2048:
                raise ValueError('invalid body size')
            value = json.loads(self.rfile.read(length))
            if self.path == '/api/start':
                return self.reply(start(value))
            if self.path == '/api/stop':
                with LOCK:
                    if PROCESS is not None and PROCESS.poll() is None:
                        PROCESS.send_signal(signal.SIGTERM)
                return self.reply({'stopping': True})
            self.send_error(404)
        except (ValueError, OSError) as error:
            self.reply({'error': str(error)}, code=400)


def main():
    global OUTPUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8128)
    p.add_argument('--output', type=Path, default=Path.home()/'Pictures/fpSup/slit-scan')
    args = p.parse_args()
    OUTPUT = args.output.expanduser().resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer((args.bind, args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
