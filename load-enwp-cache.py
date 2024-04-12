#!/usr/bin/env python3
# su - www-data -s /bin/bash -c '/srv2/mdwiki-cacher/load-cache.py' for testing
import os
import logging
import sys
from datetime import timedelta, date
import time
import time
import requests
import json
import argparse
import pymysql.cursors
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
from requests_cache import RedisCache
from common import *
import constants as CONST

# ToDo set enwp cache to 1 or 7 day expire or check url against some date

MDWIKI_CACHER_DIR = '/srv/mdwiki-cacher/'
os.chdir(MDWIKI_CACHER_DIR)

enwp_api_session = CachedSession(CONST.enwp_api_cache, backend='filesystem')
enwp_list = []
failed_url_list = []

ENWP_CACHE_HIST_FILE = 'enwp_cache-refresh-hist.txt'
enwp_api = "https://en.wikipedia.org/w/api.php"

# test pages
p1 = 'Adenomere'
p2 = 'Brivudine'

VERBOSE = False

def main():
    global enwp_list

    set_logger()
    get_enwp_page_list()

    refresh_cache_since = '2024-04-01T14:13:19Z'
    refresh_cache_since = '1945-03-03T00:00:00Z'

    args = parse_args()
    if args.all:
        force_refresh = True
    else:
        force_refresh = False
    if args.interactive: # allow override of path
        sys.exit()

    refresh_cache_since = get_last_run()
    if not refresh_cache_since:
        sys.exit()

    logging.info('Refreshing cached pages with changes since: %s\n', str(refresh_cache_since))

    for page in enwp_list:
        if force_refresh:
            refresh_cache_page(page, force_refresh=True)
        else:
            last_edit_date = get_last_edit_date(page)
            if last_edit_date > refresh_cache_since:
                refresh_cache_page(page, force_refresh=True)
            else:
                refresh_cache_page(page)

    logging.info('Cache refreshed\n')

    with open(ENWP_CACHE_HIST_FILE, 'a') as f:
        f.write(date.today().strftime('%Y-%m-%dT%H:%M:%SZ') + '\n')

    write_list(failed_url_list, 'failed_enwp_urls.txt')

def get_last_run():
    # look for 2022-02-19 15:31:35,007 [INFO] List Creation Succeeded.
    last_success_date = None
    try:
        log_list = read_file_list(ENWP_CACHE_HIST_FILE)
        last_success_date = log_list[-1]
    except:
        print('Log file does not exist or not readable.')
    return last_success_date


def refresh_cache_page(page, force_refresh=False):
    url = CONST.enwp_domain + CONST.parse_page + page.replace('_', '%20').replace('/', '%2F').replace(':', '%3A').replace("'", '%27').replace("+", '%2B')
    get_enwp_url(url, force_refresh)
    url = CONST.enwp_domain + CONST.videdit_page + page
    get_enwp_url(url, force_refresh)

def get_enwp_url(url, force_refresh): # read url to load cache
    # check if url in cache
    # if not get it to add to cache
    # no retry

    if force_refresh or not enwp_api_session.cache.contains(url=url):
        global failed_url_list
        if VERBOSE:
            logging.info('Getting URL: %s\n', str(url))
        resp = enwp_api_session.get(url)
        if resp.status_code != 200 or resp.content.startswith(b'{"error":'):
            logging.error('Failed URL: %s\n', str(url))
            failed_url_list.append(url)
    return

def get_last_edit_date(page):
    params = {
        'action':"compare",
        'format':"json",
        'fromtitle':page,
        'totitle':page,
        'prop':'timestamp'
    }
    resp = requests.get(url=enwp_api, params=params)
    data = resp.json()
    return data['compare']['fromtimestamp']

def breakout_resp(resp):
    headers = calc_resp_headers(resp)
    # print(resp.content)
    return str(resp.status_code), headers, resp.content

def calc_resp_headers(resp):
    headers = [('Content-type', resp.headers['content-type'])]
    # the received content length is 1 less than true length
    #if 'content-length' in resp.headers:
    #    headers.append(('content-length', resp.headers['content-length']))
    return headers

def set_logger():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s',
                                '%m-%d-%Y %H:%M:%S')

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(formatter)

    file_handler = logging.FileHandler('mdwiki-refresh-cache.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stdout_handler)

def write_list(data, file):
    with open(file, 'w') as f:
        for d in data:
            f.write(d + '\n')

def get_enwp_page_list():
    global enwp_list
    #mdwiki_redirects = read_json_file('data/mdwiki_redirects.json')
    try:
        with open('data/enwp.tsv') as f:
            txt = f.read()
        enwp_list = txt.split('\n')[:-1]
    except Exception as error:
        print(error)
        print('Failed to read enwp.tsv. Exiting.')
        sys.exit(1)

def parse_args(): # for future
    parser = argparse.ArgumentParser(description="Create or refresh cache for mdwiki-cacher.")
    parser.add_argument("-i", "--interactive", help="exit so can be run interactively", action="store_true")
    parser.add_argument("-a", "--all", help="Print messages.", action="store_true")
    return parser.parse_args()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
