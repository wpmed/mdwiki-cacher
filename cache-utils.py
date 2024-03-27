#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/load-cache.py' for testing
# This started out as load-cache.py and is retained for the extra functions for testing and bulk loading
# load-mdwiki-cache.py should be used for loading the cache
# these are other utilities with some duplication
import os
MDWIKI_CACHER_DIR = '/srv/mdwiki-cacher/'
os.chdir(MDWIKI_CACHER_DIR)
import logging
import sys
from datetime import timedelta, date
import time
import requests
import json
import argparse
import pymysql.cursors
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
from requests_cache.backends.sqlite import SQLiteCache
from common import *

# HOME_PAGE = 'App/IntroPage'
RETRY_SECONDS = 20
RETRY_LOOP = 10
mdwiki_list = []
mdwiki_domain = 'https://mdwiki.org'
mdwiki_db  = 'mdwiki_api'
mdwiki_cache  = SQLiteCache(db_path=mdwiki_db)
mdwiki_session  = CachedSession(mdwiki_db, backend='sqlite')
mdwiki_uncached_session  = CachedSession(mdwiki_db, backend='sqlite', expire_after=0)
mdwiki_changed_list = []
mdwiki_changed_rd = []
enwp_list = []
enwp_domain = 'https://en.wikipedia.org'
enwp_db ='http_cache'
request_paths =  []
mdwiki_cached_urls = []
mdwiki_uncached_urls = []
mdwiki_uncached_pages = set()
un_zimmed_pages = set()
CACHE_HIST_FILE = 'cache-refresh-hist.txt'

parse_page = 'https://mdwiki.org/w/api.php?action=parse&format=json&prop=modules%7Cjsconfigvars%7Cheadhtml&page='
videdit_page = 'https://mdwiki.org/w/api.php?action=visualeditor&mobileformat=html&format=json&paction=parse&page='

# session = CachedSession(cache_control=True)
# https://requests-cache.readthedocs.io/en/stable/user_guide/headers.html
status503_list = []
failed_url_list = []

def main():
    global mdwiki_cached_urls
    global mdwiki_uncached_urls
    global mdwiki_uncached_pages

    set_logger()

    args = parse_args()
    # args.device is either value or None
    if args.interactive: # allow override of path
        sys.exit()

    refresh_cache_since = get_last_run()
    get_mdwiki_page_list()
    # in ? earlier version of CachedSession this is mdwiki_session.cache.urls, not a function
    mdwiki_cached_urls = mdwiki_session.cache.urls() # pretty slow


    logging.info('Cache utilities ready\n')

def get_last_run():
    # look for 2022-02-19 15:31:35,007 [INFO] List Creation Succeeded.
    last_success_date = None
    try:
        log_list = read_file_list(CACHE_HIST_FILE)
        last_success_date = log_list[-1]
    except:
        print('Log file does not exist or not readable.')
    return last_success_date

def get_mdwiki_changed_page_list(since):
    global mdwiki_changed_list
    global mdwiki_changed_rd
    mdwiki_changed_list = []
    mdwiki_changed_rd = []
    #since = '2021-11-01T00:00:00Z'
    # q = 'https://www.mdwiki.org/w/api.php?action=query&format=json&list=recentchanges&rclimit=max&rcnamespace=0|4&rctoponly'
    q = 'https://www.mdwiki.org/w/api.php?action=query&format=json&list=recentchanges&rclimit=max&rctoponly&rcprop=redirect|title'
    q += '&rcnamespace=0&rcstart=now&rcend=' + since
    rccontinue_param = ''
    loop_count = -1
    while(loop_count):
        try:
            r = requests.get(q + rccontinue_param).json()
        except Exception as error:
            logging.error(error)
            logging.error('Request failed. Exiting.')
            sys.exit(1)
        pages = r['query']['recentchanges']
        rccontinue = r.get('continue',{}).get('rccontinue')
        print(rccontinue)
        for page in pages:
            if page in mdwiki_changed_list:
                print(page + ' encountered more than once')
            if page.get('redirect') == '':
                mdwiki_changed_rd.append(page['title'].replace(' ', '_'))
            else:
                mdwiki_changed_list.append(page['title'].replace(' ', '_'))
        if not rccontinue:
            break
        rccontinue_param = '&rccontinue=' + rccontinue
        loop_count -= 1

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

########################################
# Below here are utilities for testing #
########################################

def load_cache():
    global mdwiki_cached_urls
    global mdwiki_uncached_urls
    global mdwiki_uncached_pages
    count = -1
    print('Getting mdwiki pages')
    get_mdwiki_page_list()

    print('Getting list of cached urls')
    mdwiki_cached_urls = list(mdwiki_session.cache.urls) # all urls in cache
    print('Searching for uncached urls')
    for page in mdwiki_list:
        url = parse_page + page.replace('_', '%20').replace('/', '%2F').replace(':', '%3A').replace("'", '%27')
        url2 = videdit_page + page
        missing = False
        if url not in mdwiki_cached_urls:
            mdwiki_uncached_urls.append(url)
            missing = True
        if url2 not in mdwiki_cached_urls:
            mdwiki_uncached_urls.append(url2)
            missing = True
        if missing:
            print(page)
            mdwiki_uncached_pages.append(page)

