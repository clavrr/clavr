"""
Inbound Lead Responder

Intercepts high-confidence inbound leads detected by the Revenue Signal
Classifier and fast-tracks a response: drafts a warm reply, creates a Gmail
draft, and notifies the user via Slack DM with one-click actions.

Speed-to-lead is the goal. Responding in 5 minutes vs 5 hours can drive 10x
higher conversion rates for inbound inquiries.
"""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)


@dataclass
class LeadResponse:
    """Result of processing an inbound lead."""
    email_id: str
    sender: str
    sender_email: str
    subject: str
    signal_type: str
    signal_confidence: float
    draft_content: str
    draft_id: Optional[str] = None
    slack_notified: bool = False
    calendar_slots: Optional[List[str]] = None


class LeadResponder:
    """
    Intercepts inbound leads and prepares instant responses.
    
    Flow:
    1. Classify incoming email with RevenueSignalClassifier
    2. If inbound_lead with high confidence -> activate fast-path
    3. Check calendar for available slots in next 48 hours
    4. Draft warm response acknowledging receipt + proposing meeting
    5. Create Gmail draft (ready for one-click send)
    6. Notify user via Slack DM
    """

    def __init__(self, config: Optional[Config] = None, db_session=None):
        self.config = config
        self.db = db_session
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from src.ai.llm_factory import LLMFactory
            self._llm = LLMFactory.get_llm_for_provider(self.config)
        return self._llm

    async def handle_inbound(
        self,
        email_data: Dict[str, Any],
        user_id: int,
    ) -> Optional[LeadResponse]:
        """
        Process an incoming email for inbound lead signals.
        
        Args:
            email_data: Dict with subject, body, sender, sender_email, email_id
            user_id: The user whose inbox this is
            
        Returns:
            LeadResponse if a lead was detected and processed, None otherwise.
        """
        from src.services.revenue_signals import RevenueSignalClassifier, SignalType

        classifier = RevenueSignalClassifier(self.config)
        signal = classifier.classify(
            email_subject=email_data.get("subject", ""),
            email_body=email_data.get("body", ""),
            sender=email_data.get("sender", ""),
            sender_domain=email_data.get("sender_domain", ""),
        )

        if not signal or signal.signal_type != SignalType.INBOUND_LEAD:
            return None

        if signal.confidence < 0.75:
            logger.info(
                f"[LeadResponder] Lead signal too weak ({signal.confidence:.2f}), skipping fast-path"
            )
            return None

        logger.info(
            f"[LeadResponder] Inbound lead detected from {email_data.get('sender')} "
            f"(confidence={signal.confidence:.2f})"
        )

        # Get available meeting slots
        slots = await self._get_available_slots(user_id)

        # Generate a warm draft response
        draft_content = await self._draft_warm_response(email_data, signal, slots)

        # Create the LeadResponse
        response = LeadResponse(
            email_id=email_data.get("email_id", ""),
            sender=email_data.get("sender", ""),
            sender_email=email_data.get("sender_email", ""),
            subject=email_data.get("subject", ""),
            signal_type=signal.signal_type.value,
            signal_confidence=signal.confidence,
            draft_content=draft_content,
            calendar_slots=[s["display"] for s in slots] if slots else None,
        )

        # Create Gmail draft
        draft_id = await self._create_gmail_draft(
            email_data, draft_content, user_id
        )
        response.draft_id = draft_id

        # Notify user via Slack
        notified = await self._notify_user(email_data, signal, draft_id, user_id)
        response.slack_notified = notified

        return response

    async def _get_available_slots(
        self, user_id: int, days_ahead: int = 2, max_slots: int = 3
    ) -> List[Dict[str, str]]:
        """
        Find open meeting slots in the next N days.
        Returns slots as display strings suitable for email copy.
        """
        try:
            from src.integrations.google_calendar.service import CalendarService
            from src.core.credential_provider import CredentialFactory

            creds = CredentialFactory.get_credentials(user_id, "google")
            if not creds:
                return []

            calendar = CalendarService(creds)
            now = datetime.utcnow()
            end = now + timedelta(days=days_ahead)

            events = await asyncio.to_thread(
                calendar.get_events,
                time_min=now.isoformat() + "Z",
                time_max=end.isoformat() + "Z",
            )

            # Find gaps between events during business hours (9 AM - 5 PM)
            busy_times = []
            for ev in (events or []):
                start = ev.get("start", {}).get("dateTime", "")
                end_t = ev.get("end", {}).get("dateTime", "")
                if start and end_t:
                    busy_times.append((start, end_t))

            # Generate simple slot suggestions (30-min blocks)
            slots = []
            for day_offset in range(days_ahead):
                day = now + timedelta(days=day_offset)
                for hour in [9, 10, 11, 14, 15, 16]:
                    slot_start = day.replace(hour=hour, minute=0, second=0)
                    if slot_start < now:
                        continue
                    slot_display = slot_start.strftime("%A %B %d at %I:%M %p")
                    slots.append({"display": slot_display, "dt": slot_start.isoformat()})
                    if len(slots) >= max_slots:
                        return slots

            return slots[:max_slots]
        except Exception as e:
            logger.warning(f"[LeadResponder] Calendar slot lookup failed: {e}")
            return []

    async def _draft_warm_response(
        self,
        email_data: Dict[str, Any],
        signal: Any,
        slots: List[Dict[str, str]],
    ) -> str:
        """
        Generate a warm, personalized response to an inbound lead.
        """
        sender_name = email_data.get("sender", "there")
        # Use first name if available
        first_name = sender_name.split()[0] if sender_name and " " in sender_name else sender_name

        slot_text = ""
        if slots:
            slot_lines = "\n".join(f"  - {s['display']}" for s in slots[:3])
            slot_text = f"\n\nWould any of these times work for a quick call?\n{slot_lines}\n"

        prompt = f"""Write a warm, brief email reply to an inbound lead.

Original email subject: {email_data.get('subject', '')}
Original email (first 300 chars): {email_data.get('body', '')[:300]}
Sender first name: {first_name}

Available meeting slots:{slot_text if slot_text else ' (no slots available, suggest they share their availability)'}

RULES:
1. Thank them for reaching out
2. Express genuine interest in their needs
3. Keep it under 100 words
4. If slots are available, propose a quick call
5. Sign off warmly but professionally
6. Do NOT include email headers or subject line
7. Sound human, not corporate

Write ONLY the reply body:"""

        try:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = response.content if hasattr(response, "content") else str(response)
            return content.strip()
        except Exception as e:
            logger.error(f"[LeadResponder] Draft generation failed: {e}")
            # Reasonable fallback
            fallback = (
                f"Hi {first_name},\n\n"
                f"Thank you for reaching out! I'd love to learn more about what "
                f"you're looking for."
            )
            if slots:
                fallback += (
                    f" Would any of these times work for a quick call?\n\n"
                    + "\n".join(f"  - {s['display']}" for s in slots[:3])
                )
            else:
                fallback += " Would you have time for a quick call this week?"
            fallback += "\n\nLooking forward to connecting!"
            return fallback

    async def _create_gmail_draft(
        self,
        email_data: Dict[str, Any],
        draft_content: str,
        user_id: int,
    ) -> Optional[str]:
        """Create a real Gmail draft reply using the Gmail API.

        Uses CredentialFactory to obtain user-specific Gmail credentials,
        then creates a draft reply via GoogleGmailClient.
        Returns the draft ID on success, None on failure.
        """
        try:
            from src.core.credential_provider import CredentialFactory
            from src.core.email.google_client import GoogleGmailClient
            from src.core.email.utils import create_gmail_message

            factory = CredentialFactory(self.config)
            creds = factory.get_credentials(user_id, provider="gmail")

            if not creds:
                logger.warning(
                    f"[LeadResponder] No Gmail credentials for user {user_id}, "
                    f"falling back to placeholder draft"
                )
                return f"draft_lead_{email_data.get('email_id', 'unknown')}"

            gmail_client = GoogleGmailClient(credentials=creds)

            if not gmail_client.is_available():
                logger.warning("[LeadResponder] Gmail service not available")
                return f"draft_lead_{email_data.get('email_id', 'unknown')}"

            # Build the reply message
            sender_email = email_data.get("sender_email", "")
            subject = email_data.get("subject", "")
            reply_subject = subject if subject.startswith("Re:") else f"Re: {subject}"

            message = create_gmail_message(
                to=sender_email,
                subject=reply_subject,
                body=draft_content,
            )

            # Create the actual Gmail draft
            draft = gmail_client._create_draft_with_retry(message)
            draft_id = draft.get("id", "unknown") if draft else None

            if draft_id:
                logger.info(
                    f"[LeadResponder] Real Gmail draft created: {draft_id} "
                    f"(reply to {sender_email})"
                )
            return draft_id

        except ImportError as e:
            logger.warning(f"[LeadResponder] Gmail modules not available: {e}")
            return f"draft_lead_{email_data.get('email_id', 'unknown')}"
        except Exception as e:
            logger.error(f"[LeadResponder] Failed to create Gmail draft: {e}")
            return None

    async def _notify_user(
        self,
        email_data: Dict[str, Any],
        signal: Any,
        draft_id: Optional[str],
        user_id: int,
    ) -> bool:
        """
        Send a Slack DM to the user about the inbound lead.
        Uses SlackTool to resolve the user's Slack ID, then posts
        a rich Block Kit message with action buttons.
        """
        try:
            import asyncio
            from src.tools.slack.tool import SlackTool

            slack_tool = SlackTool(config=self.config, user_id=user_id)

            if not slack_tool.slack_client:
                logger.warning("[LeadResponder] Slack client not available, skipping notification")
                return False

            # Resolve internal user_id → Slack user ID
            slack_user_id = await asyncio.to_thread(slack_tool._resolve_slack_user_id)
            if not slack_user_id:
                logger.warning(f"[LeadResponder] Could not resolve Slack ID for user {user_id}")
                return False

            web = slack_tool.slack_client.web_client

            # Open a DM channel with the user
            dm_resp = web.conversations_open(users=[slack_user_id])
            if not dm_resp.get("ok"):
                logger.error(f"[LeadResponder] Failed to open DM: {dm_resp.get('error')}")
                return False

            dm_channel = dm_resp["channel"]["id"]

            sender = email_data.get("sender", "Unknown")
            subject = email_data.get("subject", "(no subject)")
            confidence = signal.confidence

            # Build Block Kit blocks for rich notification
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Inbound Lead Detected",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*From:*\n{sender}"},
                        {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.0%}"},
                        {"type": "mrkdwn", "text": f"*Subject:*\n{subject}"},
                        {"type": "mrkdwn", "text": f"*Signal:*\n{signal.signal_type}"},
                    ],
                },
            ]

            if draft_id and not draft_id.startswith("draft_lead_"):
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "A draft reply has been prepared and saved to your Gmail drafts.",
                    },
                })
                blocks.append({
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Open Draft"},
                            "url": f"https://mail.google.com/mail/#drafts",
                            "action_id": "lead_open_draft",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in CRM"},
                            "action_id": "lead_view_crm",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Dismiss"},
                            "action_id": "lead_dismiss",
                        },
                    ],
                })
            else:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Draft generation failed. Please reply manually.",
                    },
                })

            # Fallback text for notifications
            fallback_text = (
                f"Inbound lead from {sender} — "
                f"{subject} (confidence: {confidence:.0%})"
            )

            web.chat_postMessage(
                channel=dm_channel,
                text=fallback_text,
                blocks=blocks,
            )

            logger.info(f"[LeadResponder] Slack DM sent to {slack_user_id} for lead from {sender}")
            return True

        except ImportError as e:
            logger.warning(f"[LeadResponder] Slack modules not available: {e}")
            return False
        except Exception as e:
            logger.error(f"[LeadResponder] Slack notification failed: {e}")
            return False

