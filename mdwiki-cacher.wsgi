#!/usr/bin/env python3
import sys
import time
from datetime import timedelta
import requests
import json
import base64
# import pymysql.cursors
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
from common import * # functions common to several modules

mdwiki_list = []
mdwiki_redirect_list = []
mdwiki_rd_lookup = {}

mdwiki_domain = 'https://mdwiki.org'
enwp_list = []
enwp_domain = 'https://en.wikipedia.org'

mdwiki_api_db  = 'mdwiki_api'
# these have 7 day expiry
mdwiki_wiki_db  = 'mdwiki_wiki'
mdwiki_other_db  = 'mdwiki_other'
enwp_db ='enwp'

expiry_days = timedelta(days=7)

nonwiki_url = '/nonwiki/'
article_list = 'data/mdwikimed.tsv'

# /robots.txt handled by nginx

# these are probing queris at the start of a run
mdwiki_urls = ['/',
                '/wiki/',
                '/wiki/App%2FIntroPage',
                '/api/rest_v1/page/mobile-sections/Main_Page',
                '/api/rest_v1/page/html/Main_Page',
                '/w/api.php?action=visualeditor&mobileformat=html&format=json&paction=parse&page=Main_Page',
                '/w/api.php?',
                '/w/api.php?action=query&format=json&prop=redirects%7Crevisions%7Ccoordinates&rdlimit=max&rdnamespace=',
                '/w/api.php?action=query&meta=siteinfo&siprop=namespaces%7Cnamespacealiases&format=json',
                '/wiki/?title=Mediawiki%3Aoffline.css&action=raw',
                '/logo.png',
                '/logo.svg',
                '/favicon.ico']

#enwp_session = CachedSession(enwp_db, backend='sqlite')
#mdwiki_session = CachedSession(mdwiki_db, backend='sqlite')

def application(environ, start_response):
    req_method = environ['REQUEST_METHOD']
    # req_uri = environ['REQUEST_URI'].split('?')[0] # remove any cache buster
    req_uri = environ['REQUEST_URI']

    print(req_uri)
    if req_method == 'GET':
        log_request(req_uri, environ)
        if req_uri in mdwiki_urls: # some hardcoded urls that must go to mdwiki
            status, response_headers, response_body = get_mdwiki_other_url(req_uri)

        elif req_uri.startswith(nonwiki_url):
            status, response_headers, response_body = do_nonwiki(req_uri, environ)

        else:
            status, response_headers, response_body = do_GET(req_uri)
        start_response(status, response_headers)
        # convert string response back to bytes
        # return [response_body.encode()]
        return [response_body]

    elif req_method == 'POST':
        pass

def do_GET(path):
    # _set_response()
    #resp = read_html_file('general.json')
    # 5 cases:
    #   is path with no titles - get_path with mdwiki_domain
    #   is redirect no titles - get_path with mdwiki_domain
    #   is redirect with titles - get_redirect
    #   is page=page on mdwiki - get_path with mdwiki_domain
    #   is page=page not on mdwiki - get_path with enwp_domain

    # args = parse_qs(urlparse(path).query) FUTURE

    # N.B. the param for getting pages is &page= not &title=
    # current code will just get all enwp from mdwiki

    # TO DO: INTEGRATE THE OTHER APIS

    if path.startswith('/w/api.php?'):
        if '&titles=' in path: # is a redirect or a page request
            if '&prop=redirects' in path:
                return get_redir_path(path)
            else:
                # this is not expected for zims
                # but can happen when mirroring site
                # print("Skipping Unknown Path: " + str(path))
                return get_mdwiki_other_url(path)
        elif '&page=' in path:
            # page = path.split('&page=')[1]
            args = parse_qs(urlparse(path).query)
            page = args['page'][0].replace(' ', '_')
            if page in mdwiki_list:
                return get_mdwiki_api_url(path)
            elif page in enwp_list:
                return get_enwp_url(path)
                # return get_enwp_url_direct(path) # changed 3/5/2022
            else:
                print("Skipping Unknown Page: " + str(path))
                return respond_404()
        else:
            return get_mdwiki_other_url(path) # use mdwiki for anything else

    elif path.startswith('/wiki/'):
        if path.startswith('/wiki/File:'):
            return get_mdwiki_other_url(path) # will route all media through mdwiki, but no choice
        else:
            # see if path is mdwiki or en wp and set domain
            article = path.split('/wiki/')[-1]
            if article in mdwiki_list:
                return get_mdwiki_wiki_url(path)
            elif article in enwp_list:
                return get_enwp_url(path)
                return get_enwp_url_direct(path) # changed 3/5/2022
            else:
                return respond_404()
    elif path.startswith('/w/'):
        return get_mdwiki_other_url(path)
    elif path.startswith('/media/'):
        return get_mdwiki_other_url(path)
    else:
        print("Skipping Unknown Page: " + str(path))
        return respond_404()

