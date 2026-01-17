# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Phase 3: Worker Refactoring Complete** (Nov 16, 2025)
  - Centralized credential management with `CredentialProvider` and `CredentialFactory`
  - All 16 worker functions now use CredentialFactory pattern
  - Eliminated manual credential loading across entire worker layer
  - 272 lines of code removed (68% reduction in credential handling)
  - Created comprehensive documentation:
    - `docs/CREDENTIAL_MANAGEMENT.md` - Complete credential management guide
    - `PHASE3_WORKER_REFACTORING_COMPLETE.md` - Phase 3 summary
    - `PHASE1_2_COMPLETE.md` - Phases 1 & 2 summary

- **Architecture Improvements** (Nov 16, 2025)
  - Enforced proper layering pattern: API/Workers/Tools → Services → Core → External
  - All workers now use service layer instead of direct core client access
  - All tools refactored to use service layer
  - Enhanced `TaskService` with `tasklist_id` parameter support
  - Created comprehensive architecture analysis documents:
    - `ARCHITECTURE_IMPROVEMENTS_COMPLETE.md`
    - `CORE_INTEGRATION_ANALYSIS.md`
    - `FEATURES_INTEGRATION_ANALYSIS.md`
  - Migration guide for CalendarClient deprecation (`docs/MIGRATION_CALENDAR_CLIENT.md`)
  - Credential management centralization (CredentialProvider, CredentialFactory)

- Initial project structure
- Email client with IMAP/SMTP support
- AI-powered response generation
- OpenAI and Anthropic LLM support
- Configuration management system
- Structured logging
- Email filtering system
- Dry-run mode
- Comprehensive test suite
- Documentation

### Changed
- **Workers Layer - Phase 3 Refactoring** (Nov 16, 2025)
  - `email_tasks.py`: All 4 functions use CredentialFactory (68 lines removed)
    - `sync_user_emails()`, `send_email()`, `archive_old_emails()`, `cleanup_spam()`
  - `calendar_tasks.py`: All 4 functions use CredentialFactory (68 lines removed)
    - `sync_user_calendar()`, `create_calendar_event()`, `update_recurring_event()`, `cleanup_old_calendar_events()`
  - `tasks_tasks.py`: All 6 functions use CredentialFactory (102 lines removed)
    - `sync_user_tasks()`, `create_google_task()`, `complete_task()`, `delete_task()`, `cleanup_completed_tasks()`, `sync_all_task_lists()`
  - `indexing_tasks.py`: All 2 functions use CredentialFactory (34 lines removed)
    - `index_user_emails()`, `index_user_calendar()`
  - Zero manual credential loading remaining in workers
  - Consistent pattern across all worker functions

- **Workers Layer - Initial Refactoring** (Nov 16, 2025)
  - `email_tasks.py`: Uses `EmailService` instead of `GoogleGmailClient` (2 functions)
  - `tasks_tasks.py`: Uses `TaskService` instead of `GoogleTasksClient` (4 functions)
  - `indexing_tasks.py`: Uses services instead of direct clients (2 functions)
  - Email archiving now uses batch operations for better performance

- **Tools Layer** (Nov 16, 2025)
  - Calendar tools (actions, search, analytics, availability) use `CalendarService`
  - Email tools (actions, search, indexing) use `EmailService`
  - Maintained backward compatibility with `google_client` reference

- **Services Layer** (Nov 16, 2025)
  - `TaskService`: Added `tasklist_id` and `show_completed` parameters to multiple methods
  - Enhanced API documentation

### Deprecated
- **CalendarClient** (Nov 16, 2025)
  - `src/core/calendar/client.py` is DEPRECATED
  - Will be removed in version 3.0.0 (Q2 2026)
  - Use `GoogleCalendarClient` from `src/core/calendar/google_client.py` instead
  - Runtime deprecation warnings added
  - Migration guide created at `docs/MIGRATION_CALENDAR_CLIENT.md`
  - Lazy import with deprecation warning in `src/core/__init__.py`

### Removed
- N/A

### Fixed
- **Architecture Violations** (Nov 16, 2025)
  - Fixed 39 direct core client imports in workers and tools
  - Eliminated all service layer bypassing
  - 100% compliance with architectural layering pattern

- N/A

### Security
- **Credential Management** (Nov 16, 2025)
  - Centralized credential handling through service layer
  - Reduced credential exposure in workers/tools
  - Better audit trails for credential usage

- N/A

## [0.1.0] - 2025-10-22

### Added
- Initial release
- Basic email agent functionality
- AI integration
- Configuration system
- Test framework

