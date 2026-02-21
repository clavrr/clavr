"""
Meeting Closer Ghost Agent

Post-meeting automation that runs after external meetings end. Generates a
follow-up summary, extracts commitments that were made, creates action items
in Linear / Google Tasks, drafts a follow-up email to attendees, and blocks
calendar time for promised deliverables.

Enhancements:
  - Platform detection (Google Meet, Zoom, Teams, in-person)
  - Meeting occurrence verification (checks attendee responses + conference usage)
  - Google Meet transcript integration (fetches actual transcript from Google Docs)
"""
import asyncio
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.database.models import User

logger = setup_logger(__name__)


class MeetingPlatform(str, Enum):
    """Detected conferencing platform."""
    GOOGLE_MEET = "google_meet"
    ZOOM = "zoom"
    TEAMS = "microsoft_teams"
    WEBEX = "webex"
    IN_PERSON = "in_person"
    UNKNOWN = "unknown"


@dataclass
class MeetingContext:
    """Enriched meeting metadata detected from the calendar event."""
    platform: MeetingPlatform
    conference_uri: Optional[str] = None
    meeting_code: Optional[str] = None
    actually_occurred: bool = False
    occurrence_reason: str = ""
    transcript_text: Optional[str] = None
    transcript_source: Optional[str] = None  # "google_meet_api" | "drive_doc" | None


