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
PROVIDER_CALENDAR = 'calendar'
PROVIDER_GOOGLE_TASKS = 'google_tasks'
PROVIDER_GOOGLE_KEEP = 'google_keep'
PROVIDER_LINEAR = 'linear'
PROVIDER_WEATHER = 'weather'
PROVIDER_MAPS = 'maps'

# Crawler Types (often map to providers, but can be distinct)
CRAWLER_EMAIL = 'email'
CRAWLER_DRIVE = 'drive'
CRAWLER_SLACK = 'slack'
CRAWLER_NOTION = 'notion'
CRAWLER_ASANA = 'asana'
CRAWLER_CALENDAR = 'calendar'
CRAWLER_TASKS = 'google_tasks'
CRAWLER_KEEP = 'google_keep'
CRAWLER_LINEAR = 'linear'
CRAWLER_CONTACTS = 'google_contacts'

# Service Names
SERVICE_UNIFIED_INDEXER = '[UnifiedIndexer]'
