"""Scrapy settings for senado_scrapy project."""

BOT_NAME = "senado_scrapy"
SPIDER_MODULES = ["senado_scrapy.spiders"]
NEWSPIDER_MODULE = "senado_scrapy.spiders"

# --- scrapy-impersonate (curl_cffi TLS fingerprinting) ---
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

DOWNLOAD_HANDLERS = {
    "http": "scrapy_impersonate.ImpersonateDownloadHandler",
    "https": "scrapy_impersonate.ImpersonateDownloadHandler",
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy_impersonate.RandomBrowserMiddleware": 1000,
}

# Sin UA propio — curl_cffi genera el correcto según el browser impersonado
USER_AGENT = ""

# WAF mitigation
ROBOTSTXT_OBEY = False
DOWNLOAD_TIMEOUT = 30
COOKIES_ENABLED = True

# Throttle conservador para no triggerar rate limiting
DOWNLOAD_DELAY = 0.5
CONCURRENT_REQUESTS_PER_DOMAIN = 8
CONCURRENT_REQUESTS = 16

# Autorthrottle deshabilitado — usamos throttle manual
AUTOTHROTTLE_ENABLED = False

# Retry con backoff
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504]

# Pipeline
ITEM_PIPELINES = {
    "senado_scrapy.pipelines.SenadoSQLitePipeline": 300,
}

# Output
LOG_LEVEL = "INFO"
