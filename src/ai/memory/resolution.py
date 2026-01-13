"""
Entity Resolution Service

Responsible for cleaning and deduping the Knowledge Graph.
It finds entities that likely refer to the same real-world object (e.g., a Slack Person
and an Email Contact) and links them or merges them.

Core Strategies:
1. Exact Email Match: High confidence (1.0).
2. Slack Profile Email Match: High confidence (0.95).
3. Fuzzy Name Match: Medium confidence (0.5-0.8 based on similarity).
4. Nickname/Alias Match: Medium confidence (0.75).
5. Contextual Match: (Future) Using LLM/Embeddings.

"""
from typing import List, Dict, Any, Optional, Set, Tuple
import asyncio
from datetime import datetime
from difflib import SequenceMatcher

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.parsers.base import ParsedNode
from src.services.indexing.graph.schema_constants import (
    HIGH_CONFIDENCE_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    MIN_ENTITY_RESOLUTION_CONFIDENCE,
    CROSS_APP_LINKING_TITLE_SIMILARITY_THRESHOLD,
    CROSS_APP_LINKING_TIME_PROXIMITY_HOURS,
)

logger = setup_logger(__name__)


# Common nickname mappings for fuzzy matching
NICKNAME_MAP: Dict[str, Set[str]] = {
    "robert": {"bob", "rob", "bobby", "robbie"},
    "william": {"will", "bill", "billy", "willy", "liam"},
    "michael": {"mike", "mikey", "mick"},
    "james": {"jim", "jimmy", "jamie"},
    "richard": {"rick", "dick", "rich", "richie"},
    "elizabeth": {"liz", "beth", "lizzy", "eliza", "betty"},
    "jennifer": {"jen", "jenny"},
    "christopher": {"chris", "topher"},
    "matthew": {"matt", "matty"},
    "anthony": {"tony", "ant"},
    "joseph": {"joe", "joey"},
    "daniel": {"dan", "danny"},
    "david": {"dave", "davey"},
    "thomas": {"tom", "tommy"},
    "charles": {"charlie", "chuck", "chas"},
    "katherine": {"kate", "kathy", "katie", "kit"},
    "margaret": {"maggie", "meg", "peggy", "marge"},
    "alexander": {"alex", "xander", "lex"},
    "benjamin": {"ben", "benny", "benji"},
    "nicholas": {"nick", "nicky"},
    "jonathan": {"jon", "john", "johnny"},
    "samuel": {"sam", "sammy"},
    "andrew": {"andy", "drew"},
    "steven": {"steve", "stevie"},
    "edward": {"ed", "eddie", "ted", "teddy"},
    "timothy": {"tim", "timmy"},
    "gregory": {"greg", "gregg"},
    "peter": {"pete", "petey"},
}


