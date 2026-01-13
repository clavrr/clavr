"""
Topic Extractor Service

LLM-powered service for extracting topics, concepts, and themes from content.
Creates Topic nodes in the knowledge graph and links them across apps.

This enables cross-app queries like "Show me everything about the Q4 Launch"
by connecting emails, Slack messages, Notion pages, and calendar events
that all relate to the same topic.
"""
import json
import asyncio
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from langchain_core.messages import SystemMessage, HumanMessage
from difflib import SequenceMatcher

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.ai.llm_factory import LLMFactory
from src.services.indexing.graph.manager import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType
from src.services.indexing.graph.schema_constants import (
    CROSS_APP_LINKING_TITLE_SIMILARITY_THRESHOLD,
    MIN_ENTITY_RESOLUTION_CONFIDENCE,
)

logger = setup_logger(__name__)

# Topic extraction prompt
TOPIC_EXTRACTION_PROMPT = """You are an intelligent Topic Extractor. Analyze the following content and extract distinct topics/concepts.

For each topic, provide:
1. name: A short, canonical name (e.g., "Q4 Product Launch", "Budget Review 2024")
2. category: One of: project, initiative, discussion, event, decision, issue, idea
3. keywords: 2-5 related keywords that help identify this topic elsewhere
4. confidence: 0.0-1.0 how confident you are this is a real topic worth tracking

Rules:
- Extract 0-3 topics per content piece (don't over-extract)
- Topics should be specific enough to be useful, but general enough to appear across apps
- Ignore generic topics like "meeting" or "email" - focus on WHAT the content is about
- Consider named projects, initiatives, decisions, recurring themes

Return JSON: {"topics": [{"name": "...", "category": "...", "keywords": [...], "confidence": 0.9}]}
Return {"topics": []} if no meaningful topics found.
"""


