#!/usr/bin/python3
# su - www-data -s /bin/bash -c '/srv/mdwiki-cacher/mk-combined-tsv.py' for testing
# su - www-data -s /bin/bash -c 'python3 -i /srv/mdwiki-cacher/mk-combined-tsv.py -i'
import fcntl
import json
import logging
import logging.handlers
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

import requests

# Bumped manually; sent to mdwiki.org/openZIM as part of the User-Agent so operators can
# identify which build of this script is making requests.
VERSION = "1.0.2"
USER_AGENT = f"MDWikiCacher/{VERSION} (https://mdwiki.wmcloud.org/nonwiki/status)"
HTTP_REQ_HEADERS =  {'User-Agent': USER_AGENT} # not auth_cacher_headers

# Directory holding all generated/state files. The production path is overridden by the
# local dev path below so the script can be run from a checkout without touching /srv.
MDWIKI_CACHER_DATA = Path('/srv/mdwiki-cacher/data/')
MDWIKI_CACHER_DATA = Path('./data/')

LOG_FILE = MDWIKI_CACHER_DATA / 'mdwiki-list.log'
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# Exclusive lock held for the duration of a run. This script is meant to be scheduled
# every minute, but a full mirrored-list build can take ~20 minutes, so without this an
# overlapping cron invocation would race the in-progress run on the same output files.
# Released automatically by the OS when the process exits or dies, so no stale-lock
# cleanup is needed -- see main().
BUILD_LOCK_FILE = MDWIKI_CACHER_DATA / "build.lock"

# --- mdwiki.org action API -------------------------------------------------
MDWIKI_ACTION_API_URL = 'https://mdwiki.org/w/api.php'
# Env vars holding bot-password credentials for MDWIKI_ACTION_API_URL; login is skipped
# (anonymous/read-only access) if either is unset.
MDWIKI_USERNAME_ENV = 'MDWIKI_USERNAME'
MDWIKI_PASSWORD_ENV = 'MDWIKI_PASSWORD'
# MediaWiki API limits on the `titles` parameter: at most this many titles per request...
MDWIKI_QUERY_BATCH_MAX_TITLES = 50
# ...and at most this many bytes once the titles are '|'-joined and URL-encoded.
MDWIKI_QUERY_BATCH_MAX_BYTES = 7400

# Articles that exist locally on mdwiki.org (i.e. "forked" from Wikipedia rather than mirrored).
FORKED_DATA_FILE = MDWIKI_CACHER_DATA / "forked.tsv"
# Minimum time between full forked-article crawls: refresh_forked_list paginates the
# entire mdwiki.org allpages list, which is too expensive to redo on every run if this
# script is scheduled every minute. Forked articles change rarely, so a stale list here
# doesn't hurt Kiwix/mirror change detection, which is what needs the tight cadence.
FORKED_LIST_REFRESH_INTERVAL = timedelta(hours=1)
FORKED_LIST_LAST_REFRESH_FILE = MDWIKI_CACHER_DATA / "forked_list_last_refresh.txt"

# --- Kiwix Medicine ----------------------------------------------------------
# Source of truth for which medicine articles Kiwix considers in-scope.
KIWIX_MEDICINE_URL = 'https://wp1.download.openzim.org/enwiki/customs/medicine.tsv'
# Full Kiwix Medicine article list (raw download from KIWIX_MEDICINE_URL).
KIWIX_MEDICINE_DATA_FILE = MDWIKI_CACHER_DATA / "kiwix_medicine.tsv"
# HTTP Last-Modified header from the last successful KIWIX_MEDICINE_URL download. Only
# written once the download has fully completed (see refresh_kiwix_medicine_list), so an
# interrupted download leaves it stale and gets retried next run instead of being
# mistaken for "nothing changed" with a truncated data file left in place.
KIWIX_MEDICINE_LAST_MODIFIED_FILE = MDWIKI_CACHER_DATA / "kiwix_medicine_last_modified.txt"

