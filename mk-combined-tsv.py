#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv2/mdwiki-cacher/mk-combined-tsv.py' for testing
import sys
import requests
import json
import pymysql.cursors
from common import *

MDWIKI_CACHER_DATA = '/srv2/mdwiki-cacher/data/'
DBPARAMS_FILE = MDWIKI_CACHER_DATA + 'dbparams.json'
WPMED_LIST = 'http://download.openzim.org/wp1/enwiki/customs/medicine.tsv'

import logging
import logging.handlers
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(MDWIKI_CACHER_DATA + "mdwiki-list.log", 'a', maxBytes=5000, backupCount=10),
        logging.StreamHandler()
    ]
)

MAX_LOOPS = -1 # -1 is all, used for testing

# these pages cause mwoffliner to fail when used with cacher
EXCLUDE_PAGES = ['1%_Rule_(aviation_medicine)',
                '1%_rule_(aviation_medicine)',
                'Nitrous_oxide_50%-oxygen_50%']

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
    global mdwiki_list

    logging.info('Getting list of pages from mdwiki.')
    mdwiki_list = get_mdwiki_list() # list from mdwiki api
    logging.info('Processing downloaded list of redirects from mdwiki.')
    get_mdwiki_redirect_lists() # read from mdwiki db and process
    logging.info('Getting list of pages from EN WP.')
    enwp_list = get_enwp_list() # list from kiwix medicine

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

    logging.info('List Creation Succeeded.')
    sys.exit(0)

# https://en.wikipedia.org/w/api.php?action=query&prop=redirects&titles=Cilazapril

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
                logging.error('Request failed. Exiting.')
                sys.exit(1)
            pages = r['query']['allpages']
            apcontinue = r.get('continue',{}).get('apcontinue')
            for page in pages:
                #allpages[page['title']] = page
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
        mdwiki_redirects_hex = json.loads(result[0][0]) # result is tuple with json embedded
        return mdwiki_redirects_hex
    except Exception as error:
        logging.error(error)
        logging.error('Reading redirect.json failed.')
        raise

def get_enwp_list():
    enwp_pages = []
    try:
        r = requests.get(WPMED_LIST) # medicine.tsv
        wikimed_pages = r._content.decode().split('\n')
        for p in wikimed_pages[0:-1]:
            if p in EXCLUDE_PAGES:
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

def write_output(data, output_file):
    try:
        with open(output_file, 'w') as f:
            for item in data:
                f.write("%s\n" % item)
    except Exception as error:
        logging.error(error)
        logging.error('Failed to write to list file.')

if __name__ == "__main__":
    main()
