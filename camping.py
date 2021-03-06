#!/usr/bin/env python3

import argparse
import json
import logging
import sys
import time
import os.path
from datetime import date, datetime, timedelta
from dateutil import rrule, relativedelta
from itertools import count, groupby

import requests
from fake_useragent import UserAgent


LOG = logging.getLogger(__name__)
formatter = logging.Formatter("%(asctime)s - %(process)s - %(levelname)s - %(message)s")
sh = logging.StreamHandler()
sh.setFormatter(formatter)
LOG.addHandler(sh)

BASE_URL = "https://www.recreation.gov"
AVAILABILITY_ENDPOINT = "/api/camps/availability/campground/"
MAIN_PAGE_ENDPOINT = "/api/camps/campgrounds/"
PERMITS_ENDPOINT = "/api/permits/"

INPUT_DATE_FORMAT = "%Y-%m-%d"
ISO_DATE_FORMAT_REQUEST = "%Y-%m-%dT00:00:00.000Z"
ISO_DATE_FORMAT_RESPONSE = "%Y-%m-%dT00:00:00Z"

SUCCESS_EMOJI = "🏕"
FAILURE_EMOJI = "❌"

DELAY_TIME_SEC = 20

headers = {"User-Agent": UserAgent().random}


def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist!" % arg)
    else:
        return open(arg, 'r')  # return an open file handle


def format_date(date_object, format_string=ISO_DATE_FORMAT_REQUEST):
    """
    This function doesn't manipulate the date itself at all, it just
    formats the date in the format that the API wants.
    """
    date_formatted = datetime.strftime(date_object, format_string)
    return date_formatted


def send_request(url, params):
    resp = requests.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        print("failedRequest -> " + 
            "ERROR, {} code received from {}: {}".format(
                resp.status_code, url, resp.text
            ),)
        return None
    return resp.json()


def get_park_information(park_id, start_date, end_date, campsite_type="STANDARD NONELECTRIC"):
    """
    This function consumes the user intent, collects the necessary information
    from the recreation.gov API, and then presents it in a nice format for the
    rest of the program to work with. If the API changes in the future, this is
    the only function you should need to change.

    The only API to get availability information is the `month?` query param
    on the availability endpoint. You must query with the first of the month.
    This means if `start_date` and `end_date` cross a month boundary, we must
    hit the endpoint multiple times.

    The output of this function looks like this:

    {"<campsite_id>": [<date>, <date>]}

    Where the values are a list of ISO 8601 date strings representing dates
    where the campsite is available.

    Notably, the output doesn't tell you which sites are available. The rest of
    the script doesn't need to know this to determine whether sites are available.
    """

    # Get each first of the month for months in the range we care about.
    start_of_month = datetime(start_date.year, start_date.month, 1)
    months = list(rrule.rrule(rrule.MONTHLY, dtstart=start_of_month, until=end_date))

    # Get data for each month.
    api_data = []
    for month_date in months:
        params = {"start_date": format_date(month_date)}
        LOG.debug("Querying for {} with these params: {}".format(park_id, params))
        url = "{}{}{}/month?".format(BASE_URL, AVAILABILITY_ENDPOINT, park_id)
        resp = send_request(url, params)
        if (resp != None) :
          api_data.append(resp)

    # Collapse the data into the described output format.
    # Filter by campsite_type if necessary.
    data = {}
    for month_data in api_data:
        for campsite_id, campsite_data in month_data["campsites"].items():
            available = []
            for date, availability_value in campsite_data["availabilities"].items():
                if availability_value != "Available":
                    continue
                if campsite_type and campsite_type != campsite_data["campsite_type"]:
                    continue
                available.append(date)
            if available:
                a = data.setdefault(campsite_id, [])
                a += available

    return data


def get_name_of_site(park_id):
    url = "{}{}{}".format(BASE_URL, MAIN_PAGE_ENDPOINT, park_id)
    resp = send_request(url, {})
    if resp == None :
      return resp
    return resp["campground"]["facility_name"]


def get_num_available_sites(park_information, start_date, end_date, nights=None):
    maximum = len(park_information)

    num_available = 0
    num_days = (end_date - start_date).days

    dates0 = [end_date - timedelta(days=i) for i in range(1, num_days + 1)]
    dates = []
    for d in dates0 :
        if (d.weekday() > 3 and d.weekday() <= 6) :
            dates.append(d)

    dates = set(format_date(i, format_string=ISO_DATE_FORMAT_RESPONSE) for i in dates)

    if nights not in range(1, num_days + 1):
        nights = num_days
        LOG.debug('Setting number of nights to {}.'.format(nights))

    for site, availabilities in park_information.items():
        # List of dates that are in the desired range for this site.
        desired_available = []
        for date in availabilities:
            if date not in dates:
                continue
            desired_available.append(date)
        if desired_available and consecutive_nights(desired_available, nights):
            num_available += 1
            print("Available site {}: {}".format(num_available, site))

    return num_available, maximum


