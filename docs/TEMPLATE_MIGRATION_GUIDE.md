# Calendar & Task Presets - PostgreSQL Storage

## Overview

Presets are stored in PostgreSQL with user-specific isolation, ACID transactions, and full database integration.

## Features

- ✅ Multi-user support (presets are user-specific)
- ✅ ACID transactions
- ✅ Better scalability
- ✅ Relationships with User model
- ✅ Easy backups and replication

## Usage

### Calendar Presets

```python
from src.core.calendar.presets import TemplateStorage
from src.database import get_db

db = next(get_db())
storage = TemplateStorage(db_session=db, user_id=user_id)

# Create
storage.create_template(
    name="standup",
    title="Daily Standup",
    duration_minutes=30,
    description="Team sync",
    location="Zoom",
    default_attendees=["team@example.com"],
    recurrence="DAILY"
)

# Get
template = storage.get_template("standup")  # Returns dict or None

# List
template_names = storage.list_templates()  # Returns List[str]
templates = storage.list_templates_full()  # Returns List[Dict]

# Update
storage.update_template(
    name="standup",
    duration_minutes=45  # Only update provided fields
)

# Delete (soft delete)
storage.delete_template("standup")
```

### Task Presets

```python
from src.core.tasks.presets import TaskTemplateStorage
from src.database import get_db

db = next(get_db())
storage = TaskTemplateStorage(db_session=db, user_id=user_id)

# Create
template = storage.create_template(
    name="weekly_review",
    description="Weekly Review",
    task_description="Weekly review and planning",
    priority="high",
    category="work",
    tags=["review", "planning"],
    recurrence="weekly"
)

# Expand with variables
expanded = storage.expand_template(
    template_name="project_kickoff",
    variables={"project_name": "Website Redesign"}
)
```

## Database Models

### MeetingTemplate
- `id`: Primary key
- `user_id`: Foreign key to users table
- `name`: Preset name (unique per user)
- `title`: Default meeting title
- `duration_minutes`: Default duration
- `description`: Default description
- `location`: Default location
- `default_attendees`: JSON array of email addresses
- `recurrence`: Recurrence pattern (e.g., "WEEKLY")
- `is_active`: Soft delete flag
- `created_at`, `updated_at`: Timestamps

### TaskTemplate
- `id`: Primary key
- `user_id`: Foreign key to users table
- `name`: Preset name (unique per user)
- `description`: Preset display name
- `task_description`: Task description (supports {variables})
- `priority`: Default priority ('low', 'medium', 'high')
- `category`: Default category
- `tags`: JSON array of tags
- `subtasks`: JSON array of subtask descriptions
- `recurrence`: Recurrence pattern
- `is_active`: Soft delete flag
- `created_at`, `updated_at`: Timestamps

## Setup

### 1. Run Database Migration

```bash
# Create the tables
python scripts/migrate_templates_to_db.py
```

Or if using Alembic:
```bash
alembic revision --autogenerate -m "Add preset tables"
alembic upgrade head
```

## Benefits

1. **Multi-user Support**: Each user has their own presets
2. **Data Integrity**: ACID transactions prevent corruption
3. **Relationships**: Presets linked to User model
4. **Querying**: Can search/filter presets efficiently
5. **Backups**: Included in database backups
6. **Scalability**: Handles concurrent access properly

## Troubleshooting

### "Template already exists" error
- Presets are unique per user. Check if the preset name already exists for that user.

### "User not found" error
- Ensure the `user_id` exists in the `users` table.

### Migration script fails
- Ensure PostgreSQL is running and `DATABASE_URL` is set correctly.
- Check database permissions.
