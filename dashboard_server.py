#!/usr/bin/env python3
import json
import mimetypes
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / 'game-scout-daily.json'
HOST = '0.0.0.0'
PORT = 8000


def load_data():
    with DATA_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_data(data):
    with DATA_PATH.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _serve_logo_proxy(self):
        game_id = self.path.removeprefix('/assets/logo-proxy/')
        if not game_id:
            self.send_error(404, 'Missing game id')
            return

        try:
            data = load_data()
        except Exception:
            self.send_error(500, 'Could not load dashboard data')
            return

        games = data.get('games') or []
        game = next((item for item in games if item.get('id') == game_id), None)
        logo_url = str((game or {}).get('logo_path') or '').strip()
        if not logo_url:
            self.send_error(404, 'Logo not configured')
            return

        parsed = urlparse(logo_url)
        if parsed.scheme not in {'http', 'https'}:
            local_path = (ROOT / logo_url).resolve()
            if not local_path.exists() or ROOT not in local_path.parents:
                self.send_error(404, 'Local logo not found')
                return
            content = local_path.read_bytes()
            mime_type = mimetypes.guess_type(local_path.name)[0] or 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)
            return

        req = Request(logo_url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Referer': 'https://www.taptap.cn/',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        })
        try:
            with urlopen(req, timeout=20) as response:
                content = response.read()
                mime_type = response.headers.get_content_type() or 'image/png'
        except (HTTPError, URLError, TimeoutError):
            self.send_error(502, 'Failed to fetch remote logo')
            return

        self.send_response(200)
        self.send_header('Content-Type', mime_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path.startswith('/assets/logo-proxy/'):
            self._serve_logo_proxy()
            return
        super().do_GET()

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', '0') or 0)
        raw = self.rfile.read(content_length)
        try:
            payload = json.loads(raw.decode('utf-8') or '{}')
        except Exception:
            self._send_json({'ok': False, 'error': 'Invalid JSON'}, status=400)
            return

        if self.path == '/api/game-update':
            game_id = str(payload.get('game_id', '')).strip()
            if not game_id:
                self._send_json({'ok': False, 'error': 'game_id is required'}, status=400)
                return

            data = load_data()
            games = data.get('games') or []
            target = next((game for game in games if game.get('id') == game_id), None)
            if not target:
                self._send_json({'ok': False, 'error': f'Unknown game_id: {game_id}'}, status=404)
                return

            timestamp = now_iso()
            response_payload = {'ok': True, 'game_id': game_id}

            if 'status' in payload:
                status_value = str(payload.get('status', '')).strip()
                if not status_value:
                    self._send_json({'ok': False, 'error': 'status cannot be empty'}, status=400)
                    return
                previous = target.get('status')
                target['status'] = status_value
                target['last_status_updated'] = timestamp
                history = target.setdefault('status_history', [])
                if previous != status_value:
                    history.append({'at': timestamp, 'from': previous, 'to': status_value})
                response_payload['status'] = status_value
                response_payload['last_status_updated'] = timestamp

            if 'comment' in payload:
                comment_value = str(payload.get('comment', ''))
                target['comment'] = comment_value
                target['last_comment_updated'] = timestamp
                response_payload['comment'] = comment_value
                response_payload['last_comment_updated'] = timestamp

            meta = data.setdefault('meta', {})
            meta['generated_at'] = timestamp
            write_data(data)
            self._send_json(response_payload)
            return

        if self.path == '/api/save-snapshot':
            data = load_data()
            timestamp = now_iso()
            today = str(payload.get('date') or data.get('meta', {}).get('date') or timestamp[:10])
            games = data.get('games') or []
            reports = data.setdefault('daily_reports', [])
            report = next((r for r in reports if r.get('date') == today), None)
            if report is None:
                report = {'date': today}
                reports.append(report)
            report['headline'] = payload.get('headline') or report.get('headline') or f'Daily snapshot for {today}'
            explicit_game_ids = payload.get('game_ids') or []
            if explicit_game_ids:
                report['game_ids'] = [game_id for game_id in explicit_game_ids if game_id]
            elif report.get('game_ids'):
                report['game_ids'] = [game_id for game_id in report.get('game_ids', []) if game_id]
            else:
                report['game_ids'] = [
                    g.get('id') for g in games
                    if g.get('id') and str(g.get('first_seen') or '') == today
                ]
            report['new_game_ids'] = payload.get('new_game_ids') or report.get('new_game_ids') or []
            report['top_pick_ids'] = payload.get('top_pick_ids') or report.get('top_pick_ids') or []
            report['cross_game_insight'] = payload.get('cross_game_insight') or report.get('cross_game_insight') or ''
            report['notes'] = payload.get('notes') or report.get('notes') or []
            report['game_snapshots'] = [
                {'game_id': g.get('id'), 'status': g.get('status') or g.get('default_status') or 'Reviewing', 'comment': g.get('comment', '')}
                for g in games if g.get('id')
            ]
            data.setdefault('meta', {})['date'] = today
            data['meta']['generated_at'] = timestamp
            write_data(data)
            self._send_json({'ok': True, 'date': today, 'snapshot_count': len(report['game_snapshots'])})
            return

        self._send_json({'ok': False, 'error': 'Not found'}, status=404)


def main():
    httpd = HTTPServer((HOST, PORT), DashboardHandler)
    print(f'Serving dashboard on http://{HOST}:{PORT}')
    httpd.serve_forever()


if __name__ == '__main__':
    main()
