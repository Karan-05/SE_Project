'''Automation runner for downloading and ingesting Topcoder challenge data.'''

from __future__ import annotations

import argparse
import logging
import os
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import List

from setUp import setUp
from uploader import Uploader


@dataclass(frozen=True)
class DateWindow:
    start: date
    end: date


class Automation:
    '''
        This class contains functions to fetch and upload challenge to database
    '''

    def __init__(
        self,
        year: int,
        status: str,
        storage_directory,
        track: str = "Dev",
        db_config=None,
        *,
        force_refresh_members: bool = False,
        member_cache_ttl_hours: int | None = None,
    ) -> None:
        self.year = year
        self.status = status
        self.storage_directory = Path(storage_directory).expanduser().resolve()
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self.db_config = db_config
        self.track = track
        self.force_refresh_members = force_refresh_members
        self.member_cache_ttl_hours = member_cache_ttl_hours

    def month_windows(self) -> List[DateWindow]:
        """Return contiguous, gap-free month windows for the configured year."""
        windows: List[DateWindow] = []
        for month in range(1, 13):
            last_day = monthrange(self.year, month)[1]
            start_dt = date(self.year, month, 1)
            end_dt = date(self.year, month, last_day)
            windows.append(DateWindow(start=start_dt, end=end_dt))
        return windows

    def fetch_challenges(self):
        ''' Fetches challenge and memeber from the API and uploads the data 
            to the db
        '''
        for window in self.month_windows():
            logging.info(
                "Downloading data from %s to %s",
                window.start.isoformat(),
                window.end.isoformat(),
            )
            obj = {
                "storage_directory": self.storage_directory,
                "Start_date_start": window.start,
                "Start_date_end": window.end,
                "Status": self.status,
                "SortedOrder": "asc",
                "track": self.track,
            }

            setup_obj = setUp(obj)
            setup_obj.request_info()
            directory_name = f'challengeData_{window.start}_{window.end}'
            storage_path = os.path.join(self.storage_directory, directory_name)
            Uploader(
                storage_path,
                db_config=self.db_config,
                force_refresh_members=self.force_refresh_members,
                member_cache_ttl_hours=self.member_cache_ttl_hours,
            )


def main():
    logging.basicConfig(
        level=os.environ.get("TOPCODER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    parser = argparse.ArgumentParser(description='Automate Topcoder challenge download and upload')
    parser.add_argument('--year', type=int, required=True, help='Target year for automation run')
    parser.add_argument('--status', default='Completed', choices=['New', 'Draft', 'Cancelled', 'Active', 'Completed'],
                        help='Challenge status to filter by (default: Completed)')
    parser.add_argument('--storage', required=True, help='Directory to store downloaded challenge data')
    parser.add_argument('--track', default='Dev', choices=['Dev', 'DS', 'Des', 'QA'],
                        help='Challenge track filter (default: Dev)')
    parser.add_argument('--force-refresh-members', action='store_true',
                        help='Bypass member cache and refresh all profiles/skills')
    parser.add_argument('--member-cache-ttl-hours', type=int, default=None,
                        help='Only refresh member profiles older than this many hours (default: 720)')

    args = parser.parse_args()

    start = time.perf_counter()
    automation = Automation(
        year=args.year,
        status=args.status,
        storage_directory=args.storage,
        track=args.track,
        force_refresh_members=args.force_refresh_members,
        member_cache_ttl_hours=args.member_cache_ttl_hours,
    )
    automation.fetch_challenges()
    print(round(time.perf_counter() - start, 2))


if __name__ == '__main__':
    main()
