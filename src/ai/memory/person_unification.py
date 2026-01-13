"""
Person Unification Service

Builds unified Person profiles from multiple application sources.
Handles cross-app identity resolution, merging, and relationship tracking.

This is the "People Intelligence" layer that enables:
- "Who do I work with most on Project X?"
- "Show me all interactions with John across apps"
- "Who should be invited to this meeting based on topic?"
"""
from typing import Dict, Any, Optional, List, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
import hashlib

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)


@dataclass
class UnifiedPerson:
    """Unified person profile aggregated from multiple sources"""
    canonical_id: str
    name: str
    emails: List[str]
    identities: Dict[str, str]  # source -> source_id mapping
    relationship_strength: float
    last_interaction: Optional[datetime]
    interaction_count: int
    topics: List[str]
    projects: List[str]


class PersonUnificationService:
    """
    Builds unified Person profiles from multiple app sources.
    
    Features:
    - Merge duplicate Person nodes into canonical profile
    - Enrich with cross-app data (Slack handle, email, Asana ID)
    - Track relationship strength across all channels
    - Generate "People You Work With" insights
    """
    
    def __init__(self, config: Config, graph_manager: KnowledgeGraphManager):
        self.config = config
        self.graph = graph_manager
        
        # Cache for unified profiles
        self._profile_cache: Dict[str, UnifiedPerson] = {}
        self._cache_ttl = timedelta(hours=1)
        self._cache_times: Dict[str, datetime] = {}
        
    async def find_all_identities(
        self,
        email: Optional[str] = None,
        name: Optional[str] = None,
        slack_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Find all Person/Contact nodes that represent the same person.
        
        Uses email matching as primary identifier, with fuzzy name
        matching as secondary.
        
        Args:
            email: Email address to search for
            name: Name to search for
            slack_id: Slack user ID
            
        Returns:
            List of matching node data
        """
        matches = []
        
        if not self.graph:
            return matches
            
        try:
            # 1. Search by email (most reliable)
            if email:
                email_query = f"""
                MATCH (p)
                WHERE (p:Person OR p:Contact)
                AND (p.email = $email OR $email IN p.emails)
                RETURN p, labels(p) as labels
                """
                result = await self.graph.query(email_query, {"email": email.lower()})
                for record in result:
                    matches.append({
                        "node": record["p"],
                        "labels": record["labels"],
                        "match_type": "email"
                    })
                    
            # 2. Search by Slack ID
            if slack_id:
                slack_query = f"""
                MATCH (p:Person)
                WHERE p.slack_user_id = $slack_id
                RETURN p, labels(p) as labels
                """
                result = await self.graph.query(slack_query, {"slack_id": slack_id})
                for record in result:
                    matches.append({
                        "node": record["p"],
                        "labels": record["labels"],
                        "match_type": "slack_id"
                    })
                    
            # 3. Fuzzy name search (lower confidence)
            if name and len(name) > 2:
                name_query = f"""
                MATCH (p)
                WHERE (p:Person OR p:Contact)
                AND toLower(p.name) CONTAINS toLower($name)
                RETURN p, labels(p) as labels
                """
                result = await self.graph.query(name_query, {"name": name})
                for record in result:
                    if record not in [m["node"] for m in matches]:
                        matches.append({
                            "node": record["p"],
                            "labels": record["labels"],
                            "match_type": "name_fuzzy"
                        })
                        
            return matches
            
        except Exception as e:
            logger.error(f"[PersonUnification] Identity search failed: {e}")
            return []
            
    async def unify_person(self, person_id: str) -> Optional[UnifiedPerson]:
        """
        Create a unified profile by merging all identities for a person.
        
        Args:
            person_id: Node ID of any Person/Contact node
            
        Returns:
            UnifiedPerson with aggregated data from all sources
        """
        # Check cache
        if self._is_cached(person_id):
            return self._profile_cache[person_id]
            
        try:
            # 1. Get the base person node
            base_query = """
            MATCH (p)
            WHERE elementId(p) = $id OR p.node_id = $id
            RETURN p
            """
            result = await self.graph.query(base_query, {"id": person_id})
            if not result:
                return None
                
            base_node = result[0]["p"]
            base_email = base_node.get("email", "").lower()
            base_name = base_node.get("name", "")
            
            # 2. Find all related identities via SAME_AS relationships
            same_as_query = """
            MATCH (p)-[:SAME_AS*0..3]-(related)
            WHERE elementId(p) = $id OR p.node_id = $id
            AND (related:Person OR related:Contact)
            RETURN DISTINCT related
            """
            related_result = await self.graph.query(same_as_query, {"id": person_id})
            
            # 3. Also find by email match
            if base_email:
                email_matches = await self.find_all_identities(email=base_email)
                for match in email_matches:
                    if match["node"] not in [r["related"] for r in related_result]:
                        related_result.append({"related": match["node"]})
            
            # 4. Aggregate data from all identities
            emails: Set[str] = set()
            identities: Dict[str, str] = {}
            topics: Set[str] = set()
            projects: Set[str] = set()
            
            for record in related_result:
                node = record.get("related", {})
                
                # Collect emails
                if node.get("email"):
                    emails.add(node["email"].lower())
                if node.get("emails"):
                    emails.update([e.lower() for e in node["emails"]])
                    
                # Collect source identities
                source = node.get("source", "unknown")
                if source == "slack":
                    identities["slack"] = node.get("slack_user_id")
                elif source == "asana":
                    identities["asana"] = node.get("asana_id")
                elif source == "notion":
                    identities["notion"] = node.get("notion_id")
                elif source == "gmail":
                    identities["gmail"] = node.get("email")
                    
            # 5. Calculate relationship strength and interactions
            strength, interaction_count, last_interaction = await self._calculate_relationship_metrics(
                person_id
            )
            
            # 6. Get associated topics and projects
            topics, projects = await self._get_associated_topics_projects(person_id)
            
            # Create unified profile
            unified = UnifiedPerson(
                canonical_id=self._generate_canonical_id(list(emails)),
                name=base_name,
                emails=list(emails),
                identities=identities,
                relationship_strength=strength,
                last_interaction=last_interaction,
                interaction_count=interaction_count,
                topics=list(topics),
                projects=list(projects)
            )
            
            # Cache it
            self._profile_cache[person_id] = unified
            self._cache_times[person_id] = datetime.utcnow()
            
            return unified
            
        except Exception as e:
            logger.error(f"[PersonUnification] Unification failed for {person_id}: {e}")
            return None
            
    async def get_person_profile(self, person_id: str) -> Dict[str, Any]:
        """
        Get a comprehensive profile for a person.
        
        Returns human-readable profile with all cross-app data.
        """
        unified = await self.unify_person(person_id)
        if not unified:
            return {}
            
        return {
            "id": unified.canonical_id,
            "name": unified.name,
            "emails": unified.emails,
            "connected_apps": list(unified.identities.keys()),
            "relationship_strength": round(unified.relationship_strength, 2),
            "interaction_count": unified.interaction_count,
            "last_interaction": unified.last_interaction.isoformat() if unified.last_interaction else None,
            "common_topics": unified.topics[:5],
            "shared_projects": unified.projects[:5]
        }
        
    async def get_relationship_summary(
        self,
        user_id: int,
        person_id: str
    ) -> Dict[str, Any]:
        """
        Get a summary of all interactions with a person across apps.
        
        This powers "Show me everything about John" queries.
        """
        try:
            # Get interactions from graph
            query = """
            MATCH (p)-[r]-(content)
            WHERE (elementId(p) = $person_id OR p.node_id = $person_id)
            AND content.user_id = $user_id
            RETURN type(r) as rel_type, 
                   labels(content) as content_type,
                   content.timestamp as timestamp,
                   content.subject as subject,
                   content.text as text
            ORDER BY content.timestamp DESC
            LIMIT 50
            """
            result = await self.graph.query(query, {
                "person_id": person_id,
                "user_id": user_id
            })
            
            summary = {
                "email_threads": 0,
                "slack_messages": 0,
                "calendar_events": 0,
                "shared_documents": 0,
                "recent_interactions": []
            }
            
            for record in result:
                content_type = record.get("content_type", [])
                
                if "Email" in content_type:
                    summary["email_threads"] += 1
                elif "Message" in content_type:
                    summary["slack_messages"] += 1
                elif "Calendar_Event" in content_type:
                    summary["calendar_events"] += 1
                elif "Document" in content_type:
                    summary["shared_documents"] += 1
                    
                # Add to recent
                if len(summary["recent_interactions"]) < 10:
                    summary["recent_interactions"].append({
                        "type": content_type[0] if content_type else "Unknown",
                        "timestamp": record.get("timestamp"),
                        "preview": (record.get("subject") or record.get("text", ""))[:100]
                    })
                    
            return summary
            
        except Exception as e:
            logger.error(f"[PersonUnification] Relationship summary failed: {e}")
            return {}
            
    async def get_top_contacts(
        self,
        user_id: int,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get the user's most frequent contacts across all apps.
        
        This powers "Who do I work with most?" queries.
        """
        try:
            query = """
            MATCH (p:Person)<-[r]-(content)
            WHERE content.user_id = $user_id
            WITH p, count(r) as interactions
            ORDER BY interactions DESC
            LIMIT $limit
            RETURN p.name as name, 
                   p.email as email,
                   elementId(p) as id,
                   interactions
            """
            result = await self.graph.query(query, {
                "user_id": user_id,
                "limit": limit
            })
            
            contacts = []
            for record in result:
                contacts.append({
                    "name": record.get("name"),
                    "email": record.get("email"),
                    "id": record.get("id"),
                    "interaction_count": record.get("interactions")
                })
                
            return contacts
            
        except Exception as e:
            logger.error(f"[PersonUnification] Top contacts query failed: {e}")
            return []
            
    async def suggest_meeting_attendees(
        self,
        user_id: int,
        topic: str
    ) -> List[Dict[str, Any]]:
        """
        Suggest people to invite based on a meeting topic.
        
        Finds people who have been involved in discussions
        about similar topics.
        """
        try:
            query = """
            MATCH (t:Topic)<-[:ABOUT]-(content)-[r]-(p:Person)
            WHERE toLower(t.name) CONTAINS toLower($topic)
            AND content.user_id = $user_id
            WITH p, count(DISTINCT content) as relevance
            ORDER BY relevance DESC
            LIMIT 5
            RETURN p.name as name, 
                   p.email as email,
                   relevance
            """
            result = await self.graph.query(query, {
                "user_id": user_id,
                "topic": topic
            })
            
            suggestions = []
            for record in result:
                suggestions.append({
                    "name": record.get("name"),
                    "email": record.get("email"),
                    "relevance_score": record.get("relevance"),
                    "reason": f"Has been involved in {topic} discussions"
                })
                
            return suggestions
            
        except Exception as e:
            logger.error(f"[PersonUnification] Attendee suggestion failed: {e}")
            return []
            
    async def _calculate_relationship_metrics(
        self,
        person_id: str
    ) -> tuple[float, int, Optional[datetime]]:
        """Calculate relationship strength and interaction metrics"""
        try:
            query = """
            MATCH (p)-[r]-(content)
            WHERE elementId(p) = $id OR p.node_id = $id
            RETURN count(r) as count,
                   max(content.timestamp) as last_ts
            """
            result = await self.graph.query(query, {"id": person_id})
            
            if result:
                count = result[0].get("count", 0)
                last_ts = result[0].get("last_ts")
                
                # Simple strength calculation based on interaction count
                # Max out at 100 interactions = 1.0 strength
                strength = min(count / 100.0, 1.0)
                
                last_interaction = None
                if last_ts:
                    try:
                        last_interaction = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    except:
                        pass
                        
                return strength, count, last_interaction
                
            return 0.0, 0, None
            
        except Exception as e:
            logger.debug(f"[PersonUnification] Metrics calculation failed: {e}")
            return 0.0, 0, None
            
    async def _get_associated_topics_projects(
        self,
        person_id: str
    ) -> tuple[Set[str], Set[str]]:
        """Get topics and projects associated with a person"""
        topics: Set[str] = set()
        projects: Set[str] = set()
        
        try:
            query = """
            MATCH (p)-[:ABOUT|DISCUSSES|WORKS_ON]-(entity)
            WHERE elementId(p) = $id OR p.node_id = $id
            RETURN labels(entity) as labels, entity.name as name
            """
            result = await self.graph.query(query, {"id": person_id})
            
            for record in result:
                labels = record.get("labels", [])
                name = record.get("name")
                if name:
                    if "Topic" in labels:
                        topics.add(name)
                    elif "Project" in labels:
                        projects.add(name)
                        
        except Exception as e:
            logger.debug(f"[PersonUnification] Topic/project query failed: {e}")
            
        return topics, projects
        
    def _generate_canonical_id(self, emails: List[str]) -> str:
        """Generate canonical ID from emails"""
        if emails:
            sorted_emails = sorted(emails)
            return hashlib.md5(sorted_emails[0].encode()).hexdigest()[:12]
        return hashlib.md5(str(datetime.utcnow()).encode()).hexdigest()[:12]
        
    def _is_cached(self, person_id: str) -> bool:
        """Check if profile is cached and still valid"""
        if person_id not in self._profile_cache:
            return False
        cache_time = self._cache_times.get(person_id)
        if not cache_time:
            return False
        return datetime.utcnow() - cache_time < self._cache_ttl
        
    def clear_cache(self, person_id: Optional[str] = None):
        """Clear profile cache"""
        if person_id:
            self._profile_cache.pop(person_id, None)
            self._cache_times.pop(person_id, None)
        else:
            self._profile_cache.clear()
            self._cache_times.clear()
