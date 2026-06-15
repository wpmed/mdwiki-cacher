#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/mk-combined-tsv.py' for testing
# su - www-data -s /bin/bash -c 'python3 -i /srv/mdwiki-cacher/mk-combined-tsv.py -i'
import sys
import requests
import json
import pymysql.cursors
from datetime import datetime
import argparse
from common import *
import constants as CONST

MDWIKI_CACHER_DATA = '/srv/mdwiki-cacher/data/'
DBPARAMS_FILE = MDWIKI_CACHER_DATA + 'dbparams.json'
LOG_FILE = MDWIKI_CACHER_DATA + 'mdwiki-list.log'
LOG_MAX_BYTES = 5000
LOG_BACKUP_COUNT = 5

WPMED_LIST = 'http://download.openzim.org/wp1/enwiki/customs/medicine.tsv'

import logging
import logging.handlers

MAX_LOOPS = -1 # -1 is all, used for testing

# these pages cause mwoffliner to fail when used with cacher
ENWP_EXCLUDE_PAGES = ['1%_Rule_(aviation_medicine)',
    '1%_rule_(aviation_medicine)',
    'Nitrous_oxide_50%-oxygen_50%']

MDWIKI_EXCLUDE_PAGES = ['Citation/CS1/styles.css',
    'Infobox/styles.css',
    'Navbar/styles.css',
    'Navbox/styles.css',
    'Reflist/styles.css']

mdwiki_list = []

def main():
    set_logger(LOG_FILE)

    args = parse_args()
    # args.device is either value or None
    if args.interactive: # allow override of path
        sys.exit()

    if args.force:
        run_flag = True
    else:
        run_flag = can_run(args.force)

    if run_flag:
        if mk_combined():
            logging.info('List Creation Succeeded.')
            force_cache_reload() # call cacher to reread data

def mk_combined():
    global mdwiki_list
    # Now start run
    logging.info('Getting list of pages from mdwiki.')
    mdwiki_list = get_mdwiki_list() # list from mdwiki api
    if not mdwiki_list:
        logging.info('Getting list of pages from mdwiki Failed.')
        return False

    logging.info('Getting list of pages from EN WP.')
    enwp_list = get_enwp_list() # list from kiwix medicine
    if not enwp_list:
        logging.info('Getting list of pages from EN WP Failed.')
        return False
    logging.info('Getting list of pages from EN WP Succeeded.')

    write_output(mdwiki_list, MDWIKI_CACHER_DATA + 'mdwiki.tsv')
    write_output(enwp_list, MDWIKI_CACHER_DATA + 'enwp.tsv')

    # put mdwiki at start so any timeouts can be rerun more easily

    combined = mdwiki_list
    for page in enwp_list:
        if page not in mdwiki_list:
            combined.append(page)

    logging.info('Writing combined page list for mwoffliner.')
    write_output(combined, MDWIKI_CACHER_DATA + 'mdwikimed.tsv')

    return True

def force_cache_reload():

    # ToDo restart uwsgi

    read_data_url = 'https://mdwiki.wmcloud.org/nonwiki/commands/read-data'
    r = requests.get(read_data_url)
    if r.status_code == 200:
        logging.info('Mdwiki cacher loaded data.')
    else:
        logging.info('Mdwiki cacher Failed to load data.')
    return

def can_run(force):
    # force:
    # if didn't find a last run date
    # if already ran
    # 7/20/2024 medicine.tsv is not being produced so allow old one
    # In future we may retry later in month

    if not force:
        last_run_date = get_last_run() # returns YYYY-MM-DD from end of log

        if not last_run_date:
            logging.error('Failed to get last run date. Exiting.')
            return False

        if last_run_date >= datetime.now().strftime('%Y-%m-01'):
            logging.info('Data already calculated for current month. Exiting.')
            return False

    if zimfarm_running('mdwiki'):
        logging.error('MWOFFLINER mdwiki run in progress. Exiting.')
        return False

    if zimfarm_running('mdwiki_app'):
        logging.error('MWOFFLINER mdwiki_app run in progress. Exiting.')
        return False

    if not is_medicine_tsv_avail():
        logging.info('medicine.tsv not available for current month. Using old copy.')
    #   return False

    return True

