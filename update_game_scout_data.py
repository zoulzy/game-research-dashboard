#!/usr/bin/env python3
"""
Enhanced update_game_scout_data.py
- Computes priority_score per game
- Auto-deduplicates by normalized title
- Detects trending games (appeared in last 3 reports)
- Auto-generates daily report summary from data
- Ensures field type correctness
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / 'game-scout-daily.json'
DEFAULT_STATUS_OPTIONS = ['New', 'Reviewing', 'Watchlist', 'Pass', 'Drop']

# ── Thai market priority weights ────────────────────────────────────────────
THAI_GENRE_WEIGHTS = {
    'RPG': 3, 'MMORPG': 4, 'Action RPG': 3, 'Idle RPG': 2,
    'Strategy': 2, 'SLG': 2, 'Simulation': 1, 'Adventure': 2,
    'Roguelike': 2, 'Puzzle': 1, 'Action': 2, 'Idle': 2,
}
IAP_WEIGHTS = {'probable': 2, 'confirmed': 3, 'none': 0}
MONETIZATION_WEIGHTS = {
    'Likely F2P + IAP': 2, 'F2P + IAP': 3,
    'F2P + IAP (heavy privilege-card structure)': 2,
    'F2P + IAP (gacha/energy)': 2, 'F2P + ads / IAP hybrid unclear': 1,
    'Hybrid / unclear': 1, 'F2P + IAP (ad-supported)': 1,
    'Free (permanent, no ads)': 0,
}
COUNTRY_WEIGHTS = {'CN': 2, 'KR': 2, 'JP': 1}


def normalize(text):
    """Normalize title for deduplication."""
    if not text:
        return ''
    t = text.lower().strip()
    t = re.sub(r'[^\w\u4e00-\u9fff]', '', t)  # keep CJK + word chars
    return re.sub(r'\s+', '', t)


def compute_priority_score(g):
    """Compute 0-100 priority score based on Thai market fit."""
    score = 0

    # Base score from scout score (0-30)
    base = float(g.get('score') or 0)
    score += min(base, 30)

    # Thai genre fit (0-25)
    thai_fits = g.get('fit_with_th_top_genres') or []
    if thai_fits:
        max_weight = max((THAI_GENRE_WEIGHTS.get(genre, 1) for genre in thai_fits), default=1)
        genre_score = min(25, max_weight * 8)
        score += genre_score

    # IAP signal (0-6)
    iap = g.get('iap_signal') or ''
    score += IAP_WEIGHTS.get(iap, 1)

    # Monetization (0-6)
    mon = g.get('monetization_model') or ''
    score += MONETIZATION_WEIGHTS.get(mon, 1)

    # Developer country (0-4)
    country = g.get('developer_country') or ''
    score += COUNTRY_WEIGHTS.get(country, 1)

    # Status bonus — new games get slight boost (0-5)
    if g.get('status') == 'New':
        score += 5
    elif g.get('status') == 'Reviewing':
        score += 3

    # Genre alignment bonus for RPG/MMORPG (0-10)
    genre = g.get('genre') or ''
    if genre in ('MMORPG', 'RPG'):
        score += 10
    elif genre in ('Action RPG', 'Idle RPG'):
        score += 6

    return min(100, max(0, int(score)))


def detect_trending(games, reports, lookback=3):
    """
    Mark games as trending if they appear in the last `lookback` reports.
    trending_direction: 'up' if new in last 2 reports, 'stable' if appeared before that.
    """
    recent_ids = set()
    for r in reports[:lookback]:
        for gid in (r.get('new_game_ids') or []):
            recent_ids.add(gid)

    trending_ids = set()
    for r in reports[:2]:  # last 2 reports = truly hot
        for gid in (r.get('new_game_ids') or []):
            trending_ids.add(gid)

    for g in games:
        gid = g.get('id') or ''
        if gid in trending_ids:
            g['trending_direction'] = 'up'
        elif gid in recent_ids:
            g['trending_direction'] = 'stable'
        else:
            g['trending_direction'] = None


def deduplicate_games(games):
    """
    Remove duplicate entries that have the same normalized title.
    Keep the one with the higher priority_score.
    """
    seen = {}  # normalized_title -> (game, priority_score)
    for g in games:
        norm = normalize(g.get('title') or '')
        if not norm:
            continue
        score = compute_priority_score(g)
        if norm not in seen or score > seen[norm][1]:
            seen[norm] = (g, score)

    kept = [g for g, _ in seen.values()]
    removed = len(games) - len(kept)
    return kept, removed


def auto_generate_report_notes(games, report):
    """
    Auto-generate a brief note paragraph from the report data.
    Falls back to existing notes if already populated.
    """
    existing = report.get('notes') or []
    if existing and isinstance(existing, list) and any(existing):
        return existing  # keep human-written notes

    new_ids = report.get('new_game_ids') or []
    top_ids = set(report.get('top_pick_ids') or [])

    new_games = [g for g in games if g.get('id') in new_ids]
    if not new_games:
        return []

    notes = []

    # Sort: top picks first, then by score desc
    new_games.sort(key=lambda g: (0 if g.get('id') in top_ids else 1, -(g.get('score') or 0)))

    genre_counts = Counter(g.get('genre') for g in new_games)
    top_genre = genre_counts.most_common(1)[0] if genre_counts else None

    if len(new_games) == 1:
        g = new_games[0]
        notes.append(f"มีเกมใหม่ 1 ตัว: {g.get('title','?')} ({g.get('genre','?')}) — score {g.get('score','?')}/30.")
    else:
        notes.append(f"พบเกมใหม่ {len(new_games)} ตัววันนี้ นำโดย {new_games[0].get('title','?')} (score {new_games[0].get('score','?')}/30).")
        if top_genre:
            notes.append(f"กลุ่ม genre หลัก: {top_genre[0]} ({top_genre[1]} ตัว)")

    # IAP quality note
    iap_games = [g for g in new_games if g.get('iap_signal') == 'probable']
    if iap_games:
        notes.append(f"{len(iap_games)} ตัวมี IAP signal ชัด — มี monetization potential.")

    return notes


def fix_field_types(data):
    """Ensure daily_reports fields have correct types."""
    reports = data.get('daily_reports') or []
    for r in reports:
        # notes must be list
        notes = r.get('notes')
        if notes is None:
            r['notes'] = []
        elif isinstance(notes, str):
            r['notes'] = [notes]

        # game_snapshots must be list
        snaps = r.get('game_snapshots')
        if snaps is None:
            r['game_snapshots'] = []
        elif isinstance(snaps, dict):
            # Convert {game_id: {status, comment}} format to [{game_id, status, comment}]
            r['game_snapshots'] = [
                {'game_id': k, **v}
                for k, v in snaps.items()
            ]

        # Ensure lists
        r['new_game_ids'] = r.get('new_game_ids') or []
        r['top_pick_ids'] = r.get('top_pick_ids') or []

    # Ensure games fields
    for g in data.get('games') or []:
        g.setdefault('status', g.get('default_status', 'New'))
        g.setdefault('comment', '')
        g.setdefault('tags', [])
        g.setdefault('fit_with_th_top_genres', [])
        g.setdefault('status_history', [])


def main():
    with DATA_PATH.open('r', encoding='utf-8') as f:
        raw = f.read()
    data = json.loads(raw[:raw.rfind('}')+1])

    fix_field_types(data)

    # ── Deduplicate ─────────────────────────────────────────────────────────
    games = data.get('games') or []
    games, dup_count = deduplicate_games(games)
    data['games'] = games

    # ── Compute priority scores ────────────────────────────────────────────
    for g in games:
        g['priority_score'] = compute_priority_score(g)

    # ── Detect trending ────────────────────────────────────────────────────
    reports = sorted(data.get('daily_reports') or [], key=lambda x: x.get('date', ''), reverse=True)
    detect_trending(games, reports)

    # ── Auto-generate report notes ─────────────────────────────────────────
    for r in reports:
        if not r.get('notes') or (isinstance(r['notes'], list) and not any(r['notes'])):
            r['notes'] = auto_generate_report_notes(games, r)

    # ── Sort reports desc ──────────────────────────────────────────────────
    data['daily_reports'] = sorted(
        data.get('daily_reports') or [],
        key=lambda x: x.get('date', ''), reverse=True
    )

    # ── KPI summary ─────────────────────────────────────────────────────────
    reports = data['daily_reports']
    latest_report = reports[0] if reports else {}

    latest_new_ids = set(latest_report.get('new_game_ids') or [])
    latest_top_ids = set(latest_report.get('top_pick_ids') or [])

    trending_games = [g for g in games if g.get('trending_direction') == 'up']
    status_counts = Counter(g.get('status') or 'None' for g in games)

    kpis = data.setdefault('kpis', {})
    kpis['games_total'] = len(games)
    kpis['duplicates_removed'] = dup_count
    kpis['new_games_today'] = len(latest_new_ids)
    kpis['top_picks_today'] = len(latest_top_ids)
    kpis['trending_games'] = len(trending_games)
    kpis['watchlist_count'] = status_counts.get('Watchlist', 0)
    kpis['reviewing_count'] = status_counts.get('Reviewing', 0)
    kpis['dropped_count'] = status_counts.get('Drop', 0)
    kpis['avg_priority_score'] = (
        int(sum(g.get('priority_score', 0) for g in games) / len(games))
        if games else 0
    )
    kpis['last_scouted'] = latest_report.get('date', '')

    # ── Meta ────────────────────────────────────────────────────────────────
    meta = data.setdefault('meta', {})
    meta.setdefault('title', 'CN/KR Mobile Game Research Dashboard')
    meta.setdefault('timezone', 'Asia/Bangkok')
    meta.setdefault('source_of_truth', 'Obsidian Vault')
    meta.setdefault('delivery_target', 'Daily 08:00')
    meta.setdefault('status_options', DEFAULT_STATUS_OPTIONS)
    meta['date'] = latest_report.get('date', meta.get('date'))
    meta['generated_at'] = datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

    # ── Write ────────────────────────────────────────────────────────────────
    with DATA_PATH.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')

    print(json.dumps({
        'games_total': len(games),
        'duplicates_removed': dup_count,
        'new_games_today': kpis['new_games_today'],
        'top_picks_today': kpis['top_picks_today'],
        'trending_games': kpis['trending_games'],
        'avg_priority_score': kpis['avg_priority_score'],
        'report_date': meta.get('date'),
        'generated_at': meta['generated_at'],
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
