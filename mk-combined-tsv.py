#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/mk-combined-tsv.py' for testing
import sys
import requests
import json
import pymysql.cursors
from datetime import datetime
import argparse
from common import *

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
mdwiki_redirects_raw = {}
mdwiki_redirect_list = []
mdwiki_rd_lookup = {}

# gets redirct data directly from mdwiki mysql

# get all non-redirect pages from mdwiki
#   get_mdwiki_page_list() (ns 0, 4)
# get medicine.tsv from open zim
# get mdwiki redirects
# calc and store as json:
# mdwiki_redirect_list = []
# mdwiki_rd_lookup = {}
# calc enwp_list
#   remove articles that are mdwiki redirects from
#   add any page in mdwiki_rd_lookup not in mdwiki_list
# combine lists into mdwikimed.tsv
# all mdwiki
# add any enwp not in mdwiki_redirect_list
# add any page in mdwiki_rd_lookup not already there

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
    logging.info('Processing downloaded list of redirects from mdwiki.')
    if not get_mdwiki_redirect_lists(): # read from mdwiki db and process
        logging.info('Getting list of redirects from mdwiki')
        return False
    logging.info('Getting list of pages from EN WP.')
    enwp_list = get_enwp_list() # list from kiwix medicine
    if not enwp_list:
        logging.info('Getting list of pages from EN WP Failed.')
        return False
    logging.info('Getting list of pages from EN WP Succeeded.')

    write_output(mdwiki_list, MDWIKI_CACHER_DATA + 'mdwiki.tsv')
    write_output(enwp_list, MDWIKI_CACHER_DATA + 'enwp.tsv')
    #en_wp_only = en_wp_med - mdwiki_list # items only in en wp
    #en_wip_redir = get_en_wp_redirects(en_wp_only)
    #combined = mdwiki_list + en_wp_med + en_wip_redir
    # combined = list(set(en_wp_med + en_wp_med))

    mdwiki_redirects = {}
    mdwiki_redirects['list'] = mdwiki_redirect_list
    mdwiki_redirects['lookup'] = mdwiki_rd_lookup

    logging.info('Writing redirects from mdwiki to json file.')
    write_json_file(mdwiki_redirects, MDWIKI_CACHER_DATA + 'mdwiki_redirects.json')

    # put mdwiki at start so any timeouts can be rerun more easily

    combined = mdwiki_list
    for page in enwp_list:
        if page not in mdwiki_list:
            combined.append(page)

    logging.info('Writing combined page list for mwoffliner.')
    write_output(combined, MDWIKI_CACHER_DATA + 'mdwikimed.tsv')

    return True

def force_cache_reload():
    read_data_url = 'http://offline.mdwiki.org/nonwiki/commands/read-data'
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
        logging.error('medicine.tsv not yet available for current month. Exiting.')
        return False

    return True

def get_mdwiki_list(apfilterredir='nonredirects'):
    md_wiki_pages = []
    for namesp in ['0']:
        # q = 'https://mdwiki.org/w/api.php?action=query&apnamespace=' + namesp + '&format=json&list=allpages&aplimit=max&apcontinue='
        q = 'https://mdwiki.org/w/api.php?action=query&apnamespace=' + namesp + '&format=json'
        q += '&list=allpages&apfilterredir=nonredirects&aplimit=max&apcontinue='
        apcontinue = ''
        loop_count = MAX_LOOPS
        while(loop_count):
            try:
                r = requests.get(q + apcontinue).json()
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
            if not apcontinue:
                break
            loop_count -= 1
    return md_wiki_pages

def get_mdwiki_redirect_lists():
    # redirect.json
    #   rd_from_id
    #   rd_to_namespace
    #   rd_to_title_hex
    #   rd_from_name_hex

    global mdwiki_redirects_raw
    global mdwiki_redirect_list
    global mdwiki_rd_lookup

    mdwiki_redirects_raw = {}
    mdwiki_redirect_list = []
    mdwiki_rd_lookup = {}
    #mdwiki_rd_lookup[HOME_PAGE] = [] # no redirects to home page

    try:
        mdwiki_redirects_hex = get_mdwiki_redirect_from_db()
    except Exception as error:
        logging.error(error)
        logging.error('Reading redirects from Database Failed.')
        return False

    for rd in mdwiki_redirects_hex:
        if rd['rd_to_namespace'] != 0: # skip if not in 0 namespace
            continue
        rd_from_title = bytearray.fromhex(rd['rd_from_name_hex']).decode()
        #print('hex: ' + rd['rd_from_name_hex'])
        # rd_from_title = decode_b64(rd['rd_from_name_hex'])
        #print('decoded: ' + rd_from_title)

        #print('hex2: ' + rd['rd_to_title_hex'])
        #rd_to_title = decode_b64(rd['rd_to_title_hex'])
        #print('decoded2: ' + rd_to_title)
        rd_to_title = bytearray.fromhex(rd['rd_to_title_hex']).decode()
        mdwiki_redirect_list.append(rd_from_title)
        if rd_to_title not in mdwiki_rd_lookup:
            mdwiki_rd_lookup[rd_to_title] = []
        mdwiki_rd_lookup[rd_to_title].append({'pageid': rd['rd_from_id'], 'ns': rd['rd_to_namespace'], 'title': rd_from_title})

    return True

def get_mdwiki_redirect_from_db():
    try:
        dbparams = read_json_file(DBPARAMS_FILE)
        dbconn = pymysql.connect(
                    host=dbparams['host'],
                    user=dbparams['user'],
                    password=dbparams['password'],
                    ssl=dbparams['ssl'],
                    database=dbparams['database']
                    )
        query = "SELECT JSON_ARRAYAGG(JSON_OBJECT('rd_from_id', r.rd_from, 'rd_from_name_hex', hex(p.page_title),"
        query += "'rd_to_title_hex', hex(r.rd_title), 'rd_to_namespace', r.rd_namespace))"
        query += " FROM redirect r INNER JOIN page p ON p.page_id = r.rd_from"
        cursor = dbconn.cursor()
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        dbconn.close()
        mdwiki_redirects_hex = json.loads(result[0][0]) # result is tuple with json embedded
        return mdwiki_redirects_hex
    except Exception as error:
        logging.error(error)
        logging.error('Reading redirect.json failed.')
        raise

def get_enwp_list():
    enwp_pages = []
    try:
        r = requests.get(WPMED_LIST) # medicine.tsv - gets latest, but not necessarily this month so force can work
        wikimed_pages = r._content.decode().split('\n')
        for p in wikimed_pages[0:-1]:
            if p in ENWP_EXCLUDE_PAGES:
                continue

            # Do Not Exclude because is somewhere in mdwiki titles
            # enwp_list needs these duplicates

            if p in mdwiki_redirect_list: # exclude because is somewhere in mdwiki redirects
                continue
            enwp_pages.append(p.replace(' ', '_'))
        # now add in any enwp pages that are the target of an mdwiki redirect
        for p in mdwiki_rd_lookup.keys():
            if p not in enwp_pages:
                enwp_pages.append(p.replace(' ', '_'))
    except Exception as error:
        logging.error(error)
        logging.error('Request for medicine.tsv failed. Ignoring.')
        enwp_pages = []
    return enwp_pages

def get_last_run():
    # look for something like 2022-02-19 15:31:35,007 [INFO] List Creation Succeeded.
    last_success_date = read_last_run('') # check current log
    if last_success_date:
        return last_success_date

    log_numbers = range(1, LOG_BACKUP_COUNT)
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