# --- Mirrored-list build (Kiwix Medicine filtered down to mdwiki.org's mirror) --------
# The (Kiwix last-modified, mdwiki dump_update, mdwiki wme_update) fingerprint that
# MIRRORED_MEDICINE_DATA_FILE was last *successfully* built from. Deliberately only
# written once build_mirrored_medicine_list finishes without error, so if it crashes
# partway through (it can take ~20 minutes), this stays stale and the next run correctly
# retries instead of concluding there's nothing to do. See rebuild_mirrored_medicine_list_if_needed.
MIRRORED_LIST_BUILD_STATE_FILE = MDWIKI_CACHER_DATA / "mirrored_list_build_state.json"
# Progress checkpoint written after every API batch during build_mirrored_medicine_list,
# so an interrupted build resumes from the last completed batch instead of starting over.
# Discarded once the build completes, or discarded and ignored if it no longer matches
# the current build inputs (a fresh Kiwix/mirror change invalidates in-progress progress).
MIRRORED_LIST_CHECKPOINT_FILE = MDWIKI_CACHER_DATA / "mirrored_list_checkpoint.json"
# Kiwix Medicine articles that are mirrored (not forked) on mdwiki.org, i.e. present in
# KIWIX_MEDICINE_DATA_FILE but absent from FORKED_DATA_FILE.
MIRRORED_MEDICINE_DATA_FILE = MDWIKI_CACHER_DATA / "mirrored_medicine.tsv"

# --- Combined output ---------------------------------------------------------
# Final combined output: FORKED_DATA_FILE + MIRRORED_MEDICINE_DATA_FILE.
MEDICINE_DATA_FILE = MDWIKI_CACHER_DATA / "medicine.tsv"
# Scratch file used while building MEDICINE_DATA_FILE, then atomically moved into place.
MEDICINE_TMP_DATA_FILE = MDWIKI_CACHER_DATA / "medicine.tsv.tmp"


class LoginError(Exception):
    """Raised when a bot-password login to the MediaWiki action API fails."""
    pass


class WikiClient:
    """Thin wrapper around a `requests.Session` for a MediaWiki action API.

    Logs in with the bot-password credentials from MDWIKI_USERNAME_ENV/MDWIKI_PASSWORD_ENV
    on construction (if set), then reuses the authenticated session's cookie jar for all
    subsequent `get` calls.
    """

    def __init__(self, action_api_url: str, domain: str = None):
        self.action_api_url = action_api_url  # e.g. "https://en.wikipedia.org/w/api.php"
        self.username = os.environ.get(MDWIKI_USERNAME_ENV)
        self.password = os.environ.get(MDWIKI_PASSWORD_ENV)
        self.domain = domain
        self.session = requests.Session()  # built-in cookie jar, persists across requests
        self.session.headers.update(HTTP_REQ_HEADERS)
        self.login()

    def get(self, params: dict, timeout: int = 10) -> requests.Response:
        """Issue a GET request against the action API with the given query params."""
        return self.session.get(self.action_api_url, params=params, timeout=timeout)

    def login(self, might_be_already_logged_in: bool = False):
        """Authenticate the session using a MediaWiki bot password.

        No-op if MDWIKI_USERNAME_ENV/MDWIKI_PASSWORD_ENV aren't set, leaving the client
        to make anonymous/read-only requests. Raises LoginError on failure, unless
        `might_be_already_logged_in` is set and the failure reason indicates the session
        is already authenticated.
        """
        if not (self.username and self.password):
            return

        logging.info(f"Login with bot password '{self.username}'")

        url = self.action_api_url + '?'
        # Add domain if configured
        if self.domain:
            url = f'{url}lgdomain={self.domain}&'

        # Getting token to login.
        token_url = (
            url
            + 'action=query&meta=tokens&type=login&format=json'
              '&formatversion=2'
        )
        resp = self.session.get(token_url)
        resp.raise_for_status()
        content = resp.content
        login_token = json.loads(content)['query']['tokens']['logintoken']

        # Logging in
        data = {
            'action': 'login',
            'format': 'json',
            'lgname': self.username,
            'lgpassword': self.password,
            'lgtoken': login_token,
        }
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        resp = self.session.post(self.action_api_url, data=data, headers=headers)
        resp.raise_for_status()
        resp_data = resp.json()

        login_result = resp_data.get('login', {}).get('result')
        if login_result != 'Success':
            reason = resp_data.get('login', {}).get('reason')
            if reason:
                if (
                    might_be_already_logged_in
                    and 'Cannot log in when using MediaWiki\\Session\\BotPasswordSessionProvider sessions' in reason
                ):
                    logging.info('Already logged in')
                else:
                    logging.error(reason)
                    raise LoginError('Login Failed')
            else:
                raise LoginError('Login Failed')
        else:
            logging.info('Login Success')

