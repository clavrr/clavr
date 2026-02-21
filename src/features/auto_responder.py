"""
Email Auto-Responder Service

Generates intelligent, personalized email draft replies using LLM.
Supports multiple tones (professional, friendly, brief) and uses the user's
writing profile for style matching if available.
"""
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.llm_factory import LLMFactory

logger = setup_logger(__name__)


@dataclass
class ReplyOption:
    """A single generated reply option"""
    tone: str
    content: str
    style_match_score: Optional[float] = None


class EmailAutoResponder:
    """
    Generates personalized email draft replies using LLM.
    
    Features:
    - Multiple tone options (professional, friendly, brief)
    - User style matching using writing profile
    - Context-aware responses
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.llm = LLMFactory.get_llm_for_provider(config)
    
    async def generate_reply(
        self,
        email_content: str,
        email_subject: str,
        sender_name: str,
        sender_email: str,
        user_style: Optional[Dict[str, Any]] = None,
        num_options: int = 3,
        revenue_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Generate reply options for an email.
        
        Args:
            email_content: The email body to reply to
            email_subject: Subject line of the email
            sender_name: Name of the person who sent the email
            sender_email: Email address of the sender
            user_style: Optional user writing profile for personalization
            num_options: Number of reply variations to generate
            
        Returns:
            List of reply options with tone and content
        """
        tones = ["professional", "friendly", "brief"][:num_options]
        
        replies = []
        for tone in tones:
            try:
                reply = await self._generate_single_reply(
                    email_content=email_content,
                    email_subject=email_subject,
                    sender_name=sender_name,
                    tone=tone,
                    user_style=user_style,
                    revenue_context=revenue_context,
                )
                replies.append(reply)
            except Exception as e:
                logger.error(f"[AutoResponder] Failed to generate {tone} reply: {e}")
                # Fallback reply
                replies.append({
                    "tone": tone,
                    "content": f"Thank you for your email, {sender_name}. I'll get back to you soon.",
                    "style_match_score": None
                })
        
        return replies
    
    async def _generate_single_reply(
        self,
        email_content: str,
        email_subject: str,
        sender_name: str,
        tone: str,
        user_style: Optional[Dict[str, Any]] = None,
        revenue_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate a single reply with a specific tone."""
        
        # Build style instructions from user profile
        style_instructions = ""
        if user_style:
            writing_style = user_style.get("writing_style", {})
            preferences = user_style.get("preferences", {})
            
            style_instructions = f"""
IMPORTANT: Match the user's personal writing style:
- Tone: {writing_style.get('tone', 'neutral')}
- Formality: {writing_style.get('formality_level', 'semi-formal')}
- Average sentence length: {writing_style.get('avg_sentence_length', 15)} words
- Uses contractions: {preferences.get('uses_contractions', True)}
- Common greetings: {', '.join([g['greeting'] for g in user_style.get('response_patterns', {}).get('greetings', [])[:3]])}
- Common sign-offs: {', '.join([s['signoff'] for s in user_style.get('response_patterns', {}).get('signoffs', [])[:3]])}
"""
        
        tone_instructions = {
            "professional": "Write in a formal, business-appropriate tone. Be clear and concise.",
            "friendly": "Write in a warm, approachable tone. Be personable and casual.",
            "brief": "Write a very short response. 1-2 sentences maximum. Get straight to the point."
        }
        
        # Build revenue signal context for deal-aware drafts
        revenue_instructions = ""
        if revenue_context:
            signal_type = revenue_context.get("signal_type", "")
            urgency = revenue_context.get("urgency", "")
            value = revenue_context.get("estimated_value")
            reminder_count = revenue_context.get("reminder_count", 0)
            value_str = f"${value:,.0f}" if value else "Unknown"
            urgency_tone = (
                "Be direct, action-oriented, and convey sense of priority"
                if urgency in ("critical", "high")
                else "Be warm but clear about next steps"
            )
            revenue_instructions = f"""
REVENUE CONTEXT (use to tailor urgency and specificity):
- Signal Type: {signal_type}
- Urgency Level: {urgency}
- Estimated Deal Value: {value_str}
- Previous Reminders Sent: {reminder_count} (this is follow-up #{reminder_count + 1})
- Tone Guidance: {urgency_tone}
- If this is a follow-up, reference the original context and add urgency proportional to the deal value
"""

        prompt = f"""Generate a reply to this email.

ORIGINAL EMAIL:
Subject: {email_subject}
From: {sender_name}
Content: {email_content}

TONE: {tone}
Instructions: {tone_instructions.get(tone, '')}

{style_instructions}
{revenue_instructions}
IMPORTANT RULES:
1. Do NOT include subject line or email headers
2. Just write the reply body text
3. Sign off appropriately for the tone
4. Keep it natural and conversational
5. Address any questions or requests in the original email
6. If revenue context is provided, tailor the response to reflect the deal's importance

Generate ONLY the reply text:"""

        try:
            # LLM client is synchronous, wrap in thread for async context
            import asyncio
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Calculate style match score if user profile exists
            style_match_score = None
            if user_style:
                style_match_score = self._calculate_style_match(content, user_style)
            
            return {
                "tone": tone,
                "content": content.strip(),
                "style_match_score": style_match_score
            }
            
        except Exception as e:
            logger.error(f"[AutoResponder] LLM call failed: {e}")
            raise
    
    def _calculate_style_match(self, content: str, user_style: Dict[str, Any]) -> float:
        """
        Calculate how well the generated reply matches user's style.
        Returns a score between 0.0 and 1.0.
        """
        score = 0.7  # Base score
        
        writing_style = user_style.get("writing_style", {})
        preferences = user_style.get("preferences", {})
        
        # Check for contractions
        has_contractions = any(c in content.lower() for c in ["'s", "'t", "'re", "'ve", "'ll", "'d"])
        uses_contractions = preferences.get("uses_contractions", True)
        if has_contractions == uses_contractions:
            score += 0.1
        
        # Check sentence length
        sentences = content.split('.')
        avg_len = sum(len(s.split()) for s in sentences if s.strip()) / max(len(sentences), 1)
        target_len = writing_style.get("avg_sentence_length", 15)
        if abs(avg_len - target_len) < 5:
            score += 0.1
        
        # Check for greeting match
        greetings = user_style.get("response_patterns", {}).get("greetings", [])
        for g in greetings:
            if g.get("greeting", "").lower() in content.lower()[:50]:
                score += 0.1
                break
        
        return min(score, 1.0)
