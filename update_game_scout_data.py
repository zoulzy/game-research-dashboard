#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / 'game-scout-daily.json'
DEFAULT_STATUS_OPTIONS = ['New', 'Reviewing', 'Watchlist', 'Pass', 'Drop']


def load_data():
    with DATA_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def normalize_list(value):
    return value if isinstance(value, list) else []


def main():
    data = load_data()
    meta = data.setdefault('meta', {})
    games = normalize_list(data.get('games'))
    reports = sorted(normalize_list(data.get('daily_reports')), key=lambda x: x.get('date', ''), reverse=True)
    pipeline = data.setdefault('candidate_pipeline', {})
    data.setdefault('watchlists', {})
    data.setdefault('cross_game_insight', {})
    data.setdefault('team_brief', {})

    latest_report = reports[0] if reports else {}
    latest_top_pick_ids = set(normalize_list(latest_report.get('top_pick_ids')))
    latest_new_ids = set(normalize_list(latest_report.get('new_game_ids')))

    top_picks_today = len(latest_top_pick_ids) if latest_top_pick_ids else min(5, len(games))
    pending_verification = len(normalize_list(pipeline.get('pending_verification')))
    candidate_pipeline = len(games)
    new_games_today = len(latest_new_ids)

    kpis = data.setdefault('kpis', {})
    kpis['top_picks_today'] = top_picks_today
    kpis['candidate_pipeline'] = candidate_pipeline
    kpis['pending_verification'] = pending_verification
    kpis['new_games_today'] = new_games_today
    kpis.setdefault('weekly_syntheses', 1)

    meta.setdefault('title', 'CN/KR Mobile Game Research Dashboard')
    meta.setdefault('timezone', 'Asia/Bangkok')
    meta.setdefault('source_of_truth', 'Obsidian Vault')
    meta.setdefault('delivery_target', 'Daily 08:00')
    meta.setdefault('status_options', DEFAULT_STATUS_OPTIONS)
    meta['date'] = latest_report.get('date', meta.get('date'))
    meta['generated_at'] = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

    with DATA_PATH.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    summary = {
        'data_path': str(DATA_PATH),
        'report_date': meta.get('date'),
        'games_total': len(games),
        'top_picks_today': kpis['top_picks_today'],
        'new_games_today': kpis['new_games_today'],
        'pending_verification': kpis['pending_verification'],
        'generated_at': meta['generated_at'],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
