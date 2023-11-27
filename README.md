# mdwiki-cacher

## Installs

- apt install python3-pip
- pip3 install requests-cache

## Docs

https://requests-cache.readthedocs.io/en/stable/user_guide.html

## Executables

### Deployed as of 11/27/2023
- mdwiki-cacher.wsgi from Apr  8  2022
- common.py from Apr  8  2022
- load-mdwiki-cache.py from May 17  2023
- mk-combined-tsv.py from May 28  2022

- These are in /srv2/downloads/mdwiki-cacher
- These are branch 0.4

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
- Causes reread of data by invoking http://offline.mdwiki.org/nonwiki/commands/read-data
- OR can manually restart uwsgi after this runs so mdwiki-cacher.wsgi reloads the lists
- Typically takes less than 2 minutes
- Checks for several conditions to run, such as existence of medicine.tsv for current month

### load-mdwiki-cache.py
- Refreshes the mdwiki cache with pages that have changed since some date
- Reads last refresh date from history file
- Can also be run interactively to rebuild the entire mdwiki cache calling rebuild_cache()

## Permissions
- common - root and 644
- mdwiki-cacher.wsgi  - root (can be www-data) and 644

### Cron jobs
30 22 *  *  * www-data  /bin/bash -c '/srv2/mdwiki-cacher/mk-combined-tsv.py'
0  1  *  *  7 www-data  /bin/bash -c '/srv2/mdwiki-cacher/load-mdwiki-cache.py'