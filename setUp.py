''' This file '''
import sys
import json
from progress.bar import Bar
import os
from pathlib import Path
from typing import Any
from requests.exceptions import RequestException
from fetch_functions import get_data, CHALLENGES_ENDPOINT
from http_utils import request_with_retries


class setUp:
    ''' This class sets up the data calls based on the config provided'''

    def __init__(self, argsParsedData):
        data = self._normalise_args(argsParsedData)

        self.storage_directory = Path(data["storage_directory"]).expanduser().resolve()
        self.storage_directory.mkdir(parents=True, exist_ok=True)
        self.start_date_start_range = data["Start_date_start"]
        self.start_date_end_range = data["Start_date_end"]
        self.status = data["Status"]
        self.sortedOrder = data["SortedOrder"]
        self.track = data['track']

        self.params = {
            'page': 1,
            'perPage': 50,
            'tracks[]': [self.track],
            'sortBy': 'startDate',
            'startDateStart': self.start_date_start_range.isoformat(),
            'startDateEnd': self.start_date_end_range.isoformat(),
            'sortOrder': self.sortedOrder
        }
        if self.status != 'All':
            self.params['status'] = self.status

    def _normalise_args(self, argsParsedData: Any) -> dict:
        if hasattr(argsParsedData, "__dict__"):
            raw = vars(argsParsedData)
        else:
            raw = dict(argsParsedData)

        def _get(*keys, default=None):
            for key in keys:
                if key in raw and raw[key] is not None:
                    return raw[key]
            if default is not None:
                return default
            raise KeyError(f"Missing configuration keys: {keys}")

        storage_directory = _get("storage_directory", "Path")
        start_date = _get("Start_date_start", "Start_date")
        end_date = _get("Start_date_end", "End_date")

        start_date = self._ensure_date(start_date)
        end_date = self._ensure_date(end_date)

        status = _get("Status")
        sorted_order = _get("SortedOrder")
        track = _get("track", "Track")

        return {
            "storage_directory": storage_directory,
            "Start_date_start": start_date,
            "Start_date_end": end_date,
            "Status": status,
            "SortedOrder": sorted_order,
            "track": track,
        }

    @staticmethod
    def _ensure_date(date_obj):
        try:
            import datetime
            if isinstance(date_obj, datetime.datetime):
                return date_obj.date()
            if isinstance(date_obj, datetime.date):
                return date_obj
        except Exception:
            pass
        raise TypeError("Start and end dates must be datetime or date objects")

    def request_info(self):
        ''' This fuction displays the available data on the provided config '''

        params = self.params

        try:
            response = request_with_retries(
                "get",
                CHALLENGES_ENDPOINT,
                params=params,
                timeout=10.00,
            )
        except RequestException as exc:
            raise ConnectionError(f"Failed to retrieve challenges: {exc}") from exc

        challenge_list = response.json()

        directory_path = self.storage_directory

        demo_file = os.path.join(directory_path, 'demoData.json')
        with open(demo_file, "w", encoding="utf-8") as my_file:
            bar = Bar('Processing', max=1)
            json.dump(challenge_list, my_file, indent=4)
            bar.next()
            bar.finish()

        print(
            f'--- Sample data loaded to demoData.json at the path {directory_path} ---')

        total_pages = int(response.headers.get("X-Total-Pages", 1))
        total_challenges = int(response.headers.get("X-Total", len(challenge_list)))
        print(
            f'Do you want to go ahead and download {total_challenges} challenges? [y/n]?')
        # ans: str = input()
        print('The download will begin now')
        get_data(total_pages, total_challenges, self.params,
                 self.start_date_start_range, self.start_date_end_range, self.storage_directory)
        # if ans == 'y':
        #     print('The download will begin now')
        #     get_data(total_pages, total_challenges, self.params,
        #              self.start_date_start_range, self.start_date_end_range, self.storage_directory)
        # else:
        #     print('Program terminated')
        #     sys.exit()


# This store directly to DB
    # def get_data(self, total_pages: int, total_challenges: int):
    #     ''' This function downloads all the data based on the given config '''

    #     params = self.params
    #     # Database config can be added here
    #     db_Config = {
    #         "username": "root",
    #         "hostname": "localhost",
    #         "password": "password",
    #         "port": "3306",
    #         "database": "dataCollector",
    #         "table_name": "Challenges"
    #     }

    #     try:
    #         print('connecting database')
    #         my_db = dbConnect(db_Config)
    #         print(' database connected')
    #         bar = Bar('Processing', max=int(total_pages))
    #         for i in range(1, int(total_pages) + 1):
    #             params['page'] = i

    #             response = requests.get(
    #                 'http://api.topcoder.com/v5/challenges/', params=params,
    #                 timeout=2.00)

    #             if response.ok:
    #                 challenge_list = response.json()
    #                 my_db.upload_data(challenge_list, "Challenges")

    #                 print('Downloaded and store data from page {i}')
    #             else:
    #                 print('Could not download data from page {i}')
    #             bar.next()
    #         bar.finish()
    #         print('All data downloaded')
    #     except Exception as e:
    #         print('hello')
    #         print(e)
