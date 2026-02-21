"""
Revenue Signal Classifier

Classifies emails and messages by revenue potential using a fast keyword
heuristic first, then an LLM fallback for ambiguous cases. Designed to be
called inline by BriefService and the Follow-Up Tracker to separate
money-relevant signals from noise.
"""
import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.utils.logger import setup_logger
from src.utils.config import Config

logger = setup_logger(__name__)

# ---------------------------------------------------------------------------
# Configurable value thresholds for urgency override
# ---------------------------------------------------------------------------
HIGH_VALUE_THRESHOLD = 10_000       # Override to HIGH if estimated_value >= $10k
CRITICAL_VALUE_THRESHOLD = 50_000   # Override to CRITICAL if estimated_value >= $50k

# ---------------------------------------------------------------------------
# Regex for extracting monetary values  ($50k, $1.2M, $200,000, etc.)
# ---------------------------------------------------------------------------
_MONEY_RE = re.compile(
    r"\$\s*([\d,]+(?:\.\d{1,2})?)\s*(k|mm|million|billion|thousand|b|m)?\b",
    re.IGNORECASE,
)

_MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000,
    "m": 1_000_000, "mm": 1_000_000, "million": 1_000_000,
    "b": 1_000_000_000, "billion": 1_000_000_000,
}


def _extract_monetary_value(text: str) -> Optional[float]:
    """
    Extract the largest monetary value from free text.

    Handles formats like $50k, $1.2M, $200,000, $500.
    Returns None if no monetary value is found.
    """
    matches = _MONEY_RE.findall(text)
    if not matches:
        return None

    values: list[float] = []
    for raw_num, suffix in matches:
        num = float(raw_num.replace(",", ""))
        if suffix:
            multiplier = _MULTIPLIERS.get(suffix.lower(), 1)
            num *= multiplier
        values.append(num)

    return max(values) if values else None


class SignalType(str, Enum):
    """Categories of revenue-relevant signals."""
    INBOUND_LEAD = "inbound_lead"
    DEAL_PROGRESS = "deal_progress"
    CHURN_RISK = "churn_risk"
    RENEWAL = "renewal"
    UPSELL = "upsell"
    INVOICE = "invoice"
    PARTNERSHIP = "partnership"
    NONE = "none"


class SignalUrgency(str, Enum):
    """How fast the user should act."""
    CRITICAL = "critical"  # respond within minutes
    HIGH = "high"          # respond today
    MEDIUM = "medium"      # respond this week
    LOW = "low"            # informational


@dataclass
class RevenueSignal:
    """A classified revenue signal extracted from a message."""
    signal_type: SignalType
    confidence: float  # 0.0 - 1.0
    urgency: SignalUrgency
    estimated_value: Optional[float] = None
    entities: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "confidence": self.confidence,
            "urgency": self.urgency.value,
            "estimated_value": self.estimated_value,
            "entities": self.entities,
            "reasoning": self.reasoning,
        }


