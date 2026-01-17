"""
Indexing Constants
Centralized constants for the indexing service and crawlers.
"""

# Integration Providers
PROVIDER_SLACK = 'slack'
PROVIDER_NOTION = 'notion'
PROVIDER_ASANA = 'asana'
PROVIDER_GMAIL = 'gmail'
PROVIDER_GOOGLE_DRIVE = 'google_drive'
PROVIDER_WEATHER = 'weather'
PROVIDER_MAPS = 'maps'

# Crawler Types (often map to providers, but can be distinct)
CRAWLER_EMAIL = 'email'
CRAWLER_DRIVE = 'drive'
CRAWLER_SLACK = 'slack'
CRAWLER_NOTION = 'notion'
CRAWLER_ASANA = 'asana'

# Service Names
SERVICE_UNIFIED_INDEXER = '[UnifiedIndexer]'
