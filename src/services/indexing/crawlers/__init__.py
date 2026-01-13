"""
Crawlers Package

Background indexers for various data sources.
Each crawler extends BaseIndexer to provide:
- Periodic sync with the data source
- Topic extraction from content
- Temporal linking to TimeBlocks
- Relationship strength tracking
"""

from src.services.indexing.crawlers.email import EmailCrawler
from src.services.indexing.crawlers.slack import SlackCrawler
from src.services.indexing.crawlers.notion import NotionCrawler
from src.services.indexing.crawlers.calendar import CalendarCrawler
from src.services.indexing.crawlers.asana import AsanaCrawler
from src.services.indexing.crawlers.tasks import TasksCrawler
from src.services.indexing.crawlers.keep import KeepCrawler

__all__ = [
    'EmailCrawler',
    'SlackCrawler',
    'NotionCrawler',
    'CalendarCrawler',
    'AsanaCrawler',
    'TasksCrawler',
    'KeepCrawler',
]
