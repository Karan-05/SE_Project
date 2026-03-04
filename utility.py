import datetime
import argparse
from typing import List, Dict, Optional
''' This file stores all the utility methods '''

'''
    Refernce to below code
    https://stackoverflow.com/questions/25470844/specify-format-for-input-arguments-argparse-python
'''


def valid_date(s):
    ''' Converts string input to datetime object '''
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(s)
        raise argparse.ArgumentTypeError(msg)

#  from benjamin Cai.. Add proper reference


def parse_iso_dt(tc_date_str, fmt='%Y-%m-%d %H:%M:%S'):
    """ Parse a ISO-8601 formatted date string to given format
        default format is MySQL Datetime type compatible.
        TopCoder's date string is fixed to `yyyy-mm-ddThh:mm:ss.fffZ`
        the datetime.fromisoformat() method support string in the format of
        `YYYY-MM-DD[*HH[:MM[:SS[.mmm[mmm]]]][+HH:MM[:SS[.ffffff]]]]` P.S. no trailing 'Z' accepted!
    """
    return datetime.datetime.fromisoformat(tc_date_str[:-1]).strftime(fmt)


def calculate_prizes(prize_sets: Optional[List[Dict[str, str]]]) -> int:
    ''' Calculates total prize in dollar for a challenge '''
    if not prize_sets:
        return 0

    total_prize_value: int = 0
    for prize_group in prize_sets:
        prizes = prize_group.get("prizes", []) if isinstance(prize_group, dict) else []
        for prize_dict in prizes:
            total_prize_value += int(prize_dict.get("value", 0))

    return total_prize_value
