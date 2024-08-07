#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/load-mdwiki-cache.py' for testing
# su - www-data -s /bin/bash -c 'python3 -i /srv/mdwiki-cacher/load-mdwiki-cache.py -i'
import os
MDWIKI_CACHER_DIR = '/srv/mdwiki-cacher/'
os.chdir(MDWIKI_CACHER_DIR)
import logging, logging.handlers
import sys
from datetime import timedelta, date
import time
import requests
import json
import subprocess
import argparse
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
from requests_cache import FileCache
from requests_cache import DO_NOT_CACHE
from common import *
import constants as CONST

# To Do
# Should we force inclusion of failed articles from previous run?

# HOME_PAGE = 'App/IntroPage'
RETRY_SECONDS = 20
RETRY_LOOP = 10
mdwiki_list = []
mdwiki_changed_list = []
mdwiki_changed_rd = []
enwp_list = []
request_paths =  []
mdwiki_cached_urls = []
mdwiki_uncached_urls = []
mdwiki_uncached_pages = []
MDWIKI_CACHE_HIST_FILE = 'mdwiki_cache-refresh-hist.txt'

mdwiki_api_session = CachedSession(CONST.mdwiki_api_cache, backend='filesystem')

parse_page = CONST.mdwiki_domain + CONST.parse_page
videdit_page = CONST.mdwiki_domain + CONST.videdit_page

# session = CachedSession(cache_control=True)
# https://requests-cache.readthedocs.io/en/stable/user_guide/headers.html
status503_list = []
failed_url_list = []

config = read_json_file('config.json')

def main():
    global mdwiki_cached_urls
    global mdwiki_uncached_urls
    global mdwiki_uncached_pages
    global mdwiki_list

    set_logger()
    mdwiki_list = get_mdwiki_page_list()

    args = parse_args()
    # args.device is either value or None
    if args.interactive: # allow override of path
        sys.exit()

    last_day_of_prev_month = date.today().replace(day=1) - timedelta(days=1)
    start_day_of_prev_month = date.today().replace(day=1) - timedelta(days=last_day_of_prev_month.day)
    refresh_cache_since = start_day_of_prev_month.strftime('%Y-%m-%dT%H:%M:%SZ')

    # refresh_cache_since = '2021-12-11T00:00:00Z'
    # refresh_cache_since = '2022-01-09T00:00:00Z'
    # refresh_cache_since = '2022-02-17T00:00:00Z'
    refresh_cache_since = '2022-03-03T00:00:00Z'

    refresh_cache_since = get_last_run()

    logging.info('Refreshing cached pages with changes since: %s\n', str(refresh_cache_since))

    refresh_cache(refresh_cache_since)
    logging.info('Cache refreshed\n')

    with open(MDWIKI_CACHE_HIST_FILE, 'a') as f:
        f.write(date.today().strftime('%Y-%m-%dT%H:%M:%SZ') + '\n')

    write_list(failed_url_list, 'failed_mdwiki_urls.txt')

    if len(failed_url_list) > 0:
        send_failed_url_email()

def get_last_run():
    # look for 2022-02-19 15:31:35,007 [INFO] List Creation Succeeded.
    last_success_date = None
    try:
        log_list = read_file_list(MDWIKI_CACHE_HIST_FILE)
        last_success_date = log_list[-1]
    except:
        print('Log file does not exist or not readable.')
    return last_success_date

def refresh_cache(since):
    get_mdwiki_changed_page_list(since)
    for page in mdwiki_changed_list:
        refresh_cache_page(page)

def rebuild_cache(mdwiki_list): # run interactively
    # see load_cache()
    set_logger()
    logging.info('Starting to create cache')
    for page in mdwiki_list:
        refresh_cache_page(page)

    # refresh_cache_page

    # verify space or underscore
    # get_mdwiki_changed_page_list converts
    # find_in_cache('Heart_failure')
    # https://mdwiki.org/w/api.php?action=visualeditor&mobileformat=html&format=json&paction=parse&page=Heart_failure
    # https://mdwiki.org/w/api.php?action=query&format=json&prop=revisions&rdlimit=max&rdnamespace=0%7C3000&redirects=true&titles=Heart_failure
    # N.B find_in_cache('Heart failure') returns nothing
    # so in cache all spaces converted to underscore
    # same in mdwikimed.tsv, so already done at source

    # logging.info('Refreshing cache for page: %s\n', str(page))

def refresh_cache_page(page):
    url = parse_page + page.replace('_', '%20').replace('/', '%2F').replace(':', '%3A').replace("'", '%27').replace("+", '%2B')
    refresh_cache_url(url)
    url2 = videdit_page + page
    refresh_cache_url(url2)

def refresh_cache_url(url):
    global failed_url_list
    get_except = False
    try:
        r = uncached_session.get(url, headers=CONST.cacher_headers)
    except:
        get_except = True

    if get_except or r.status_code == 503 or r.content.startswith(b'{"error":'):
        r = retry_url(url)
    if r:
        mdwiki_api_session.cache.save_response(r)
    else:
        logging.info('Failed to get URL: %s\n', str(url))
        failed_url_list.append(url)

def retry_url(url):
    logging.info("Error or 503 in URL: %s\n", str(url))
    sleep_secs = 20
    for i in range(10):
        get_except = False
        try:
            resp = requests.get(url, headers=CONST.cacher_headers) # did not use mdwiki_uncached_session to avoid conflict on retry
        except:
            get_except = True
        if not get_except and resp.status_code != 503 and not resp.content.startswith(b'{"error":'):
            return resp
        logging.info('Retrying URL: %s\n', str(url))
        time.sleep(i * sleep_secs)
    return None

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
            r = requests.get(q + rccontinue_param, headers=CONST.cacher_headers).json()
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

    file_handler = logging.handlers.RotatingFileHandler('mdwiki-refresh-cache.log', maxBytes=10000, backupCount=5)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stdout_handler)

def get_mdwiki_page_list():
    mdwiki_list = []
    print('Getting mdwiki pages')
    with open('data/mdwiki.tsv') as f:
        txt = f.read()
    # last item can be ''
    mdwiki_list = txt.split('\n')[:-1]
    return mdwiki_list

def send_failed_url_email():
    msg = 'Subject: Failed MdWiki URLs\n'
    msg += 'This is an automated email on ' + date.today().strftime("%m/%d/%Y") + '\n'
    msg += 'The following URLs failed to be added to the MdWiki cache:\n'
    with open('/tmp/failed_url_email.txt', 'w') as f:
        f.write(msg)
        for d in failed_url_list:
            f.write(d + '\n')
    for email in config['to_email']:
        completed_process = subprocess.run('/usr/sbin/sendmail ' + email + ' </tmp/failed_url_email.txt', shell=True)

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
