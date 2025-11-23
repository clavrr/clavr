"""
Task management core modules

Main exports:
- GoogleTasksClient: Direct Google Tasks API client (low-level)

Recommended:
- Use TaskService from services layer for full task management functionality
"""

from .google_client import GoogleTasksClient

__all__ = ['GoogleTasksClient']

