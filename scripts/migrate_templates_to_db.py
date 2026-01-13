"""
Migration script to create template tables in PostgreSQL

Run this script to create the meeting_templates and task_templates tables.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database.database import get_engine
from src.database.models import Base, MeetingTemplate, TaskTemplate
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def create_tables():
    """Create template tables in the database"""
    try:
        engine = get_engine()
        
        logger.info("Creating template tables...")
        
        # Create only the template tables
        MeetingTemplate.__table__.create(engine, checkfirst=True)
        TaskTemplate.__table__.create(engine, checkfirst=True)
        
        logger.info("✅ Template tables created successfully!")
        logger.info("   - meeting_templates")
        logger.info("   - task_templates")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to create tables: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Template Storage Migration: Creating PostgreSQL Tables")
    print("=" * 60)
    print()
    
    success = create_tables()
    
    if success:
        print()
        print("✅ Migration completed successfully!")
        print()
        print("Next steps:")
        print("1. Update your code to use the new database-backed storage:")
        print("   from src.core.calendar.presets import TemplateStorage")
        print("   from src.core.tasks.presets import TaskTemplateStorage")
        print()
        print("2. Pass db_session and user_id when initializing:")
        print("   storage = TemplateStorage(db_session=db, user_id=user_id)")
        print()
    else:
        print()
        print("❌ Migration failed. Check the logs above for details.")
        sys.exit(1)