# Keyword banks for fast-path classification.
# Each maps a SignalType to (keywords, urgency, min_confidence).
_SIGNAL_KEYWORDS: Dict[SignalType, Dict[str, Any]] = {
    SignalType.INBOUND_LEAD: {
        "keywords": [
            "interested in pricing", "request a demo", "want to learn more",
            "looking for a solution", "can we schedule a call", "pricing page",
            "free trial", "how much does", "get started", "sign up",
            "interested in your product", "want to try", "quote request",
        ],
        "urgency": SignalUrgency.CRITICAL,
        "min_confidence": 0.85,
    },
    SignalType.DEAL_PROGRESS: {
        "keywords": [
            "proposal", "contract", "agreement", "terms", "sow",
            "statement of work", "moving forward", "next steps",
            "procurement", "purchase order", "budget approved",
            "legal review", "ready to sign", "close the deal",
        ],
        "urgency": SignalUrgency.HIGH,
        "min_confidence": 0.80,
    },
    SignalType.CHURN_RISK: {
        "keywords": [
            "cancel", "cancellation", "not renewing", "disappointed",
            "looking at alternatives", "competitor", "switching to",
            "downgrade", "unhappy", "frustrated", "unsubscribe",
            "end our contract", "terminate",
        ],
        "urgency": SignalUrgency.CRITICAL,
        "min_confidence": 0.75,
    },
    SignalType.RENEWAL: {
        "keywords": [
            "renewal", "renew", "subscription expir", "contract expir",
            "upcoming renewal", "auto-renew", "renewal date",
        ],
        "urgency": SignalUrgency.HIGH,
        "min_confidence": 0.80,
    },
    SignalType.UPSELL: {
        "keywords": [
            "additional seats", "upgrade", "enterprise plan", "more licenses",
            "expand", "add users", "premium", "higher tier",
        ],
        "urgency": SignalUrgency.MEDIUM,
        "min_confidence": 0.75,
    },
    SignalType.INVOICE: {
        "keywords": [
            "invoice", "payment", "billing", "overdue", "past due",
            "outstanding balance", "receipt",
        ],
        "urgency": SignalUrgency.MEDIUM,
        "min_confidence": 0.80,
    },
    SignalType.PARTNERSHIP: {
        "keywords": [
            "partnership", "collaborate", "joint venture", "co-marketing",
            "reseller", "affiliate", "integration partner",
        ],
        "urgency": SignalUrgency.MEDIUM,
        "min_confidence": 0.70,
    },
}


