#!/usr/bin/env python3
import sys
import time
import requests
import json
import base64
# import pymysql.cursors
from urllib.parse import urljoin, urldefrag, urlparse, parse_qs
from requests_cache import CachedSession
# import  basicspider.sp_lib as sp

mdwiki_list = []
mdwiki_redirect_list = []
mdwiki_rd_lookup = {}

mdwiki_domain = 'https://mdwiki.org'
enwp_list = []
enwp_domain = 'https://en.wikipedia.org'

enwp_db ='http_cache'
mdwiki_db  = 'mdwiki'

#enwp_session = CachedSession(enwp_db, backend='sqlite')
#mdwiki_session = CachedSession(mdwiki_db, backend='sqlite')

def application(environ, start_response):
    req_method = environ['REQUEST_METHOD']
    # req_uri = environ['REQUEST_URI'].split('?')[0] # remove any cache buster
    req_uri = environ['REQUEST_URI']

    print(req_uri)
    if req_method == 'GET':
        log_request(req_uri, environ)
        if req_uri == '/status':
            # return env as test
            response_headers = [('Content-type', 'text/plain')]
            status = '200 OK'
            response_body = dump(environ)

        else:
            status, response_headers, response_body = do_GET(req_uri)
            #response_headers = [('Content-type', 'text/plain')]
            #status = '200 OK'
            #print(response_body)
        #print(status, response_headers)
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

    if '&titles=' in path: # is a redirect or a page request
        if '&prop=redirects' in path:
            return get_redir_path(path)
        else:
            # this is not expected
            print("Skipping Unknown Path: " + str(path))
    elif '&page=' in path:
        # page = path.split('&page=')[1]
        args = parse_qs(urlparse(path).query)
        page = args['page'][0].replace(' ', '_')
        if page in mdwiki_list:
            return get_mdwiki_url(path)
            #get_mdwiki_url(path)
        elif page in enwp_list:
            return get_enwp_url(path)
        else:
            print("Skipping Unknown Page: " + str(path))
            return respond_404()
    else:
        return get_mdwiki_url(path) # use mdwiki for anything else
        #get_mdwiki_url(path) # use mdwiki for anything else

def do_POST():
    pass

def dump(environ):
    print("Dump Environment")
    response_body = ['%s: %s' % (key, value) for key, value in sorted(environ.items())]
    response_body = '\n'.join(response_body)
    return response_body.encode()

def get_mdwiki_url( path):
    # ADD RETRY
    url = mdwiki_domain + path
    #logging.info("Downloading from URL: %s\n", str(url))
    mdwiki_session = CachedSession(mdwiki_db, backend='sqlite')
    resp = mdwiki_session.get(url)
    if resp.status_code == 503 or resp.content.startswith(b'{"error":'):
        resp = retry_url(url)
    # start_response(resp)
    # REWRITE  wfile.write(resp.content)
    return breakout_resp(resp)

def get_enwp_url(path):
    # ADD RETRY
    url = enwp_domain + path
    enwp_session = CachedSession(enwp_db, backend='sqlite')
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
    mdwiki_session = CachedSession(mdwiki_db, backend='sqlite')
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
        mdwiki_list = txt.split('\n')
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

# taken from sp_lib
def read_json_file(file_path):
    try:
        with open(file_path, 'r') as json_file:
            readstr = json_file.read()
            json_dict = json.loads(readstr)
        return json_dict
    except OSError as e:
        print('Unable to read url json file', e)
        raise

def log_request(req_uri, environ):
    print(f"GET request, Path: {str(req_uri)}")
    # \nHeaders:\n{str(environ)}\n")

def init():
    print('Starting httpd...\n')
    print('Getting page and redirect lists...\n')
    get_mdwiki_page_list()
    get_mdwiki_redirect_lists()
    get_enwp_page_list()
    print('Mdwiki cache ready\n')

# initialize lists
init()