class EntityResolutionService:
    """
    Background service that periodically scans the graph for duplicate entities
    and resolves them using multiple strategies with confidence scoring.
    """
    
    # Resolution strategy weights
    CONFIDENCE_SCORES = {
        "email_exact": 1.0,
        "slack_email": 0.95,
        "notion_email": 0.95,
        "nickname": 0.75,
        "fuzzy_name_high": 0.80,  # Similarity > 0.9
        "fuzzy_name_medium": 0.65,  # Similarity 0.8-0.9
        "fuzzy_name_low": 0.50,  # Similarity 0.7-0.8
        "contextual": 0.60,
    }
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.is_running = False
        self._stop_event = asyncio.Event()
        
    async def start(self):
        """Start the periodic resolution loop"""
        if self.is_running:
            return
            
        self.is_running = True
        self._stop_event.clear()
        
        logger.info("[EntityResolution] Service started (v2.0 - multi-strategy)")
        asyncio.create_task(self._run_loop())
        
    async def stop(self):
        """Stop the service"""
        self.is_running = False
        self._stop_event.set()
        logger.info("[EntityResolution] Service stopped")

    async def _run_loop(self):
        """Main periodic loop"""
        while self.is_running:
            try:
                logger.info("[EntityResolution] Starting resolution cycle...")
                stats = await self.run_resolution_cycle()
                logger.info(f"[EntityResolution] Cycle complete. Stats: {stats}")
                
                # Sleep for 1 hour (or config interval)
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=3600)
                except asyncio.TimeoutError:
                    pass
                    
            except Exception as e:
                logger.error(f"[EntityResolution] Error in loop: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def run_resolution_cycle(self) -> Dict[str, int]:
        """
        Run one full pass of entity resolution with all strategies.
        """
        stats = {
            "email_exact": 0,
            "slack_email": 0,
            "fuzzy_name": 0,
            "nickname": 0,
            "high_confidence": 0,
            "low_confidence": 0,
            "errors": 0,
        }
        
        # 1. Email-based Resolution (High Confidence)
        try:
            links = await self.resolve_by_email()
            stats["email_exact"] += links
            stats["high_confidence"] += links
        except Exception as e:
            logger.error(f"[EntityResolution] Error resolving by email: {e}")
            stats["errors"] += 1
            
        # 2. Slack Profile Email Resolution
        try:
            links = await self.resolve_slack_to_person()
            stats["slack_email"] += links
            stats["high_confidence"] += links
        except Exception as e:
            logger.error(f"[EntityResolution] Error resolving Slack profiles: {e}")
            stats["errors"] += 1
            
        # 3. Fuzzy Name Matching
        try:
            high, low = await self.resolve_by_fuzzy_name()
            stats["fuzzy_name"] += high + low
            stats["high_confidence"] += high
            stats["low_confidence"] += low
        except Exception as e:
            logger.error(f"[EntityResolution] Error in fuzzy name matching: {e}")
            stats["errors"] += 1
            
        # 4. Nickname Resolution
        try:
            links = await self.resolve_by_nickname()
            stats["nickname"] += links
        except Exception as e:
            logger.error(f"[EntityResolution] Error in nickname resolution: {e}")
            stats["errors"] += 1
        
        # 5. Cross-App: Task to Calendar Event Resolution
        try:
            links = await self.resolve_task_to_event()
            stats["task_to_event"] = links
            stats["high_confidence"] += links
        except Exception as e:
            logger.error(f"[EntityResolution] Error in task-to-event resolution: {e}")
            stats["errors"] += 1
        
        # 6. Cross-App: Slack Message to Email Discussion
        try:
            links = await self.resolve_message_to_discussion()
            stats["message_to_email"] = links
        except Exception as e:
            logger.error(f"[EntityResolution] Error in message-to-email resolution: {e}")
            stats["errors"] += 1
        
        # 7. Cross-App: Contact Unification (Asana, Notion, Slack, Gmail)
        try:
            links = await self.resolve_contact_across_apps()
            stats["contact_unification"] = links
            stats["high_confidence"] += links
        except Exception as e:
            logger.error(f"[EntityResolution] Error in contact unification: {e}")
            stats["errors"] += 1
            
        return stats

    async def resolve_by_email(self) -> int:
        """
        Find nodes that share the same email address and link them with SAME_AS.
        
        Matches: Person <-> Contact, Person <-> User
        """
        count = 0
        
        # Person <-> Contact matching
        query = """
        FOR p IN Person
            FOR c IN Contact
                FILTER p.email != null AND c.email != null
                FILTER LOWER(p.email) == LOWER(c.email)
                LET same_as_exists = LENGTH(
                    FOR r IN SAME_AS 
                    FILTER (r._from == p._id AND r._to == c._id) OR (r._from == c._id AND r._to == p._id) 
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT same_as_exists
                LIMIT 100
                RETURN {
                    source_id: p.id,
                    target_id: c.id,
                    email: p.email,
                    source_name: p.name,
                    target_name: c.name,
                    source_type: 'Person',
                    target_type: 'Contact'
                }
        """
        
        count += await self._execute_linking_query(
            query, 
            method="email_exact_match",
            confidence=self.CONFIDENCE_SCORES["email_exact"]
        )
        
        # Person <-> User matching
        query_user = """
        FOR p IN Person
            FOR u IN User
                FILTER p.email != null AND u.email != null
                FILTER LOWER(p.email) == LOWER(u.email)
                LET same_as_exists = LENGTH(
                    FOR r IN SAME_AS 
                    FILTER (r._from == p._id AND r._to == u._id) OR (r._from == u._id AND r._to == p._id) 
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT same_as_exists
                LIMIT 100
                RETURN {
                    source_id: p.id,
                    target_id: u.id,
                    email: p.email,
                    source_name: p.name,
                    target_name: u.name,
                    source_type: 'Person',
                    target_type: 'User'
                }
        """
        
        count += await self._execute_linking_query(
            query_user,
            method="email_exact_match",
            confidence=self.CONFIDENCE_SCORES["email_exact"]
        )
        
        return count

    async def resolve_slack_to_person(self) -> int:
        """
        Link Slack Person nodes to Email-based Person nodes using Slack profile email.
        
        Slack ingestion creates Person nodes with slack_user_id and potentially email from profile.
        """
        query = """
        FOR slack_person IN Person
            FOR email_person IN Person
                FILTER slack_person.slack_user_id != null
                FILTER slack_person.email != null
                FILTER email_person.email != null
                FILTER email_person.slack_user_id == null
                FILTER LOWER(slack_person.email) == LOWER(email_person.email)
                FILTER slack_person._id != email_person._id
                LET same_as_exists = LENGTH(
                    FOR r IN SAME_AS 
                    FILTER (r._from == slack_person._id AND r._to == email_person._id) OR (r._from == email_person._id AND r._to == slack_person._id)
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT same_as_exists
                LIMIT 100
                RETURN {
                    source_id: slack_person.id,
                    target_id: email_person.id,
                    email: slack_person.email,
                    source_name: slack_person.name,
                    target_name: email_person.name,
                    source_type: 'Person(Slack)',
                    target_type: 'Person(Email)'
                }
        """
        
        return await self._execute_linking_query(
            query,
            method="slack_email_match",
            confidence=self.CONFIDENCE_SCORES["slack_email"]
        )

    async def resolve_by_fuzzy_name(self) -> Tuple[int, int]:
        """
        Use fuzzy string matching to find similar names.
        
        Returns:
            Tuple of (high_confidence_links, low_confidence_links)
        """
        high_conf_count = 0
        low_conf_count = 0
        
        # Get all Person nodes for comparison
        query = """
        FOR p IN Person
            FILTER p.name != null AND p.email == null
            RETURN { id: p.id, name: p.name }
        """
        
        try:
            persons = await self.graph.execute_query(query)
            if not persons:
                return 0, 0
            
            # Get all Contact nodes
            contact_query = """
            FOR c IN Contact
                FILTER c.name != null
                RETURN { id: c.id, name: c.name, email: c.email }
            """
            contacts = await self.graph.execute_query(contact_query)
            if not contacts:
                return 0, 0
            
            # Compare each person to each contact
            for person in persons:
                p_name = person["name"].strip().lower()
                p_id = person["id"]
                
                for contact in contacts:
                    c_name = contact["name"].strip().lower() if contact["name"] else ""
                    c_id = contact["id"]
                    
                    if not c_name or p_id == c_id:
                        continue
                    
                    # Calculate similarity
                    similarity = self._calculate_name_similarity(p_name, c_name)
                    
                    if similarity >= 0.9:
                        confidence = self.CONFIDENCE_SCORES["fuzzy_name_high"]
                        await self._create_same_as_link(
                            p_id, c_id, 
                            method="fuzzy_name_high",
                            confidence=confidence,
                            similarity=similarity
                        )
                        high_conf_count += 1
                        logger.info(f"[EntityResolution] Fuzzy match (high): '{person['name']}' ~ '{contact['name']}' (sim={similarity:.2f})")
                        
                    elif similarity >= 0.8:
                        confidence = self.CONFIDENCE_SCORES["fuzzy_name_medium"]
                        await self._create_same_as_link(
                            p_id, c_id,
                            method="fuzzy_name_medium",
                            confidence=confidence,
                            similarity=similarity
                        )
                        low_conf_count += 1
                        logger.info(f"[EntityResolution] Fuzzy match (medium): '{person['name']}' ~ '{contact['name']}' (sim={similarity:.2f})")
                        
        except Exception as e:
            logger.error(f"[EntityResolution] Fuzzy matching error: {e}")
            raise
            
        return high_conf_count, low_conf_count

    async def resolve_by_nickname(self) -> int:
        """
        Match names that are known nicknames of each other.
        E.g., "Robert Smith" matches "Bob Smith"
        """
        count = 0
        
        # Get persons and contacts
        query = """
        FOR p IN Person
            FILTER p.name != null
            RETURN { id: p.id, name: p.name, type: 'Person' }
        """
        # Note: We'll query contacts separately or UNION if needed, but separate is fine for simplified AQL matching
        # Actually let's use UNION for single query
        query = """
        FOR doc IN UNION(
            (FOR p IN Person FILTER p.name != null RETURN { id: p.id, name: p.name, type: 'Person' }),
            (FOR c IN Contact FILTER c.name != null RETURN { id: c.id, name: c.name, type: 'Contact' })
        )
        RETURN doc
        """
        
        try:
            entities = await self.graph.execute_query(query)
            if not entities or len(entities) < 2:
                return 0
            
            # Build lookup by first name
            by_first_name: Dict[str, List[Dict]] = {}
            for entity in entities:
                full_name = entity["name"].strip()
                parts = full_name.lower().split()
                if parts:
                    first_name = parts[0]
                    if first_name not in by_first_name:
                        by_first_name[first_name] = []
                    by_first_name[first_name].append(entity)
            
            # Find nickname matches
            processed_pairs: Set[Tuple[str, str]] = set()
            
            for canonical, nicknames in NICKNAME_MAP.items():
                # Check if we have entities with this canonical name
                canonical_entities = by_first_name.get(canonical, [])
                
                for nickname in nicknames:
                    nickname_entities = by_first_name.get(nickname, [])
                    
                    # Link canonical to nickname variants
                    for c_entity in canonical_entities:
                        for n_entity in nickname_entities:
                            if c_entity["id"] == n_entity["id"]:
                                continue
                            
                            pair = tuple(sorted([c_entity["id"], n_entity["id"]]))
                            if pair in processed_pairs:
                                continue
                            
                            # Check if last names match (if both have last names)
                            c_parts = c_entity["name"].lower().split()
                            n_parts = n_entity["name"].lower().split()
                            
                            if len(c_parts) > 1 and len(n_parts) > 1:
                                if c_parts[-1] != n_parts[-1]:
                                    continue  # Last names don't match
                            
                            await self._create_same_as_link(
                                c_entity["id"], n_entity["id"],
                                method="nickname_match",
                                confidence=self.CONFIDENCE_SCORES["nickname"]
                            )
                            processed_pairs.add(pair)
                            count += 1
                            logger.info(f"[EntityResolution] Nickname match: '{c_entity['name']}' ~ '{n_entity['name']}'")
                            
        except Exception as e:
            logger.error(f"[EntityResolution] Nickname resolution error: {e}")
            raise
            
        return count

    def _calculate_name_similarity(self, name1: str, name2: str) -> float:
        """
        Calculate similarity between two names using SequenceMatcher.
        
        Returns:
            Similarity score between 0.0 and 1.0
        """
        return SequenceMatcher(None, name1, name2).ratio()

    async def _execute_linking_query(
        self, 
        query: str, 
        method: str,
        confidence: float
    ) -> int:
        """Execute a linking query and create SAME_AS relationships."""
        count = 0
        
        try:
            results = await self.graph.execute_query(query)
            
            for record in results:
                source_id = record["source_id"]
                target_id = record["target_id"]
                
                logger.info(f"[EntityResolution] Match ({method}): "
                           f"'{record.get('source_name', 'Unknown')}' ({record.get('source_type', '')}) == "
                           f"'{record.get('target_name', 'Unknown')}' ({record.get('target_type', '')})")
                
                await self._create_same_as_link(
                    source_id, target_id,
                    method=method,
                    confidence=confidence
                )
                count += 1
                
        except Exception as e:
            logger.error(f"Error executing linking query: {e}")
            raise
            
        return count

    async def _create_same_as_link(
        self,
        source_id: str,
        target_id: str,
        method: str,
        confidence: float,
        **extra_props
    ) -> None:
        """Create a SAME_AS relationship with metadata."""
        properties = {
            "confidence": confidence,
            "method": method,
            "created_at": datetime.utcnow().isoformat(),
            "is_auto_resolved": True,
            **extra_props
        }
        
        await self.graph.create_relationship(
            from_id=source_id,
            to_id=target_id,
            relation_type=RelationType.SAME_AS,
            properties=properties
        )
    
    # =========================================================================
    # CROSS-APP RESOLUTION METHODS
    # =========================================================================
    
    async def resolve_task_to_event(self) -> int:
        """
        Link Tasks (Google Tasks, Asana) to Calendar Events via title similarity.
        
        This enables queries like "What did I work on related to the Marketing Review?"
        to return both the task AND the meeting.
        
        Strategy:
        1. Find ActionItems (tasks) and CalendarEvents within time proximity
        2. Compare titles using fuzzy matching
        3. Create RELATED_TO relationships for high-confidence matches
        """
        count = 0
        
        # Find tasks and events that might be related
        query = """
        FOR t IN ActionItem
            FOR e IN CalendarEvent
                FILTER t.description != null AND e.title != null
                FILTER t.due_date != null AND e.start_time != null
                LET related_exists = LENGTH(
                    FOR r IN RELATED_TO 
                    FILTER (r._from == t._id AND r._to == e._id) OR (r._from == e._id AND r._to == t._id)
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT related_exists
                LIMIT 200
                RETURN {
                    task_id: t.id,
                    task_title: t.description,
                    task_date: t.due_date,
                    event_id: e.id,
                    event_title: e.title,
                    event_time: e.start_time
                }
        """
        
        try:
            results = await self.graph.query(query, {})
            
            for record in results:
                task_title = (record.get("task_title") or "").lower().strip()
                event_title = (record.get("event_title") or "").lower().strip()
                
                if not task_title or not event_title:
                    continue
                
                # Calculate title similarity
                similarity = self._calculate_name_similarity(task_title, event_title)
                
                if similarity >= CROSS_APP_LINKING_TITLE_SIMILARITY_THRESHOLD:
                    # Check time proximity (task due date near event time)
                    # For now, just link based on title - time check would require date parsing
                    
                    # Create RELATED_TO relationship
                    await self.graph.add_relationship(
                        from_node=record["task_id"],
                        to_node=record["event_id"],
                        rel_type=RelationType.RELATED_TO,
                        properties={
                            "confidence": similarity,
                            "method": "title_similarity",
                            "created_at": datetime.utcnow().isoformat(),
                            "context": "scheduled"
                        }
                    )
                    count += 1
                    logger.info(f"[EntityResolution] Task-Event link: '{task_title[:30]}' ~ '{event_title[:30]}' (sim={similarity:.2f})")
                    
        except Exception as e:
            logger.error(f"[EntityResolution] Task-to-event error: {e}")
            raise
            
        return count
    
    async def resolve_message_to_discussion(self) -> int:
        """
        Link Slack messages/threads to Email discussions about the same topic.
        
        This enables seeing when a Slack conversation continues or references
        an email thread (or vice versa).
        
        Strategy:
        1. Find Slack Messages and Emails with entity/keyword overlap
        2. Check for shared mentions (same Person nodes)
        3. Create RELATED_TO relationships
        """
        count = 0
        
        # Find messages and emails that share participants and have similar timing
        # AQL approach: Join Message -> Mentions -> Person <- (To/From/CC) <- Email
        query = """
        FOR m IN Message
            FOR e IN Email
                FILTER m.timestamp != null AND e.date != null
                
                // Check if already related
                LET related_exists = LENGTH(
                    FOR r IN RELATED_TO 
                    FILTER (r._from == m._id AND r._to == e._id) OR (r._from == e._id AND r._to == m._id) 
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT related_exists

                // Find shared people
                LET message_people = (
                    FOR r IN MENTIONS 
                    FILTER r._from == m._id 
                    RETURN r._to
                )
                
                LET email_people = (
                    FOR r IN UNION(
                        (FOR x IN FROM FILTER x._from == e._id RETURN x._to),
                        (FOR x IN TO FILTER x._to == e._id RETURN x._from),
                        (FOR x IN CC FILTER x._to == e._id RETURN x._from)
                    )
                    RETURN r
                )
                
                LET shared_count = LENGTH(INTERSECTION(message_people, email_people))
                
                FILTER shared_count >= 1
                LIMIT 100
                RETURN {
                    message_id: m.id,
                    message_text: m.text,
                    email_id: e.id,
                    email_subject: e.subject,
                    shared_people: shared_count
                }
        """
        
        try:
            results = await self.graph.query(query, {})
            
            for record in results:
                msg_text = (record.get("message_text") or "")[:200].lower()
                email_subject = (record.get("email_subject") or "").lower()
                shared_people = record.get("shared_people", 0)
                
                if not msg_text or not email_subject:
                    continue
                
                # Calculate a confidence score based on shared participants and text overlap
                # Basic keyword check - in production, use embeddings
                subject_words = set(email_subject.split())
                msg_words = set(msg_text.split())
                common_words = subject_words & msg_words - {"the", "a", "an", "is", "are", "to", "in", "for"}
                
                if len(common_words) >= 2 or shared_people >= 2:
                    confidence = min(0.8, 0.4 + (len(common_words) * 0.1) + (shared_people * 0.15))
                    
                    await self.graph.add_relationship(
                        from_node=record["message_id"],
                        to_node=record["email_id"],
                        rel_type=RelationType.RELATED_TO,
                        properties={
                            "confidence": confidence,
                            "method": "participant_keyword_overlap",
                            "created_at": datetime.utcnow().isoformat(),
                            "shared_participants": shared_people,
                            "context": "communication"
                        }
                    )
                    count += 1
                    logger.info(f"[EntityResolution] Message-Email link: shared_people={shared_people}, common_words={len(common_words)}")
                    
        except Exception as e:
            logger.error(f"[EntityResolution] Message-to-discussion error: {e}")
            raise
            
        return count
    
    async def resolve_contact_across_apps(self) -> int:
        """
        Unify Person/Contact nodes across all connected apps.
        
        Creates SAME_AS relationships when we find the same person in:
        - Gmail (Contact)
        - Slack (Person with slack_user_id)
        - Asana (Person with asana_user_id)
        - Notion (Person with notion_user_id)
        
        Strategy:
        1. Email matching (highest confidence)
        2. Name matching when email doesn't exist
        3. Check for existing SAME_AS chains and extend them
        """
        count = 0
        
        # First: Link any Person with asana_user_id to matching email Persons
        asana_query = """
        FOR asana_person IN Person
            FOR other IN Person
                FILTER asana_person.asana_user_id != null
                FILTER asana_person.email != null
                FILTER other.email != null
                FILTER other.asana_user_id == null
                FILTER LOWER(asana_person.email) == LOWER(other.email)
                FILTER asana_person._id != other._id
                
                LET same_as_exists = LENGTH(
                    FOR r IN SAME_AS 
                    FILTER (r._from == asana_person._id AND r._to == other._id) OR (r._from == other._id AND r._to == asana_person._id)
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT same_as_exists
                
                LIMIT 50
                RETURN {
                    source_id: asana_person.id,
                    target_id: other.id,
                    source_name: asana_person.name,
                    target_name: other.name,
                    email: asana_person.email
                }
        """
        
        try:
            results = await self.graph.query(asana_query, {})
            for record in results:
                await self._create_same_as_link(
                    record["source_id"],
                    record["target_id"],
                    method="asana_email_match",
                    confidence=0.95
                )
                count += 1
                logger.info(f"[EntityResolution] Asana-Person link: {record.get('email', 'unknown')}")
                
        except Exception as e:
            logger.error(f"[EntityResolution] Asana resolution error: {e}")
        
        # Second: Link Notion users
        notion_query = """
        FOR notion_person IN Person
            FOR other IN Person
                FILTER notion_person.notion_user_id != null
                FILTER notion_person.email != null
                FILTER other.email != null
                FILTER other.notion_user_id == null
                FILTER LOWER(notion_person.email) == LOWER(other.email)
                FILTER notion_person._id != other._id
                
                LET same_as_exists = LENGTH(
                    FOR r IN SAME_AS 
                    FILTER (r._from == notion_person._id AND r._to == other._id) OR (r._from == other._id AND r._to == notion_person._id)
                    LIMIT 1 
                    RETURN 1
                ) > 0
                FILTER NOT same_as_exists
                
                LIMIT 50
                RETURN {
                    source_id: notion_person.id,
                    target_id: other.id,
                    source_name: notion_person.name,
                    target_name: other.name,
                    email: notion_person.email
                }
        """
        
        try:
            results = await self.graph.query(notion_query, {})
            for record in results:
                await self._create_same_as_link(
                    record["source_id"],
                    record["target_id"],
                    method="notion_email_match",
                    confidence=0.95
                )
                count += 1
                logger.info(f"[EntityResolution] Notion-Person link: {record.get('email', 'unknown')}")
                
        except Exception as e:
            logger.error(f"[EntityResolution] Notion resolution error: {e}")
        
        return count

    async def resolve_immediately(self, node: ParsedNode):
        """
        Attempt to resolve a single newly indexed node immediately.
        
        Called by indexers for 'Person' or 'Contact' nodes to link them
        without waiting for the background job.
        """
        if node.node_type not in ['Person', 'Contact']:
            return
            
        try:
            # 1. Email matching (Very fast, high confidence)
            properties = node.properties
            email = properties.get('email')
            node_id = node.node_id
            
            if email:
                # Find direct matches
                query = """
                FOR other IN UNION(
                    (FOR p IN Person RETURN p),
                    (FOR c IN Contact RETURN c)
                )
                    FILTER other.email == @email
                    FILTER other.id != @node_id
                    
                    LET same_as_exists = LENGTH(
                        FOR r IN SAME_AS
                        FILTER (r._from == other._id AND r._to == CONCAT('Person/', @node_id)) OR (r._from == CONCAT('Person/', @node_id) AND r._to == other._id)
                         // Note: constructing _id might be tricky if @node_id is just ID not _id. 
                         // Assuming node_id in vars is just the ID part. Use other.id check first.
                         // Actually checking against just ID is safer if schema is consistent.
                        LIMIT 1
                        RETURN 1
                    ) > 0
                    // Better check: 
                    // FILTER NOT (LENGTH(FOR r IN SAME_AS FILTER (r._from == other._id AND r._to == @node_full_id) OR ...))
                    
                    FILTER NOT same_as_exists
                    RETURN {
                        id: other.id, 
                        labels: [PARSE_IDENTIFIER(other._id).collection],
                        name: other.name
                    }
                """
                
                # Check if @node_id param is full ID or just part. usually it's passed as full ID or we construct it?
                # The code passes `node.node_id`. If `node_id` is just '123', then `_id` is 'Person/123'.
                # Let's assume we can pass `node_full_id`? 
                
                # Actually, ArangoDB queries usually don't mix `id` and `_id` easily without knowing collection.
                # But here we UNION(Person, Contact).
                # The `node_id` param seems to be the unique ID prop.
                # Let's keep it simple: just filter by `other.id != @node_id`.
                # For relationship check, we need the full _id of the new node.
                # We can construct strictly if we know the type. `node.node_type` is available.
                
                
                results = await self.graph.execute_query(query, {
                    'email': email,
                    'node_id': node_id
                })
                
                if results:
                    for res in results:
                        await self._create_same_as_link(
                            node_id, res['id'],
                            method="email_exact_immediate",
                            confidence=1.0
                        )
                        logger.info(f"[EntityResolution] Immediate match (email): {properties.get('name')} == {res.get('name')}")
            
            # 2. Name matching (slower but useful if no email)
            name = properties.get('name')
            if name and not email:
                # Basic exact name matching for immediate resolution
                query = """
                FOR other IN UNION(Person, Contact)
                    FILTER LOWER(other.name) == LOWER(@name)
                    FILTER other.id != @node_id
                    # Skip relationship check for speed or assume none exist if new
                    LIMIT 5
                    RETURN { id: other.id, name: other.name }
                """
                
                results = await self.graph.execute_query(query, {
                    'name': name,
                    'node_id': node_id
                })
                
                if results:
                    for res in results:
                        # Slightly lower confidence for name only
                        await self._create_same_as_link(
                            node_id, res['id'],
                            method="name_exact_immediate",
                            confidence=0.9
                        )
                        logger.info(f"[EntityResolution] Immediate match (name): {name} == {res.get('name')}")

        except Exception as e:
            logger.warning(f"[EntityResolution] Immediate resolution failed for {node.node_id}: {e}")