def main():
    """Entry point: configure logging then run the full medicine.tsv build.

    Acquires BUILD_LOCK_FILE for the duration of the run and exits immediately if another
    invocation already holds it (see BUILD_LOCK_FILE), instead of racing it.

    Any failure during the run is logged here, with a full traceback, before being
    re-raised. This is the single point every code path passes through, so individual
    functions don't each need their own try/except/log/raise -- that would either miss
    failures that happen outside of them (e.g. a network error while fetching mirrorinfo)
    or log the same exception more than once as it propagates back up.
    """
    set_logger(LOG_FILE)
    with open(BUILD_LOCK_FILE, "w") as lock_fh:
        try:
            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info("Another run is already in progress, skipping this invocation.")
            return
        try:
            make_medicine_tsv()
        except Exception:
            logging.error('build-medicine-tsv run failed.', exc_info=True)
            raise

def set_logger(log_file):
    """Configure root logging to write to both a rotating file handler and stdout."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.handlers.RotatingFileHandler(log_file, 'a', maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT),
            logging.StreamHandler()
        ]
    )

def make_medicine_tsv():
    """Rebuild MEDICINE_DATA_FILE from mdwiki.org and Kiwix Medicine.

    Refreshes the forked-article list from mdwiki.org (throttled, see refresh_forked_list)
    and the Kiwix Medicine list (only re-downloaded if changed upstream, see
    refresh_kiwix_medicine_list), then (re)builds the mirrored-article list only if Kiwix
    Medicine or mdwiki's mirror actually changed since the last *successful* build (see
    rebuild_mirrored_medicine_list_if_needed), before merging forked + mirrored articles
    into MEDICINE_DATA_FILE. Safe to schedule at a tight interval (e.g. every minute):
    main()'s lock skips overlapping runs, every step here is cheap to repeat except the
    mirrored-list build, and that one is both skipped when not needed and checkpointed
    so an interrupted run resumes instead of restarting from scratch.
    """
    # # Now start run
    wiki_client = WikiClient(MDWIKI_ACTION_API_URL)

    logging.info('Getting list of pages from mdwiki.')
    refresh_forked_list(wiki_client) # list of forked articles in mdwiki, throttled

    logging.info('Updating list of pages from Kiwix Medicine.')
    refresh_kiwix_medicine_list() # list from kiwix medicine

    logging.info("Checking if mirrored pages have been updated.")
    rebuild_mirrored_medicine_list_if_needed(wiki_client)

    merge_forked_and_mirrored()

    return True

def refresh_forked_list(wiki_client: WikiClient):
    """Write every non-redirect article title in mdwiki.org's main namespace to FORKED_DATA_FILE.

    Pages titles have spaces replaced with underscores (MediaWiki's canonical DB form).
    Paginates through `list=allpages` using `apcontinue` until the API stops returning one.
    Skipped if the last refresh is younger than FORKED_LIST_REFRESH_INTERVAL, since this
    crawl is too expensive to redo on every run when this script is scheduled tightly.
    Returns True if the list was refreshed, False if skipped.
    """
    last_refresh = FORKED_LIST_LAST_REFRESH_FILE.read_text() if FORKED_LIST_LAST_REFRESH_FILE.exists() else None
    if last_refresh and datetime.now() - datetime.fromisoformat(last_refresh) < FORKED_LIST_REFRESH_INTERVAL:
        logging.info(f"Forked list was refreshed less than {FORKED_LIST_REFRESH_INTERVAL} ago, skipping")
        return False

    count = 0
    last_report = 0
    with open(FORKED_DATA_FILE, "w") as fh:
        for namesp in ['0']:
            apcontinue = ''
            while(True):
                response = wiki_client.get({
                    'action': 'query',
                    'apnamespace': namesp,
                    'format': 'json',
                    'list': 'allpages',
                    'apfilterredir': 'nonredirects',
                    'aplimit': 'max',
                    'apcontinue': apcontinue,
                })
                response.raise_for_status()
                response_data = response.json()
                pages = response_data['query']['allpages']
                apcontinue = response_data.get('continue',{}).get('apcontinue')
                for page in pages:
                    fh.write(f"{page['title'].replace(' ', '_')}\n")
                    count += 1
                    if (last_report + 1000) <= count:
                        last_report += 1000
                        logging.info(f"{count} pages retrieved")

                if not apcontinue:
                    break
    logging.info(f"{count} forked pages retrieved")
    FORKED_LIST_LAST_REFRESH_FILE.write_text(datetime.now().isoformat())
    return True

def refresh_kiwix_medicine_list():
    """Refresh KIWIX_MEDICINE_DATA_FILE from KIWIX_MEDICINE_URL if it changed upstream.

    Compares the response's Last-Modified header against KIWIX_MEDICINE_LAST_MODIFIED_FILE
    (the value saved on the previous run) to avoid re-downloading an unchanged file.
    KIWIX_MEDICINE_LAST_MODIFIED_FILE is only written after the download fully succeeds
    (see the comment on that constant).
    """
    response = requests.get(KIWIX_MEDICINE_URL, timeout=10, stream=True, headers=HTTP_REQ_HEADERS) # medicine.tsv
    current_last_modified = response.headers.get("Last-Modified")
    previous_last_modified = KIWIX_MEDICINE_LAST_MODIFIED_FILE.read_text() if KIWIX_MEDICINE_LAST_MODIFIED_FILE.exists() else None
    if previous_last_modified == current_last_modified:
        logging.info("Kiwix Medicine has not changed.")
        return
    logging.info("Kiwix Medicine changed, downloading ...")
    with open(KIWIX_MEDICINE_DATA_FILE, "wb") as fh:
        for page in response.iter_lines():
            fh.write(page)
            fh.write(b"\n")
    KIWIX_MEDICINE_LAST_MODIFIED_FILE.write_text(current_last_modified)
    logging.info(f"{count_lines(KIWIX_MEDICINE_DATA_FILE)} pages saved")

def count_lines(file: Path):
    """Count newlines in `file` by reading it in chunks, without loading it fully into memory."""
    def blocks(file_handler, size=65536):
        while True:
            b = file_handler.read(size)
            if not b: break
            yield b

    with open(file, "r") as fh:
        return sum(bl.count("\n") for bl in blocks(fh))

def get_mirrorinfo(wiki_client: WikiClient) -> dict:
    """Fetch mdwiki.org's current mirror state via the `meta=mirrorinfo` API.

    Returns the raw `query.mirrorinfo` dict (notably `dump_update`/`wme_update`).
    Read-only: does not persist anything, see rebuild_mirrored_medicine_list_if_needed.
    """
    response = wiki_client.get({
        'action': 'query',
        'meta': 'mirrorinfo',
        'format': 'json',
        'formatversion': '2',
    })
    response.raise_for_status()
    return response.json().get('query', {}).get('mirrorinfo', {})

def rebuild_mirrored_medicine_list_if_needed(wiki_client: WikiClient):
    """(Re)build MIRRORED_MEDICINE_DATA_FILE if Kiwix Medicine or mdwiki's mirror changed.

    Compares the current (Kiwix last-modified, mdwiki dump_update, mdwiki wme_update)
    fingerprint against MIRRORED_LIST_BUILD_STATE_FILE -- the fingerprint the mirrored
    list was last *successfully* built from. That file is only written after
    build_mirrored_medicine_list completes without error, so if a previous build crashed
    partway through (it can take ~20 minutes), the fingerprint stays stale and this
    correctly decides a rebuild is still needed, even if Kiwix/mirror haven't changed
    again since. Returns True if a (re)build ran, False if already up to date.
    """
    mirrorinfo = get_mirrorinfo(wiki_client)
    current_inputs = {
        'kiwix_last_modified': KIWIX_MEDICINE_LAST_MODIFIED_FILE.read_text() if KIWIX_MEDICINE_LAST_MODIFIED_FILE.exists() else None,
        'dump_update': mirrorinfo.get('dump_update'),
        'wme_update': mirrorinfo.get('wme_update'),
    }
    last_built_inputs = json.loads(MIRRORED_LIST_BUILD_STATE_FILE.read_text()) if MIRRORED_LIST_BUILD_STATE_FILE.exists() else None

    if current_inputs == last_built_inputs:
        MIRRORED_LIST_CHECKPOINT_FILE.unlink(missing_ok=True)  # clear any stale leftover
        logging.info("Mirrored list already reflects the current Kiwix Medicine list and mdwiki mirror state.")
        return False

    logging.info('Kiwix Medicine or the mdwiki mirror changed since the last successful build; (re)building mirrored list.')
    build_mirrored_medicine_list(wiki_client, current_inputs)

    # Only recorded once the build has fully completed, so a crash partway through is
    # retried on the next run instead of being mistaken for "nothing to do".
    MIRRORED_LIST_BUILD_STATE_FILE.write_text(json.dumps(current_inputs))
    return True

def batch_titles(titles, max_titles=MDWIKI_QUERY_BATCH_MAX_TITLES, max_bytes=MDWIKI_QUERY_BATCH_MAX_BYTES):
    """Group `titles` into lists that fit within the MediaWiki API's `titles` param limits.

    Yields batches of at most `max_titles` titles, stopping a batch early if adding the
    next title would push the '|'-joined, URL-encoded size over `max_bytes`.
    """
    batch = []
    for title in titles:
        candidate = batch + [title]
        encoded_bytes = len(quote_plus('|'.join(candidate)).encode())
        if batch and (len(candidate) > max_titles or encoded_bytes > max_bytes):
            yield batch
            batch = [title]
        else:
            batch = candidate
    if batch:
        yield batch

def build_mirrored_medicine_list(wiki_client: WikiClient, build_inputs: dict):
    """Build MIRRORED_MEDICINE_DATA_FILE: Kiwix Medicine titles that are mirrored (not forked) on mdwiki.org.

    Queries mdwiki.org in batches (see batch_titles) with `redirects=1` so redirects are
    resolved to their target title. A title counts as "mirrored" when the API reports it
    as `known` (i.e. has a mdwiki.org page/redirect entry) but `missing` (no local content,
    meaning it's served via the mirror extension rather than forked). Titles that are fully
    missing (no entry at all) or that exist locally (forked) are counted but not written.

    This crawl takes on the order of 20 minutes and issues many API calls, so progress is
    checkpointed to MIRRORED_LIST_CHECKPOINT_FILE after every batch. If a previous call was
    interrupted (crash, restart, cron overlap) and `build_inputs` still matches what that
    checkpoint was taken against, processing resumes from the last completed batch instead
    of starting over; otherwise the stale checkpoint is discarded and the build starts
    fresh. `build_inputs` is opaque here -- it's the caller's fingerprint (see
    rebuild_mirrored_medicine_list_if_needed), only used to validate the checkpoint.
    """
    checkpoint = json.loads(MIRRORED_LIST_CHECKPOINT_FILE.read_text()) if MIRRORED_LIST_CHECKPOINT_FILE.exists() else None
    if checkpoint and checkpoint.get('build_inputs') == build_inputs:
        resume_from = checkpoint['processed_count']
        saved_count = checkpoint['saved_count']
        fully_missing_count = checkpoint['fully_missing_count']
        existing_count = checkpoint['existing_count']
        logging.info(f"Resuming mirrored list build from title {resume_from} (checkpoint found).")
    else:
        if checkpoint:
            logging.info("Discarding stale mirrored list checkpoint (Kiwix/mirror state changed since it was taken).")
        resume_from = 0
        saved_count = 0
        fully_missing_count = 0
        existing_count = 0

    with open(KIWIX_MEDICINE_DATA_FILE, "r") as fh:
        titles = [line.strip() for line in fh if line.strip()]

    processed_count = resume_from
    last_report = processed_count - (processed_count % 1000)

    with open(MIRRORED_MEDICINE_DATA_FILE, "a" if resume_from else "w") as out_fh:
        for batch in batch_titles(titles[resume_from:]):
            processed_count += len(batch)
            response = wiki_client.get({
                'action': 'query',
                'format': 'json',
                'redirects': '1',
                'formatversion': '2',
                'titles': '|'.join(batch),
            })
            response.raise_for_status()
            for page in response.json().get('query', {}).get('pages', []):
                if page.get('known') is True and page.get('missing') is True:
                    # write page title so that redirects are "solved"
                    out_fh.write(page['title'] + "\n")
                    saved_count += 1
                elif page.get('missing') is True:
                    fully_missing_count += 1
                else:
                    existing_count += 1
            if (last_report + 1000) <= processed_count:
                last_report += 1000
                logging.info(f"{processed_count} titles processed")

            out_fh.flush()
            MIRRORED_LIST_CHECKPOINT_FILE.write_text(json.dumps({
                'build_inputs': build_inputs,
                'processed_count': processed_count,
                'saved_count': saved_count,
                'fully_missing_count': fully_missing_count,
                'existing_count': existing_count,
            }))
    logging.info(f"{saved_count} pages saved")
    logging.info(f"{fully_missing_count} pages ignored because fully missing (not yet mirrored probably)")
    logging.info(f"{existing_count} pages ignored because forked locally")
    logging.info(f"TOTAL: {saved_count + fully_missing_count + existing_count}")
    MIRRORED_LIST_CHECKPOINT_FILE.unlink(missing_ok=True)
    return saved_count

def merge_forked_and_mirrored():
    """Concatenate FORKED_DATA_FILE and MIRRORED_MEDICINE_DATA_FILE into MEDICINE_DATA_FILE.

    Writes to MEDICINE_TMP_DATA_FILE first and moves it into place so readers never see
    a partially-written MEDICINE_DATA_FILE.
    """
    with open(MEDICINE_TMP_DATA_FILE, "w") as fh_target:
        with open(FORKED_DATA_FILE, "r") as fh_source:
            fh_target.writelines(fh_source.readlines())
        with open(MIRRORED_MEDICINE_DATA_FILE, "r") as fh_source:
            fh_target.writelines(fh_source.readlines())
    shutil.move(MEDICINE_TMP_DATA_FILE, MEDICINE_DATA_FILE)
    logging.info(f'Data has been merged in {MEDICINE_DATA_FILE}.')

if __name__ == "__main__":
    main()
