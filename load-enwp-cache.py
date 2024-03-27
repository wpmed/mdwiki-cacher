#!/usr/bin/env python3
# su - www-data -s /bin/bash -c '/srv2/mdwiki-cacher/load-cache.py' for testing
import os
import logging
import sys
import datetime
import time
import requests
import json
import argparse
import pymysql.cursors
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
from requests_cache.backends.sqlite import SQLiteCache
from common import *

# set enwp cache to 1 or 7 day expire

MDWIKI_CACHER_DIR = '/srv2/mdwiki-cacher/'
os.chdir(MDWIKI_CACHER_DIR)

# HOME_PAGE = 'App/IntroPage'
RETRY_SECONDS = 20
RETRY_LOOP = 10
enwp_db ='enwp'

enwp_list = []
enwp_domain = 'https://en.wikipedia.org'

parse_page = '/w/api.php?action=parse&format=json&prop=modules%7Cjsconfigvars%7Cheadhtml&page='
videdit_page = '/w/api.php?action=visualeditor&mobileformat=html&format=json&paction=parse&page='

failed_url_list = []

def main():
    global enwp_list

    set_logger()

    get_enwp_page_list()
    for path in enwp_list:
        refresh_cache_page(path)

    write_list(failed_url_list, 'failed_urls.txt')

def refresh_cache_page(page):
    path = parse_page + page.replace('_', '%20').replace('/', '%2F').replace(':', '%3A').replace("'", '%27').replace("+", '%2B')
    get_enwp_url(path)
    path = videdit_page + page
    get_enwp_url(path)

def get_enwp_url(path): # read url to load cache
    # ADD RETRY
    url = enwp_domain + path
    enwp_session = CachedSession(enwp_db, backend='sqlite')
    #logging.info("Downloading from URL: %s\n", str(url))
    resp = enwp_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)

    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def retry_url(url):
    logging.info("Error or 503 in URL: %s\n", str(url))
    sleep_secs = 20
    for i in range(10):
        resp = requests.get(url)
        if resp.status_code != 503 and not resp.content.startswith(b'{"error":'):
            return resp
        logging.info('Retrying URL: %s\n', str(url))
        time.sleep(i * sleep_secs)
    logging.error('Failed URL: %s\n', str(url))
    failed_url_list.append(url)
    return None

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