def do_POST():
    pass

def dump(environ):
    print("Dump Environment")
    response_body = ['%s: %s' % (key, value) for key, value in sorted(environ.items())]
    response_body = '\n'.join(response_body)
    return response_body

def get_mdwiki_api_url(path):
    # ADD RETRY
    url = mdwiki_domain + path
    #logging.info("Downloading from URL: %s\n", str(url))
    mdwiki_session = CachedSession(mdwiki_api_db, backend='sqlite')
    resp = mdwiki_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)
    # start_response(resp)
    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_mdwiki_wiki_url(path):
    # ADD RETRY
    url = mdwiki_domain + path
    #logging.info("Downloading from URL: %s\n", str(url))
    mdwiki_session = CachedSession(mdwiki_wiki_db, backend='sqlite', expire_after=expiry_days)
    resp = mdwiki_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)
    # start_response(resp)
    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_mdwiki_other_url(path):
    # ADD RETRY
    url = mdwiki_domain + path
    #logging.info("Downloading from URL: %s\n", str(url))
    mdwiki_session = CachedSession(mdwiki_other_db, backend='sqlite', expire_after=expiry_days)
    resp = mdwiki_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)
    # start_response(resp)
    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_enwp_url_direct(path): # not used as causes random failure
    # ADD RETRY
    url = enwp_domain + path
    headers = get_request_headers()
    resp = requests.get(url, headers)
    #if 'Portal' in resp.text:
    #print(resp.text)

    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_request_headers():
    headers = {}
    headers['User-Agent'] = 'MWOffliner/HEAD (info@iiab.me)'
    headers['Cookie'] = ''
    headers['Connection'] = 'close'
    return headers

