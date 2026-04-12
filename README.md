# Game Research Dashboard

Static deployment package for the Obsidian-backed CN/KR mobile game research dashboard.

## Files
- `game-research-dashboard.html` — main dashboard UI
- `game-scout-daily.json` — current dataset served to the UI
- `assets/` — local fallback logo assets
- `vercel.json` — Vercel static deployment config

## Local preview
```bash
python3 -m http.server 8000
```
Then open `http://127.0.0.1:8000/game-research-dashboard.html`.

For local write-back features, use the richer local server instead:
```bash
python3 dashboard_server.py
```

## Vercel behavior
This deployment is static/read-only on Vercel:
- the dashboard loads the JSON dataset normally
- status/comment save actions are disabled on hosted/static environments
- snapshot saving is disabled on hosted/static environments

## Updating content
Edit `game-scout-daily.json`, optionally run:
```bash
python3 update_game_scout_data.py
```
Then commit and push to GitHub. Vercel will redeploy automatically.
