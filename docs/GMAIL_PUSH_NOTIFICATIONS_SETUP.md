# Gmail Push Notifications Setup Guide

## Overview

This guide explains how to set up Gmail Push Notifications for real-time email indexing. With push notifications enabled, new emails are indexed immediately when they arrive, eliminating the need for frequent polling.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Gmail Push Flow                           │
└─────────────────────────────────────────────────────────────┘

User Authenticates
       ↓
Set up Gmail Watch (via watch API)
       ↓
Gmail sends push notification → Webhook endpoint
       ↓
Webhook triggers Celery task → Index new emails
       ↓
Emails indexed in real-time!
```

## Prerequisites

1. **Google Cloud Project** with Gmail API enabled
2. **Pub/Sub Topic** configured in Google Cloud
3. **Public Webhook URL** accessible from the internet
4. **Gmail API Scopes** including `https://www.googleapis.com/auth/gmail.modify`

## Setup Steps

### 1. Create Google Cloud Pub/Sub Topic

Gmail requires a Pub/Sub topic to send notifications to:

```bash
# Create topic
gcloud pubsub topics create gmail-notifications

# Grant Gmail service account permission to publish
gcloud pubsub topics add-iam-policy-binding gmail-notifications \
  --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
  --role="roles/pubsub.publisher"
```

### 2. Configure Environment Variables

Add these to your `.env` file:

```bash
# Base URL for webhooks (must be publicly accessible)
WEBHOOK_BASE_URL=https://your-domain.com

# Google Cloud Project ID (required for Pub/Sub topic)
GOOGLE_CLOUD_PROJECT_ID=your-project-id

# Pub/Sub topic name (optional, defaults to 'gmail-notifications')
# Can be just the topic name (will be auto-formatted) or full path
GMAIL_PUBSUB_TOPIC=gmail-notifications
# OR provide full path:
# GMAIL_PUBSUB_TOPIC=projects/your-project-id/topics/gmail-notifications

# Optional: Channel token for verification (recommended for production)
GMAIL_WATCH_CHANNEL_TOKEN=your-secret-token-here
```

### 3. Set Up Gmail Watch for Users

When a user authenticates, set up Gmail watch:

```python
from src.services.gmail_watch_helper import setup_gmail_watch_for_user
from src.core.email.google_client import GoogleGmailClient

# After user authenticates
google_client = GoogleGmailClient(config=config, credentials=user_credentials)

result = await setup_gmail_watch_for_user(
    user_id=user.id,
    google_client=google_client,
    label_ids=['INBOX']  # Watch inbox only
)

if result['success']:
    print(f"Watch set up! Expires: {result['expiration_datetime']}")
    # Store expiration in database for renewal
else:
    print(f"Watch setup failed: {result['error']}")
    # Will fall back to polling
```

### 4. Webhook Endpoint

The webhook endpoint is automatically registered at:
- **URL**: `/api/gmail/push/notification`
- **Method**: POST
- **Headers**: Gmail sends various `X-Goog-*` headers

The endpoint is already implemented in `api/routers/gmail_push.py`.

### 5. Automatic Renewal

Gmail watch subscriptions expire after 7 days. Set up a periodic task to renew:

```python
from src.services.gmail_watch_helper import renew_gmail_watch_if_needed

# In a Celery Beat scheduled task (run daily)
@celery_app.task
def renew_gmail_watches():
    users = get_users_with_gmail_auth()
    for user in users:
        if user.gmail_watch_expiration:
            result = await renew_gmail_watch_if_needed(
                user_id=user.id,
                google_client=user.google_client,
                current_expiration_ms=user.gmail_watch_expiration
            )
```

## How It Works

### 1. Watch Setup

When `setup_gmail_watch_for_user()` is called:

1. Creates a watch subscription via Gmail API
2. Gmail starts monitoring the specified labels (default: INBOX)
3. Returns a `historyId` and expiration timestamp

### 2. Push Notification

When a new email arrives:

1. Gmail sends POST request to `/api/gmail/push/notification`
2. Webhook handler extracts user ID and triggers Celery task
3. Celery task `index_new_email_notification` runs
4. Task fetches new emails and indexes them immediately

### 3. Fallback to Polling

If push notifications fail or aren't configured:

- System automatically falls back to polling
- Inbox checked every 30 seconds (configurable)
- All folders checked every 60 seconds (configurable)

## Configuration Options

### Watch Labels

Control which labels to watch:

```python
# Watch inbox only (default, most efficient)
label_ids = ['INBOX']

# Watch multiple labels
label_ids = ['INBOX', 'IMPORTANT', 'STARRED']

# Watch all emails (not recommended - high volume)
label_ids = []  # Empty list watches all
```

### Polling Intervals (Fallback)

If push notifications aren't available:

```bash
# Inbox check interval (seconds)
INBOX_INDEXING_INTERVAL=30

# All folders check interval (seconds)
EMAIL_INDEXING_INTERVAL=60
```

## Monitoring

### Check Watch Status

```python
from src.services.gmail_watch_service import GmailWatchService

watch_service = GmailWatchService(google_client=client)
is_active = watch_service.is_watch_active(expiration_ms)

if not is_active:
    # Renew watch
    await setup_gmail_watch_for_user(...)
```

### Health Check

Check webhook endpoint health:

```bash
curl https://your-domain.com/api/gmail/push/health
```

Response:
```json
{
  "status": "healthy",
  "service": "gmail-push-notifications",
  "webhook_url": "https://your-domain.com"
}
```

## Troubleshooting

### Watch Setup Fails

**Error**: `insufficientPermissions`
- **Solution**: Ensure Gmail API scope `gmail.modify` is granted

**Error**: `invalidArgument`
- **Solution**: Verify Pub/Sub topic exists and Gmail has publish permission

### Notifications Not Received

1. **Check webhook URL is public**: Use `ngrok` or similar for local testing
2. **Verify Pub/Sub topic**: Ensure topic exists and permissions are correct
3. **Check logs**: Look for errors in webhook handler logs
4. **Verify watch is active**: Check expiration timestamp hasn't passed

### Fallback to Polling

If push notifications aren't working:

- System automatically uses polling fallback
- Check logs for watch setup errors
- Verify `WEBHOOK_BASE_URL` is set correctly
- Ensure Pub/Sub topic is configured

## Benefits

- **Real-time indexing**: Emails indexed within seconds of arrival
- **Reduced API calls**: No need for frequent polling
- **Better user experience**: New emails searchable immediately
- **Cost efficient**: Lower Gmail API quota usage
- **Automatic fallback**: Polling ensures reliability  

## Limitations

- **7-day expiration**: Watch subscriptions expire after 7 days (renewal needed)
- **Pub/Sub required**: Requires Google Cloud Pub/Sub setup
- **Public webhook**: Webhook URL must be publicly accessible
- **Label-based**: Can only watch specific labels (not all emails efficiently)  

## Next Steps

1. Set up Google Cloud Pub/Sub topic
2. Configure `WEBHOOK_BASE_URL` environment variable
3. Call `setup_gmail_watch_for_user()` after user authentication
4. Set up periodic renewal task (Celery Beat)
5. Monitor webhook endpoint for incoming notifications

## Example Integration

See `src/services/gmail_watch_helper.py` for helper functions and examples.