def get_enwp_url(path):
    # ADD RETRY
    url = enwp_domain + path
    enwp_session = CachedSession(enwp_db, backend='sqlite', expire_after=expiry_days)
    #logging.info("Downloading from URL: %s\n", str(url))
    resp = enwp_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)

    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_redir_path(path): # top level
    # path queried for redirects can have multiple titles
    # break them out because some could be mdwiki and some enwp
    # the query also requests other properties than redirect
    # process redirect separately from the other properties
    # skip enwp page redirect if is name of mdwiki page or redirect
    args = parse_qs(urlparse(path).query)
    titles = args['titles'][0].split('|')
    base_query = path.split('&titles=')[0] + '&titles='
    more_rd_query = '/w/api.php?action=query&format=json&prop=redirects&rdlimit=max&rdnamespace=0&redirects=true&titles='
    enwp_session = CachedSession(enwp_db, backend='sqlite')
    mdwiki_session = CachedSession(mdwiki_api_db, backend='sqlite')
    pages_resp = {}
    title_page_ids = {}
    for title in titles:
        if title in mdwiki_list: # do one mdwiki title
            #print(f'Getting redirect for {title}')
            # remove redirect from query
            query = base_query.replace('&prop=redirects%7C', '&prop=') + title
            resp = mdwiki_session.get(mdwiki_domain + query)
            #resp = requests.session.get(mdwiki_domain + query)
            batch_resp = json.loads(resp.content)
            mdwiki_pageid = next(iter(batch_resp['query']['pages'])) # there should only be one
            title_page_ids[title] = {}
            title_page_ids[title]['mdwiki_pageid'] = mdwiki_pageid
            page_resp = batch_resp['query']['pages'][mdwiki_pageid]
            #pages_resp[title] = {}
            #pages_resp[title][mdwiki_pageid] = page_resp
            pages_resp[mdwiki_pageid] = page_resp

            redirects = get_mdwiki_redirects(title) # all redirects for this title known to mdwiki
            pages_resp[mdwiki_pageid]['redirects'] = redirects

            # get any redirects from EN WP
            # do not include if is name of page or redirect on mdwiki
            # mdwiki is primary so we only want any unknown redirects

            #'Gefitinib' in enwp_list
            #False
            # problem is that titles in enwp_list removed if in mdwiki_list
            # excluded in mk-combined
            if title in enwp_list:
                # now get list from enwp
                enwp_resp = enwp_session.get(enwp_domain + more_rd_query + title)
                wp_batch_resp = json.loads(enwp_resp.content)
                enwp_pageid = next(iter(wp_batch_resp['query']['pages'])) # there should only be one
                enwp_rd = wp_batch_resp['query']['pages'][enwp_pageid].get('redirects', []) # make it have an empty list instead of no list
                title_page_ids[title]['enwp_pageid'] = enwp_pageid # store in case need it

                for rd in enwp_rd:
                    if rd['title'] in mdwiki_list: # exclude because is somewhere in mdwiki titles
                        continue
                    if rd['title'] in mdwiki_redirect_list: # exclude because is somewhere in mdwiki redirects
                        continue
                    redirects.append(rd) # add it

                #pages_resp[title][mdwiki_pageid]['redirects'] = redirects
                pages_resp[mdwiki_pageid]['redirects'] = redirects
        else: # do one enwp title that is not in mdwiki
            resp = enwp_session.get(enwp_domain + base_query + title)
            #enwp_resp = requests.session.get(enwp_domain + base_query + title)
            batch_resp = json.loads(resp.content)
            enwp_pageid = next(iter(batch_resp['query']['pages'])) # there should only be one
            title_page_ids[title] = {}
            title_page_ids[title]['enwp_pageid'] = enwp_pageid
            title_rds = batch_resp['query']['pages'][enwp_pageid].get('redirects', [])

            # add any mdwiki redirects to this enwp page
            more_rds = mdwiki_rd_lookup.get(title, [])
            title_rds += more_rds

            if title_rds: # not sure if mwoffliner supports empty redirects list
                batch_resp['query']['pages'][enwp_pageid]['redirects'] = title_rds

            page_resp = batch_resp['query']['pages'][enwp_pageid]

            pages_resp[enwp_pageid] = page_resp

    # now reassemble response for all page tiles requested
    #print('***pages_resp')
    #print(pages_resp)
    batch_resp['query']['pages'] = pages_resp
    #print('***batch_resp')
    #print(batch_resp)

    outp = json.dumps(batch_resp)
    # start_response(resp)
    # REWRITE  wfile.write(bytes(outp, "utf-8"))

    status_code = '200'
    headers = [('Content-type', 'application/json; charset=utf-8')]

    return status_code, headers, outp.encode()

def retry_url( url):
    print("Error or 503 in URL: " + str(url))
    sleep_secs = 20
    for i in range(10):
        resp = requests.get(url)
        if resp.status_code != 503 and not resp.content.startswith(b'{"error":'):
            return resp
        print('Retrying URL: ' + str(url))
        time.sleep(i * sleep_secs)
    return None

def respond_404():
    # REWRITE  send_response(404)
    # REWRITE  send_header('Content-type', 'text/html')
    # REWRITE  end_headers()
    # REWRITE  wfile.write(b'Unknown Page')
    headers = [('Content-type', 'text/html; charset=UTF-8')]
    status_code = '404'
    body = b'Unknown Page'
    return status_code, headers, body


