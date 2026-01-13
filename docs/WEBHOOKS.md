# Webhook Documentation

## Overview

Clavr Agent supports webhooks to send real-time notifications about events to external services. When an event occurs (like receiving an email, completing a task, or finishing an export), Clavr Agent can automatically POST a JSON payload to your configured webhook endpoints.

## Table of Contents

- [Getting Started](#getting-started)
- [Event Types](#event-types)
- [Webhook Payload](#webhook-payload)
- [Security (HMAC Signatures)](#security-hmac-signatures)
- [Retry Policy](#retry-policy)
- [API Endpoints](#api-endpoints)
- [Best Practices](#best-practices)
- [Examples](#examples)

## Getting Started

### 1. Create a Webhook Endpoint

First, you need to create an HTTP endpoint that can receive POST requests. This endpoint should:

- Accept POST requests with JSON payloads
- Return a 2xx status code (200-299) to indicate success
- Respond within the configured timeout (default: 10 seconds)
- Verify the HMAC signature (recommended)

Example endpoint (Node.js/Express):

```javascript
const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

app.post('/webhook', (req, res) => {
  // Verify signature (see Security section)
  const signature = req.headers['x-webhook-signature'];
  const secret = 'your-webhook-secret';
  
  if (!verifySignature(req.body, signature, secret)) {
    return res.status(401).send('Invalid signature');
  }
  
  // Process webhook event
  const { event_type, data } = req.body;
  console.log(`Received event: ${event_type}`, data);
  
  // Return success
  res.status(200).send('OK');
});

function verifySignature(payload, signature, secret) {
  const hmac = crypto.createHmac('sha256', secret);
  hmac.update(JSON.stringify(payload));
  const expectedSignature = 'sha256=' + hmac.digest('hex');
  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expectedSignature)
  );
}

app.listen(3000);
```

### 2. Create a Webhook Subscription

Use the API to create a webhook subscription:

```bash
curl -X POST https://your-api-domain.com/api/webhooks \
  -H "Authorization: Bearer YOUR_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/webhook",
    "event_types": ["email.received", "task.completed"],
    "description": "Production webhook",
    "retry_count": 3,
    "timeout_seconds": 10
  }'
```

Response:

```json
{
  "id": 1,
  "user_id": 123,
  "url": "https://example.com/webhook",
  "event_types": ["email.received", "task.completed"],
  "description": "Production webhook",
  "secret": "abc123...xyz",
  "is_active": true,
  "retry_count": 3,
  "timeout_seconds": 10,
  "created_at": "2024-01-15T10:30:00Z",
  "total_deliveries": 0,
  "successful_deliveries": 0,
  "failed_deliveries": 0
}
```

**Important:** Save the `secret` value! It's only returned during creation and is used to verify webhook signatures.

### 3. Test Your Webhook

Test your webhook endpoint:

```bash
curl -X POST https://your-api-domain.com/api/webhooks/1/test \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```

## Event Types

Clavr Agent supports the following webhook event types:

### Email Events

| Event Type | Description |
|------------|-------------|
| `email.received` | Email received and indexed |
| `email.sent` | Email sent successfully |
| `email.indexed` | Email indexed in vector database |

**Payload Example:**
```json
{
  "event_type": "email.received",
  "event_id": "msg-123456",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "message_id": "msg-123456",
    "subject": "Meeting Reminder",
    "from": "john@example.com",
    "to": ["me@example.com"],
    "date": "2024-01-15T10:00:00Z",
    "body_preview": "Don't forget about our meeting at 2 PM..."
  }
}
```

### Calendar Events

| Event Type | Description |
|------------|-------------|
| `calendar.event.created` | Calendar event created |
| `calendar.event.updated` | Calendar event updated |
| `calendar.event.deleted` | Calendar event deleted |

**Payload Example:**
```json
{
  "event_type": "calendar.event.created",
  "event_id": "cal-789",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "event_id": "cal-789",
    "title": "Team Meeting",
    "start": "2024-01-15T14:00:00Z",
    "end": "2024-01-15T15:00:00Z",
    "location": "Conference Room A",
    "attendees": ["john@example.com", "jane@example.com"]
  }
}
```

### Task Events

| Event Type | Description |
|------------|-------------|
| `task.created` | Task created |
| `task.updated` | Task updated |
| `task.completed` | Task marked as completed |
| `task.deleted` | Task deleted |

**Payload Example:**
```json
{
  "event_type": "task.completed",
  "event_id": "task-456",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "task_id": "task-456",
    "title": "Review PR #123",
    "description": "Review and approve pull request",
    "completed_at": "2024-01-15T10:30:00Z",
    "due_date": "2024-01-15T17:00:00Z"
  }
}
```

### Indexing Events

| Event Type | Description |
|------------|-------------|
| `indexing.started` | Indexing process started |
| `indexing.completed` | Indexing process completed |
| `indexing.failed` | Indexing process failed |

**Payload Example:**
```json
{
  "event_type": "indexing.completed",
  "event_id": "job-abc123",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "job_id": "job-abc123",
    "item_count": 150,
    "duration_seconds": 45,
    "errors": 0
  }
}
```

### User Events

| Event Type | Description |
|------------|-------------|
| `user.created` | User account created |
| `user.settings.updated` | User settings updated |

### System Events

| Event Type | Description |
|------------|-------------|
| `export.completed` | Data export completed |
| `sync.completed` | Sync process completed |

**Export Payload Example:**
```json
{
  "event_type": "export.completed",
  "event_id": "export-xyz789",
  "timestamp": "2024-01-15T10:30:00Z",
  "data": {
    "export_id": "export-xyz789",
    "format": "json",
    "file_path": "/exports/data-2024-01-15.json",
    "size_bytes": 1048576,
    "item_count": 500
  }
}
```

## Webhook Payload

All webhook payloads follow this structure:

```json
{
  "event_type": "string",      // Event type (e.g., "email.received")
  "event_id": "string",         // Unique event identifier
  "timestamp": "ISO8601",       // Event timestamp
  "data": {                     // Event-specific data
    // Varies by event type
  }
}
```

## Security (HMAC Signatures)

All webhook requests include an HMAC-SHA256 signature in the `X-Webhook-Signature` header. This allows you to verify that the request came from Clavr Agent and hasn't been tampered with.

### Verifying Signatures

**Python Example:**

```python
import hmac
import hashlib
import json

def verify_webhook_signature(payload: dict, signature: str, secret: str) -> bool:
    """Verify webhook HMAC signature"""
    # Convert payload to JSON string
    payload_json = json.dumps(payload, separators=(',', ':'))
    
    # Calculate expected signature
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload_json.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Remove "sha256=" prefix if present
    if signature.startswith("sha256="):
        signature = signature[7:]
    
    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature)

# Usage in Flask endpoint
from flask import request

@app.route('/webhook', methods=['POST'])
def webhook():
    signature = request.headers.get('X-Webhook-Signature')
    payload = request.get_json()
    secret = 'your-webhook-secret'
    
    if not verify_webhook_signature(payload, signature, secret):
        return 'Invalid signature', 401
    
    # Process webhook...
    return 'OK', 200
```

**Node.js Example:**

```javascript
const crypto = require('crypto');

function verifyWebhookSignature(payload, signature, secret) {
  // Calculate expected signature
  const hmac = crypto.createHmac('sha256', secret);
  hmac.update(JSON.stringify(payload));
  const expectedSignature = hmac.digest('hex');
  
  // Remove "sha256=" prefix if present
  if (signature.startsWith('sha256=')) {
    signature = signature.substring(7);
  }
  
  // Constant-time comparison
  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expectedSignature)
  );
}
```

### Headers

Each webhook request includes these headers:

- `Content-Type: application/json`
- `X-Webhook-Signature: sha256=<hmac>`
- `X-Webhook-Event: <event_type>`
- `X-Webhook-Delivery: <delivery_id>`

## Retry Policy

If a webhook delivery fails, Clavr Agent will automatically retry with exponential backoff:

1. **First retry:** 2 seconds after failure
2. **Second retry:** 4 seconds after first retry
3. **Third retry:** 8 seconds after second retry

**Failure Conditions:**
- HTTP status code outside 200-299 range
- Request timeout (exceeds configured timeout)
- Network error or connection refused

**Configuration:**
- `retry_count`: Maximum retry attempts (default: 3, max: 10)
- `timeout_seconds`: Request timeout (default: 10s, max: 60s)

After all retries are exhausted, the delivery is marked as `failed` and will not be retried automatically.

## API Endpoints

### List Event Types

```
GET /api/webhooks/event-types
```

Returns a list of all available event types.

### Create Webhook Subscription

```
POST /api/webhooks
```

Create a new webhook subscription.

**Request Body:**
```json
{
  "url": "https://example.com/webhook",
  "event_types": ["email.received"],
  "description": "Optional description",
  "retry_count": 3,
  "timeout_seconds": 10
}
```

### List Webhook Subscriptions

```
GET /api/webhooks?active_only=true
```

Get all webhook subscriptions for the current user.

### Get Webhook Subscription

```
GET /api/webhooks/{subscription_id}
```

Get details for a specific webhook subscription.

### Update Webhook Subscription

```
PATCH /api/webhooks/{subscription_id}
```

Update a webhook subscription.

**Request Body (all fields optional):**
```json
{
  "url": "https://example.com/webhook-v2",
  "event_types": ["email.received", "task.completed"],
  "is_active": true,
  "retry_count": 5
}
```

### Delete Webhook Subscription

```
DELETE /api/webhooks/{subscription_id}
```

Delete a webhook subscription.

### Test Webhook

```
POST /api/webhooks/{subscription_id}/test
```

Send a test event to verify your webhook endpoint is working.

### Get Delivery History

```
GET /api/webhooks/{subscription_id}/deliveries?limit=100
```

Get delivery history for a webhook subscription.

## Best Practices

### 1. Use HTTPS

Always use HTTPS endpoints in production to ensure webhook payloads are encrypted in transit.

### 2. Verify Signatures

Always verify HMAC signatures to ensure requests are authentic and haven't been tampered with.

### 3. Respond Quickly

Return a 2xx status code as quickly as possible (ideally < 1 second). If you need to perform long-running operations, process them asynchronously:

```python
from flask import Flask, request
from queue import Queue
import threading

app = Flask(__name__)
webhook_queue = Queue()

@app.route('/webhook', methods=['POST'])
def webhook():
    # Verify signature
    if not verify_signature(request.get_json(), request.headers.get('X-Webhook-Signature')):
        return 'Invalid signature', 401
    
    # Queue for async processing
    webhook_queue.put(request.get_json())
    
    # Return success immediately
    return 'OK', 200

def process_webhooks():
    while True:
        payload = webhook_queue.get()
        # Process payload...
        webhook_queue.task_done()

# Start background worker
threading.Thread(target=process_webhooks, daemon=True).start()
```

### 4. Handle Duplicates

Due to retries, you may receive duplicate webhooks. Use the `event_id` to detect and ignore duplicates:

```python
processed_events = set()

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_json()
    event_id = payload['event_id']
    
    # Check if already processed
    if event_id in processed_events:
        return 'Already processed', 200
    
    # Process webhook...
    processed_events.add(event_id)
    
    return 'OK', 200
```

### 5. Monitor Failures

Regularly check the delivery history to identify and fix issues:

```bash
curl https://your-api-domain.com/api/webhooks/1/deliveries?limit=100 \
  -H "Authorization: Bearer YOUR_API_TOKEN"
```

### 6. Rate Limiting

If you expect high webhook volumes, implement rate limiting on your endpoint to prevent overload.

### 7. Logging

Log all webhook events for debugging and audit purposes:

```python
import logging

logger = logging.getLogger(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_json()
    logger.info(f"Received webhook: {payload['event_type']} - {payload['event_id']}")
    # Process...
```

## Examples

### Full Flask Example

```python
from flask import Flask, request
import hmac
import hashlib
import json
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

WEBHOOK_SECRET = 'your-webhook-secret'
processed_events = set()

def verify_signature(payload, signature, secret):
    """Verify webhook HMAC signature"""
    payload_json = json.dumps(payload, separators=(',', ':'))
    expected_signature = hmac.new(
        secret.encode('utf-8'),
        payload_json.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if signature.startswith("sha256="):
        signature = signature[7:]
    
    return hmac.compare_digest(expected_signature, signature)

@app.route('/webhook', methods=['POST'])
def webhook():
    # Get payload and signature
    payload = request.get_json()
    signature = request.headers.get('X-Webhook-Signature')
    
    # Verify signature
    if not verify_signature(payload, signature, WEBHOOK_SECRET):
        logger.warning("Invalid webhook signature")
        return 'Invalid signature', 401
    
    # Check for duplicates
    event_id = payload['event_id']
    if event_id in processed_events:
        logger.info(f"Duplicate event: {event_id}")
        return 'Already processed', 200
    
    # Process webhook
    event_type = payload['event_type']
    data = payload['data']
    
    logger.info(f"Processing webhook: {event_type} - {event_id}")
    
    if event_type == 'email.received':
        handle_email_received(data)
    elif event_type == 'task.completed':
        handle_task_completed(data)
    # ... handle other event types
    
    # Mark as processed
    processed_events.add(event_id)
    
    return 'OK', 200

def handle_email_received(data):
    logger.info(f"Email received: {data['subject']}")
    # Your logic here...

def handle_task_completed(data):
    logger.info(f"Task completed: {data['title']}")
    # Your logic here...

if __name__ == '__main__':
    app.run(port=3000)
```

### Full Express Example

```javascript
const express = require('express');
const crypto = require('crypto');

const app = express();
app.use(express.json());

const WEBHOOK_SECRET = 'your-webhook-secret';
const processedEvents = new Set();

function verifySignature(payload, signature, secret) {
  const hmac = crypto.createHmac('sha256', secret);
  hmac.update(JSON.stringify(payload));
  const expectedSignature = hmac.digest('hex');
  
  if (signature.startsWith('sha256=')) {
    signature = signature.substring(7);
  }
  
  return crypto.timingSafeEqual(
    Buffer.from(signature),
    Buffer.from(expectedSignature)
  );
}

app.post('/webhook', (req, res) => {
  const payload = req.body;
  const signature = req.headers['x-webhook-signature'];
  
  // Verify signature
  if (!verifySignature(payload, signature, WEBHOOK_SECRET)) {
    console.warn('Invalid webhook signature');
    return res.status(401).send('Invalid signature');
  }
  
  // Check for duplicates
  const eventId = payload.event_id;
  if (processedEvents.has(eventId)) {
    console.log(`Duplicate event: ${eventId}`);
    return res.status(200).send('Already processed');
  }
  
  // Process webhook
  const { event_type, data } = payload;
  console.log(`Processing webhook: ${event_type} - ${eventId}`);
  
  switch (event_type) {
    case 'email.received':
      handleEmailReceived(data);
      break;
    case 'task.completed':
      handleTaskCompleted(data);
      break;
    // ... handle other event types
  }
  
  // Mark as processed
  processedEvents.add(eventId);
  
  res.status(200).send('OK');
});

function handleEmailReceived(data) {
  console.log(`Email received: ${data.subject}`);
  // Your logic here...
}

function handleTaskCompleted(data) {
  console.log(`Task completed: ${data.title}`);
  // Your logic here...
}

app.listen(3000, () => {
  console.log('Webhook server listening on port 3000');
});
```

## Troubleshooting

### Webhook Not Received

1. Check that the webhook subscription is active
2. Verify the event type is in the subscription's `event_types` list
3. Check the delivery history for error messages
4. Test the webhook endpoint manually

### Signature Verification Fails

1. Ensure you're using the correct secret (from creation response)
2. Verify you're not modifying the payload before verification
3. Check that you're using the raw request body (not parsed JSON)
4. Use the example code above for proper verification

### Timeouts

1. Ensure your endpoint responds within the configured timeout
2. Process webhooks asynchronously if needed
3. Increase the timeout if necessary (max 60s)

### High Failure Rate

1. Check delivery history for common error patterns
2. Monitor your endpoint's uptime and performance
3. Ensure your endpoint can handle the webhook volume
4. Consider implementing rate limiting

## Support

For additional help with webhooks:

- Check the [API documentation](./API.md)
- Review the [Architecture documentation](./engineering_docs/)
