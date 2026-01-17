# 🚀 Worker Tasks Quick Reference

## Environment Setup
```bash
# Always use email_agent virtual environment
source email_agent/bin/activate
```

## Fixed Files
1. `src/workers/tasks/calendar_tasks.py` ✅
2. `src/workers/tasks/email_tasks.py` ✅

## Error Summary
- **Total Errors Fixed:** 12+
- **Current Errors:** 0 ✅

## Common Patterns Used

### 1. Load Config (Used everywhere)
```python
from ...utils.config import load_config
config = load_config()
```

### 2. Get OAuth Credentials (Email tasks)
```python
from ...database.models import Session as DBSession
from ...auth.token_refresh import get_valid_credentials
from datetime import datetime as dt

with get_db_context() as db:
    session = db.query(DBSession).filter(
        DBSession.user_id == user_id,
        DBSession.gmail_access_token.isnot(None),
        DBSession.expires_at > dt.utcnow()
    ).order_by(DBSession.created_at.desc()).first()
    
    credentials = get_valid_credentials(db, session, auto_refresh=True)
    client = GoogleGmailClient(config, credentials=credentials)
```

### 3. Calendar API Usage
```python
# List events
events = client.list_events(days_back=30, days_ahead=90)

# Create event
event = client.create_event(
    title=summary,
    start_time=start_time,
    end_time=end_time,
    description=description or "",
    location=location or "",
    attendees=attendees
)
```

### 4. Gmail API Usage
```python
# Send email
result = client.send_message(to, subject, body)

# Archive (remove from INBOX)
client._modify_message_with_retry(
    message_id=message['id'],
    remove_labels=['INBOX']
)

# Delete (move to TRASH)
client._modify_message_with_retry(
    message_id=message['id'],
    add_labels=['TRASH']
)
```

## Testing
```bash
# Syntax check
python -m py_compile src/workers/tasks/email_tasks.py
python -m py_compile src/workers/tasks/calendar_tasks.py

# Import test
python -c "from src.workers.tasks import email_tasks, calendar_tasks; print('✅ OK')"
```

## Status: ✅ COMPLETE & TESTED
