# mdwiki-cacher

## Installs

apt install python3-pip
pip3 install requests-cache

## Executables

### mdwiki-cacher.wsgi
- Lives at http://offline.mdwiki.org
- Replies to requests using cache
- Has special responses from urls that begin /nonwiki
- Returns an environment dump from /nonwiki/status

### mk-combined-tsv.py
- Generates the Article List that drives the zim creation process
- Available at http://offline.mdwiki.org/nonwiki/lists/mdwikimed.tsv
- Also generates lists of mdwiki pages, en wp pages, and redirects used by mdwiki-cacher.wsgi
- MUST restart uwsgi after this runs so mdwiki-cacher.wsgi reloads the lists
- Typically takes less than 2 minutes

### load-cache.py
- Refreshes the mdwiki cache with pages that have changed since some date