"""
Calendar Action Handlers

Handles core calendar event CRUD operations: create, update, delete.
This module centralizes action handling logic to keep the main CalendarTool class clean.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from ...utils.logger import setup_logger
from ...integrations.google_calendar.exceptions import ServiceUnavailableException

logger = setup_logger(__name__)


class CalendarActionHandlers:
    """
    Handles core calendar event CRUD operations.
    
    This class centralizes create, update, and delete action handling
    to improve maintainability and keep the main CalendarTool class focused.
    """
    
    def __init__(self, calendar_tool):
        """
        Initialize action handlers.
        
        Args:
            calendar_tool: Parent CalendarTool instance for accessing services, config, etc.
        """
        self.calendar_tool = calendar_tool
        self.config = calendar_tool.config if hasattr(calendar_tool, 'config') else None
    
    def handle_create(
        self,
        title: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        duration_minutes: int,
        attendees: Optional[List[str]],
        description: Optional[str],
        location: Optional[str],
        recurrence: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle calendar event creation.
        
        Args:
            title: Event title
            start_time: Event start time
            end_time: Event end time
            duration_minutes: Event duration in minutes
            attendees: List of attendee names/emails
            description: Event description
            location: Event location
            recurrence: Recurrence pattern
            **kwargs: Additional arguments (workflow_emitter, etc.)
            
        Returns:
            Response string
        """
        if not title or not start_time:
            return "[ERROR] Please provide 'title' and 'start_time' for create action"
        
        # CRITICAL: Resolve attendee names to email addresses before creating event
        # Uses Contact Resolver role: Neo4j graph lookup first, then email search fallback
        if attendees:
            logger.info(f"[CAL] Resolving attendee names to emails: {attendees}")
            from ...core.calendar.utils import resolve_attendees_to_emails
            
            # Try to get email_service for contact resolution
            email_service = None
            try:
                email_service = self.calendar_tool.email_service
                logger.info(f"[CAL] EmailService available: {email_service is not None}")
            except Exception as e:
                logger.warning(f"[CAL] Failed to get email_service: {e}")
            
            # Try to get graph_manager for Neo4j contact resolution
            graph_manager = None
            if email_service:
                try:
                    if hasattr(email_service, 'hybrid_coordinator') and email_service.hybrid_coordinator:
                        logger.info(f"[CAL] EmailService has hybrid_coordinator")
                        if hasattr(email_service.hybrid_coordinator, 'graph_manager'):
                            graph_manager = email_service.hybrid_coordinator.graph_manager
                            logger.info(f"[CAL] Graph manager available: {graph_manager is not None}")
                except Exception as e:
                    logger.debug(f"[CAL] Failed to get graph_manager: {e}")
            
            logger.info(f"[CAL] Attempting to resolve attendees: email_service={email_service is not None}, graph_manager={graph_manager is not None}")
            
            try:
                resolved_emails, unresolved_names = resolve_attendees_to_emails(
                    attendees,
                    email_service=email_service,
                    config=self.config,
                    graph_manager=graph_manager,
                    user_id=self.calendar_tool._user_id if hasattr(self.calendar_tool, '_user_id') else None
                )
                
                logger.info(f"[CAL] Resolution result: resolved={resolved_emails}, unresolved={unresolved_names}")
                
                # If we have unresolved names, inform the user
                if unresolved_names:
                    names_str = ', '.join(unresolved_names)
                    if resolved_emails:
                        # Some resolved, some not
                        logger.info(f"[CAL] Partial resolution: {len(resolved_emails)} resolved, {len(unresolved_names)} unresolved")
                        return f"I found email addresses for some attendees, but I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can add them to the meeting?"
                    else:
                        # None resolved
                        logger.info(f"[CAL] No resolution: all {len(unresolved_names)} attendees unresolved")
                        return f"I couldn't find email addresses for: {names_str}. Could you provide their email addresses so I can book the meeting?"
                
                # Use resolved emails
                if resolved_emails:
                    logger.info(f"[CAL] Successfully resolved all attendees to emails: {resolved_emails}")
                    attendees = resolved_emails
                else:
                    logger.warning(f"[CAL] No emails resolved, but no unresolved names either - this shouldn't happen")
                    attendees = None
            except Exception as e:
                logger.error(f"[CAL] Error during attendee resolution: {e}", exc_info=True)
                # If resolution fails, ask user for emails
                names_str = ', '.join(attendees)
                return f"I encountered an error while trying to find email addresses for: {names_str}. Could you provide their email addresses so I can book the meeting?"
        
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit high-level action event
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr scheduling...",
                data={'title': title, 'start_time': start_time}
            )
        
        result = self.calendar_tool.calendar_service.create_event(
            title=title,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            description=description,
            location=location,
            attendees=attendees,
            recurrence=recurrence
        )
        
        # Generate conversational response
        event_info = []
        if start_time:
            event_info.append(f"starting at {start_time}")
        if location:
            event_info.append(f"at {location}")
        if attendees:
            event_info.append(f"with {', '.join(attendees)}")
        
        if event_info:
            info_text = " " + ", ".join(event_info)
            return f"Done! I've created '{title}'{info_text}."
        else:
            return f"Done! I've created '{title}'."
    
    def handle_update(
        self,
        event_id: Optional[str],
        title: Optional[str],
        start_time: Optional[str],
        end_time: Optional[str],
        description: Optional[str],
        location: Optional[str],
        attendees: Optional[List[str]],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle calendar event update.
        
        Args:
            event_id: Event ID to update
            title: New title
            start_time: New start time
            end_time: New end time
            description: New description
            location: New location
            attendees: New attendees
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for updating event
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr updating event...",
                data={'action': 'update'}
            )
        
        # SMART UPDATE HANDLER: Uses context, handles follow-ups, auto-updates when obvious
        if not event_id:
            # Check if this is a follow-up query (e.g., "the first one", "the second one")
            selected_event = self.calendar_tool._handle_follow_up_selection(query, title)
            if selected_event:
                event_id = selected_event.get('id')
                event_title = selected_event.get('title', selected_event.get('summary', 'event'))
                logger.info(f"[CAL] Resolved follow-up selection for update: {event_title}")
            else:
                query_lower = (query or "").lower()
                
                # Check if query mentions "my event", "the event", "this event", etc.
                if any(phrase in query_lower for phrase in ["my event", "the event", "this event", "that event", "my meeting", "the meeting"]):
                    # Get upcoming events and use the first one if only one exists
                    events = self.calendar_tool.calendar_service.list_events(days_ahead=7)
                    # Limit to first 10 for processing
                    events = events[:10]
                    if len(events) == 1:
                        event_id = events[0].get('id')
                        event_title = events[0].get('title', events[0].get('summary', 'event'))
                        logger.info(f"[CAL] Auto-updating single upcoming event: {event_title}")
                    elif len(events) > 1:
                        # Multiple events - show list and store for follow-up
                        self.calendar_tool._last_event_list = events
                        self.calendar_tool._last_event_list_query = query or "upcoming events"
                        
                        return self._format_event_selection_list(events, "update")
                    else:
                        return "You don't have any upcoming events to update."
                elif title:
                    # Search for event by title
                    events = self.calendar_tool.calendar_service.search_events(query=title)
                    # Limit to first 10 for processing
                    events = events[:10]
                    if not events:
                        return f"I couldn't find any events matching '{title}'."
                    elif len(events) == 1:
                        event_id = events[0].get('id')
                        event_title = events[0].get('title', events[0].get('summary', 'event'))
                        logger.info(f"[CAL] Auto-updating single matching event: {event_title}")
                    else:
                        # Multiple matches - show list and store for follow-up
                        self.calendar_tool._last_event_list = events
                        self.calendar_tool._last_event_list_query = title
                        
                        return self._format_event_selection_list(events, "update", title)
                else:
                    return "I need to know which event to update. You can say something like 'update my event' or 'update event X'."
        
        # Get event details for better response
        event_title = title or "event"
        try:
            # Try to get event details if method exists
            if hasattr(self.calendar_tool.calendar_service, 'get_event'):
                event_details = self.calendar_tool.calendar_service.get_event(event_id)
                if event_details:
                    event_title = event_details.get('title', event_details.get('summary', event_title))
        except Exception as e:
            logger.debug(f"[CAL] Could not get event details: {e}")
            # Use title from query or fallback
            pass
        
        # Update the event
        result = self.calendar_tool.calendar_service.update_event(
            event_id=event_id,
            title=title if title and title != event_title else None,  # Only update if different
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
            attendees=attendees
        )
        
        # Clear the stored list since we updated an event
        self.calendar_tool._last_event_list = None
        self.calendar_tool._last_event_list_query = None
        
        # Generate conversational response
        updates = []
        if start_time:
            updates.append(f"start time to {start_time}")
        if end_time:
            updates.append(f"end time to {end_time}")
        if location:
            updates.append(f"location to {location}")
        if attendees:
            updates.append(f"attendees to {', '.join(attendees)}")
        if title and title != event_title:
            updates.append(f"title to '{title}'")
        
        if updates:
            if len(updates) == 1:
                return f"Done! I've updated the {updates[0]} for '{event_title}'."
            else:
                update_text = ", ".join(updates[:-1]) + f", and {updates[-1]}"
                return f"Done! I've updated '{event_title}' with {update_text}."
        else:
            return f"Done! I've updated '{event_title}'."
    
    def handle_delete(
        self,
        event_id: Optional[str],
        title: Optional[str],
        query: Optional[str],
        **kwargs
    ) -> str:
        """
        Handle calendar event deletion.
        
        Args:
            event_id: Event ID to delete
            title: Event title for searching
            query: Original query for context
            **kwargs: Additional arguments
            
        Returns:
            Response string
        """
        # Get workflow_emitter from kwargs if available
        workflow_emitter = kwargs.get('workflow_emitter')
        
        # Emit workflow event for deleting event
        if workflow_emitter:
            self.calendar_tool._emit_workflow_event(
                workflow_emitter,
                'action_executing',
                "Clavr deleting event...",
                data={'action': 'delete'}
            )
        
        # SMART DELETE HANDLER: Uses context, handles follow-ups, auto-deletes when obvious
        if not event_id:
            # Check if this is a follow-up query
            selected_event = self.calendar_tool._handle_follow_up_selection(query, title)
            if selected_event:
                event_id = selected_event.get('id')
                event_title = selected_event.get('title', selected_event.get('summary', 'event'))
                logger.info(f"[CAL] Resolved follow-up selection for delete: {event_title}")
            else:
                query_lower = (query or "").lower()
                
                if any(phrase in query_lower for phrase in ["my event", "the event", "this event", "that event", "my meeting", "the meeting"]):
                    events = self.calendar_tool.calendar_service.list_events(days_ahead=7)
                    events = events[:10]
                    if len(events) == 1:
                        event_id = events[0].get('id')
                        event_title = events[0].get('title', events[0].get('summary', 'event'))
                        logger.info(f"[CAL] Auto-deleting single upcoming event: {event_title}")
                    elif len(events) > 1:
                        self.calendar_tool._last_event_list = events
                        self.calendar_tool._last_event_list_query = query or "upcoming events"
                        
                        return self._format_event_selection_list(events, "delete")
                    else:
                        return "You don't have any upcoming events to delete."
                elif title:
                    events = self.calendar_tool.calendar_service.search_events(query=title)
                    events = events[:10]
                    if not events:
                        return f"I couldn't find any events matching '{title}'."
                    elif len(events) == 1:
                        event_id = events[0].get('id')
                        event_title = events[0].get('title', events[0].get('summary', 'event'))
                        logger.info(f"[CAL] Auto-deleting single matching event: {event_title}")
                    else:
                        self.calendar_tool._last_event_list = events
                        self.calendar_tool._last_event_list_query = title
                        
                        return self._format_event_selection_list(events, "delete", title)
                else:
                    return "I need to know which event to delete. You can say something like 'delete my event' or 'delete event X'."
        
        # Get event title for response
        event_title = title or "event"
        try:
            if hasattr(self.calendar_tool.calendar_service, 'get_event'):
                event_details = self.calendar_tool.calendar_service.get_event(event_id)
                if event_details:
                    event_title = event_details.get('title', event_details.get('summary', event_title))
        except Exception as e:
            logger.debug(f"[CAL] Could not get event details: {e}")
        
        # Delete the event
        self.calendar_tool.calendar_service.delete_event(event_id)
        
        # Clear the stored list since we deleted an event
        self.calendar_tool._last_event_list = None
        self.calendar_tool._last_event_list_query = None
        
        return f"Done! I've deleted '{event_title}'."
    
    def _format_event_selection_list(
        self,
        events: List[Dict[str, Any]],
        action: str,
        search_term: Optional[str] = None
    ) -> str:
        """
        Format a list of events for user selection.
        
        Args:
            events: List of event dictionaries
            action: Action being performed ("update" or "delete")
            search_term: Optional search term used
            
        Returns:
            Formatted selection list string
        """
        event_list_parts = []
        for i, e in enumerate(events[:5], 1):
            event_title = e.get('title', e.get('summary', 'Untitled'))
            start_time = self.calendar_tool._extract_start_time_from_event(e)
            event_desc = f"{i}. **{event_title}**"
            if start_time:
                try:
                    # Handle both ISO string and datetime object
                    if isinstance(start_time, datetime):
                        parsed_time = start_time
                    else:
                        parsed_time = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                    event_desc += f" (at {parsed_time.strftime('%b %d, %I:%M %p')})"
                except:
                    pass
            event_list_parts.append(event_desc)
        
        event_list = "\n".join(event_list_parts)
        
        if search_term:
            return f"I found {len(events)} events matching '{search_term}'. Which one should I {action}?\n\n{event_list}\n\nJust say 'the first one', 'the second one', or 'the one at [time]' and I'll {action} it!"
        else:
            return f"I found {len(events)} upcoming events. Which one should I {action}?\n\n{event_list}\n\nJust say 'the first one', 'the second one', or 'the one at [time]' and I'll {action} it!"