class TopicExtractor:
    """
    Extracts topics from content and creates/links Topic nodes in the graph.
    
    Key Features:
    - LLM-powered topic extraction from any content type
    - Topic deduplication across extractions
    - Cross-app topic linking via RELATED_TO relationships
    - Confidence-based topic merging
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        self.llm = None
        self._topic_cache: Dict[str, str] = {}  # name_lower -> node_id
        
    def _get_llm(self):
        """Lazy-load LLM for topic extraction."""
        if not self.llm:
            try:
                self.llm = LLMFactory.get_llm_for_provider(self.config, temperature=0.0)
            except Exception as e:
                logger.error(f"Failed to initialize LLM for TopicExtractor: {e}")
        return self.llm
    
    async def extract_topics(
        self, 
        content: str, 
        source: str = "unknown",
        source_node_id: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Extract topics from content and create/update Topic nodes.
        
        Args:
            content: Text content to extract topics from
            source: Source app (gmail, slack, notion, calendar, asana)
            source_node_id: Optional node ID that this content came from
            user_id: User ID for scoping topics
            
        Returns:
            List of extracted topic dicts with node_ids
        """
        if not content or len(content.strip()) < 20:
            return []
            
        llm = self._get_llm()
        if not llm:
            return []
            
        try:
            # Extract topics via LLM
            prompt_msgs = [
                SystemMessage(content=TOPIC_EXTRACTION_PROMPT),
                HumanMessage(content=f"Source: {source}\n\nContent:\n{content[:3000]}")
            ]
            
            result = await asyncio.to_thread(llm.invoke, prompt_msgs)
            response_text = result.content if hasattr(result, 'content') else str(result)
            
            # Parse JSON response
            clean_text = response_text.replace("```json", "").replace("```", "").strip()
            if not clean_text.startswith("{"):
                import re
                match = re.search(r'\{.*\}', clean_text, re.DOTALL)
                if match:
                    clean_text = match.group(0)
                    
            data = json.loads(clean_text)
            extracted_topics = data.get("topics", [])
            
            if not extracted_topics:
                return []
                
            # Process each extracted topic
            result_topics = []
            for topic_data in extracted_topics:
                if topic_data.get("confidence", 0) < MIN_ENTITY_RESOLUTION_CONFIDENCE:
                    continue
                    
                topic_node = await self._create_or_link_topic(
                    topic_data=topic_data,
                    source=source,
                    source_node_id=source_node_id,
                    user_id=user_id
                )
                if topic_node:
                    result_topics.append(topic_node)
                    
            return result_topics
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse topic extraction response: {e}")
            return []
        except Exception as e:
            logger.error(f"Topic extraction failed: {e}")
            return []
    
    async def _create_or_link_topic(
        self,
        topic_data: Dict[str, Any],
        source: str,
        source_node_id: Optional[str],
        user_id: Optional[int]
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new Topic node or find existing and link.
        
        Uses fuzzy matching to find similar existing topics and
        creates RELATED_TO links between them.
        """
        name = topic_data.get("name", "").strip()
        if not name:
            return None
            
        name_lower = name.lower()
        
        # Check cache first
        if name_lower in self._topic_cache:
            existing_id = self._topic_cache[name_lower]
            # Link source node to existing topic
            if source_node_id:
                await self._link_to_topic(source_node_id, existing_id, source)
            return {"node_id": existing_id, "name": name, "is_new": False}
        
        # Search for similar existing topics
        similar_topic = await self._find_similar_topic(
            name, 
            user_id,
            keywords=topic_data.get("keywords", [])
        )
        
        if similar_topic:
            # Found a similar topic - link them
            self._topic_cache[name_lower] = similar_topic["id"]
            if source_node_id:
                await self._link_to_topic(source_node_id, similar_topic["id"], source)
            return {"node_id": similar_topic["id"], "name": similar_topic["name"], "is_new": False}
        
        # Create new topic node
        topic_id = f"topic:{name_lower.replace(' ', '_')}:{user_id or 'global'}"
        
        properties = {
            "name": name,
            "category": topic_data.get("category", "general"),
            "keywords": topic_data.get("keywords", []),
            "confidence": topic_data.get("confidence", 0.8),
            "source": source,
            "related_apps": [source],
            "entity_count": 1,
            "last_mentioned": datetime.utcnow().isoformat(),
        }
        if user_id:
            properties["user_id"] = user_id
            
        try:
            await self.graph.add_node(topic_id, NodeType.TOPIC, properties)
            self._topic_cache[name_lower] = topic_id
            
            # Link source node to topic
            if source_node_id:
                await self._link_to_topic(source_node_id, topic_id, source)
                
            logger.info(f"Created new Topic node: {name} [{topic_id}]")
            return {"node_id": topic_id, "name": name, "is_new": True}
            
        except Exception as e:
            logger.error(f"Failed to create Topic node: {e}")
            return None
    
    async def _find_similar_topic(
        self, 
        name: str, 
        user_id: Optional[int],
        keywords: List[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Find an existing topic similar to the given name.
        Uses fuzzy string matching, keyword overlap, and LLM verification.
        """
        try:
            # Query existing topics - AQL version
            query = """
            FOR t IN Topic
                FILTER t.user_id == @user_id OR t.user_id == null
                LIMIT 100
                RETURN {
                    id: t.id,
                    name: t.name,
                    keywords: t.keywords,
                    category: t.category
                }
            """
            results = await self.graph.query(query, {"user_id": user_id})
            
            name_lower = name.lower()
            keywords = keywords or []
            keywords_lower = [k.lower() for k in keywords]
            
            best_match = None
            best_score = 0.0
            
            # First pass: name similarity and keyword overlap
            candidates = []
            for result in results:
                existing_name = result.get("name", "").lower()
                existing_keywords = result.get("keywords") or []
                
                # Calculate name similarity
                name_sim = SequenceMatcher(None, name_lower, existing_name).ratio()
                
                # Calculate keyword overlap
                keyword_overlap = 0
                if keywords_lower and existing_keywords:
                    overlap_count = sum(1 for k in existing_keywords if k.lower() in keywords_lower)
                    keyword_overlap = overlap_count / max(len(existing_keywords), len(keywords_lower))
                
                # Combined score
                score = name_sim * 0.7 + keyword_overlap * 0.3
                
                # If high confidence match, return immediately
                if score > 0.85:
                    return {
                        "id": result.get("id"),
                        "name": result.get("name"),
                        "score": score
                    }
                
                # Only consider candidates with some similarity for LLM check
                if score > 0.4 or name_sim > 0.6:
                    candidates.append({
                        "node": result,
                        "score": score
                    })
            
            # Second pass: LLM Verification for top candidates
            if candidates and self.llm:
                # Sort by score descending
                candidates.sort(key=lambda x: x["score"], reverse=True)
                top_candidates = candidates[:3]
                
                for candidate in top_candidates:
                    is_same = await self._check_semantic_equivalence(
                        name, keywords, 
                        candidate["node"].get("name"), 
                        candidate["node"].get("keywords", [])
                    )
                    
                    if is_same:
                        logger.info(f"LLM confirmed semantic match: '{name}' == '{candidate['node'].get('name')}'")
                        return {
                            "id": candidate["node"].get("id"),
                            "name": candidate["node"].get("name"),
                            "score": 0.95  # High confidence
                        }
                    
            return None
            
        except Exception as e:
            logger.warning(f"Failed to search for similar topics: {e}")
            return None

    async def _check_semantic_equivalence(
        self, 
        name1: str, 
        keywords1: List[str], 
        name2: str,
        keywords2: List[str]
    ) -> bool:
        """Use LLM to check if two topics are semantically the same."""
        try:
            prompt = f"""Are these two topics referring to the same thing?
Topic A: "{name1}" (Keywords: {', '.join(keywords1)})
Topic B: "{name2}" (Keywords: {', '.join(keywords2 or [])})

Answer strictly 'YES' or 'NO'. Consider them the same if they are synonyms or refer to the same project/event (e.g., 'Q4 Launch' and 'Q4 Product Release').
"""
            msg = HumanMessage(content=prompt)
            result = await asyncio.to_thread(self.llm.invoke, [msg])
            res_text = result.content.strip().upper() if hasattr(result, 'content') else str(result).strip().upper()
            return "YES" in res_text
        except Exception:
            return False
    
    async def _link_to_topic(
        self, 
        source_node_id: str, 
        topic_id: str,
        source: str
    ) -> bool:
        """Link a source node to a topic via DISCUSSES relationship."""
        try:
            # Determine the correct relationship based on source node type
            # Most content types use DISCUSSES
            await self.graph.add_relationship(
                source_node_id,
                topic_id,
                RelationType.DISCUSSES,
                properties={
                    "source": source,
                    "first_seen": datetime.utcnow().isoformat(),
                    "strength": 0.5
                }
            )
            
            # Update topic's related_apps and entity_count - AQL version
            update_query = """
            FOR t IN Topic
                FILTER t.id == @topic_id
                LET new_apps = (
                    @source IN (t.related_apps == null ? [] : t.related_apps) 
                    ? t.related_apps 
                    : APPEND(t.related_apps == null ? [] : t.related_apps, @source)
                )
                UPDATE t WITH {
                    entity_count: (t.entity_count == null ? 1 : t.entity_count + 1),
                    last_mentioned: @now,
                    related_apps: new_apps
                } IN Topic
            """
            await self.graph.query(update_query, {
                "topic_id": topic_id,
                "source": source,
                "now": datetime.utcnow().isoformat()
            })
            
            return True
        except Exception as e:
            logger.warning(f"Failed to link to topic: {e}")
            return False
    
    async def link_related_topics(
        self,
        topic_id_1: str,
        topic_id_2: str,
        confidence: float = 0.7
    ) -> bool:
        """
        Create a RELATED_TO relationship between two topics.
        
        Called when we detect topics that should be linked across apps.
        """
        try:
            await self.graph.add_relationship(
                topic_id_1,
                topic_id_2,
                RelationType.RELATED_TO,
                properties={
                    "confidence": confidence,
                    "first_seen": datetime.utcnow().isoformat(),
                    "strength": confidence
                }
            )
            logger.info(f"Linked topics: {topic_id_1} <-> {topic_id_2}")
            return True
        except Exception as e:
            logger.warning(f"Failed to link topics: {e}")
            return False
    
    async def get_topics_for_entity(
        self,
        entity_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get all topics associated with an entity (email, event, etc.)."""
        try:
            query = """
            FOR edge IN UNION(
                (FOR e IN DISCUSSES FILTER e._from == @entity_id RETURN e),
                (FOR e IN ABOUT FILTER e._from == @entity_id RETURN e)
            )
                LET t = DOCUMENT(edge._to)
                FILTER IS_DOCUMENT(t) AND t.node_type == 'Topic'
                LIMIT @limit
                RETURN {
                    id: t.id,
                    name: t.name,
                    category: t.category,
                    keywords: t.keywords,
                    confidence: t.confidence
                }
            """
            results = await self.graph.query(query, {"entity_id": entity_id, "limit": limit})
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"Failed to get topics for entity: {e}")
            return []
    
    async def get_entities_for_topic(
        self,
        topic_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all entities that discuss a topic - enables cross-app queries."""
        try:
            query = """
            FOR edge IN UNION(
                (FOR e IN DISCUSSES FILTER e._to == @topic_id RETURN e),
                (FOR e IN ABOUT FILTER e._to == @topic_id RETURN e)
            )
                LET e = DOCUMENT(edge._from)
                SORT e.timestamp DESC
                LIMIT @limit
                RETURN {
                    id: e.id,
                    type: e.node_type,
                    title: e.subject != null ? e.subject : (e.title != null ? e.title : (e.name != null ? e.name : e.text)),
                    source: e.source,
                    timestamp: e.timestamp
                }
            """
            results = await self.graph.query(query, {"topic_id": topic_id, "limit": limit})
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"Failed to get entities for topic: {e}")
            return []
    
    async def get_related_topics(
        self,
        topic_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get topics related to a given topic."""
        try:
            query = """
            FOR edge IN RELATED_TO
                FILTER edge._from == @topic_id OR edge._to == @topic_id
                LET t2 = edge._from == @topic_id ? DOCUMENT(edge._to) : DOCUMENT(edge._from)
                FILTER t2.node_type == 'Topic'
                LIMIT @limit
                RETURN {
                    id: t2.id,
                    name: t2.name,
                    category: t2.category,
                    related_apps: t2.related_apps
                }
            """
            results = await self.graph.query(query, {"topic_id": topic_id, "limit": limit})
            return [dict(r) for r in results]
        except Exception as e:
            logger.warning(f"Failed to get related topics: {e}")
            return []
