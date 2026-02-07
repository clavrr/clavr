"""
Thread Analyzer Ghost Agent

Watches Slack threads for patterns that indicate actionable items:
- Bug reports that need Linear tickets
- Decision requests that need follow-up
- Heated discussions that may need escalation

The "Ghost Collaborator" feature - works while you sleep.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
import re

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User, GhostDraft
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.ai.llm_factory import LLMFactory
from src.services.notifications.notification_service import NotificationService, NotificationRequest, NotificationType, NotificationPriority
from src.utils.config import Config, ConfigDefaults

logger = setup_logger(__name__)


class ThreadAnalyzerAgent:
    """
    Ghost Agent that analyzes Slack threads and suggests actions.
    
    Triggers:
    - slack.thread.updated: When a thread gets new messages
    - slack.message.created: When a message is posted (analyze for thread potential)
    
    Actions:
    - Draft Linear issue if bug pattern detected
    - Alert user if heated discussion
    - Extract and summarize action items
    """
    
    def __init__(self, db_session, config: Config, graph_manager: Optional[KnowledgeGraphManager] = None):
        self.db = db_session
        self.config = config
        self.graph = graph_manager
        self.llm = None
        self.notification_service = NotificationService(db_session)
    
    async def handle_event(self, event_type: str, payload: Dict[str, Any], user_id: int):
        """Handle Slack thread events."""
        if event_type not in ["slack.thread.updated", "slack.message.created"]:
            return
        
        logger.info(f"[Ghost] ThreadAnalyzer examining message in channel {payload.get('channel')}")
        
        # Analyze the message/thread
        analysis = await self._analyze_thread(payload)
        
        if not analysis.get("needs_action"):
            return
        
        # Take action based on analysis
        await self._take_action(analysis, user_id, payload)
    
    async def _analyze_thread(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a Slack thread/message using LLM for high-fidelity detection.
        """
        messages = payload.get("messages", [])
        if not messages:
            messages = [{"text": payload.get("text", ""), "user": payload.get("user", "unknown")}]
        
        # Format thread for LLM
        thread_transcript = "\n".join([f"{m.get('user', 'User')}: {m.get('text', '')}" for m in messages])
        
        analysis = {
            "needs_action": False,
            "action_type": None,
            "confidence": 0.0,
            "summary": "",
            "suggested_action": "",
            "message_count": len(messages),
            "channel": payload.get("channel"),
            "thread_ts": payload.get("thread_ts"),
            "draft_title": "",
            "draft_description": ""
        }

        # 1. AI Pattern Detection (The Clavr Difference)
        try:
            detected = await self._llm_analyze_sentiment(thread_transcript)
            if detected and detected.get("needs_action"):
                analysis.update(detected)
                
                # 2. Duplicate Check (Autonomous Glue)
                if analysis["action_type"] == "bug_report" and self.graph:
                    is_duplicate = await self._is_already_ticketed(analysis["draft_title"])
                    if is_duplicate:
                        logger.info(f"[Ghost] Skipping already ticketed issue: {analysis['draft_title']}")
                        analysis["needs_action"] = False
        except Exception as e:
            logger.error(f"[Ghost] LLM analysis failed, falling back to heuristics: {e}")
            # Fallback to simple heuristics (existing logic moved to helper)
            analysis = self._heuristic_analysis(payload, analysis)
        
        return analysis

    async def _llm_analyze_sentiment(self, transcript: str) -> Optional[Dict[str, Any]]:
        """Deep analysis of thread sentiment and intent."""
        if not self.llm:
            self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.2)
        
        from langchain_core.messages import SystemMessage, HumanMessage
        import json

        system_prompt = """
        You are 'The Ghost Collaborator', a proactive AI observer. 
        Analyze this Slack thread. Determine if it contains a bug report, a heated discussion needing attention, or clear action items.
        
        Return JSON format:
        {
          "needs_action": bool,
          "action_type": "bug_report" | "heated" | "action_items" | null,
          "confidence": float (0-1),
          "summary": "concise summary of thread",
          "draft_title": "Short descriptive title if bug",
          "draft_description": "Detailed description if bug"
        }
        """
        
        try:
            response = await asyncio.to_thread(
                self.llm.invoke,
                [SystemMessage(content=system_prompt), HumanMessage(content=transcript)]
            )
            content = response.content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        except Exception as e:
            logger.debug(f"LLM analysis failed to parse response: {e}")
            return None

    async def _is_already_ticketed(self, title: str) -> bool:
        """Check ArangoDB for similar issues to prevent noise."""
        if not self.graph: return False
        
        # Simple fuzzy search in the graph for issues with similar titles
        query = """
        FOR i IN Issue
            FILTER LIKE(i.title, @pattern, true)
            LIMIT 1
            RETURN i.id
        """
        # Create a basic like pattern (words > 3 chars)
        words = [w for w in title.split() if len(w) > 3]
        if not words: return False
        
        pattern = f"%{words[0]}%"
        results = await self.graph.execute_query(query, {"pattern": pattern})
        return len(results) > 0

    def _heuristic_analysis(self, payload: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Original keyword-based heuristic fallback."""
        messages = payload.get("messages", [])
        if not messages:
            messages = [{"text": payload.get("text", "")}]
        
        full_text = " ".join(m.get("text", "") for m in messages).lower()
        
        # Check for bug report pattern
        bug_score = self._calculate_pattern_score(full_text, ConfigDefaults.GHOST_BUG_KEYWORDS)
        if bug_score > ConfigDefaults.GHOST_CONFIDENCE_THRESHOLD:
            analysis["needs_action"] = True
            analysis["action_type"] = "bug_report"
            analysis["confidence"] = bug_score
            analysis["summary"] = self._extract_summary(full_text, ConfigDefaults.GHOST_BUG_KEYWORDS)
            analysis["draft_title"] = f"Bug Report: {analysis['summary'][:50]}"
            analysis["suggested_action"] = "Create Linear issue"
        
        return analysis
    
    def _calculate_pattern_score(self, text: str, keywords: List[str]) -> float:
        """Calculate how strongly text matches a pattern."""
        matches = sum(1 for kw in keywords if kw in text)
        return min(1.0, matches / len(keywords) * 2)
    
    def _extract_summary(self, text: str, context_keywords: List[str]) -> str:
        """Extract a brief summary around matching keywords."""
        for kw in context_keywords:
            idx = text.find(kw)
            if idx != -1:
                start = max(0, idx - 50)
                end = min(len(text), idx + 100)
                return "..." + text[start:end].strip() + "..."
        return text[:150] + "..."
    
    async def _take_action(self, analysis: Dict[str, Any], user_id: int, payload: Dict[str, Any]):
        """Take action based on analysis."""
        action_type = analysis.get("action_type")
        
        if action_type == "bug_report":
            await self._draft_linear_issue(analysis, user_id, payload)
        elif action_type == "heated":
            await self._alert_user(analysis, user_id, payload)
        elif action_type in ["decision", "action_items"]:
            await self._alert_user(analysis, user_id, payload)
    
    async def _draft_linear_issue(self, analysis: Dict[str, Any], user_id: int, payload: Dict[str, Any]):
        """Draft a Linear issue, persist it, and notify user."""
        channel = payload.get("channel", "Unknown")
        thread_ts = payload.get("thread_ts")
        
        title = analysis.get("draft_title") or f"Bug Report: {analysis.get('summary', 'Issue from Slack')[:50]}"
        description = analysis.get("draft_description") or f"Source: Slack thread in #{channel}\n\nSummary: {analysis.get('summary')}"
        
        # 1. Persist Draft
        draft = GhostDraft(
            user_id=user_id,
            title=title,
            description=description,
            status="draft",
            source_channel=channel,
            source_thread_ts=thread_ts,
            integration_type="linear",
            confidence=analysis.get("confidence", 0.0),
            summary=analysis.get("summary")
        )
        self.db.add(draft)
        await self.db.commit()
        await self.db.refresh(draft)

        # 2. Notification Service for In-App Alert
        req = NotificationRequest(
            user_id=user_id,
            title=f"🐛 Potential Bug: {title[:40]}...",
            message=f"I've drafted a Linear issue based on the discussion in #{channel}. Review it in your Ghost dashboard.",
            notification_type=NotificationType.APPROVAL_NEEDED,
            priority=NotificationPriority.HIGH if analysis.get("confidence", 0) > 0.8 else NotificationPriority.NORMAL,
            icon="git-pull-request",
            action_label="Review & Post",
            action_url=f"/dashboard/ghost/drafts/{draft.id}"
        )
        
        await self.notification_service.send_notification(req)
        
        # Fallback to Email (Secondary)
        await self._send_fallback_email(title, description, analysis, user_id, channel)

    async def _alert_user(self, analysis: Dict[str, Any], user_id: int, payload: Dict[str, Any]):
        """Alert user about heated or decision threads."""
        action_type = analysis.get("action_type")
        channel = payload.get("channel", "Unknown")
        
        type_emoji = {"heated": "🔥", "decision": "🤔", "action_items": "✅"}
        type_title = {"heated": "Heated Discussion", "decision": "Decision Needed", "action_items": "Action Items Detected"}
        
        req = NotificationRequest(
            user_id=user_id,
            title=f"{type_emoji.get(action_type, '📢')} {type_title.get(action_type, 'Thread Alert')}",
            message=f"Discussion in #{channel} seems {action_type}. {analysis.get('summary')}",
            notification_type=NotificationType.SYSTEM,
            priority=NotificationPriority.NORMAL,
            icon=type_emoji.get(action_type, 'bell'),
            action_label="View Thread",
            action_url=f"slack://channel?team=&id={channel}"
        )
        
        await self.notification_service.send_notification(req)

    async def _send_fallback_email(self, title, description, analysis, user_id, channel):
        """Original email logic moved to fallback."""
        from sqlalchemy import select
        stmt = select(User).where(User.id == user_id)
        res = await self.db.execute(stmt)
        user = res.scalar_one_or_none()
        
        if not user: return

        draft = {"title": title, "description": description, "priority": "high" if analysis.get("confidence", 0) > 0.7 else "medium"}
        html = self._build_draft_notification(draft, analysis)
        
        from src.workers.tasks.email_tasks import send_email
        send_email.delay(to=user.email, subject=f"🐛 Ghost Draft: {title[:40]}...", body=html, user_id=str(user_id), html=True)
    
    def _build_draft_notification(self, draft: Dict[str, Any], analysis: Dict[str, Any]) -> str:
        """Build HTML notification for draft Linear issue."""
        return f"""
        <div style="font-family: sans-serif; color: #333; max-width: 600px;">
            <h2 style="color: #5e6ad2;">🐛 I've drafted a Linear issue for you</h2>
            
            <p>A Slack thread looks like a bug report ({int(analysis.get('confidence', 0) * 100)}% confidence).</p>
            
            <div style="background: #f0f4ff; padding: 20px; border-radius: 8px; border-left: 4px solid #5e6ad2; margin: 15px 0;">
                <h3 style="margin-top: 0;">{draft.get('title')}</h3>
                <pre style="background: #fff; padding: 10px; border-radius: 4px; overflow-x: auto; font-size: 0.85em;">{draft.get('description', '')[:500]}</pre>
                <p><strong>Priority:</strong> {draft.get('priority', 'medium').title()}</p>
            </div>
            
            <p>
                <a href="#" style="background: #5e6ad2; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">
                    Create Issue in Linear
                </a>
                <a href="#" style="margin-left: 10px; color: #64748b;">Dismiss</a>
            </p>
            
            <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
            <p style="font-size: 0.8em; color: #94a3b8;">
                Ghost Collaborator • Clavr is watching your Slack so you don't have to
            </p>
        </div>
        """