def get_mdwiki_list(apfilterredir='nonredirects'):
    md_wiki_pages = []
    for namesp in ['0']:
        q = 'https://mdwiki.org/w/api.php?action=query&apnamespace=' + namesp + '&format=json&list=allpages'
        q += '&apfilterredir=' + apfilterredir + '&aplimit=max&apcontinue='
        # q = 'https://mdwiki.org/w/api.php?action=query&apnamespace=' + namesp + '&format=json'
        # q += '&list=allpages&apfilterredir=nonredirects&aplimit=max&apcontinue='
        apcontinue = ''
        loop_count = MAX_LOOPS
        while(loop_count):
            try:
                r = requests.get(q + apcontinue, headers=CONST.cacher_headers).json()
            except Exception as error:
                logging.error(error)
                logging.error('Request mdwiki list failed. Exiting.')
                return None
            pages = r['query']['allpages']
            apcontinue = r.get('continue',{}).get('apcontinue')
            for page in pages:
                #allpages[page['title']] = page
                if page not in MDWIKI_EXCLUDE_PAGES:
                    md_wiki_pages.append(page['title'].replace(' ', '_'))
                    #md_wiki_pages.append(page['title'].replace(' ', '_'))
            if not apcontinue:
                break
            loop_count -= 1
    return md_wiki_pages

def get_enwp_list():
    enwp_pages = []
    try:
        r = requests.get(WPMED_LIST) # medicine.tsv - gets latest, but not necessarily this month so force can work
        wikimed_pages = r._content.decode().split('\n')
        for p in wikimed_pages[0:-1]:
            if p in ENWP_EXCLUDE_PAGES:
                continue
            enwp_pages.append(p.replace(' ', '_'))
    except Exception as error:
        logging.error(error)
        logging.error('Request for medicine.tsv failed. Ignoring.')
        enwp_pages = []
    return enwp_pages

def get_last_revision_list(target, page_list):
    revison_list = {}
    start_page = 0
    end_page = 0
    while(start_page < len(page_list)):
        end_page = start_page + 50
        revison_list.update(get_50_last_revision_list(target, page_list[start_page:end_page]))
        start_page = end_page
    return revison_list

def get_50_last_revision_list(target, batch_page_list):
    revison_list = {}
    if len(batch_page_list) > 50:
        return None
    pages = batch_page_list[0]
    for page in batch_page_list[1:]:
        pages += '|' + page
    if target == 'enwp':
        url = CONST.enwp_domain + CONST.last_revision_query + pages
    else:
        url = CONST.mdwiki_domain + CONST.last_revision_query + pages
    try:
        r = requests.get(url, headers=CONST.cacher_headers).json()
    except Exception as error:
        logging.error(error)
        logging.error('Request mdwiki list failed. Exiting.')
        return None
    for item in r['query']['pages']:
        if item.get('revisions'):
            revison_list[item['title'].replace(' ', '_')] = item['revisions'][0]['timestamp']
        else:
            print('page not found', item)
    return revison_list

def get_last_run():
    # look for something like 2022-02-19 15:31:35,007 [INFO] List Creation Succeeded.
    last_success_date = read_last_run('') # check current log
    if last_success_date:
        return last_success_date

    log_numbers = range(1, LOG_BACKUP_COUNT + 1)
    for log_number in log_numbers:
        last_success_date = read_last_run('.' + str(log_number))
        if last_success_date:
            return last_success_date
    return None

def read_last_run(log_num_str):
    try:
        log_list = read_file_list(LOG_FILE + log_num_str)
        for i in reversed(log_list):
            #print(i)
            if 'List Creation Succeeded' in i:
                last_success_date = i.split()[0]
                return last_success_date
    except:
        print('Log file does not exist or not readable.')
    return None

def write_output(data, output_file):
    try:
        with open(output_file, 'w') as f:
            for item in data:
                f.write("%s\n" % item)
    except Exception as error:
        logging.error(error)
        logging.error('Failed to write to list file.')

def set_logger(log_file):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(log_file, 'a', maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT),
            logging.StreamHandler()
        ]
    )

def parse_args():
    parser = argparse.ArgumentParser(description="Create or refresh page lists for mdwiki-cacher.")
    parser.add_argument("-i", "--interactive", help="exit so can be run interactively", action="store_true")
    parser.add_argument("-f", "--force", help="Run even if already run this month.", action="store_true")
    return parser.parse_args()

if __name__ == "__main__":
    main()
