# mdwiki-cacher

## Installs
- run setup
- edit /etc/crontab (see below)

### Install tailscale for access to mdwiki mysql server
- curl -fsSL https://tailscale.com/install.sh | sh
- obtain auth key from skiznet
- start tailscale with no inbound connections
- ? disable iptables with --netfilter-mode off; on by default
- subnets are blocked by default

```
tailscale up --shields-up --authkey <key obtained>
OR tailscale up --authkey <key obtained> --shields-up --netfilter-mode off

```
- get IP address (currently 100.127.141.126)
- authorize on Skiznet store

### Build initial caches
- obtain /srv/mdwiki-cacher/data/dbparams.json file to access mdwiki.org database
- su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/mk-combined-tsv.py -f'
- su - www-data -s /bin/bash -c '/usr/bin/python3 -i /srv/mdwiki-cacher/load-mdwiki-cache.py -i'
- this will exit after which run
- rebuild_cache()

### Edit config.json
- Edit /srv/mdwiki-cacher/config.json
- Add email addresses for sendmail

## Docs

https://requests-cache.readthedocs.io/en/stable/user_guide.html

## Executables

### Latest Version
- These are in git repo https://github.com/wpmed/mdwiki-cacher
- Branch main

### mdwiki-cacher.wsgi
- Lives at https://mdwiki.wmcloud.org/
- Replies to requests using cache
- Has special responses from urls that begin /nonwiki
- Returns status and an environment dump from /nonwiki/status
- Handles w/api.php style queries

### mk-combined-tsv.py
- Generates the Article List that drives the zim creation process
- Available at https://mdwiki.wmcloud.org/nonwiki/lists/mdwikimed.tsv
- Also generates lists of mdwiki pages, en wp pages, and redirects used by mdwiki-cacher.wsgi
- Reads redirects from mdwiki db using dbparams
- Causes reread of data by invoking https://mdwiki.wmcloud.org/nonwiki/commands/read-data
- OR can manually restart uwsgi after this runs so mdwiki-cacher.wsgi reloads the lists
- Typically takes less than 2 minutes
- Checks for several conditions to run
- Uses most recent medicine.tsv in case was not created in current month

### load-mdwiki-cache.py
- Refreshes the mdwiki cache with pages that have changed since some date
- Reads last refresh date from history file
- Can also be run interactively to rebuild the entire mdwiki cache calling rebuild_cache()

### Common Files
- common.py: library used by other executables
- constants.py: as the name suggests

## Cache Files
- Cache now stored in files not sqlite db
- see constants.py for details

## Permissions
- common - root and 644
- mdwiki-cacher.wsgi  - root (can be www-data) and 644

### Cron jobs
- add the following to /etc/crontab:

```
# for mdwiki-cacher
30 22 *  *  * www-data  /bin/bash -c '/srv/mdwiki-cacher/mk-combined-tsv.py'
0  1  *  *  7 www-data  /bin/bash -c '/srv/mdwiki-cacher/load-mdwiki-cache.py'
```
