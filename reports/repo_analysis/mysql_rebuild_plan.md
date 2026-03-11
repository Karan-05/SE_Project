# MySQL Rebuild Plan

## Goals
1. Spin up a reproducible MySQL instance that matches the schema in `schema_registry.py`.
2. Supply credentials via environment variables (or `.env`) so `Uploader`, `automation.py`, and `analysis/report.py --from-api` can ingest directly from the live database.
3. Enable optional submission/member enrichment by providing `TOPCODER_BEARER_TOKEN`.

## Recommended Setup
1. **Launch MySQL 8 with Docker Compose**
   ```yaml
   # docker-compose.mysql.yml
   services:
     mysql:
       image: mysql:8.0
       restart: unless-stopped
       ports:
         - "3306:3306"
       environment:
         MYSQL_ROOT_PASSWORD: change_me
         MYSQL_DATABASE: dataCollector_v2
       volumes:
         - ./mysql_data:/var/lib/mysql
   ```
   ```bash
   docker compose -f docker-compose.mysql.yml up -d
   ```
2. **Populate `.env` (read by `config.py`)**
   ```ini
   TOPCODER_DB_HOST=127.0.0.1
   TOPCODER_DB_PORT=3306
   TOPCODER_DB_USER=root
   TOPCODER_DB_PASSWORD=change_me
   TOPCODER_DB_NAME=dataCollector_v2
   TOPCODER_DB_TABLE_CHALLENGES=Challenges
   TOPCODER_DB_TABLE_MEMBERS=Members
   TOPCODER_DB_TABLE_MAPPING=Challenge_Member_Mapping
   TOPCODER_API_BASE_URL=https://api.topcoder.com/v5
   # Optional, required for submissions/artifacts
   TOPCODER_BEARER_TOKEN=<paste token>
   ```
3. **Verify connectivity**
   ```bash
   mysql -h 127.0.0.1 -uroot -pchange_me -e "SHOW DATABASES;"
   ```

## Rebuild Procedure
1. **Regenerate challenge windows**
   ```bash
   source venv/bin/activate
   python automation.py --year 2024 --status Completed --storage ./challenge_data --track Dev --force-refresh-members
   ```
   - Repeat per year/track; pass `--member-cache-ttl-hours 24` during catch-up.
2. **Manual uploads** (if you want ad-hoc windows)
   ```bash
   python init.py ./challenge_data 2025-01-01 2025-01-31 -st Completed -tr Dev
   python - <<'PY'
   from uploader import Uploader
   Uploader('challenge_data/challengeData_2025-01-01_2025-01-31')
   PY
   ```
3. **Snapshot tables**
   ```bash
   python dbConnect.py --hostname 127.0.0.1 --password change_me --database dataCollector_v2 --export-table challenges
   python dbConnect.py --hostname 127.0.0.1 --password change_me --database dataCollector_v2 --export-table challenge_member_mapping
   python dbConnect.py --hostname 127.0.0.1 --password change_me --database dataCollector_v2 --export-table members
   ```

## Checklist Before Running
- [ ] Docker (or a native MySQL) running and reachable.
- [ ] `.env` or shell exports populated with DB + token values.
- [ ] `pip install -r requirements.txt` already complete.
- [ ] `TOPCODER_BEARER_TOKEN` verified via a quick `curl https://api.topcoder.com/v5/submissions?challengeId=<id>` to ensure 200 responses.

## Troubleshooting
- **Access denied** – confirm root password matches `.env`. `config.py` uses those env vars on every run.
- **SSL / auth plugin errors** – add `MYSQL_ROOT_HOST=%` to the compose file or create a dedicated user via `CREATE USER 'collector'@'%' IDENTIFIED WITH mysql_native_password BY 'pw';` and update `.env` accordingly.
- **Member refresh storms** – `Uploader` respects `TOPCODER_MEMBER_CACHE_TTL_HOURS` (default 720). Set `TOPCODER_FORCE_REFRESH_MEMBERS=false` unless backfilling stale handles.

## Current Status (2026-03-08)
- `docker compose -f docker-compose.mysql.yml up -d` and `docker-compose ...` both fail with `permission denied ... connect: operation not permitted` because the sandbox cannot write to `/Users/karanallagh/.colima/default/colima.yaml` or access the Colima socket.
- `colima start` also errors with `failed to read sysctl "sysctl.proc_translated": operation not permitted`.
- Until Colima/Docker privileges are granted (or the compose stack is run outside this environment), the MySQL rebuild plan above cannot be executed. All other steps (automation scripts, data exports) are ready once the database is reachable.
