# constants

from requests_cache import CachedSession, FileCache, DO_NOT_CACHE

mdwiki_domain = 'https://mdwiki.org'
enwp_domain = 'https://en.wikipedia.org'

cache_dir = '/srv/cache/'
mdwiki_api_cache  = cache_dir + 'mdwiki_api'
mdwiki_wiki_cache  = cache_dir + 'mdwiki_wiki'
mdwiki_other_cache  = cache_dir + 'mdwiki_other'
enwp_api_cache = cache_dir + 'enwp_api'
enwp_other_cache = cache_dir + 'enwp_other'

# paste these
# mdwiki_api_session = CachedSession(CONST.mdwiki_api_cache, backend='filesystem')
# mdwiki_wiki_session = CachedSession(CONST.mdwiki_wiki_cache, backend='filesystem')
# mdwiki_other_session = CachedSession(CONST.mdwiki_other_cache, backend='filesystem')
# enwp_api_session = CachedSession(CONST.enwp_api_cache, backend='filesystem')
# enwp_other_session = CachedSession(CONST.enwp_api_other_cache, backend='filesystem')

VERSION = '0.8'

parse_page = '/w/api.php?action=parse&format=json&prop=modules%7Cjsconfigvars%7Cheadhtml&page='
videdit_page = '/w/api.php?action=visualeditor&mobileformat=html&format=json&paction=parse&page='

uncached_session = CachedSession(expire_after=DO_NOT_CACHE)
