"""
Graph Observer Service

The "Living Loop" of the memory system.
This service periodically queries the Knowledge Graph for recent changes and uses an LLM
to generate proactive insights, warnings, or connections that weren't explicitly stated.

Example Insights:
- "You have a meeting with Bob, but he just posted in Slack he's out sick."
- "You just created a project 'Marketing', here are 3 documents from last year related to it."
"""
from typing import List, Dict, Any, Optional
import asyncio
from datetime import datetime, timedelta
from langchain_core.messages import SystemMessage, HumanMessage

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.parsers.base import ParsedNode
from src.ai.llm_factory import LLMFactory
from src.utils.json_utils import repair_json

logger = setup_logger(__name__)

SYSTEM_PROMPT = """
You are an intelligent Graph Observer for a personal AI assistant.
Your job is to analyze RECENT CHANGES in the user's knowledge graph and generate ACTIONABLE INSIGHTS.
You will be given a set of recently added or modified nodes (Emails, Slack Messages, Calendar Events, Projects).

Look for:
1. Conflicts (e.g., Meeting with someone who is OOO)
2. Connections (e.g., A new Slack message discusses a Project defined in Notion)
3. Suggestions (e.g., "You seem to be working on X, here is a related contact")

Output a JSON object with a list of 'insights'.
Each insight should have:
- content: A clear, concise sentence describing the insight.
- type: 'conflict', 'connection', or 'suggestion'.
- confidence: 0.0 to 1.0.
- related_node_ids: List of node IDs this insight is about.
- actionable: true/false.

If no insights are found, return {"insights": []}.

Special Context for Follow-ups:
- If you detect a 'stale_lead' (no contact in 3+ days), generate a draft follow-up email.
- If you detect an 'unanswered_question', suggest a reply.
- Use 'type': 'follow_up' for these.
- Include 'draft_body' in the insight properties if actionable.
"""