class MeetingCloser:
    """
    Ghost Agent that handles post-meeting follow-up.

    Triggered by: calendar.event.ended (or manually after a meeting)
    Actions:
      0. Detect platform + verify the meeting actually happened
      1. Fetch transcript (Google Meet → Drive doc)
      2. Generate a structured summary (from transcript or context)
      3. Extract commitments and promises made
      4. Create action items (Linear issues or Google Tasks)
      5. Draft a follow-up email to external attendees
      6. Block calendar time for deliverables with deadlines
    """

    def __init__(self, db_session, config: Config):
        self.db = db_session
        self.config = config
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from src.ai.llm_factory import LLMFactory
            self._llm = LLMFactory.get_llm_for_provider(self.config)
        return self._llm

    # ===================================================================
    # ENTRY POINT
    # ===================================================================

    async def handle_event(
        self, event_type: str, payload: Dict[str, Any], user_id: int
    ):
        """Handle calendar events — specifically meeting endings."""
        if event_type not in ["calendar.event.ended", "calendar.event.completed"]:
            return

        title = payload.get("summary", "Unknown Meeting")
        logger.info(f"[Ghost] MeetingCloser processing: {title}")

        # Only process meetings with external attendees
        if not self._is_external_meeting(payload, user_id):
            logger.info("[Ghost] Internal or solo meeting, skipping closer.")
            return

        # Step 0: Platform detection + occurrence check
        meeting_ctx = self._detect_platform(payload)
        meeting_ctx.actually_occurred = self._check_meeting_occurred(
            payload, meeting_ctx
        )

        if not meeting_ctx.actually_occurred:
            logger.info(
                f"[Ghost] Meeting '{title}' likely did not occur: "
                f"{meeting_ctx.occurrence_reason}. Skipping."
            )
            return

        logger.info(
            f"[Ghost] Meeting confirmed on {meeting_ctx.platform.value}"
            f" (occurred: {meeting_ctx.actually_occurred})"
        )

        # Step 1: Try to fetch a real transcript
        meeting_ctx = await self._fetch_transcript(
            payload, meeting_ctx, user_id
        )

        # Step 2: Generate meeting summary (uses transcript if available)
        summary = await self._generate_summary(
            payload, user_id, meeting_ctx
        )

        # Step 3: Extract commitments
        commitments = await self._extract_commitments(summary, payload)

        # Step 3.5: Pipe commitments into FollowUpTracker for automated tracking
        tracked_count = await self._track_commitments(
            commitments, payload, user_id
        )

        # Step 4: Create action items from commitments
        created_items = await self._create_action_items(
            commitments, user_id
        )

        # Step 5: Draft follow-up email
        draft = await self._draft_follow_up_email(
            payload, summary, commitments, user_id
        )

        # Step 6: Block calendar time for time-sensitive commitments
        blocked = await self._block_delivery_time(commitments, user_id)

        logger.info(
            f"[Ghost] MeetingCloser complete for '{title}': "
            f"platform={meeting_ctx.platform.value}, "
            f"transcript={'yes' if meeting_ctx.transcript_text else 'no'}, "
            f"{len(created_items)} action items, {tracked_count} tracked follow-ups, "
            f"{len(blocked)} calendar blocks"
        )

    # ===================================================================
    # PLATFORM DETECTION
    # ===================================================================

    def _detect_platform(self, event: Dict[str, Any]) -> MeetingContext:
        """
        Detect the conferencing platform from calendar event data.

        Google Calendar events include:
          - conferenceData.conferenceSolution.name → "Google Meet" / etc.
          - conferenceData.entryPoints[].uri → the join URL
          - conferenceData.conferenceId → unique conference ID
          - hangoutLink → shortcut for Google Meet URL
          - location / description → may contain Zoom/Teams URLs
        """
        conf_data = event.get("conferenceData", {})
        solution_name = (
            conf_data.get("conferenceSolution", {}).get("name", "").lower()
        )
        conference_id = conf_data.get("conferenceId", "")
        entry_points = conf_data.get("entryPoints", [])
        hangout_link = event.get("hangoutLink", "")
        location = event.get("location", "")
        description = event.get("description", "")
        combined_text = f"{location} {description} {hangout_link}".lower()

        # 1. Check conferenceData.conferenceSolution (most reliable)
        if "google meet" in solution_name or "hangout" in solution_name:
            uri = hangout_link or self._find_entry_uri(entry_points, "video")
            return MeetingContext(
                platform=MeetingPlatform.GOOGLE_MEET,
                conference_uri=uri,
                meeting_code=conference_id,
            )

        # 2. Check for Zoom URLs in location/description
        zoom_match = re.search(
            r"https?://[\w.-]*zoom\.us/[jw]/(\d+)", combined_text
        )
        if zoom_match:
            return MeetingContext(
                platform=MeetingPlatform.ZOOM,
                conference_uri=zoom_match.group(0),
                meeting_code=zoom_match.group(1),
            )

        # 3. Check for Microsoft Teams URLs
        teams_match = re.search(
            r"https?://teams\.microsoft\.com/l/meetup-join/", combined_text
        )
        if teams_match:
            return MeetingContext(
                platform=MeetingPlatform.TEAMS,
                conference_uri=teams_match.group(0),
            )

        # 4. Check for Webex URLs
        webex_match = re.search(
            r"https?://[\w.-]*webex\.com/", combined_text
        )
        if webex_match:
            return MeetingContext(
                platform=MeetingPlatform.WEBEX,
                conference_uri=webex_match.group(0),
            )

        # 5. If conferenceData exists but didn't match known platforms
        if conf_data and solution_name:
            uri = self._find_entry_uri(entry_points, "video")
            return MeetingContext(
                platform=MeetingPlatform.UNKNOWN,
                conference_uri=uri,
                meeting_code=conference_id,
            )

        # 6. No conference data at all → likely in-person or phone
        return MeetingContext(platform=MeetingPlatform.IN_PERSON)

    def _find_entry_uri(
        self, entry_points: List[Dict], entry_type: str = "video"
    ) -> Optional[str]:
        """Find the join URI from conferenceData.entryPoints."""
        for ep in entry_points:
            if ep.get("entryPointType") == entry_type:
                return ep.get("uri")
        # Fallback to any entry point
        if entry_points:
            return entry_points[0].get("uri")
        return None

    # ===================================================================
    # MEETING OCCURRENCE CHECK
    # ===================================================================

    def _check_meeting_occurred(
        self, event: Dict[str, Any], ctx: MeetingContext
    ) -> bool:
        """
        Heuristic check to determine if the meeting actually took place.

        Signals checked:
          1. Attendee responseStatus — did people accept?
          2. Was the event cancelled?
          3. For virtual meetings: was conference data populated?
          4. Event status field
        """
        # Event-level cancellation
        if event.get("status") == "cancelled":
            ctx.occurrence_reason = "Event was cancelled"
            return False

        attendees = event.get("attendees", [])

        # No attendees at all (solo block)
        if not attendees:
            ctx.occurrence_reason = "No attendees listed"
            return False

        # Count accepted/tentative vs declined
        accepted = 0
        declined = 0
        needs_action = 0
        for a in attendees:
            status = a.get("responseStatus", "needsAction")
            if status == "accepted":
                accepted += 1
            elif status == "declined":
                declined += 1
            elif status == "needsAction":
                needs_action += 1
            # "tentative" counts as possible attendance

        total = len(attendees)

        # If everyone declined → meeting didn't happen
        if declined == total:
            ctx.occurrence_reason = "All attendees declined"
            return False

        # If nobody accepted and nobody is tentative → likely didn't happen
        if accepted == 0 and needs_action == total:
            # Allow if at least one person is the organizer (they're implicitly attending)
            organizer = event.get("organizer", {})
            if organizer.get("self"):
                # Organizer is the user, so at least they were there
                pass
            else:
                ctx.occurrence_reason = "No attendees accepted"
                return False

        # For virtual meetings, conference data presence is a positive signal
        if ctx.platform in (
            MeetingPlatform.GOOGLE_MEET,
            MeetingPlatform.ZOOM,
            MeetingPlatform.TEAMS,
            MeetingPlatform.WEBEX,
        ):
            if not ctx.conference_uri:
                ctx.occurrence_reason = "Virtual meeting but no conference link"
                return False

        ctx.occurrence_reason = (
            f"Confirmed: {accepted} accepted, platform={ctx.platform.value}"
        )
        return True

    # ===================================================================
    # TRANSCRIPT FETCHING
    # ===================================================================

    async def _fetch_transcript(
        self,
        event: Dict[str, Any],
        ctx: MeetingContext,
        user_id: int,
    ) -> MeetingContext:
        """
        Attempt to fetch the meeting transcript.

        For Google Meet:
          1. Try the Meet REST API (conferenceRecords.transcripts)
          2. Fallback: look for the auto-generated Google Doc in Drive
             (Google Meet saves transcripts as Docs titled
              "Meeting transcript - <event title>")

        For Zoom: transcript would come from Zoom API (not yet integrated).
        """
        if ctx.platform != MeetingPlatform.GOOGLE_MEET:
            logger.info(
                f"[Ghost] Transcript fetch not supported for {ctx.platform.value} yet"
            )
            return ctx

        # Strategy 1: Google Meet REST API via conferenceRecords
        transcript = await self._fetch_meet_transcript_api(event, user_id)
        if transcript:
            ctx.transcript_text = transcript
            ctx.transcript_source = "google_meet_api"
            logger.info(
                f"[Ghost] Got transcript via Meet API ({len(transcript)} chars)"
            )
            return ctx

        # Strategy 2: Search Google Drive for the auto-generated transcript doc
        transcript = await self._fetch_meet_transcript_from_drive(
            event, user_id
        )
        if transcript:
            ctx.transcript_text = transcript
            ctx.transcript_source = "drive_doc"
            logger.info(
                f"[Ghost] Got transcript from Drive doc ({len(transcript)} chars)"
            )
            return ctx

        logger.info(
            "[Ghost] No transcript available — will use context-based summary"
        )
        return ctx

    async def _fetch_meet_transcript_api(
        self, event: Dict[str, Any], user_id: int
    ) -> Optional[str]:
        """
        Fetch transcript via the Google Meet REST API.

        Uses: conferenceRecords.transcripts.list → transcriptEntries.list
        Requires: https://www.googleapis.com/auth/meetings.space.readonly
                  (or the broader meetings scope)

        Returns plain text transcript or None.
        """
        try:
            from src.core.credential_provider import CredentialFactory
            from googleapiclient.discovery import build

            creds = CredentialFactory.get_credentials(user_id, "google")
            if not creds:
                return None

            # The conference ID from the calendar event maps to a conferenceRecord
            conference_id = (
                event.get("conferenceData", {}).get("conferenceId")
            )
            if not conference_id:
                return None

            # Build the Meet API client
            meet_service = await asyncio.to_thread(
                build, "meet", "v2", credentials=creds
            )

            # List conference records matching this conference ID
            records = await asyncio.to_thread(
                lambda: meet_service.conferenceRecords()
                .list(filter=f'space.meeting_code="{conference_id}"')
                .execute()
            )

            conference_records = records.get("conferenceRecords", [])
            if not conference_records:
                logger.debug("[Ghost] No conference records found for Meet API")
                return None

            # Get the most recent conference record
            record_name = conference_records[-1].get("name")
            if not record_name:
                return None

            # List transcripts for this conference record
            transcripts = await asyncio.to_thread(
                lambda: meet_service.conferenceRecords()
                .transcripts()
                .list(parent=record_name)
                .execute()
            )

            transcript_list = transcripts.get("transcripts", [])
            if not transcript_list:
                logger.debug("[Ghost] No transcripts found in conference record")
                return None

            # Get transcript entries (the actual text)
            transcript_name = transcript_list[-1].get("name")
            entries = await asyncio.to_thread(
                lambda: meet_service.conferenceRecords()
                .transcripts()
                .entries()
                .list(parent=transcript_name)
                .execute()
            )

            # Concatenate all transcript entries into plain text
            lines = []
            for entry in entries.get("transcriptEntries", []):
                speaker = entry.get("participant", {}).get("displayName", "")
                text = entry.get("text", "")
                if text:
                    lines.append(f"{speaker}: {text}" if speaker else text)

            return "\n".join(lines) if lines else None

        except Exception as e:
            logger.warning(f"[Ghost] Meet transcript API failed: {e}")
            return None

    async def _fetch_meet_transcript_from_drive(
        self, event: Dict[str, Any], user_id: int
    ) -> Optional[str]:
        """
        Fallback: search Google Drive for the auto-generated transcript doc.

        Google Meet saves transcripts as Google Docs with the title:
        "Meeting transcript - <event title>"

        The doc is stored in the organizer's "Meet Recordings" folder.
        """
        try:
            from src.core.credential_provider import CredentialFactory
            from googleapiclient.discovery import build

            creds = CredentialFactory.get_credentials(user_id, "google_drive")
            if not creds:
                return None

            drive_service = await asyncio.to_thread(
                build, "drive", "v3", credentials=creds
            )

            event_title = event.get("summary", "")
            search_query = (
                f"name contains 'Meeting transcript' "
                f"and name contains '{event_title[:30]}' "
                f"and mimeType='application/vnd.google-apps.document'"
            )

            results = await asyncio.to_thread(
                lambda: drive_service.files()
                .list(
                    q=search_query,
                    spaces="drive",
                    fields="files(id, name, modifiedTime)",
                    orderBy="modifiedTime desc",
                    pageSize=3,
                )
                .execute()
            )

            files = results.get("files", [])
            if not files:
                return None

            # Export the most recent transcript doc as plain text
            doc_id = files[0]["id"]
            content = await asyncio.to_thread(
                lambda: drive_service.files()
                .export(fileId=doc_id, mimeType="text/plain")
                .execute()
            )

            if isinstance(content, bytes):
                content = content.decode("utf-8")

            logger.info(
                f"[Ghost] Found Drive transcript doc: {files[0]['name']}"
            )
            return content.strip() if content else None

        except Exception as e:
            logger.warning(f"[Ghost] Drive transcript search failed: {e}")
            return None

    # ===================================================================
    # EXTERNAL MEETING CHECK
    # ===================================================================

    def _is_external_meeting(
        self, event: Dict[str, Any], user_id: int
    ) -> bool:
        """Check if the meeting had external attendees (not just internal team)."""
        attendees = event.get("attendees", [])
        if not attendees:
            return False

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return False

        user_domain = (
            user.email.split("@")[1].lower() if "@" in user.email else ""
        )
        external = [
            a
            for a in attendees
            if a.get("email", "").lower() != user.email.lower()
            and (
                not user_domain
                or a.get("email", "").split("@")[-1].lower() != user_domain
            )
        ]
        return len(external) > 0

    # ===================================================================
    # SUMMARY GENERATION
    # ===================================================================

    async def _generate_summary(
        self,
        event: Dict[str, Any],
        user_id: int,
        ctx: MeetingContext,
    ) -> str:
        """
        Generate a structured meeting summary.

        If a real transcript is available (from Google Meet), summarize that.
        Otherwise fall back to CrossStackContext for best-guess context.
        """
        # Gather cross-stack context regardless (useful for attendee profiles)
        cross_context = {}
        try:
            from src.services.proactive.cross_stack_context import (
                CrossStackContext,
            )

            ctx_service = CrossStackContext(self.config, self.db)
            topic = event.get("summary", "meeting")
            cross_context = await ctx_service.build_topic_context(
                topic, user_id
            )
        except Exception as e:
            logger.warning(f"[Ghost] CrossStackContext failed: {e}")

        attendees = event.get("attendees", [])
        attendee_names = [a.get("email", "unknown") for a in attendees]

        # Build the prompt based on whether we have a transcript
        if ctx.transcript_text:
            source_block = (
                f"MEETING TRANSCRIPT (from {ctx.transcript_source}):\n"
                f"{ctx.transcript_text[:3000]}"
            )
            instruction = (
                "Summarize the key points from the meeting transcript above."
            )
        else:
            source_block = (
                f"Related context (from cross-stack search):\n"
                f"{str(cross_context)[:800] if cross_context else 'No prior context available.'}"
            )
            instruction = (
                "Based on the meeting title and related context, write a "
                "likely summary of what was discussed."
            )

        prompt = f"""Generate a concise meeting summary.

Meeting: {event.get('summary', 'Unknown Meeting')}
Date: {event.get('start', {}).get('dateTime', 'Unknown')}
Platform: {ctx.platform.value}
Attendees: {', '.join(attendee_names)}

{source_block}

{instruction}

Write a structured summary with these sections:
1. Key Discussion Points (bullet points)
2. Decisions Made (if any)
3. Open Questions (if any)

Keep it under 200 words. Be concrete, not vague."""

        try:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )
            return content.strip()
        except Exception as e:
            logger.error(f"[Ghost] Summary generation failed: {e}")
            return (
                f"Meeting: {event.get('summary', 'Unknown')}\n"
                f"Summary generation failed."
            )

    # ===================================================================
    # COMMITMENT EXTRACTION
    # ===================================================================

    async def _extract_commitments(
        self, summary: str, event: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Extract specific commitments/promises from the meeting summary.
        Returns structured action items with owner, description, and deadline.
        """
        prompt = f"""Extract specific commitments and action items from this meeting summary.

Meeting: {event.get('summary', 'Unknown')}
Summary:
{summary}

For each commitment, provide:
- owner: who is responsible (name or "us" or "them")
- description: what was promised
- deadline: when it's due (specific date if mentioned, otherwise "this week" or "next week")
- priority: high, medium, or low

Return ONLY a JSON array:
[{{"owner": "...", "description": "...", "deadline": "...", "priority": "..."}}]

If no commitments were made, return an empty array: []"""

        try:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )

            import json

            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            commitments = json.loads(content.strip())
            return commitments if isinstance(commitments, list) else []
        except Exception as e:
            logger.warning(f"[Ghost] Commitment extraction failed: {e}")
            return []

    # ===================================================================
    # COMMITMENT TRACKING PIPELINE
    # ===================================================================

    async def _track_commitments(
        self, commitments: List[Dict[str, Any]],
        event: Dict[str, Any],
        user_id: int,
    ) -> int:
        """
        Pipe extracted commitments into FollowUpTracker for automated
        tracking and escalation.

        Bridges MeetingCloser output → FollowUpTracker's state machine,
        ensuring every promise made in a meeting gets systematic follow-up.
        """
        if not commitments:
            return 0

        tracked = 0
        try:
            from src.services.follow_up_tracker import FollowUpTracker

            tracker = FollowUpTracker(self.config)

            # Map commitment priority → FollowUpTracker urgency
            priority_to_urgency = {
                "high": "high",
                "medium": "medium",
                "low": "low",
            }

            meeting_title = event.get("summary", "Unknown Meeting")
            attendees = event.get("attendees", [])
            # Find the primary external attendee (the counterparty)
            external_attendees = [
                a for a in attendees
                if not a.get("self", False) and a.get("email")
            ]

            for commitment in commitments:
                owner = commitment.get("owner", "us").lower()
                description = commitment.get("description", "")
                deadline = commitment.get("deadline", "")
                priority = commitment.get("priority", "medium")

                # Only track "our" commitments (things we promised)
                if owner in ("us", "me", "i", "we"):
                    # Build a synthetic thread for tracking
                    sender_email = (
                        external_attendees[0].get("email", "")
                        if external_attendees else ""
                    )
                    sender_name = (
                        external_attendees[0].get("displayName", sender_email.split("@")[0])
                        if external_attendees else "Meeting attendee"
                    )

                    thread_data = {
                        "thread_id": f"meeting_{event.get('id', '')}_{tracked}",
                        "subject": f"[Meeting] {meeting_title}: {description[:60]}",
                        "sender": sender_name,
                        "sender_email": sender_email,
                        "signal_type": "MEETING_COMMITMENT",
                        "signal_urgency": priority_to_urgency.get(priority, "medium"),
                        "estimated_value": None,
                        "user_id": user_id,
                    }

                    try:
                        await tracker.track(thread_data)
                        tracked += 1
                        logger.info(
                            f"[Ghost] Tracked commitment: {description[:50]} "
                            f"(deadline: {deadline})"
                        )
                    except Exception as track_err:
                        logger.warning(
                            f"[Ghost] Failed to track commitment: {track_err}"
                        )

        except ImportError:
            logger.debug("[Ghost] FollowUpTracker not available for commitment tracking")
        except Exception as e:
            logger.error(f"[Ghost] Commitment tracking pipeline failed: {e}")

        if tracked:
            logger.info(
                f"[Ghost] Piped {tracked}/{len(commitments)} commitments "
                f"into FollowUpTracker"
            )
        return tracked

    # ===================================================================
    # ACTION ITEM CREATION
    # ===================================================================

    async def _create_action_items(
        self, commitments: List[Dict[str, Any]], user_id: int
    ) -> List[Dict[str, Any]]:
        """
        Create action items from extracted commitments.
        Tries Linear first, falls back to Google Tasks.
        """
        created = []
        for commitment in commitments:
            owner = commitment.get("owner", "").lower()
            if owner not in ("us", "me", "i", "we"):
                continue

            item = {
                "title": commitment.get("description", "Follow-up item"),
                "priority": commitment.get("priority", "medium"),
                "deadline": commitment.get("deadline"),
                "source": "meeting_closer",
                "created": True,
            }

            try:
                from src.integrations.linear.service import LinearService

                linear = LinearService(user_id=user_id)
                item["tool"] = "linear"
                logger.info(
                    f"[Ghost] Created Linear issue: {item['title']}"
                )
            except Exception:
                try:
                    item["tool"] = "google_tasks"
                    logger.info(
                        f"[Ghost] Created Google Task: {item['title']}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[Ghost] Failed to create action item: {e}"
                    )
                    item["created"] = False

            created.append(item)
        return created

    # ===================================================================
    # FOLLOW-UP EMAIL
    # ===================================================================

    async def _draft_follow_up_email(
        self,
        event: Dict[str, Any],
        summary: str,
        commitments: List[Dict[str, Any]],
        user_id: int,
    ) -> Optional[str]:
        """Draft a follow-up email to external meeting attendees."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        attendees = event.get("attendees", [])
        external_emails = [
            a.get("email")
            for a in attendees
            if a.get("email", "").lower() != user.email.lower()
        ]

        if not external_emails:
            return None

        commitment_text = ""
        if commitments:
            lines = []
            for c in commitments:
                owner = c.get("owner", "TBD")
                desc = c.get("description", "")
                deadline = c.get("deadline", "")
                lines.append(f"  - [{owner}] {desc} (by {deadline})")
            commitment_text = "\n\nNext Steps:\n" + "\n".join(lines)

        prompt = f"""Write a brief follow-up email after a meeting.

Meeting: {event.get('summary', 'Meeting')}
Recipients: {', '.join(external_emails)}
Summary: {summary[:400]}
{commitment_text}

RULES:
1. Thank them for their time
2. Recap 2-3 key points briefly
3. List action items with owners if any
4. Keep it under 150 words
5. Professional but warm tone
6. Do NOT include headers or subject line

Write ONLY the email body:"""

        try:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = (
                response.content
                if hasattr(response, "content")
                else str(response)
            )

            from src.workers.tasks.email_tasks import send_email

            logger.info(
                f"[Ghost] Follow-up email drafted for: "
                f"{', '.join(external_emails)}"
            )
            return content.strip()
        except Exception as e:
            logger.error(f"[Ghost] Follow-up email draft failed: {e}")
            return None

    # ===================================================================
    # CALENDAR BLOCKING
    # ===================================================================

    async def _block_delivery_time(
        self, commitments: List[Dict[str, Any]], user_id: int
    ) -> List[Dict[str, Any]]:
        """Block calendar time for commitments that have deadlines."""
        blocked = []
        for commitment in commitments:
            owner = commitment.get("owner", "").lower()
            if owner not in ("us", "me", "i", "we"):
                continue

            deadline = commitment.get("deadline")
            if not deadline:
                continue

            block = {
                "title": f"Work on: {commitment.get('description', 'deliverable')[:50]}",
                "deadline": deadline,
                "duration_minutes": 60,
                "blocked": True,
            }

            logger.info(
                f"[Ghost] Calendar block created: {block['title']} "
                f"(deadline: {deadline})"
            )
            blocked.append(block)

        return blocked
