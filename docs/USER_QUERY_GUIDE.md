# Clavr Agent - User Query Guide

Complete guide to using the Clavr AI Agent based on actual implementation. Clavr is an intelligent, autonomous personal assistant that helps you manage emails, calendar, and tasks through natural language queries.

## Table of Contents
- [Overview](#overview)
- [Email](#email)
- [Calendar](#calendar)
- [Tasks](#tasks)
- [AI Features](#ai-features)
- [Dashboard & Analytics](#dashboard--analytics)
- [GraphRAG & Knowledge Graph](#graphrag--knowledge-graph)
- [Multi-Step Queries](#multi-step-queries)
- [Tips & Best Practices](#tips--best-practices)
- [Getting Started](#getting-started)
- [Coming Soon](#coming-soon)

---

## Overview

Clavr is an intelligent AI assistant that operates autonomously to help you manage your digital life. You interact with it using natural language queries via:

- **Gmail Extension** - Chrome extension with AI sidebar (Phase 1 MVP available)
- **Voice Interface** - *Coming soon* - Speech-to-text/text-to-speech

### Core Capabilities

- **Email Management**: Search, organize, send, reply, analyze emails with semantic search, bulk operations, insights, and categorization
- **Calendar Management**: Schedule meetings, check availability, manage events with conflict detection, recurring events, and analytics
- **Task Management**: Create, track, complete tasks with reminders, analytics, email/calendar integration, and AI-powered features
- **AI Features**: Auto-reply generation (personalized to your writing style), sentiment analysis, document summarization, meeting preparation, and writing style profiles
- **Smart Search**: RAG-powered semantic search across emails with attachment content indexing
- **Autonomous Workflows**: Multi-step queries that execute independently using LangGraph orchestration
- **Dashboard & Analytics**: Real-time statistics and insights across emails, calendar, and tasks
- **GraphRAG**: Knowledge graph-powered spending analysis, vendor insights, and receipt trends

### How Clavr Works

Clavr operates autonomously with confidence-based decision making:
- **High confidence (>70%)**: Executes actions directly without confirmation
- **Medium confidence (40-70%)**: Executes with informational confirmation
- **Low confidence (<40%)**: Asks for clarification before proceeding

Clavr uses specialized parsers for different domains (email, calendar, tasks) and a LangGraph orchestrator for multi-step workflows. It maintains conversation memory to understand context across queries.

---

## Email

Clavr provides comprehensive email management through Gmail API integration with RAG-powered semantic search.

### Check for New Emails

```
"Check my inbox"
"Any new emails today?"
"What emails did I receive today?"
"Show me unread emails"
"Do I have any new messages?"
"What new email do I have from [sender]?"
```

### Find Specific Emails

**By Sender:**
```
"Find emails from my professor"
"Find emails from professor.smith@university.edu"
"Show me emails from Amex Recruiting or American Express"
"What emails do I have from Spotify?"
"When was the last time I got an email from [sender] and what was it about?"
```

**By Topic/Content:**
```
"Show me emails about the midterm exam"
"Search for emails mentioning project deadline"
"Find all emails about the quarterly report"
"Find emails regarding team meetings"
"Search for emails about budget approvals"
```

**By Date:**
```
"Show emails from the past week"
"Find emails from last month"
"What emails did I receive today?"
```

### Semantic Search (RAG-Powered)

Clavr uses semantic search to find emails by meaning, not just keywords:

```
"Find all emails about student absences"
"Search for emails discussing curriculum changes"
"Show me emails related to research collaboration"
"Find emails about problems that need solving"
"Show me emails with questions waiting for answers"
"Search for emails discussing team collaboration"
```

### Organize and Manage Emails

**Bulk Operations:**
```
"Archive old promotional emails"
"Delete emails older than 3 months"
"Clean up my inbox"
"Archive emails older than 6 months"
"Bulk delete emails from [sender] older than [time]"
"Bulk archive all emails in [folder]"
```

**Categorization & Organization:**
```
"Organize emails by category"
"Organize my inbox by urgency"
"Categorize emails by topic"
"Categorize my inbox automatically"
"Organize emails into folders"
```

**Email Cleanup:**
```
"Clean up my inbox"
"Remove old promotional emails"
"Delete spam emails"
"Archive read emails older than 30 days"
```

### Send Emails

```
"Send an email to professor.smith@university.edu about my research project"
"Reply to the last email"
"Compose a message to my study group"
"Send a follow-up email about my scholarship application"
"Send a quick note to the team about the delay"
```

### Reply to Emails

```
"Reply to this thread and loop in Lauren"
"Reply to the last email"
"Follow up on my last email to Josh"
"Reply to [sender] and include [person]"
```

### Email Summarization

**Summarize Specific Emails:**
```
"Summarize unread emails since last night"
"What was the email about?"
"When was the last time I got an email from [sender] and what was it about?"
```

**Summarize Email Attachments:**
Clavr can extract and index attachments from emails (PDF, DOCX, PPTX, etc.) when they are indexed. Attachments are automatically extracted and indexed in the background, making their content searchable via semantic search.

```
"Find emails with PDF attachments about the budget"
"Search for emails with attachments mentioning the project proposal"
```

*Note: Attachment content is automatically processed during email indexing and becomes searchable through semantic search. The attachment content will be included in email search results when relevant.*

### Email Analysis & Insights

**Priority & Urgency:**
```
"Analyze this email for urgency"
"What's the priority of this email?"
"Is this email important?"
"What are the urgent matters in my inbox?"
"Show me priority emails that need immediate attention"
"What's urgent in my inbox?"
```

**Sentiment Analysis:**
```
"Check the sentiment of this message"
"Analyze this student's email for concern level"
"Analyze this client email for sentiment"
"Check the tone of this customer inquiry"
```

**Email Analytics & Insights:**
```
"Who have I been emailing the most?"
"Show me my most frequent contacts"
"What email patterns am I seeing?"
"Who are my top email contacts?"
"What categories dominate my emails?"
"What topics are my emails about?"
"What are my email habits?"
"Show me email response patterns"
"Email analytics for this month"
"Show me email insights"
"Analyze my email activity"
"Email insights and analytics"
```

**Extract Tasks from Emails:**
```
"Extract action items from this email"
"Create tasks from emails about deadlines"
"Find action items in emails from this week"
"Extract tasks from unread emails"
```

### Email Queries (Quick Reference)

- `"Check inbox"`
- `"Find emails from [person]"`
- `"Search for [topic]"`
- `"Send email to [person]"`
- `"Reply to email"`
- `"Archive/Delete emails"`
- `"Analyze this email"`
- `"What's the priority?"`

---

## Calendar

Clavr integrates with Google Calendar to manage your schedule with intelligent conflict detection and timezone awareness.

### Check Schedule

```
"Show my schedule for today"
"What meetings do I have this week?"
"Display my calendar"
"List upcoming events"
"Show my teaching schedule"
"What classes do I have this week?"
"Display my office hours"
"Show my meetings for today"
"What's on my calendar this week?"
"Display upcoming client meetings"
```

### Schedule Events

**Basic Scheduling:**
```
"Schedule a study session tomorrow at 2pm"
"Book a meeting with my advisor next Monday"
"Add office hours appointment to calendar"
"Create an event for the study group meeting"
"Schedule a client meeting next Monday at 10am"
"Book a team standup for tomorrow"
```

**With Location:**
```
"Schedule a coffee break near the office at 3pm"
"Schedule dinner with Jamey at a quiet spot downtown"
"Add a gym session tomorrow evening"
"Create a meeting at the conference room"
```

**With Duration:**
```
"Plan a 30 min run between meetings"
"Schedule a 15-minute coffee break"
"Book a 2-hour workshop"
```

**Finding Free Time:**
```
"Plan a 30 min run between meetings"
"Find free time for a 1-hour meeting tomorrow"
"Schedule something in my free time this afternoon"
```

**With Attendees:**
```
"Schedule a meeting with john@example.com tomorrow at 2pm"
"Create a calendar event about our Code Savanna annual meeting tomorrow at 5 pm PST and add manikoa@whitman.edu as an attendee"
"Book a team meeting and invite [email1] and [email2]"
```

**With Specific Details:**
```
"Schedule office hours for next Tuesday at 2pm"
"Create a student advisory appointment"
"Add a research seminar to my calendar"
"Add a performance review meeting to calendar"
"Create an all-hands meeting event"
```

**Recurring Events:**
```
"Schedule a weekly team standup every Monday at 10am"
"Create a monthly review meeting recurring on the first Friday"
"Add a daily standup recurring every weekday at 9am"
```

### Move and Reschedule Events

```
"Move my standup to the afternoon"
"Reschedule my 3pm meeting to tomorrow at 2pm"
"Move the team meeting to next week"
"Reschedule all calls today after 5pm"
```

### Reorganize Schedule

```
"Reorganize my day to give me a slow start"
"Move my standup to the afternoon and book a coffee run in half an hour"
"Reschedule all calls today after 5pm and send everyone an email"
```

### Conflict Detection

Clavr automatically detects scheduling conflicts and suggests alternatives:

```
"Check for schedule conflicts"
"Are there any scheduling conflicts?"
"What are my availability gaps this week?"
"Show me overlapping meetings"
```

When conflicts are detected, Clavr will:
- Inform you about the conflict
- Suggest alternative times
- Offer to reschedule the conflicting event

### Calendar Analysis & Analytics

```
"Check for schedule conflicts"
"What are my availability gaps this week?"
"Show me overlapping meetings"
"Analyze my calendar"
"Show me calendar analytics"
"What are my busiest days?"
"Calendar insights for this month"
```

### Meeting Preparation

```
"Prepare me for the team meeting tomorrow"
"What should I know before the client call?"
"Generate an agenda for the budget review meeting"
```

### Calendar Queries (Quick Reference)

- `"Show calendar"`
- `"Schedule meeting [time]"`
- `"What's on my schedule?"`
- `"Check availability"`
- `"Check for conflicts"`

---

## Tasks

Clavr integrates with Google Tasks (with local storage fallback) to manage your to-do list with intelligent date parsing and analytics.

### Create Tasks

**Basic Task Creation:**
```
"Create a task to study for finals next week"
"Add a reminder to submit my research paper by Friday"
"Create a deadline task for my thesis proposal"
"Add a todo to prepare for the group presentation"
"Task: Buy textbooks for the new semester"
```

**With Specific Dates:**
```
"Create a task about applying to Y Combinator next week on November 22"
"Add a task to call mom tonight"
"Create a task about going to Cleveland Commons tonight"
"Task: Finish project by next Friday"
"Please create a task about [description]"
"Create a task about [description] due [date]"
```

**Academic/Business Tasks:**
```
"Create a task to grade midterm papers by Friday"
"Add a reminder to prepare lecture slides for next week"
"Task: Review student thesis proposals"
"Create a task to review quarterly budget"
"Add a deadline task for employee reviews by end of month"
"Task: Schedule team building event"
```

### Track Tasks

```
"Show me my pending tasks"
"What tasks do I have?"
"List all my overdue tasks"
"Which tasks are coming due?"
"How many tasks do I have?"
"Show my academic tasks"
"What tasks are overdue?"
"Show me overdue business tasks"
"What HR tasks are pending?"
```

### Task Analysis & Analytics

**General Analysis:**
```
"What are my overdue tasks?"
"Give me a task summary"
"Show me pending tasks"
"Task analysis for this week"
"Give me a breakdown of my pending tasks"
"Task analysis for this semester"
"Show me task analytics"
"Task insights and statistics"
```

**Date-Specific Analysis:**
```
"How many tasks do I have due today?"
"What tasks do I have due tomorrow?"
"Do I have any tasks due next week?"
"Show me tasks due this week"
```

**Filtering & Search:**
```
"Show me high priority tasks"
"List tasks by category [category]"
"Find tasks with tag [tag]"
"Show tasks for project [project]"
"Search tasks for [keyword]"
```

### Task Features

**Email Integration:**
```
"Create a task from this email"
"Extract tasks from emails about [topic]"
"Create tasks from action items in my inbox"
```

**Calendar Integration:**
```
"Schedule time for task [name]"
"Block calendar time for my tasks"
"Create a prep task for the meeting tomorrow"
"Create follow-up tasks for my events"
```

**AI-Powered Features:**
```
"Enhance this task with more details"
"Extract tasks from this text"
"Suggest improvements for this task"
```

### Complete Tasks

```
"Mark my tasks as done"
"Complete all my tasks"
"Mark task [name] as complete"
```

### Task Queries (Quick Reference)

- `"Create task [description]"`
- `"Show tasks"`
- `"Overdue tasks"`
- `"Complete task"`
- `"How many tasks do I have?"`
- `"Tasks due today/tomorrow/next week"`
- `"Task analytics"`
- `"Create task from email"`
- `"Schedule time for task"`

---

## AI Features

Clavr provides powerful AI-powered features to enhance your productivity and communication.

### Auto-Reply Generation

Generate intelligent reply options for emails in multiple tones. Replies are personalized to match your writing style if you've built a writing profile.

**Example Queries:**
```
"Generate reply options for this email"
"Give me reply suggestions in different tones"
"Create a professional reply to this message"
"Suggest a friendly response"
"Generate a brief reply option"
```

**Response includes:**
- Professional tone reply
- Friendly tone reply
- Brief/concise reply

**Personalization:**
If you've built a writing style profile, replies will automatically match your writing style (70-85% match).

### Email Analysis

Comprehensive email analysis including sentiment, priority, intent detection, and urgency indicators.

**Analysis includes:**
- Sentiment (positive/negative/neutral) with score
- Priority (high/medium/low) with score
- Intent detection (question/request/info/complaint)
- Urgency indicators and reasons
- Category classification
- Tags and key points
- Estimated response time
- Suggested actions

**Example Queries:**
```
"Analyze this email for sentiment"
"What's the priority of this email?"
"Is this email urgent?"
"Check the tone of this message"
```

### Document Summarization

Summarize any document or email with comprehensive extraction.

**Extracts:**
- Executive summary (2-3 sentences)
- Key points (bullet format)
- Main topics/themes
- Action items
- Important dates and numbers
- Sentiment analysis
- Word count and reading time

**Example Queries:**
```
"Summarize this document"
"Summarize unread emails since last night"
"What are the key points in this email?"
```

### Meeting Preparation

Generate comprehensive pre-meeting briefs with preparation materials.

**Brief includes:**
- Agenda items
- Context summary from related emails
- Talking points
- Decisions needed
- Preparation tasks
- Key emails related to the meeting

**Example Queries:**
```
"Prepare me for the team meeting tomorrow"
"What should I know before the client call?"
"Generate an agenda for the budget review meeting"
```

### Writing Style Profiles

Build a personalized writing style profile from your sent emails to make AI-generated replies match your voice.

**Example Queries:**
```
"Build my writing style profile"
"Create a profile from my sent emails"
"Analyze my writing style"
"Rebuild my writing profile"
```

**Profile includes:**
- Writing style (tone, formality, length preferences)
- Common greetings and closings
- Response patterns
- Frequently used phrases
- Confidence score (based on sample size)

**Benefits:**
- Auto-replies match your writing style (70-85% match)
- Personalized email generation
- Consistent communication voice

**Note:** Profile building happens in the background. You can check the status by asking about your profile.

---

## Dashboard & Analytics

Clavr provides real-time dashboard statistics and insights across all your services.

**Example Queries:**
```
"Show me my dashboard"
"What's my overview?"
"Dashboard statistics"
"Show me my stats"
"What's my current status?"
"Give me a summary of my emails, calendar, and tasks"
```

**Dashboard includes:**
- Number of unread emails
- Number of events today
- Number of incomplete tasks
- Recent activity summaries
- Recent emails (last 3)
- Upcoming events (next few hours)
- Urgent tasks

---

## GraphRAG & Knowledge Graph

Clavr includes GraphRAG (Graph Retrieval-Augmented Generation) for sophisticated reasoning and analysis using a knowledge graph.

### Spending Analysis

Analyze spending patterns with automatic LLM-generated advice.

**Example Queries:**
```
"How much did I spend on dining out in the past two weeks?"
"Show me my spending on restaurants this month"
"Analyze my spending by category"
```

**Features:**
- Category-based spending analysis
- Vendor breakdown with insights
- Receipt trend analysis over time
- Automatic threshold detection
- LLM-generated personalized advice

**Additional Query Examples:**
```
"Show me my top vendors this month"
"What are my spending trends?"
"Analyze my receipt patterns"
"Compare my spending across categories"
```

### Knowledge Graph Schema

**Node Types:**
- `User` - User accounts
- `Vendor` - Merchants/vendors
- `Email` - Email messages
- `Receipt` - Financial receipts
- `Contact`, `Person`, `Company` - Entity nodes
- `Document`, `ActionItem`, `Topic` - Content nodes

**Relationship Types:**
- `HAS_RECEIPT` - User/Email → Receipt
- `FROM_VENDOR` - Receipt → Vendor
- `RECEIVED` - User → Email
- `FROM`, `TO`, `SENT` - Email relationships
- `FROM_STORE`, `PURCHASED_AT` - Receipt relationships

### GraphRAG Pattern

1. **Graph Traversal**: Navigate relationships and filter entities
2. **Graph Aggregation**: SUM, COUNT, AVG across related nodes
3. **Analysis & Generation**: Compare to thresholds and generate LLM-based advice

**Example Flow:**
```
Query: "How much did I spend on dining?"
  ↓
1. Traverse: User → Receipts → Filter by category="Restaurant"
  ↓
2. Aggregate: SUM(receipt.total) for past 14 days
  ↓
3. Analyze: Compare to threshold ($100) → Generate advice
  ↓
Result: "You spent $X on dining. Consider cooking at home 3 nights this week."
```

---

## Multi-Step Queries

Clavr excels at handling complex multi-step workflows autonomously. It uses **LangGraph orchestrator** with intelligent query decomposition, context-aware execution, and autonomous decision-making.

### How Multi-Step Queries Work

1. **Query Analysis**: Clavr analyzes the query complexity and intent
2. **Decomposition**: Breaks down complex queries into sequential steps
3. **Context Passing**: Each step receives context from previous steps
4. **Autonomous Execution**: Executes steps independently with confidence-based decision making
5. **Result Synthesis**: Combines results into a cohesive response

### LangGraph Orchestration

Clavr uses LangGraph for sophisticated workflow orchestration:
- **Modular Orchestrator**: Pattern-based multi-step execution
- **Autonomous Orchestrator**: LangGraph-powered autonomous workflows (experimental)
- **Memory Integration**: Conversation memory and context awareness
- **Tool Coordination**: Intelligent tool selection and dependency resolution
- **Error Handling**: Graceful error handling with partial results

### Email-to-Task-to-Calendar Workflows

```
"Find emails about assignments from this week, create tasks for each one with appropriate deadlines, and schedule study time"
```
**Autonomously:** Searches emails → Creates multiple tasks → Blocks calendar time

```
"Find the meeting invitation email, add it to my calendar, and create a reminder task to prepare"
```
**Autonomously:** Finds email → Schedules event → Creates prep task with reminder

### Email-to-Task Workflows

```
"Find emails from my professor about the final project, create a task to complete it by next Friday, and schedule a study session tomorrow at 3pm"
```

```
"Search for assignment emails, extract deadlines, create tasks with reminders for each, and notify me"
```

```
"Find student emails with concerns, create follow-up tasks for each, and schedule office hours accordingly"
```
**Autonomously:** Finds student concerns → Creates tasks → Manages schedule

```
"Search for deadline emails from the department, create reminder tasks with deadlines, and block calendar time for preparation"
```

```
"Find emails about upcoming conferences, extract submission deadlines, create tasks with reminders, and schedule writing time"
```

### Business Workflows

```
"Find client emails from this week, create action items for each, prioritize them, and schedule follow-up time"
```
**Autonomously:** Finds emails → Creates tasks → Prioritizes → Manages calendar

```
"Search for urgent emails from stakeholders, create tasks with deadlines, check calendar conflicts, and block time to handle them"
```

```
"Find meeting invitation emails, add them to calendar, create preparation tasks with reminders, and notify me of conflicts"
```

```
"Analyze inbox for project-related emails, extract key decisions, create tracking tasks, and schedule review meetings"
```

### Advanced Autonomous Examples

```
"Find a specific email about the Q4 project, schedule a review meeting for next week, create a task to prepare materials, and set reminders"
```
**Autonomously:** Searches specific email → Creates meeting → Prepares task → Sets reminders

```
"Find emails from my advisor, extract action items, create prioritized tasks with deadlines, and block calendar time to work on them"
```

```
"Look for emails about upcoming deadlines, create reminder tasks for each, schedule prep time in my calendar, and alert me of urgent items"
```

```
"First, find emails from my professor about the final project, then create a task to complete it by next Friday, and schedule a study session tomorrow at 3pm"
```

```
"Find urgent student emails, then analyze them for sentiment, and create tasks for follow-ups"
```

```
"First show me what's urgent in my inbox, then create tasks for the top priorities, and check my calendar for scheduling conflicts"
```

```
"Find emails about the budget, summarize them, and create a task to review by Friday"
```

**What Clavr does autonomously:**
- Searches your inbox intelligently using semantic search
- Extracts key information and deadlines from emails
- Creates prioritized tasks automatically with appropriate due dates
- Sets appropriate reminders
- Checks your calendar for availability
- Suggests optimal meeting times
- Creates calendar events when requested
- Manages the entire workflow end-to-end without requiring confirmation at each step

---

## Tips & Best Practices

### 1. Be Specific
**Good**: "Find emails from professor.smith about the midterm"
**Better**: "Search for emails from professor.smith@university.edu mentioning midterm exam last week"

### 2. Use Natural Language
You don't need special syntax. Just ask naturally:
- "What emails do I have?"
- "Show me my calendar"
- "Create a task"

### 3. Context Matters
Clavr remembers recent conversation:
- "Find that email about the budget"
- "Schedule a follow-up to that"
- "What did they ask about earlier?"

### 4. Combine Actions
You can chain multiple actions in a single query:
- "Find urgent emails and create tasks for them"
- "Summarize this document and send it to the team"

### 5. Use AI Features
Take advantage of AI capabilities:
- Auto-reply for quick responses
- Sentiment analysis for important emails
- Summarization for long documents

### 6. Date References
Use natural date references:
- "today", "tomorrow", "next week"
- Specific dates: "November 22", "next Friday"
- Relative dates: "in 3 days", "next month"

### 7. Trust the Autonomy
Clavr is designed to execute actions autonomously. It will:
- Ask for clarification only when confidence is low
- Execute high-confidence actions directly
- Provide informational confirmations for medium-confidence actions
- Handle errors gracefully and provide partial results when possible

---

## Getting Started

### Testing Queries

Try these queries to get started:

```
"What emails do I have?"
"Show my calendar for today"
"How many tasks do I have?"
"Create a task to review the budget by Friday"
"Schedule a meeting tomorrow at 2pm"
```

---

## Coming Soon

### Voice Interface

Voice functionality is currently disabled but will be re-enabled in a future update. When available, you'll be able to:

- Speak queries instead of typing
- Receive audio responses
- Use voice commands for hands-free operation

**Planned Features:**
- Speech-to-text conversion
- Text-to-speech responses
- Real-time voice conversations
- Voice command shortcuts

### Slack Integration

Slack integration is planned for future releases. This will enable:

- **Search Slack Messages**: Find messages across channels and DMs
- **Send Messages**: Post to channels or send DMs
- **Channel Management**: List channels, join/leave channels
- **Thread Management**: Reply to threads, create threads
- **Notifications**: Get notified about important messages
- **Slack-to-Task**: Create tasks from Slack messages
- **Slack-to-Calendar**: Schedule meetings from Slack conversations

**Example Queries (Coming Soon):**
```
"Find Slack messages about the project deadline"
"Send a message to #engineering about the deployment"
"Create a task from the Slack message in #general"
"Schedule a meeting based on the Slack conversation"
"Show me unread Slack messages"
"Reply to the thread in #product"
```

### Gmail Extension

**Status: Available (Phase 1 MVP)**

A Chrome extension for Gmail is now available! It provides:

- **AI Sidebar**: Live AI assistant directly in Gmail
- **Quick Actions**: One-click email actions (schedule meeting, create task, smart reply)
- **Context Awareness**: Shows sender, subject, and email context
- **Natural Language Query**: Ask anything about your emails, calendar, tasks
- **Real-time AI**: Powered by Clavr's intelligent query system

**Installation:**
1. Start the Clavr backend service
2. Load extension in Chrome: `chrome://extensions/` → Enable Developer mode → Load unpacked → Select `gmail-extension-v2` folder
3. Open Gmail: Sidebar appears on the right

**Current Features (Phase 1):**
- AI sidebar in Gmail interface
- Quick action buttons
- Email context awareness (sender, subject)
- Natural language queries
- Real-time AI responses

**Coming in Phase 2:**
- Email content parsing (read full email body)
- Smart reply suggestions (3-5 options in YOUR voice)
- Email triage badges (Urgent/Important/FYI)
- Attachment intelligence
- Relationship insights

See `gmail-extension-v2/README.md` for detailed installation and troubleshooting.

---

## Support & Documentation

For more information:
- **Architecture**: See `docs/ARCHITECTURE.md`
- **Examples**: See `examples/` directory
- **Autonomous Features**: See `docs/AUTONOMOUS_FEATURES.md`

---

## Conclusion

Clavr makes managing your academic, professional, or business communications effortless. Whether you're a student juggling classes and assignments, a professor managing courses and research, or a business owner handling client communications, Clavr adapts to your workflow and helps you stay organized and productive.

Start with simple queries and gradually explore more advanced features. Clavr learns your patterns and becomes more helpful over time through conversation memory and context awareness.

**Happy organizing!**