class GraphObserverService:
    """
    Background service that monitors graph changes and generates insights.
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.is_running = False
        self._stop_event = asyncio.Event()
        self.last_run_time = datetime.utcnow() - timedelta(hours=24) # Start looking at last 24h
        self._notify_callback = None
        self.cross_stack_context = None # Will be set by Indexer
        self.llm = None
        
    def set_cross_stack_context(self, context_service):
        """Link the cross-stack context service for proactive sync triggers."""
        self.cross_stack_context = context_service
        
    def set_notification_callback(self, callback):
        """Register a callback to push alerts to the client."""
        self._notify_callback = callback
        if not self.llm:
            try:
                # Use a smart model for reasoning
                self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.2)
            except Exception as e:
                logger.error(f"Failed to initialize LLM for GraphObserver: {e}")
        return self.llm
        
    async def start(self):
        """Start the observer loop"""
        if self.is_running:
            return
            
        self.is_running = True
        self._stop_event.clear()
        
        logger.info("[GraphObserver] Service started")
        asyncio.create_task(self._run_loop())
        
    async def stop(self):
        """Stop the service"""
        self.is_running = False
        self._stop_event.set()
        logger.info("[GraphObserver] Service stopped")

    async def _run_loop(self):
        """Main periodic loop"""
        while self.is_running:
            try:
                logger.info("[GraphObserver] Starting observation cycle...")
                await self.run_observation_cycle()
                
                # Sleep interval (e.g., 30 mins)
                # Shorter for demo purposes? Let's say 15 mins.
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=900)
                except asyncio.TimeoutError:
                    pass 
                    
            except Exception as e:
                logger.error(f"[GraphObserver] Error in loop: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def run_observation_cycle(self):
        """
        Fetch recent nodes and ask LLM for insights.
        """
        # 1. Fetch recent nodes
        # We look for specific "active" types: Message, Email, CalendarEvent, ActionItem
        # created AFTER self.last_run_time
        
        start_time_iso = self.last_run_time.isoformat()
        current_time = datetime.utcnow()
        
        logger.info(f"[GraphObserver] Fetching changes since {start_time_iso}")
        
        # Native AQL Query for recent changes (filtered by user context)
        # Note: In a production multi-user system, we should iterate over active users
        # or structure the query to process all users but attribute correctly.
        # For now, we fetch recent changes and will group them by user_id.
        query = """
        FOR n IN UNION(
            (FOR x IN Message RETURN x),
            (FOR x IN Email RETURN x),
            (FOR x IN CalendarEvent RETURN x),
            (FOR x IN ActionItem RETURN x),
            (FOR x IN Project RETURN x)
        )
            FILTER n.created_at != null
            SORT n.created_at DESC
            LIMIT 25
            RETURN {
                id: n._id,
                type: [PARSE_IDENTIFIER(n._id).collection],
                props: n,
                user_id: n.user_id
            }
        """

        try:
            results = await self.graph.execute_query(query)
            
            if not results:
                logger.info("[GraphObserver] No recent activity found.")
                self.last_run_time = current_time
                return
                
            # Contextualize for LLM
            context_text = "Recent Activity:\n"
            node_map = {}
            
            for record in results:
                node_id = record['id']
                node_type = record['type'][0] # List of labels
                props = record['props']
                
                # Filter massive bodies to save tokens
                summary = props.get('subject') or props.get('text') or props.get('title') or props.get('name') or "No content"
                summary = summary[:200]
                
                context_text += f"- [{node_type}] (ID: {node_id}): {summary}\n"
                node_map[node_id] = node_type
                
            # 2. Call LLM
            llm = self._get_llm()
            if not llm:
                return

            response = await asyncio.to_thread(
                llm.invoke, 
                [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=context_text)]
            )
            
            content = response.content
            
            # Robust JSON parsing using utility
            data = repair_json(content)
            insights = data.get("insights", [])
            
            count = 0
            for insight in insights:
                # Find a reasonable user_id for this insight
                # If related_node_ids contains nodes we know about, use their user_id
                target_user_id = None
                related_ids = insight.get("related_node_ids", [])
                
                for rel_id in related_ids:
                    if rel_id in node_map:
                        # Find the original record to get user_id
                        for r in results:
                            if r['id'] == rel_id:
                                target_user_id = r.get('user_id')
                                break
                    if target_user_id: break
                
                props = {
                    "content": insight.get('content', 'Generated insight'),
                    "type": insight.get('type', 'suggestion'),
                    "confidence": float(insight.get('confidence', 0.5)),
                    "actionable": insight.get('actionable', False),
                    "created_at": datetime.utcnow().isoformat(),
                    "source": "GraphObserver",
                    "user_id": target_user_id or 1 # Fallback to default user
                }
                
                insight_id = await self.graph.create_node(NodeType.INSIGHT, props)
                
                # Link to System
                # Assuming a "System" node exists, or just leave unlinked source?
                # Let's just link to the related nodes.
                
                related_ids = insight.get("related_node_ids", [])
                for rel_id in related_ids:
                    # Only link to nodes that we know exist from our query
                    if rel_id not in node_map:
                        logger.debug(f"Skipping link to {rel_id} (not in current context)")
                        continue
                        
                    # Verify node exists? Graph manager might handle error
                    try:

                        await self.graph.create_relationship(
                            from_id=insight_id,
                            to_id=rel_id,
                            relation_type=RelationType.ABOUT
                        )
                    except Exception as e:
                         # Provide soft fail
                         logger.warning(f"Could not link insight to node {rel_id}: {e}")
                         
                count += 1
            
            # 3. Proactive Semantic Sync (Autonomous Glue Trigger)
            if self.cross_stack_context:
                await self._trigger_proactive_semantic_sync(results)
                
            if count > 0:
                logger.info(f"[GraphObserver] Generated {count} new insights")
            
            self.last_run_time = current_time
            
        except Exception as e:
            logger.error(f"[GraphObserver] Error in observation cycle: {e}")
            
    async def generate_immediate_insight(self, node: ParsedNode) -> Optional[Dict[str, Any]]:
        # 1. Quick heuristic check to avoid LLM calls for every node
        text_content = node.searchable_text or ""
        subject = node.properties.get('subject', '') or node.properties.get('title', '')
        
        is_potentially_urgent = False
        
        # Check for urgent keywords
        urgent_keywords = ['urgent', 'asap', 'emergency', 'deadline', 'important', 'conflict']
        content_lower = (text_content + " " + subject).lower()
        
        if any(w in content_lower for w in urgent_keywords):
            is_potentially_urgent = True
            
        # Check for specific types that are often urgent
        if node.node_type in ['CalendarEvent', 'ActionItem']:
            is_potentially_urgent = True
            
        if not is_potentially_urgent:
            return None
            
        # 2. Use LLM to analyze for specific insights
        try:
            llm = self._get_llm()
            if not llm:
                return None
                
            prompt = f"""
            Analyze this new {node.node_type} for immediate actionable insights.
            
            Item: {subject}
            Content: {text_content[:500]}
            
            Return a JSON object with 'insight' key if there is a conflict, connection, or urgent action.
            Format: {{ "insight": {{ "content": "...", "type": "conflict|connection|action", "confidence": 0.9 }} }}
            If no important insight, return {{ "insight": null }}
            """
            
            import json
            from langchain_core.messages import SystemMessage, HumanMessage
            
            response = await asyncio.to_thread(
                llm.invoke,
                [SystemMessage(content="You are a personal assistant observer."), HumanMessage(content=prompt)]
            )
            
            # Robust JSON parsing using utility
            data = repair_json(response.content)
            insight_data = data.get("insight")
            
            if not insight_data or insight_data.get("confidence", 0) < 0.8:
                return None
                
            # 3. Store insight in graph
            props = {
                "content": insight_data.get('content', 'Immediate action required'),
                "type": insight_data.get('type', 'action'),
                "confidence": float(insight_data.get('confidence', 0.9)),
                "actionable": True,
                "created_at": datetime.utcnow().isoformat(),
                "source": "GraphObserver_Immediate",
                "urgency_shown": False,  # Flag to ensure it gets shown immediately
                "user_id": node.properties.get('user_id')
            }
            
            insight_id = await self.graph.create_node(NodeType.INSIGHT, props)
            
            # Link to source node
            await self.graph.create_relationship(
                from_id=insight_id,
                to_id=node.node_id,
                relation_type=RelationType.ABOUT
            )
            
            logger.info(f"[GraphObserver] Generated immediate insight: {props['content']}")
            
            # 4. Trigger Notification Callback if urgency > 0.8
            if self._notify_callback and props.get('confidence', 0) >= 0.9:
                try:
                    await self._notify_callback(props)
                except Exception as e:
                    logger.error(f"[GraphObserver] Failed to trigger notification callback: {e}")
            
            return props
            
        except Exception as e:
            logger.warning(f"[GraphObserver] Immediate insight generation failed: {e}")
            return None
            
    def _get_llm(self, max_tokens: int = 2048):
        """Get or initialize the LLM for insight generation."""
        # We check if the cached LLM has the same max_tokens, if not we recreate it
        # Actually, LLMFactory caches them internally by key, so we can just call it.
        try:
            return LLMFactory.get_llm_for_provider(self.config, temperature=0.2, max_tokens=max_tokens)
        except Exception as e:
            logger.error(f"[GraphObserver] Failed to get LLM: {e}")
            return None
        
    # =========================================================================
    # Enhanced Intelligence Methods
    # =========================================================================
    
    async def correlate_recent_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Correlate related events to generate more meaningful insights.
        
        Groups events by:
        - Same sender/author
        - Same topic/project
        - Same time window
        - Same attendees
        
        Returns aggregated insights instead of point-by-point analysis.
        """
        if not events or len(events) < 2:
            return []
            
        correlated_insights = []
        
        # Group by author/sender
        by_author: Dict[str, List[Dict]] = {}
        for event in events:
            author = event.get('from') or event.get('author') or event.get('sender')
            if author:
                by_author.setdefault(author, []).append(event)
                
        # Find authors with multiple events (potential spam or urgent pattern)
        for author, author_events in by_author.items():
            if len(author_events) >= 3:
                event_types = set(e.get('type', 'unknown') for e in author_events)
                correlated_insights.append({
                    "type": "correlation",
                    "pattern": "multiple_from_same_sender",
                    "count": len(author_events),
                    "author": author,
                    "event_types": list(event_types),
                    "content": f"Received {len(author_events)} items from {author} recently",
                    "confidence": 0.8
                })
                
        # Group by topic keywords
        topic_events: Dict[str, List[Dict]] = {}
        topic_keywords = ['project', 'meeting', 'deadline', 'urgent', 'review', 'task']
        
        for event in events:
            content = (
                event.get('subject', '') + ' ' + 
                event.get('title', '') + ' ' + 
                event.get('text', '')[:100]
            ).lower()
            
            for keyword in topic_keywords:
                if keyword in content:
                    topic_events.setdefault(keyword, []).append(event)
                    
        # Find clustered topics
        for topic, topic_items in topic_events.items():
            if len(topic_items) >= 3:
                correlated_insights.append({
                    "type": "correlation",
                    "pattern": "topic_cluster",
                    "topic": topic,
                    "count": len(topic_items),
                    "content": f"Multiple recent items about '{topic}'",
                    "confidence": 0.7
                })
                
        return correlated_insights
        
    async def detect_anomalies(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Detect anomalous patterns in user activity.
        
        Anomalies include:
        - Unusual activity times (meetings at 2 AM)
        - Unusual volume (50 emails when normal is 10)
        - Unusual patterns (weekend work when never done before)
        """
        anomalies = []
        
        try:
            # Check for unusual time activities
            query = """
            FOR n IN UNION(
                (FOR x IN CalendarEvent RETURN x),
                (FOR x IN Email RETURN x),
                (FOR x IN ActionItem RETURN x)
            )
                FILTER n.user_id == @user_id
                FILTER n.created_at != null
                SORT n.created_at DESC
                LIMIT 50
                RETURN {
                    created: n.created_at,
                    type: PARSE_IDENTIFIER(n._id).collection,
                    title: n.title
                }
            """
            
            results = await self.graph.execute_query(query, {"user_id": user_id})
            
            unusual_hours = []
            weekend_activity = []
            
            for record in results or []:
                created_str = record.get('created')
                if not created_str:
                    continue
                    
                try:
                    if isinstance(created_str, str):
                        created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
                    else:
                        created = created_str
                        
                    hour = created.hour
                    weekday = created.weekday()
                    
                    # Check for unusual hours (before 6 AM or after 10 PM)
                    if hour < 6 or hour > 22:
                        unusual_hours.append({
                            "time": created.isoformat(),
                            "type": record.get('type'),
                            "title": record.get('title', 'Unknown')[:50]
                        })
                        
                    # Check for weekend activity
                    if weekday >= 5:
                        weekend_activity.append({
                            "time": created.isoformat(),
                            "type": record.get('type'),
                            "title": record.get('title', 'Unknown')[:50]
                        })
                except (ValueError, AttributeError):
                    continue
                    
            # Report unusual hours
            if len(unusual_hours) >= 3:
                anomalies.append({
                    "type": "anomaly",
                    "pattern": "unusual_hours",
                    "count": len(unusual_hours),
                    "examples": unusual_hours[:3],
                    "content": f"Detected {len(unusual_hours)} activities at unusual hours",
                    "confidence": 0.7,
                    "actionable": True
                })
                
            # Report weekend activity
            if len(weekend_activity) >= 5:
                anomalies.append({
                    "type": "anomaly",
                    "pattern": "weekend_work",
                    "count": len(weekend_activity),
                    "content": f"Significant weekend activity detected ({len(weekend_activity)} items)",
                    "confidence": 0.6,
                    "actionable": True
                })
                
        except Exception as e:
            logger.error(f"[GraphObserver] Anomaly detection failed: {e}")
            
        return anomalies
        
    async def run_business_watchdog(self) -> List[Dict[str, Any]]:
        """
        Specifically identify business opportunities that need attention:
        1. Stale Leads (Lead nodes with no recent interaction)
        2. Unanswered Questions (Emails with questions but no reply)
        """
        watchdog_insights = []
        
        try:
            # 1. Detect Stale Leads
            # LEAD nodes created > 3 days ago with no FOLLOWS relationship in the last 7 days
            stale_leads_query = """
            FOR l IN Lead
                // Filter by recent changes if we had a user_id context, 
                // but watchdog often runs globally. We MUST ensure it returns user_id.
                FILTER l.created_at < DATE_SUBTRACT(DATE_NOW(), 3, "days")
                
                // Check for recent interactions (RELATED_TO from Email)
                LET recent_interactions = LENGTH(
                    FOR r IN RELATED_TO
                        FILTER r._to == l._id
                        FOR e IN Email
                            FILTER e._id == r._from
                            FILTER e.date > DATE_SUBTRACT(DATE_NOW(), 7, "days")
                            LIMIT 1
                            RETURN 1
                )
                
                FILTER recent_interactions == 0
                LIMIT 20
                RETURN {
                    id: l.id,
                    name: l.name,
                    level: l.interest_level,
                    topic: l.topic,
                    user_id: l.user_id
                }
            """
            
            # Execute AQL query directly against ArangoDB
            
            leads = await self.graph.execute_query(stale_leads_query)
            for lead in leads or []:
                watchdog_insights.append({
                    "type": "follow_up",
                    "subtype": "stale_lead",
                    "content": f"Lead '{lead['name']}' hasn't been contacted in over 3 days regarding {lead.get('topic', 'their interest')}.",
                    "related_node_ids": [lead['id']],
                    "confidence": 0.85,
                    "actionable": True,
                    "metadata": {"lead_name": lead['name'], "topic": lead.get('topic')}
                })

            # 2. Detect Unanswered Questions
            # Email nodes with has_questions=True and no outgoing REPLIED_TO relationship
            unanswered_query = """
            FOR e IN Email
                FILTER e.has_questions == true
                FILTER e.date > DATE_SUBTRACT(DATE_NOW(), 7, "days")
                
                // Check for replies (REPLIED_TO -> e)
                LET has_reply = LENGTH(
                    FOR r IN REPLIED_TO
                        FILTER r._to == e._id
                        LIMIT 1
                        RETURN 1
                ) > 0
                
                FILTER NOT has_reply
                LIMIT 10
                RETURN {
                    id: e.id,
                    subject: e.subject,
                    sender: e.sender_name
                }
            """
            
            emails = await self.graph.execute_query(unanswered_query)
            for email in emails or []:
                watchdog_insights.append({
                    "type": "follow_up",
                    "subtype": "unanswered_question",
                    "content": f"You haven't replied to questions from {email['sender']} in '{email['subject']}'.",
                    "related_node_ids": [email['id']],
                    "confidence": 0.9,
                    "actionable": True,
                    "metadata": {"sender": email['sender'], "subject": email['subject']}
                })

            # 3. For each watchdog insight, use LLM to generate a draft if actionable
            for insight in watchdog_insights:
                if insight.get('actionable'):
                    draft = await self._generate_draft_content(insight)
                    if draft:
                        insight['content'] += f" Draft: {draft[:100]}..."
                        insight['draft_body'] = draft

            # 4. Detect Overdue Tasks (Google Tasks + Asana ActionItems)
            overdue_tasks_query = """
            FOR task IN GoogleTask
                FILTER task.status == 'pending' OR task.status == 'needsAction'
                FILTER task.due != null
                FILTER task.due < DATE_ISO8601(DATE_NOW())
                LIMIT 10
                RETURN {
                    id: task._id,
                    title: task.title,
                    due: task.due,
                    source: 'google_tasks',
                    user_id: task.user_id
                }
            """
            
            try:
                overdue_results = await self.graph.execute_query(overdue_tasks_query)
                for task in overdue_results or []:
                    watchdog_insights.append({
                        "type": "follow_up",
                        "subtype": "overdue_task",
                        "content": f"Task '{task['title']}' is overdue (due: {task.get('due', 'unknown')}).",
                        "related_node_ids": [task['id']],
                        "confidence": 0.9,
                        "actionable": True,
                        "metadata": {"title": task['title'], "due": task.get('due'), "source": task.get('source')},
                        "user_id": task.get('user_id')
                    })
            except Exception as e:
                logger.debug(f"[GraphObserver] Overdue tasks query failed (collection may not exist): {e}")
            
            # Also check Asana ActionItem overdue
            overdue_asana_query = """
            FOR item IN ActionItem
                FILTER item.source == 'asana'
                FILTER item.status IN ['pending', 'not_started', 'in_progress']
                FILTER item.due_date != null
                FILTER item.due_date < DATE_ISO8601(DATE_NOW())
                LIMIT 10
                RETURN {
                    id: item._id,
                    title: item.title,
                    due: item.due_date,
                    source: 'asana',
                    user_id: item.user_id
                }
            """
            
            try:
                overdue_asana = await self.graph.execute_query(overdue_asana_query)
                for item in overdue_asana or []:
                    watchdog_insights.append({
                        "type": "follow_up",
                        "subtype": "overdue_task",
                        "content": f"Asana task '{item['title']}' is overdue (due: {item.get('due', 'unknown')}).",
                        "related_node_ids": [item['id']],
                        "confidence": 0.9,
                        "actionable": True,
                        "metadata": {"title": item['title'], "due": item.get('due'), "source": "asana"},
                        "user_id": item.get('user_id')
                    })
            except Exception as e:
                logger.debug(f"[GraphObserver] Overdue Asana query failed: {e}")
            
            # 5. Detect Stale Linear Issues (no update in 7+ days, not completed)
            stale_linear_query = """
            FOR issue IN LinearIssue
                FILTER issue.stateType NOT IN ['completed', 'cancelled', 'done']
                FILTER issue.updated_at != null
                FILTER DATE_DIFF(issue.updated_at, DATE_NOW(), 'day') > 7
                LIMIT 10
                RETURN {
                    id: issue._id,
                    title: issue.title,
                    identifier: issue.identifier,
                    state: issue.state,
                    updated_at: issue.updated_at,
                    user_id: issue.user_id
                }
            """
            
            try:
                stale_issues = await self.graph.execute_query(stale_linear_query)
                for issue in stale_issues or []:
                    days_stale = 7  # minimum
                    if issue.get('updated_at'):
                        try:
                            updated = datetime.fromisoformat(str(issue['updated_at']).replace('Z', '+00:00'))
                            days_stale = (datetime.utcnow() - updated.replace(tzinfo=None)).days
                        except (ValueError, AttributeError):
                            pass
                    
                    watchdog_insights.append({
                        "type": "follow_up",
                        "subtype": "stale_issue",
                        "content": f"Linear issue {issue.get('identifier', '')} '{issue['title']}' hasn't been updated in {days_stale} days (state: {issue.get('state', 'unknown')}).",
                        "related_node_ids": [issue['id']],
                        "confidence": 0.85,
                        "actionable": True,
                        "metadata": {
                            "identifier": issue.get('identifier'),
                            "title": issue['title'],
                            "state": issue.get('state'),
                            "days_stale": days_stale
                        },
                        "user_id": issue.get('user_id')
                    })
            except Exception as e:
                logger.debug(f"[GraphObserver] Stale Linear issues query failed: {e}")

        except Exception as e:
            logger.error(f"[GraphObserver] Business Watchdog failed: {e}")
            
        return watchdog_insights

    async def _generate_draft_content(self, insight: Dict[str, Any]) -> Optional[str]:
        """Use LLM to generate a context-aware follow-up draft."""
        try:
            llm = self._get_llm()
            if not llm:
                return None
                
            prompt = (
                f"Generate a short, professional follow-up email draft based on this insight:\n"
                f"Insight: {insight['content']}\n"
                f"Type: {insight.get('subtype')}\n\n"
                f"Guidelines:\n"
                f"- Keep it brief (2-3 sentences).\n"
                f"- Professional but friendly tone.\n"
                f"- Focus on helping the recipient.\n\n"
                f"Respond only with the email body content."
            )
            
            response = await asyncio.to_thread(llm.invoke, [HumanMessage(content=prompt)])
            return response.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate draft: {e}")
            return None

    def prioritize_insights(self, insights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not insights:
            return []
            
        # Define priority weights
        type_weights = {
            'conflict': 1.0,
            'anomaly': 0.8,
            'action': 0.7,
            'correlation': 0.5,
            'connection': 0.4,
            'suggestion': 0.3
        }
        
        def calculate_priority(insight: Dict) -> float:
            insight_type = insight.get('type', 'suggestion')
            type_weight = type_weights.get(insight_type, 0.3)
            confidence = insight.get('confidence', 0.5)
            actionable_bonus = 0.2 if insight.get('actionable', False) else 0.0
            
            # Calculate final priority
            priority = (type_weight * 0.5) + (confidence * 0.3) + actionable_bonus
            return priority
            
        # Sort by priority (highest first)
        sorted_insights = sorted(insights, key=calculate_priority, reverse=True)
        
        # Add priority rank
        for i, insight in enumerate(sorted_insights):
            insight['priority_rank'] = i + 1
            insight['priority_score'] = round(calculate_priority(insight), 2)
            
        return sorted_insights
        
    async def run_enhanced_observation(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        stats = {"insights": 0, "correlations": 0, "anomalies": 0}
        
        try:
            # 1. Run standard observation cycle
            await self.run_observation_cycle()
            
            # 2. If user_id provided, run user-specific enhanced analysis
            if user_id:
                # Detect anomalies
                anomalies = await self.detect_anomalies(user_id)
                stats["anomalies"] = len(anomalies)
                
                # Store anomalies as insights
                for anomaly in anomalies:
                    if anomaly.get('confidence', 0) >= 0.6:
                        await self.graph.create_node(NodeType.INSIGHT, {
                            "content": anomaly.get('content', ''),
                            "type": "anomaly",
                            "confidence": anomaly.get('confidence', 0.5),
                            "actionable": anomaly.get('actionable', False),
                            "created_at": datetime.utcnow().isoformat(),
                            "source": "GraphObserver_Enhanced",
                            "user_id": user_id
                        })
            
            # 3. Run Business Watchdog
            watchdog_insights = await self.run_business_watchdog()
            stats["watchdog_items"] = len(watchdog_insights)
            
            for insight in watchdog_insights:
                await self.graph.create_node(NodeType.INSIGHT, {
                    "content": insight['content'],
                    "type": insight['type'],
                    "subtype": insight.get('subtype'),
                    "confidence": insight.get('confidence', 0.5),
                    "actionable": insight.get('actionable', False),
                    "draft_body": insight.get('draft_body'),
                    "created_at": datetime.utcnow().isoformat(),
                    "source": "GraphObserver_Watchdog",
                    "user_id": user_id or insight.get('user_id')
                })
                        
            logger.info(f"[GraphObserver] Enhanced observation complete: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"[GraphObserver] Enhanced observation failed: {e}")
            return stats

    async def _trigger_proactive_semantic_sync(self, recent_nodes: List[Dict[str, Any]]):
        """
        Detect mentioned projects/IDs in recent activity and trigger a 360-degree summary.
        This provides the "Semantic Sync" proactively.
        """
        from src.ai.capabilities.nlp_processor import NLPProcessor
        processor = NLPProcessor()
        
        detected_topics = [] # List of tuples (topic, user_id)
        
        for node in recent_nodes:
            props = node.get('props', {})
            content = (props.get('subject') or props.get('text') or props.get('title') or "")
            if not content: continue
            
            node_user_id = props.get('user_id') or node.get('user_id')
            if not node_user_id: continue
            
            # Extract topics using NLP patterns (Linear IDs, Projects)
            nlp_res = processor.process_query(content)
            for entity in nlp_res.get('entities', []):
                if entity.entity_type in ['linear_id', 'project_name']:
                    detected_topics.append((entity.resolved_value, node_user_id))
        
        # Trigger sync for each new topic detected
        processed_pairs = set()
        for topic, u_id in detected_topics:
            if (topic, u_id) in processed_pairs: continue
            processed_pairs.add((topic, u_id))
            
            try:
                logger.info(f"[GraphObserver] Proactive Semantic Sync triggered for {topic} (User {u_id})")
                # Build the rich 360-degree context
                context = await self.cross_stack_context.build_topic_context(topic, u_id)
                
                # Save as a premium INSIGHT node
                summary = context.get('summary', 'Synthesis failed.')
                await self.graph.create_node(NodeType.INSIGHT, {
                    "content": f"360° Perspective on '{topic}': {summary}",
                    "type": "semantic_sync",
                    "subtype": "autonomous_glue",
                    "topic": topic,
                    "confidence": 0.95,
                    "actionable": len(context.get('action_items', [])) > 0,
                    "created_at": datetime.utcnow().isoformat(),
                    "source": "AutonomousGlue_Proactive",
                    "user_id": u_id
                })
            except Exception as e:
                logger.warning(f"Failed to trigger proactive sync for {topic}: {e}")

