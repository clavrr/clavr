"""
Writing Style Profile Builder
Analyzes sent emails to extract user's writing patterns and preferences.
Enhanced with NLP and LLM capabilities for intelligent analysis
"""
from typing import Dict, List, Any, Optional
from collections import Counter
import re
import asyncio
from datetime import datetime

from ..utils.logger import setup_logger
from ..utils.config import Config
from .llm_constants import MODEL_GEMINI_3_FLASH, DEFAULT_TEMPERATURE

logger = setup_logger(__name__)


class ProfileBuilder:
    """
    Analyzes user's sent emails to build a writing style profile.
    Enhanced with NLP and LLM for intelligent pattern recognition.
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize ProfileBuilder.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.profile = None
        
        # Initialize NLP utilities for intelligent analysis
        self.classifier = None
        self.llm_client = None
        self._init_nlp()
    
    def _init_nlp(self):
        """Initialize NLP utilities for intelligent profile building"""
        if not self.config:
            return
        
        try:
            from .query_classifier import QueryClassifier
            from .llm_factory import LLMFactory
            
            self.classifier = QueryClassifier(self.config)
            # Use specific model and lower temperature for analysis consistency
            self.llm_client = LLMFactory.get_llm_for_provider(
                self.config, 
                temperature=0.1
            )
            logger.info("NLP capabilities initialized for ProfileBuilder")
        except Exception as e:
            logger.warning(f"NLP initialization failed: {e}")
    
    async def build_profile(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyze sent emails and build a comprehensive writing profile.
        
        Args:
            sent_emails: List of sent email dictionaries with content and metadata
            
        Returns:
            Dictionary containing writing style profile
        """
        logger.info(f"Building profile from {len(sent_emails)} sent emails")
        
        if not sent_emails:
            logger.warning("No sent emails provided - returning default profile")
            return self._default_profile()
        
        # Validate and filter emails
        valid_emails = self._validate_emails(sent_emails)
        
        if not valid_emails:
            logger.warning(f"No valid emails found in {len(sent_emails)} sent emails - returning default profile")
            return self._default_profile()
        
        logger.info(f"Using {len(valid_emails)} valid emails out of {len(sent_emails)} total")
        
        # Run consolidated LLM analysis asynchronously if available
        if self.llm_client:
            llm_analysis = await self._run_comprehensive_llm_analysis(valid_emails)
            writing_style = llm_analysis.get('writing_style', self._analyze_style(valid_emails))
            common_phrases = llm_analysis.get('common_phrases', self._extract_common_phrases(valid_emails))
        else:
            writing_style = self._analyze_style(valid_emails)
            common_phrases = self._extract_common_phrases(valid_emails)
        
        profile = {
            'created_at': datetime.now().isoformat(),
            'sample_size': len(valid_emails),
            'writing_style': writing_style,
            'response_patterns': self._analyze_response_patterns(valid_emails),
            'preferences': self._extract_preferences(valid_emails),
            'common_phrases': common_phrases,
        }
        
        self.profile = profile
        logger.info("Profile building complete")
        return profile
    
    def _validate_emails(self, sent_emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Validate email structure and filter out invalid emails.
        
        Args:
            sent_emails: List of email dictionaries
            
        Returns:
            List of valid email dictionaries
        """
        valid_emails = []
        
        for i, email in enumerate(sent_emails):
            if not isinstance(email, dict):
                logger.warning(f"Email {i} is not a dictionary, skipping")
                continue
            
            # Check for required fields (flexible - use 'content' or 'body')
            content = email.get('content') or email.get('body', '')
            
            if not content or not isinstance(content, str):
                logger.debug(f"Email {i} missing or invalid content/body field, skipping")
                continue
            
            # Skip very short emails (likely signatures or automated responses)
            if len(content.strip()) < 20:
                logger.debug(f"Email {i} has insufficient content (<20 chars), skipping")
                continue
            
            # Normalize email structure (ensure 'content' field exists)
            if 'content' not in email and 'body' in email:
                email['content'] = email['body']
            
            valid_emails.append(email)
        
        return valid_emails
    
    def _analyze_style(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze overall writing style characteristics."""
        
        word_counts = []
        sentence_counts = []
        paragraph_counts = []
        formality_scores = []
        
        for email in sent_emails:
            content = email.get('content', '')
            
            # Word count
            words = content.split()
            word_counts.append(len(words))
            
            # Sentence count
            sentences = re.split(r'[.!?]+', content)
            sentences = [s for s in sentences if s.strip()]
            sentence_counts.append(len(sentences))
            
            # Paragraph count
            paragraphs = content.split('\n\n')
            paragraphs = [p for p in paragraphs if p.strip()]
            paragraph_counts.append(len(paragraphs))
            
            # Formality score (0-10)
            formality = self._calculate_formality(content)
            formality_scores.append(formality)
        
        # Extract greetings and closings
        greetings = self._extract_greetings(sent_emails)
        closings = self._extract_closings(sent_emails)
        
        return {
            'avg_word_count': int(sum(word_counts) / len(word_counts)) if word_counts else 0,
            'avg_sentence_count': int(sum(sentence_counts) / len(sentence_counts)) if sentence_counts else 0,
            'avg_paragraph_count': int(sum(paragraph_counts) / len(paragraph_counts)) if paragraph_counts else 0,
            'formality_score': round(sum(formality_scores) / len(formality_scores), 1) if formality_scores else 5.0,
            'tone': self._determine_tone(formality_scores),
            'common_greetings': greetings[:5],
            'common_closings': closings[:5],
            'uses_exclamations': self._count_exclamations(sent_emails) > 0.1,  # >10% of emails
            'uses_emojis': self._count_emojis(sent_emails) > 0.05,  # >5% of emails
        }
    
    def _analyze_response_patterns(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze how user responds to different types of emails."""
        
        # Categorize emails by type
        meeting_requests = []
        cold_emails = []
        colleague_emails = []
        
        for email in sent_emails:
            content = email.get('content', '').lower()
            subject = email.get('metadata', {}).get('original_subject', '').lower()
            
            if any(word in content + subject for word in ['meeting', 'schedule', 'calendar', 'call']):
                meeting_requests.append(email)
            elif any(word in content for word in ['thanks for reaching', 'appreciate your', 'not interested']):
                cold_emails.append(email)
            else:
                colleague_emails.append(email)
        
        return {
            'meeting_requests': {
                'count': len(meeting_requests),
                'avg_length': self._avg_word_count(meeting_requests),
                'typical_response': self._extract_typical_pattern(meeting_requests),
            },
            'cold_emails': {
                'count': len(cold_emails),
                'avg_length': self._avg_word_count(cold_emails),
                'typical_response': self._extract_typical_pattern(cold_emails),
            },
            'colleague_emails': {
                'count': len(colleague_emails),
                'avg_length': self._avg_word_count(colleague_emails),
                'typical_response': self._extract_typical_pattern(colleague_emails),
            },
            'categories': self._categorize_styles(sent_emails)
        }
    
    def _extract_preferences(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract user preferences from email patterns."""
        
        # Time-based patterns
        dates = []
        for email in sent_emails:
            date_str = email.get('metadata', {}).get('date')
            if date_str:
                try:
                    dates.append(datetime.fromisoformat(date_str))
                except:
                    pass
        
        # Extract scheduling preferences
        scheduling_phrases = []
        for email in sent_emails:
            content = email.get('content', '')
            # Look for time suggestions:
            # Matches: 10am, 10:00am, 10:30 am, 5 PM
            time_mentions = re.findall(r'\b((?:1[0-2]|0?[1-9])(?::\d{2})?\s*[aApP][mM])\b', content)
            day_mentions = re.findall(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', content, re.IGNORECASE)
            scheduling_phrases.extend(time_mentions)
            scheduling_phrases.extend(day_mentions)
        
        return {
            'signature': self._extract_signature(sent_emails),
            'scheduling_preferences': Counter(scheduling_phrases).most_common(5),
            'avg_response_length_preference': self._avg_word_count(sent_emails),
        }
    
    def _extract_common_phrases(self, sent_emails: List[Dict[str, Any]]) -> List[str]:
        """Extract commonly used phrases."""
        
        phrases = []
        
        for email in sent_emails:
            content = email.get('content', '')
            
            # Common opening phrases
            openings = [
                'Thanks for reaching out',
                'Thank you for',
                'I appreciate',
                'Hope this',
                'Hope you\'re',
                'Let me know',
                'Feel free to',
                'Looking forward',
                'I\'d be happy',
                'Would love to',
            ]
            
            for opening in openings:
                if opening.lower() in content.lower():
                    phrases.append(opening)
        
        # Count frequency
        phrase_counter = Counter(phrases)
        return [phrase for phrase, count in phrase_counter.most_common(10)]
    
    async def _run_comprehensive_llm_analysis(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Runs a single comprehensive LLM analysis to extract all style components.
        Reduces latency and API costs by combining tone, phrases, and patterns.
        """
        if not self.llm_client or not sent_emails:
            return {}
            
        try:
            # Sample 10 diverse emails
            sample_size = min(len(sent_emails), 12)
            sample_emails = sent_emails[:sample_size]
            
            email_text = "\n---\n".join([
                f"Subject: {e.get('metadata', {}).get('original_subject', 'None')}\n"
                f"Body: {e.get('content', '')[:300]}"
                for e in sample_emails
            ])
            
            prompt = f"""You are a master of linguistic analysis. Analyze these email samples to build a writing "Persona".

EMAI SAMPLES:
{email_text}

EXTRACT THE FOLLOWING INTO A JSON OBJECT:
1. writing_style:
   - tone: overall tone (e.g., "Warm & Direct", "Formal & Precise")
   - formality_score: 0 to 10 scale
   - common_greetings: top 3
   - common_closings: top 3
   - sentence_structure: (e.g., "Short & Punchy", "Long & Academic")
2. common_phrases: Extract the top 10 unique phrases this person uses (idiosyncrasies).
3. behavioral_patterns: 
   - uses_emojis: boolean
   - uses_exclamations: boolean
   - response_speed_hint: (e.g., "Brief for quick replies", "Detailed for project updates")

RETURN ONLY VALID JSON."""

            # Execute consolidated call
            response = await asyncio.to_thread(self.llm_client.invoke, prompt)
            llm_result = self._parse_llm_response(response)
            
            if not llm_result:
                return {}
                
            return {
                'writing_style': llm_result.get('writing_style', {}),
                'common_phrases': llm_result.get('common_phrases', []),
                'behavioral_patterns': llm_result.get('behavioral_patterns', {})
            }
            
        except Exception as e:
            logger.error(f"Comprehensive LLM analysis failed: {e}")
            return {}

    def _categorize_styles(self, sent_emails: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Categorizes writing style into Internal vs External."""
        internal_emails = []
        external_emails = []
        
        # Simple domain-based or metadata-based heuristic
        # In a real app, we'd check if recipient domain matches user domain
        for email in sent_emails:
            recipients = email.get('metadata', {}).get('to', [])
            is_internal = False
            # Mock logic for internal vs external
            if any('@clavr.ai' in str(r).lower() for r in recipients):
                is_internal = True
            
            if is_internal:
                internal_emails.append(email)
            else:
                external_emails.append(email)
                
        return {
            'internal': {
                'count': len(internal_emails),
                'tone': self._determine_tone([self._calculate_formality(e.get('content', '')) for e in internal_emails]) if internal_emails else "professional",
                'avg_length': self._avg_word_count(internal_emails)
            },
            'external': {
                'count': len(external_emails),
                'tone': self._determine_tone([self._calculate_formality(e.get('content', '')) for e in external_emails]) if external_emails else "formal",
                'avg_length': self._avg_word_count(external_emails)
            }
        }

    def _parse_llm_response(self, response) -> Any:
        """
        Parse LLM JSON response with robust error handling.
        
        Args:
            response: LLM response object or string
            
        Returns:
            Parsed JSON object or empty dict on failure
        """
        import json
        import re
        
        try:
            # Extract text from response
            if hasattr(response, 'content'):
                text = response.content
            elif isinstance(response, str):
                text = response
            else:
                text = str(response)
            
            # Remove markdown code blocks if present
            json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL | re.IGNORECASE)
            if json_match:
                text = json_match.group(1)
            else:
                # Try other markdown formats
                code_match = re.search(r'```\s*(.*?)\s*```', text, re.DOTALL)
                if code_match:
                    text = code_match.group(1)
            
            # Clean up common formatting issues
            text = text.strip()
            
            # Try to parse as JSON
            parsed = json.loads(text)
            logger.debug(f"Successfully parsed LLM response: {type(parsed)}")
            return parsed
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Problematic text: {text[:200] if 'text' in locals() else 'N/A'}")
            return {}
        except Exception as e:
            logger.warning(f"Unexpected error parsing LLM response: {e}")
            return {}
    
    def _extract_greetings(self, sent_emails: List[Dict[str, Any]]) -> List[str]:
        """Extract common greetings."""
        greetings = []
        
        for email in sent_emails:
            content = email.get('content', '').strip()
            if not content:
                continue
            
            # Get first line
            first_line = content.split('\n')[0].strip()
            
            # Common greeting patterns
            if any(word in first_line.lower() for word in ['hi', 'hello', 'hey', 'dear']):
                # Extract just the greeting part (usually first 1-3 words)
                words = first_line.split()[:3]
                greeting = ' '.join(words)
                greetings.append(greeting)
        
        # Return most common
        greeting_counter = Counter(greetings)
        return [g for g, _ in greeting_counter.most_common(5)]
    
    def _extract_closings(self, sent_emails: List[Dict[str, Any]]) -> List[str]:
        """Extract common closings."""
        closings = []
        
        for email in sent_emails:
            content = email.get('content', '').strip()
            if not content:
                continue
            
            # Get last few lines
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            if len(lines) < 2:
                continue
            
            # Look for common closing patterns in last 3 lines
            last_lines = lines[-3:]
            
            for line in last_lines:
                if any(word in line.lower() for word in ['best', 'thanks', 'sincerely', 'regards', 'cheers']):
                    closings.append(line)
                    break
        
        # Return most common
        closing_counter = Counter(closings)
        return [c for c, _ in closing_counter.most_common(5)]
    
    def _extract_signature(self, sent_emails: List[Dict[str, Any]]) -> str:
        """Extract user's email signature with noise filtering."""
        signatures = []
        
        # Phrases to exclude (mobile signatures, etc.)
        noise_phrases = [
            'sent from my', 
            'sent from my iphone', 
            'sent from my android',
            'get outlook for',
            'sent via'
        ]
        
        for email in sent_emails:
            content = email.get('content', '').strip()
            if not content:
                continue
            
            # Get non-empty lines
            lines = [line.strip() for line in content.split('\n') if line.strip()]
            
            # Filter noise lines
            clean_lines = [
                line for line in lines 
                if not any(noise in line.lower() for noise in noise_phrases)
            ]
            
            if len(clean_lines) >= 1:
                # Potential signature is the last line remaining
                # Sometimes it is 2 lines (Closing + Name), but Name is most important
                potential_sig = clean_lines[-1]
                
                # Verify it's not too long (signatures are usually short)
                if len(potential_sig) < 50:
                    signatures.append(potential_sig)
        
        # Return most common signature
        if signatures:
            sig_counter = Counter(signatures)
            return sig_counter.most_common(1)[0][0]
        
        return ""
    
    def _calculate_formality(self, content: str) -> float:
        """Calculate formality score (0-10)."""
        score = 5.0  # Start at neutral
        
        content_lower = content.lower()
        
        # Formal indicators (+)
        if 'sincerely' in content_lower:
            score += 1
        if 'regards' in content_lower:
            score += 1
        if 'dear' in content_lower:
            score += 0.5
        if 'please' in content_lower:
            score += 0.5
        
        # Informal indicators (-)
        if any(word in content_lower for word in ['hey', 'yeah', 'gonna', 'wanna']):
            score -= 1
        if '!' in content:
            score -= 0.5
        if any(emoji in content for emoji in ['[OK]', ':)', ':D', ':-)']):
            score -= 1
        
        # Clamp between 0 and 10
        return max(0, min(10, score))
    
    def _determine_tone(self, formality_scores: List[float]) -> str:
        """Determine overall tone from formality scores."""
        if not formality_scores:
            return "neutral"
        
        avg = sum(formality_scores) / len(formality_scores)
        
        if avg >= 7:
            return "formal"
        elif avg >= 5:
            return "professional"
        elif avg >= 3:
            return "casual"
        else:
            return "very_casual"
    
    def _count_exclamations(self, sent_emails: List[Dict[str, Any]]) -> float:
        """Calculate percentage of emails with exclamation marks."""
        count = sum(1 for email in sent_emails if '!' in email.get('content', ''))
        return count / len(sent_emails) if sent_emails else 0
    
    def _count_emojis(self, sent_emails: List[Dict[str, Any]]) -> float:
        """Calculate percentage of emails with emojis."""
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags
            "]+", flags=re.UNICODE)
        
        count = sum(1 for email in sent_emails if emoji_pattern.search(email.get('content', '')))
        return count / len(sent_emails) if sent_emails else 0
    
    def _avg_word_count(self, emails: List[Dict[str, Any]]) -> int:
        """Calculate average word count for a list of emails."""
        if not emails:
            return 0
        
        word_counts = [len(email.get('content', '').split()) for email in emails]
        return int(sum(word_counts) / len(word_counts))
    
    def _extract_typical_pattern(self, emails: List[Dict[str, Any]]) -> str:
        """Extract a typical response pattern from emails."""
        if not emails:
            return "Not enough data"
        
        # For now, return a simple description
        avg_length = self._avg_word_count(emails)
        
        if avg_length < 50:
            return "Brief and concise"
        elif avg_length < 100:
            return "Moderate length"
        else:
            return "Detailed and thorough"
    
    def _default_profile(self) -> Dict[str, Any]:
        """Return a default profile when no sent emails available."""
        return {
            'created_at': datetime.now().isoformat(),
            'sample_size': 0,
            'writing_style': {
                'avg_word_count': 100,
                'avg_sentence_count': 5,
                'avg_paragraph_count': 2,
                'formality_score': 5.0,
                'tone': 'professional',
                'common_greetings': ['Hi'],
                'common_closings': ['Best regards'],
                'uses_exclamations': False,
                'uses_emojis': False,
            },
            'response_patterns': {},
            'preferences': {
                'signature': '',  # No default signature - will be learned from user emails
                'scheduling_preferences': [],
                'avg_response_length_preference': 100,
            },
            'common_phrases': [],
        }
    
    def get_style_prompt_additions(self) -> str:
        """
        Generate a structured Persona block based on the profile for LLM guidance.
        """
        if not self.profile:
            return ""
        
        style = self.profile.get('writing_style', {})
        prefs = self.profile.get('preferences', {})
        phrases = self.profile.get('common_phrases', [])
        patterns = self.profile.get('response_patterns', {})
        
        persona = []
        persona.append("### 🎭 User Personality & Writing Style")
        
        # Tone & Structure
        tone = style.get('tone', 'professional')
        structure = style.get('sentence_structure', 'natural')
        persona.append(f"- **Tone**: {tone}")
        persona.append(f"- **Structure**: {structure}")
        
        # Categorization (Internal vs External)
        categories = patterns.get('categories', {})
        if categories:
            int_style = categories.get('internal', {})
            ext_style = categories.get('external', {})
            if int_style.get('count', 0) > 0:
                persona.append(f"- **Internal Style**: {int_style.get('tone')} ({int_style.get('avg_length')} words)")
            if ext_style.get('count', 0) > 0:
                persona.append(f"- **External Style**: {ext_style.get('tone')} ({ext_style.get('avg_length')} words)")

        # Idiosyncrasies
        if phrases:
            phrases_joined = '", "'.join(phrases[:5])
            persona.append(f'- **Preferred Phrases**: "{phrases_joined}"')
            
        # Greetings & Closings
        greetings = style.get('common_greetings', [])
        closings = style.get('common_closings', [])
        if greetings: persona.append(f"- **Standard Greetings**: {', '.join([f'\"{g}\"' for g in greetings[:2]])}")
        if closings: persona.append(f"- **Standard Closings**: {', '.join([f'\"{c}\"' for c in closings[:2]])}")
        
        # Signature
        sig = prefs.get('signature', '')
        if sig: persona.append(f"- **Signature**: {sig}")
        
        return "\n".join(persona)