def start_response( resp):
    # REWRITE  send_response(resp.status_code)
    # REWRITE  send_header('Content-type', resp.headers['content-type'])
    #if 'content-length' in resp.headers:
    #    # REWRITE  send_header('content-length', resp.headers['content-length'])
    # REWRITE  end_headers()
    pass

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

def get_mdwiki_redirects(rd_to_title):
    # returns list of dict of redirects to td_to_title
    rd_list = mdwiki_rd_lookup.get(rd_to_title, []) # list of rd_from_titles for rd_to_titles
    return rd_list

def do_nonwiki(path, environ):
    # all special non-wiki requests come here
    status = '200 OK'
    response_headers = [('Content-type', 'text/plain')]
    if path == nonwiki_url + 'status':
        response_body = get_cacher_stat(environ)
    elif path == nonwiki_url + 'lists/mdwikimed.tsv':
        with open(article_list, 'rb') as f:
            response_body = f.read()
    elif path == nonwiki_url + 'commands/read-data':
        try:
            init()
            response_body = b'OK'
        except:
            response_body = b'Init Failed'
    else:
        response_body = b'???'
    return status, response_headers, response_body

def get_cacher_stat(environ):
    response_body = 'Cache Refresh History:\n'
    response_body += read_file('cache-refresh-hist.txt')

    response_body += '\nArticle Lists Refresh History:\n'
    hist = read_file_list('data/mdwiki-list.log')
    hist.reverse()
    for i in hist:
        response_body += i + '\n'
        if 'List Creation Succeeded' in i:
            break

    response_body += '\nZim Farm (mdwiki) - '
    stat =  get_zimfarm_stat('mdwiki')
    response_body += stat['most_recent_task']['updated_at'] + ': ' + stat['most_recent_task']['status'] +'\n'
    response_body += 'Zim Farm (mdwiki_app) - '
    stat =  get_zimfarm_stat('mdwiki_app')
    response_body += stat['most_recent_task']['updated_at'] + ': ' + stat['most_recent_task']['status'] +'\n'

    env = '\nEnvironment:\n' + dump(environ)
    response_body += env
    return response_body.encode()

def get_enwp_page_list():
    global enwp_list
    #mdwiki_redirects = read_json_file('data/mdwiki_redirects.json')
    try:
        with open('data/enwp.tsv') as f:
            txt = f.read()
        enwp_list = txt.split('\n')
    except Exception as error:
        print(error)
        print('Failed to read enwp.tsv. Exiting.')
        sys.exit(1)

def get_mdwiki_page_list():
    global mdwiki_list

    try:
        with open('data/mdwiki.tsv') as f:
            txt = f.read()
        mdwiki_list = txt.split('\n')[:-1]
        # last item can be ''
    except Exception as error:
        print(error)
        print('Failed to read mdwiki.tsv. Exiting.')
        sys.exit(1)

def get_mdwiki_redirect_lists():
    # redirect.json
    #   rd_from_id
    #   rd_to_namespace
    #   rd_to_title_hex
    #   rd_from_name_hex

    global mdwiki_redirect_list
    global mdwiki_rd_lookup

    mdwiki_redirects = read_json_file('data/mdwiki_redirects.json')
    mdwiki_redirect_list = mdwiki_redirects['list']
    mdwiki_rd_lookup = mdwiki_redirects['lookup']

def log_request(req_uri, environ):
    print(f"GET request, Path: {str(req_uri)} \n")
    # print(f"GET request, Path: {str(req_uri)} \nHeaders:\n{str(environ)}\n")

def init():
    print('Starting httpd...\n')
    print('Getting page and redirect lists...\n')
    get_mdwiki_page_list()
    get_mdwiki_redirect_lists()
    get_enwp_page_list()
    print('Mdwiki cache ready\n')

# initialize lists
init()