class RevenueSignalClassifier:
    """
    Two-pass revenue signal classifier.
    
    Pass 1: Fast keyword scan (sub-millisecond, no API calls).
    Pass 2: LLM classification for emails that don't match keywords
            but come from interesting senders or contain ambiguous language.
    """

    def __init__(self, config: Optional[Config] = None):
        self.config = config
        self._llm = None

    @property
    def llm(self):
        """Lazy-load LLM only when needed for pass 2."""
        if self._llm is None:
            from src.ai.llm_factory import LLMFactory
            self._llm = LLMFactory.get_llm_for_provider(self.config)
        return self._llm

    def classify(
        self,
        email_subject: str,
        email_body: str,
        sender: str = "",
        sender_domain: str = "",
    ) -> Optional[RevenueSignal]:
        """
        Classify a single email for revenue signals.
        
        Returns a RevenueSignal if a revenue-relevant pattern is detected,
        None if the email is noise.
        """
        combined = f"{email_subject} {email_body}".lower()

        # Pass 1: keyword scan
        signal = self._keyword_classify(combined)
        if signal and signal.confidence >= 0.70:
            signal = self._apply_value_override(signal)
            logger.info(
                f"[RevenueSignals] Keyword hit: {signal.signal_type.value} "
                f"(confidence={signal.confidence:.2f}, "
                f"value={signal.estimated_value})"
            )
            return signal

        return None

    async def classify_deep(
        self,
        email_subject: str,
        email_body: str,
        sender: str = "",
        sender_domain: str = "",
    ) -> Optional[RevenueSignal]:
        """
        Full two-pass classification including LLM fallback.
        Use this for important emails that may contain subtle signals.
        """
        # Pass 1 first
        signal = self.classify(email_subject, email_body, sender, sender_domain)
        if signal:
            return signal

        # Pass 2: LLM for ambiguous cases
        try:
            signal = await self._llm_classify(
                email_subject, email_body, sender, sender_domain
            )
            if signal and signal.confidence >= 0.60:
                signal = self._apply_value_override(signal)
                logger.info(
                    f"[RevenueSignals] LLM classified: {signal.signal_type.value} "
                    f"(confidence={signal.confidence:.2f}, "
                    f"value={signal.estimated_value})"
                )
                return signal
        except Exception as e:
            logger.warning(f"[RevenueSignals] LLM classification failed: {e}")

        return None

    def classify_batch(
        self,
        emails: List[Dict[str, Any]],
    ) -> List[Optional[RevenueSignal]]:
        """
        Classify a batch of emails using the fast keyword path.
        Each email dict should have 'subject', 'body', 'sender', 'sender_domain'.
        """
        results = []
        for email in emails:
            signal = self.classify(
                email_subject=email.get("subject", ""),
                email_body=email.get("body", ""),
                sender=email.get("sender", ""),
                sender_domain=email.get("sender_domain", ""),
            )
            results.append(signal)
        return results

    def _keyword_classify(self, text: str) -> Optional[RevenueSignal]:
        """
        Fast-path keyword matching against predefined signal banks.
        Returns the highest-confidence match.
        """
        best_signal: Optional[RevenueSignal] = None
        best_match_count = 0

        for signal_type, config in _SIGNAL_KEYWORDS.items():
            keywords = config["keywords"]
            matches = [kw for kw in keywords if kw in text]

            if not matches:
                continue

            # More keyword matches = higher confidence
            match_ratio = len(matches) / len(keywords)
            confidence = min(
                config["min_confidence"] + (match_ratio * 0.15),
                1.0,
            )

            if len(matches) > best_match_count:
                best_match_count = len(matches)
                best_signal = RevenueSignal(
                    signal_type=signal_type,
                    confidence=round(confidence, 2),
                    urgency=config["urgency"],
                    estimated_value=_extract_monetary_value(text),
                    entities={"matched_keywords": matches},
                    reasoning=f"Matched {len(matches)} keywords: {', '.join(matches[:3])}",
                )

        return best_signal

    async def _llm_classify(
        self,
        subject: str,
        body: str,
        sender: str,
        sender_domain: str,
    ) -> Optional[RevenueSignal]:
        """
        LLM-based classification for emails that don't match keywords
        but might still contain revenue signals.
        """
        prompt = f"""Analyze this email for revenue signals.

From: {sender} ({sender_domain})
Subject: {subject}
Body (first 500 chars): {body[:500]}

Classify into ONE of these categories:
- inbound_lead: Someone wanting to buy or try the product
- deal_progress: Active deal moving forward (contracts, proposals)
- churn_risk: Customer expressing dissatisfaction or intent to leave
- renewal: Contract or subscription renewal discussion
- upsell: Existing customer wanting to expand usage
- invoice: Billing or payment related
- partnership: Business partnership opportunity
- none: Not revenue-relevant

For estimated_value: extract any monetary figure mentioned in the email
(e.g. "$50,000", "200K budget"). Return null if no value is stated.

Return ONLY a JSON object:
{{"signal_type": "...", "confidence": 0.0-1.0, "urgency": "critical|high|medium|low", "estimated_value": null, "reasoning": "one sentence"}}"""

        try:
            response = await asyncio.to_thread(self.llm.invoke, prompt)
            content = response.content if hasattr(response, "content") else str(response)

            import json
            # Try to extract JSON from the response
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            
            data = json.loads(content.strip())

            signal_type_str = data.get("signal_type", "none")
            if signal_type_str == "none":
                return None

            # Prefer LLM-extracted value; fall back to regex on raw text
            llm_value = data.get("estimated_value")
            if isinstance(llm_value, (int, float)) and llm_value > 0:
                est_value = float(llm_value)
            else:
                est_value = _extract_monetary_value(f"{subject} {body}")

            return RevenueSignal(
                signal_type=SignalType(signal_type_str),
                confidence=float(data.get("confidence", 0.5)),
                urgency=SignalUrgency(data.get("urgency", "medium")),
                estimated_value=est_value,
                reasoning=data.get("reasoning", "LLM classification"),
            )
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning(f"[RevenueSignals] Failed to parse LLM response: {e}")
            return None

    # --- value-based urgency override ---

    @staticmethod
    def _apply_value_override(signal: RevenueSignal) -> RevenueSignal:
        """
        Escalate urgency when the deal's estimated value exceeds thresholds.

        - >= CRITICAL_VALUE_THRESHOLD ($50k default) → CRITICAL
        - >= HIGH_VALUE_THRESHOLD ($10k default)     → HIGH (unless already CRITICAL)
        """
        if signal.estimated_value is None:
            return signal
        if signal.estimated_value >= CRITICAL_VALUE_THRESHOLD:
            signal.urgency = SignalUrgency.CRITICAL
        elif signal.estimated_value >= HIGH_VALUE_THRESHOLD:
            if signal.urgency not in (SignalUrgency.CRITICAL,):
                signal.urgency = SignalUrgency.HIGH
        return signal
