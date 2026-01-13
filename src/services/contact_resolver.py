"""
Contact Resolver Service

Resolves ambiguous names like "Carol" to precise email addresses using
the Identity Resolution schema in ArangoDB.

This enables queries like:
- "Schedule a 1:1 with Carol tomorrow"
- "Send this document to Mike"
- "What did Sarah say about the project?"

The resolution uses:
1. KNOWS edges (User->Person with aliases property)
2. HAS_IDENTITY edges (Person->Identity)
3. Name similarity matching
4. Frequency/recency scoring

Example graph structure:
    (:User {id: 123})-[:KNOWS {aliases: ["Carol", "C"], frequency: 15}]->
    (:Person {name: "Carol Smith"})-[:HAS_IDENTITY]->
    (:Identity {type: "email", value: "carol.smith@company.com", primary: true})
"""
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger
from src.utils.config import Config
from src.services.indexing.graph import KnowledgeGraphManager
from src.services.indexing.graph.schema import NodeType, RelationType

logger = setup_logger(__name__)


@dataclass
class ResolvedContact:
    """Result of contact resolution."""
    person_name: str
    email: str
    alias_matched: str
    confidence: float
    person_node_id: str
    identity_node_id: str
    source: str  # How we found this (alias, name_match, etc.)


class ContactResolver:
    """
    Resolves ambiguous contact names to precise email addresses.
    
    Usage:
        resolver = ContactResolver(config, graph_manager)
        
        # Resolve "Carol" for user 123
        result = await resolver.resolve_alias("Carol", user_id=123)
        if result:
            print(f"Found: {result.email}")  # carol.smith@company.com
    """
    
    def __init__(
        self,
        config: Config,
        graph_manager: Optional[KnowledgeGraphManager] = None
    ):
        self.config = config
        self.graph_manager = graph_manager or KnowledgeGraphManager(backend="arangodb")
    
    async def resolve_alias(
        self,
        alias: str,
        user_id: int,
        identity_type: str = "email"
    ) -> Optional[ResolvedContact]:
        """
        Resolve an ambiguous name/alias to a contact's email.
        
        Args:
            alias: The name to resolve (e.g., "Carol", "Mike")
            user_id: The user's ID for personalized resolution
            identity_type: Type of identity to return (email, phone, slack)
        
        Returns:
            ResolvedContact with email if found, None otherwise
        """
        if not alias or len(alias.strip()) < 2:
            return None
        
        alias = alias.strip()
        
        try:
            # Strategy 1: Check KNOWS edges with matching alias
            result = await self._resolve_via_knows_alias(alias, user_id, identity_type)
            if result:
                return result
            
            # Strategy 2: Check Person names with fuzzy match
            result = await self._resolve_via_name_match(alias, user_id, identity_type)
            if result:
                return result
            
            # Strategy 3: Check existing email addresses containing the alias
            result = await self._resolve_via_email_pattern(alias, user_id)
            if result:
                return result
            
            logger.debug(f"[ContactResolver] Could not resolve alias: {alias}")
            return None
            
        except Exception as e:
            logger.error(f"[ContactResolver] Error resolving '{alias}': {e}")
            return None
    
    async def resolve_multiple(
        self,
        aliases: List[str],
        user_id: int,
        identity_type: str = "email"
    ) -> Dict[str, Optional[ResolvedContact]]:
        """
        Resolve multiple aliases at once.
        
        Args:
            aliases: List of names to resolve
            user_id: User ID
            identity_type: Type of identity to return
        
        Returns:
            Dict mapping alias -> ResolvedContact (or None if not found)
        """
        results = {}
        for alias in aliases:
            results[alias] = await self.resolve_alias(alias, user_id, identity_type)
        return results
    
    async def _resolve_via_knows_alias(
        self,
        alias: str,
        user_id: int,
        identity_type: str
    ) -> Optional[ResolvedContact]:
        """
        Resolve via KNOWS edge aliases property.
        
        Query: Find Person connected to User via KNOWS edge where aliases contains alias,
               then get their Identity of the requested type.
        """
        try:
            # AQL query for alias resolution via KNOWS edges
            query = """
            LET user_key = CONCAT("user_", @user_id)
            
            FOR user IN User
                FILTER user._key == user_key OR user.user_id == @user_id
                FOR person, knows_edge IN 1..1 OUTBOUND user KNOWS
                    // Check if alias matches in the aliases array (case-insensitive)
                    FILTER @alias IN knows_edge.aliases 
                       OR LOWER(@alias) IN (FOR a IN (knows_edge.aliases || []) RETURN LOWER(a))
                    
                    FOR identity IN 1..1 OUTBOUND person HAS_IDENTITY
                        FILTER identity.type == @identity_type
                        SORT identity.primary DESC, knows_edge.frequency DESC
                        LIMIT 1
                        
                        RETURN {
                            person_name: person.name,
                            email: identity.value,
                            alias_matched: @alias,
                            confidence: knows_edge.frequency / 100.0,
                            person_node_id: person._key,
                            identity_node_id: identity._key,
                            source: "knows_alias"
                        }
            """
            
            results = await self.graph_manager.query(query, {
                'user_id': user_id,
                'alias': alias,
                'identity_type': identity_type
            })
            
            if results and len(results) > 0:
                r = results[0]
                return ResolvedContact(
                    person_name=r.get('person_name', ''),
                    email=r.get('email', ''),
                    alias_matched=r.get('alias_matched', alias),
                    confidence=min(1.0, r.get('confidence', 0.0)),
                    person_node_id=r.get('person_node_id', ''),
                    identity_node_id=r.get('identity_node_id', ''),
                    source=r.get('source', 'knows_alias')
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"[ContactResolver] KNOWS alias query failed: {e}")
            return None
    
    async def _resolve_via_name_match(
        self,
        alias: str,
        user_id: int,
        identity_type: str
    ) -> Optional[ResolvedContact]:
        """
        Resolve via Person name matching.
        
        Query: Find Person whose name contains the alias,
               then get their Identity of the requested type.
        """
        try:
            query = """
            FOR person IN Person
                // Match name containing alias (case-insensitive)
                FILTER CONTAINS(LOWER(person.name), LOWER(@alias))
                   OR LOWER(person.name) == LOWER(@alias)
                
                FOR identity IN 1..1 OUTBOUND person HAS_IDENTITY
                    FILTER identity.type == @identity_type
                    SORT identity.primary DESC
                    LIMIT 1
                    
                    // Calculate confidence based on name match quality
                    LET match_quality = (
                        LOWER(person.name) == LOWER(@alias) ? 1.0 :
                        STARTS_WITH(LOWER(person.name), LOWER(@alias)) ? 0.8 :
                        0.6
                    )
                    
                    RETURN {
                        person_name: person.name,
                        email: identity.value,
                        alias_matched: @alias,
                        confidence: match_quality,
                        person_node_id: person._key,
                        identity_node_id: identity._key,
                        source: "name_match"
                    }
            """
            
            results = await self.graph_manager.query(query, {
                'alias': alias,
                'identity_type': identity_type
            })
            
            if results and len(results) > 0:
                r = results[0]
                return ResolvedContact(
                    person_name=r.get('person_name', ''),
                    email=r.get('email', ''),
                    alias_matched=r.get('alias_matched', alias),
                    confidence=r.get('confidence', 0.6),
                    person_node_id=r.get('person_node_id', ''),
                    identity_node_id=r.get('identity_node_id', ''),
                    source=r.get('source', 'name_match')
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"[ContactResolver] Name match query failed: {e}")
            return None
    
    async def _resolve_via_email_pattern(
        self,
        alias: str,
        user_id: int
    ) -> Optional[ResolvedContact]:
        """
        Resolve via email address pattern matching.
        
        Query: Find Identity where email contains the alias (e.g., "carol" matches "carol@company.com").
        """
        try:
            query = """
            FOR identity IN Identity
                FILTER identity.type == "email"
                   AND CONTAINS(LOWER(identity.value), LOWER(@alias))
                
                // Get the connected Person
                FOR person IN 1..1 INBOUND identity HAS_IDENTITY
                    LIMIT 1
                    
                    RETURN {
                        person_name: person.name,
                        email: identity.value,
                        alias_matched: @alias,
                        confidence: 0.5,
                        person_node_id: person._key,
                        identity_node_id: identity._key,
                        source: "email_pattern"
                    }
            """
            
            results = await self.graph_manager.query(query, {
                'alias': alias.lower()
            })
            
            if results and len(results) > 0:
                r = results[0]
                return ResolvedContact(
                    person_name=r.get('person_name', ''),
                    email=r.get('email', ''),
                    alias_matched=r.get('alias_matched', alias),
                    confidence=r.get('confidence', 0.5),
                    person_node_id=r.get('person_node_id', ''),
                    identity_node_id=r.get('identity_node_id', ''),
                    source=r.get('source', 'email_pattern')
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"[ContactResolver] Email pattern query failed: {e}")
            return None
    
    async def add_alias(
        self,
        user_id: int,
        person_node_id: str,
        alias: str
    ) -> bool:
        """
        Add an alias to a KNOWS relationship.
        
        This is called when a user refers to someone by a new nickname,
        allowing future resolution.
        
        Args:
            user_id: User ID
            person_node_id: The Person node's ID
            alias: The new alias to add
        
        Returns:
            True if alias was added successfully
        """
        try:
            # Update or create KNOWS edge with new alias
            query = """
            LET user_key = CONCAT("user_", @user_id)
            
            FOR user IN User
                FILTER user._key == user_key OR user.user_id == @user_id
                FOR person IN Person
                    FILTER person._key == @person_key
                    
                    // Check if KNOWS edge exists
                    LET existing = (
                        FOR e IN KNOWS
                            FILTER e._from == user._id AND e._to == person._id
                            RETURN e
                    )
                    
                    // Update or create edge
                    LET edges = (
                        existing[0] != null
                        ? (
                            UPDATE existing[0]._key WITH {
                                aliases: APPEND(existing[0].aliases || [], @alias, true),
                                updated_at: DATE_ISO8601(DATE_NOW())
                            } IN KNOWS
                            RETURN NEW
                        )
                        : (
                            INSERT {
                                _from: user._id,
                                _to: person._id,
                                aliases: [@alias],
                                frequency: 1,
                                created_at: DATE_ISO8601(DATE_NOW())
                            } INTO KNOWS
                            RETURN NEW
                        )
                    )
                    
                    RETURN LENGTH(edges) > 0
            """
            
            results = await self.graph_manager.query(query, {
                'user_id': user_id,
                'person_key': person_node_id,
                'alias': alias
            })
            
            return bool(results and results[0])
            
        except Exception as e:
            logger.error(f"[ContactResolver] Failed to add alias: {e}")
            return False


# Global instance
_contact_resolver: Optional[ContactResolver] = None


def get_contact_resolver() -> Optional[ContactResolver]:
    """Get the global ContactResolver instance."""
    return _contact_resolver


def init_contact_resolver(
    config: Config,
    graph_manager: Optional[KnowledgeGraphManager] = None
) -> ContactResolver:
    """Initialize the global ContactResolver instance."""
    global _contact_resolver
    _contact_resolver = ContactResolver(config, graph_manager)
    logger.info("[ContactResolver] Initialized")
    return _contact_resolver
