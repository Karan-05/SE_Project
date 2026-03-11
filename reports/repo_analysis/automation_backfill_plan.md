# Topcoder API Backfill Plan

## Preconditions
- MySQL + credentials ready (see `mysql_rebuild_plan.md`).
- `.env` contains `TOPCODER_BEARER_TOKEN` if submissions/artifacts are desired.
- Virtualenv activated (`source venv/bin/activate`).

## Dry-Run a Single Window
```bash
python init.py ./challenge_data 2024-01-01 2024-01-31 -st Completed -tr Dev
python - <<'PY'
from uploader import Uploader
Uploader('challenge_data/challengeData_2024-01-01_2024-01-31')
PY
```
- Inspect `challenge_data/challengeData_2024-01-01_2024-01-31/` and DB row counts before scaling up.

## Automated Yearly Sweep
```bash
python automation.py \
  --year 2024 \
  --status Completed \
  --storage ./challenge_data \
  --track Dev \
  --member-cache-ttl-hours 24
```
- Repeat per track (`Dev`, `DS`, `Des`, `QA`). The automation runner creates monthly windows, downloads JSON, and immediately calls `Uploader`.

## Resuming / Rerunning
- Files are idempotent: rerunning the same window overwrites JSON and `dbConnect.upload_data` performs `ON DUPLICATE KEY UPDATE`.
- Use `--force-refresh-members` sparingly; otherwise rely on the TTL to avoid rate limiting.

## Monitoring API Usage
- The Topcoder v5 API surfaces `X-Total` and `X-Total-Pages` headers, already logged in `setUp.request_info`. Tail logs or set `TOPCODER_LOG_LEVEL=DEBUG` to see pagination progress.
- For large backfills, stagger track downloads to avoid hitting per-IP rate limits.

## Post-Download Steps
1. Re-run `scripts/export_real_tasks.py --challenge-dir challenge_data --output-dir data/raw` to include the new JSON windows.
2. Re-run `python -m src.data.preprocess --raw-dir data/raw --output-dir data/processed`.
3. Update `analysis/output/` via `python analysis/report.py --challenge-dir challenge_data --member-mapping snapshots/Challenge_Member_Mapping.csv --output-dir analysis/output`.
