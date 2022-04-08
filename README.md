# mdwiki-cacher

## Installs

- apt install python3-pip
- pip3 install requests-cache

## Executables

### mdwiki-cacher.wsgi
- Lives at http://offline.mdwiki.org
- Replies to requests using cache
- Has special responses from urls that begin /nonwiki
- Returns status and an environment dump from /nonwiki/status
- Handles w/api.php style queries

### mk-combined-tsv.py
- Generates the Article List that drives the zim creation process
- Available at http://offline.mdwiki.org/nonwiki/lists/mdwikimed.tsv
- Also generates lists of mdwiki pages, en wp pages, and redirects used by mdwiki-cacher.wsgi
- MUST restart uwsgi after this runs so mdwiki-cacher.wsgi reloads the lists
- Typically takes less than 2 minutes
- Checks for several conditions to run, such as existence of medicine.tsv for current month

### load-mdwiki-cache.py
- Refreshes the mdwiki cache with pages that have changed since some date
- Reads last refresh date from history file

## Permissions
- common - root and 644
- mdwiki-cacher.wsgi  - root (can be www-data) and 644

### Cron jobs
30 22 *  *  * www-data  /bin/bash -c '/srv2/mdwiki-cacher/mk-combined-tsv.py'
0  1  *  *  7 www-data  /bin/bash -c '/srv2/mdwiki-cacher/load-mdwiki-cache.py'