def add_to_cache():
    global status503_list
    sleep_secs = 20
    status503_list = []
    for url in mdwiki_uncached_urls:
        print('Getting ' + url)
        for i in range(10):
            resp = mdwiki_session.get(url)
            if resp.status_code == 503:
                status503_list.append(url)
                print('# %i Retrying URL: %s\n', i, str(url))
                time.sleep(i * sleep_secs)
            else:
                if resp.status_code != 200:
                    print(url)
                break

def copy_cache(): # was run from mdwiki-cache/cache-tests
    src_db ='../http_cache.sqlite'
    src_db ='has_errors.sqlite'
    dest_db  = 'mdwiki'

    src = SQLiteCache(db_path=src_db)
    dest  = SQLiteCache(db_path=dest_db)

    for key in list(src.keys()):
        r = src.get_response(key)
        if not r.url.startswith('https://mdwiki.org'):
            continue
        if r.status_code != 200:
            dest.save_response(r)
        else:
            if not r.content.startswith(b'{"error":'):
                # save in dest
                dest.save_response(r)
            else:
                # get without a 503 error
                sleep_secs = 20
                url = r.url
                print("Downloading from URL: %s\n", str(url))
                for i in range(10):
                    resp = requests.get(url)
                    if not resp.content.startswith(b'{"error":'):
                        dest.save_response(resp)
                        break
                    else:
                        print('# %i Retrying URL: %s\n', i, str(url))
                        time.sleep(i * sleep_secs)

def check_cache():
    global mdwiki_uncached_pages
    mdwiki_uncached_pages.clear()
    for page in mdwiki_list:
        url = parse_page + page.replace('_', '%20').replace('/', '%2F').replace(':', '%3A').replace("'", '%27').replace("+", '%2B')
        if not check_url_in_cache(url):
            mdwiki_uncached_pages.add(page)
            print('Parse URL not cached: ', url)
        url2 = videdit_page + page
        if not check_url_in_cache(url2):
            mdwiki_uncached_pages.add(page)
            print('Videdit URL not cached: ', url2)

def check_url_in_cache(url):
    return url in mdwiki_cached_urls

def find_to_encode():
    for u in mdwiki_cached_urls:
        if '?action=parse' in u and '&page=' in u:
            page = u.split('&page=')[1]
            if ':' in page or "'" in page or '/' in page or '_' in page:
                print(page)

def find_in_cache(match):
    for u in mdwiki_cached_urls:
        if match in u:
            print(u)

def check_zim_complete():
    global un_zimmed_pages
    un_zimmed_pages.clear()
    server_url = 'https://iiab.me/kiwix/mdwiki_en_all_2023-11/A/'
    #server_url = 'http://iiab-content/kiwix/mdwiki_en_all_2023-11/A/'
    for page in mdwiki_list:
        url = server_url + page
        r = requests.head(url)
        if r.status_code != 200:
            print(page)
            un_zimmed_pages.add(page)



def write_list(data, file):
    with open(file, 'w') as f:
        for d in data:
            f.write(d + '\n')

# https://www.mdwiki.org/w/api.php?action=query&format=json&list=recentchanges&rctoponly&rcstart=now&rcend=2021-11-01T00:00:00Z

# rcnamespace=0|4
# https://www.mdwiki.org/w/api.php?action=query&format=json&list=recentchanges&rclimit=max&rcnamespace=0|4&rctoponly&rcstart=now&rcend=2021-11-01T00:00:00Z
# changed_pages = 'https://www.mdwiki.org/w/api.php?action=query&format=json&list=recentchanges' # &rcend=2021-11-01T00:00:00Z &rctoponly

# "query":{"recentchanges":[{"type":"edit","ns":0,title":"Metastatic liver disease","pageid":61266,"revid":1274552,"old_revid":1274551,
# "rcid":144650,"timestamp":"2021-12-10T11:32:54Z"}, ... ]


def get_mdwiki_page_list():
    global mdwiki_list
    print('Getting mdwiki pages')
    with open('data/mdwiki.tsv') as f:
        txt = f.read()
    # last item can be ''
    mdwiki_list = txt.split('\n')[:-1]

def parse_args():
    parser = argparse.ArgumentParser(description="Create or refresh cache for mdwiki-cacher.")
    parser.add_argument("-i", "--interactive", help="exit so can be run interactively", action="store_true")
    parser.add_argument("-a", "--all", help="Print messages.", action="store_true")
    return parser.parse_args()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