def consecutive_nights(available, nights):
    """
    Returns whether there are `nights` worth of consecutive nights.
    """
    ordinal_dates = [datetime.strptime(dstr, ISO_DATE_FORMAT_RESPONSE).toordinal() for dstr in available]
    c = count()
    # print("c = {}".format(c))
    groups = groupby(ordinal_dates, lambda x: x-next(c))
    ret = 0
    for key, group in groups:
      l = list(group)
      l_len = len(l)
      if (l_len >= nights):
        ret = ret + 1
        l_d = [format_date(datetime.fromordinal(dor), INPUT_DATE_FORMAT) for dor in l]
        print("Option {} :".format(ret), l_d)

    return ret > 0
    # longest_consecutive = max((list(g) for _, g in groupby(ordinal_dates, lambda x: x-next(c))), key=len)
    # return len(longest_consecutive) >= nights


def main(parks):
    out = []
    availabilities = False

    if args.start_date == None or args.end_date == None:
        start_date = datetime.today()
        end_date = start_date + relativedelta.relativedelta(months=+8)
    else :
        start_date = args.start_date
        end_date = args.end_date

    LOG.debug("StartDate: {}, EndDate: {}".format(start_date, end_date))
        
    for park_id in parks:
        park_information = get_park_information(
            park_id, start_date, end_date, args.campsite_type
        )
        LOG.debug(
            "Information for park {}: {}".format(
                park_id, json.dumps(park_information, indent=2)
            )
        )
        name_of_site = get_name_of_site(park_id)
        if name_of_site == None :
          continue
        current, maximum = get_num_available_sites(
            park_information, start_date, end_date, nights=args.nights
        )
        if current:
            emoji = SUCCESS_EMOJI
            availabilities = True
        else:
            emoji = FAILURE_EMOJI

        print("{} {} ({}): {} site(s) available out of {} site(s)".format(
                        emoji, name_of_site, park_id, current, maximum
                    )
        )

        time.sleep(DELAY_TIME_SEC)

        # out.append(
        #     "{} {} ({}): {} site(s) available out of {} site(s)".format(
        #         emoji, name_of_site, park_id, current, maximum
        #     )
        # )

    if availabilities:
        print(
            "There are campsites available from {} to {}!!!".format(
                start_date.strftime(INPUT_DATE_FORMAT),
                end_date.strftime(INPUT_DATE_FORMAT),
            )
        )
    else:
        print("There are no campsites available :(")
    # print("\n".join(out))
    return availabilities


def valid_date(s):
    try:
        return datetime.strptime(s, INPUT_DATE_FORMAT)
    except ValueError:
        msg = "Not a valid date: '{0}'.".format(s)
        raise argparse.ArgumentTypeError(msg)

def positive_int(i):
    i = int(i)
    if i <= 0:
        msg = "Not a valid number of nights: {0}".format(i)
        raise argparse.ArgumentTypeError(msg)
    return i


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", "-d", action="store_true", help="Debug log level")
    parser.add_argument(
        "--start-date", help="Start date [YYYY-MM-DD]", type=valid_date
    )
    parser.add_argument(
        "--end-date",
        help="End date [YYYY-MM-DD]. You expect to leave this day, not stay the night.",
        type=valid_date,
    )
    parser.add_argument(
        "--nights",
        help="Number of consecutive nights (default is all nights in the given range).",
        type=positive_int,
    )
    parser.add_argument(
        "--campsite-type",
        help=(
            'If you want to filter by a type of campsite. For example '
            '"STANDARD NONELECTRIC" or TODO'
        ),
    )
    parks_group = parser.add_mutually_exclusive_group(required=True)
    parks_group.add_argument(
        "--parks",
        dest="parks",
        metavar="park",
        nargs="+",
        help="Park ID(s)",
        type=int,
    )
    parks_group.add_argument(
        "--parks_file",
        "-f",
        dest="parks_file",
        metavar="FILE",
        help="Read list of park ID(s) from json file",
        type=lambda x: is_valid_file(parser, x)
    )

    args = parser.parse_args()
    parks_json= False

    if args.debug:
        LOG.setLevel(logging.DEBUG)

    if args.parks != None :
        parks = args.parks
    else :
        parks_dict = json.load(args.parks_file)
        parks_json = True

    if parks_json :
        code = 0
        for park in parks_dict.keys() :
            print("Searching {}".format(park))
            try:
                code = (code + 0) if main(parks_dict[park]) else (code + 1)
            except Exception:
                print("Something went wrong")
                LOG.exception("Something went wrong")

        print("~eof~")
        sys.exit(code)

    else :
      try:
          code = 0 if main(parks) else 1
          print("~eof~")
          sys.exit(code)
      except Exception:
          print("Something went wrong")
          LOG.exception("Something went wrong")
          raise
