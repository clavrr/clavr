"""
Fact Graph - Hierarchical Fact Organization

Organizes facts into a hierarchical structure for better
navigation, querying, and context assembly.

Structure:
User Profile
├── Preferences
│   ├── Communication (email, slack, meetings)
│   ├── Scheduling (morning, afternoon, conflicts)
│   └── Work Style (focus time, collaboration)
├── Relationships
│   ├── People (colleagues, managers, reports)
│   └── Organizations (employers, clients, partners)
├── Expertise & Skills
├── Goals & Objectives (from GoalTracker)
└── Domain Knowledge (per-agent facts)
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple
from enum import Enum
from collections import defaultdict

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FactCategory(str, Enum):
    """Top-level fact categories."""
    PREFERENCE = "preference"
    RELATIONSHIP = "relationship"
    EXPERTISE = "expertise"
    GOAL = "goal"
    DOMAIN = "domain"
    CONTEXT = "context"
    INFERRED = "inferred"


class PreferenceSubcategory(str, Enum):
    """Preference subcategories."""
    COMMUNICATION = "communication"
    SCHEDULING = "scheduling"
    WORK_STYLE = "work_style"
    TOOLS = "tools"
    CONTENT = "content"


class RelationshipSubcategory(str, Enum):
    """Relationship subcategories."""
    PEOPLE = "people"
    ORGANIZATIONS = "organizations"
    PROJECTS = "projects"


@dataclass
class FactNode:
    """A node in the fact graph representing a single fact."""
    id: int
    content: str
    category: FactCategory
    subcategory: Optional[str] = None
    
    # Metadata
    confidence: float = 1.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    
    # Provenance
    source: str = "agent"
    source_type: str = "observed"  # explicit, inferred, observed, imported
    provenance_chain: List[Dict] = field(default_factory=list)
    
    # Entities mentioned
    entities: List[str] = field(default_factory=list)
    
    # Graph relationships
    related_fact_ids: List[int] = field(default_factory=list)
    parent_fact_id: Optional[int] = None
    
    # Temporal validity
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    
    def is_valid(self) -> bool:
        """Check if fact is currently valid."""
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True
    
    def record_access(self):
        """Record an access to this fact."""
        self.access_count += 1
        self.last_accessed = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "category": self.category.value,
            "subcategory": self.subcategory,
            "confidence": self.confidence,
            "entities": self.entities,
            "source": self.source,
            "source_type": self.source_type,
            "access_count": self.access_count,
            "related_fact_ids": self.related_fact_ids
        }


@dataclass
class CategoryNode:
    """A category node containing facts and subcategories."""
    name: str
    description: str
    
    # Facts in this category
    fact_ids: Set[int] = field(default_factory=set)
    
    # Subcategories
    subcategories: Dict[str, "CategoryNode"] = field(default_factory=dict)
    
    # Stats
    fact_count: int = 0
    avg_confidence: float = 0.0


class FactGraph:
    """
    Hierarchical organization of facts.
    
    Provides:
    - Category-based navigation
    - Relationship links between facts
    - Entity-based querying
    - Temporal filtering
    """
    
    def __init__(self, user_id: int):
        """Initialize fact graph for a user."""
        self.user_id = user_id
        
        # Fact storage: id -> FactNode
        self._facts: Dict[int, FactNode] = {}
        
        # Category hierarchy
        self._categories: Dict[FactCategory, CategoryNode] = self._init_categories()
        
        # Entity index: entity -> set of fact_ids
        self._entity_index: Dict[str, Set[int]] = defaultdict(set)
        
        # Keyword index for fast search
        self._keyword_index: Dict[str, Set[int]] = defaultdict(set)
        
        # Next ID
        self._next_id = 1
    
    def _init_categories(self) -> Dict[FactCategory, CategoryNode]:
        """Initialize category structure."""
        return {
            FactCategory.PREFERENCE: CategoryNode(
                name="Preferences",
                description="User preferences and likes/dislikes",
                subcategories={
                    PreferenceSubcategory.COMMUNICATION.value: CategoryNode(
                        name="Communication",
                        description="How user prefers to communicate"
                    ),
                    PreferenceSubcategory.SCHEDULING.value: CategoryNode(
                        name="Scheduling",
                        description="Scheduling and time preferences"
                    ),
                    PreferenceSubcategory.WORK_STYLE.value: CategoryNode(
                        name="Work Style",
                        description="How user likes to work"
                    ),
                    PreferenceSubcategory.TOOLS.value: CategoryNode(
                        name="Tools",
                        description="Tool and software preferences"
                    ),
                }
            ),
            FactCategory.RELATIONSHIP: CategoryNode(
                name="Relationships",
                description="People and organizations",
                subcategories={
                    RelationshipSubcategory.PEOPLE.value: CategoryNode(
                        name="People",
                        description="Colleagues, contacts, relationships"
                    ),
                    RelationshipSubcategory.ORGANIZATIONS.value: CategoryNode(
                        name="Organizations",
                        description="Companies, teams, groups"
                    ),
                    RelationshipSubcategory.PROJECTS.value: CategoryNode(
                        name="Projects",
                        description="Projects and initiatives"
                    ),
                }
            ),
            FactCategory.EXPERTISE: CategoryNode(
                name="Expertise",
                description="Skills and knowledge areas"
            ),
            FactCategory.GOAL: CategoryNode(
                name="Goals",
                description="Current objectives and targets"
            ),
            FactCategory.DOMAIN: CategoryNode(
                name="Domain Knowledge",
                description="Domain-specific facts from agents"
            ),
            FactCategory.CONTEXT: CategoryNode(
                name="Context",
                description="Contextual and situational facts"
            ),
            FactCategory.INFERRED: CategoryNode(
                name="Inferred",
                description="Facts derived through inference"
            ),
        }
    
    def add_fact(
        self,
        content: str,
        category: FactCategory,
        subcategory: Optional[str] = None,
        confidence: float = 1.0,
        entities: Optional[List[str]] = None,
        source: str = "agent",
        source_type: str = "observed",
        provenance: Optional[List[Dict]] = None,
        valid_from: Optional[datetime] = None,
        valid_until: Optional[datetime] = None,
        fact_id: Optional[int] = None
    ) -> FactNode:
        """
        Add a fact to the graph.
        
        Args:
            content: The fact content
            category: Primary category
            subcategory: Optional subcategory
            confidence: Confidence score
            entities: Entities mentioned
            source: Source of the fact
            source_type: Type of source
            provenance: Provenance chain
            valid_from: When fact becomes valid
            valid_until: When fact expires
            fact_id: Optional existing fact ID
            
        Returns:
            The created FactNode
        """
        # Generate or use provided ID
        if fact_id is None:
            fact_id = self._next_id
            self._next_id += 1
        else:
            self._next_id = max(self._next_id, fact_id + 1)
        
        # Auto-detect category if not specified
        if category == FactCategory.DOMAIN:
            detected_cat, detected_sub = self._detect_category(content)
            if detected_cat:
                category = detected_cat
                subcategory = detected_sub or subcategory
        
        # Auto-extract entities if not provided
        if entities is None:
            entities = self._extract_entities(content)
        
        # Create fact node
        fact = FactNode(
            id=fact_id,
            content=content,
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            entities=entities,
            source=source,
            source_type=source_type,
            provenance_chain=provenance or [],
            valid_from=valid_from,
            valid_until=valid_until
        )
        
        # Store fact
        self._facts[fact_id] = fact
        
        # Add to category
        self._categories[category].fact_ids.add(fact_id)
        self._categories[category].fact_count += 1
        
        if subcategory and subcategory in self._categories[category].subcategories:
            self._categories[category].subcategories[subcategory].fact_ids.add(fact_id)
            self._categories[category].subcategories[subcategory].fact_count += 1
        
        # Index entities
        for entity in entities:
            self._entity_index[entity.lower()].add(fact_id)
        
        # Index keywords
        for word in content.lower().split():
            if len(word) > 3:
                self._keyword_index[word].add(fact_id)
        
        return fact
    
    def _detect_category(
        self, 
        content: str
    ) -> Tuple[Optional[FactCategory], Optional[str]]:
        """Auto-detect category from content."""
        content_lower = content.lower()
        
        # Preference patterns
        pref_patterns = [
            (["prefers", "likes", "loves", "enjoys", "favorite"], None),
            (["slack", "email", "teams", "communicate"], PreferenceSubcategory.COMMUNICATION.value),
            (["morning", "afternoon", "schedule", "meeting time"], PreferenceSubcategory.SCHEDULING.value),
            (["focus", "deep work", "productivity", "work from"], PreferenceSubcategory.WORK_STYLE.value),
        ]
        
        for keywords, subcat in pref_patterns:
            if any(kw in content_lower for kw in keywords):
                return FactCategory.PREFERENCE, subcat
        
        # Relationship patterns
        rel_patterns = [
            (["colleague", "manager", "report", "works with"], RelationshipSubcategory.PEOPLE.value),
            (["company", "organization", "employer", "client"], RelationshipSubcategory.ORGANIZATIONS.value),
            (["project", "initiative", "program"], RelationshipSubcategory.PROJECTS.value),
        ]
        
        for keywords, subcat in rel_patterns:
            if any(kw in content_lower for kw in keywords):
                return FactCategory.RELATIONSHIP, subcat
        
        # Expertise
        if any(kw in content_lower for kw in ["expert", "skilled", "experienced", "knows", "specializes"]):
            return FactCategory.EXPERTISE, None
        
        # Goal
        if any(kw in content_lower for kw in ["goal", "objective", "target", "wants to", "aims to"]):
            return FactCategory.GOAL, None
        
        return None, None
    
    def _extract_entities(self, content: str) -> List[str]:
        """Extract entities from content using shared utility."""
        from .memory_utils import extract_entities
        return extract_entities(content)
    
    def get_fact(self, fact_id: int) -> Optional[FactNode]:
        """Get a fact by ID."""
        fact = self._facts.get(fact_id)
        if fact:
            fact.record_access()
        return fact
    
    def get_facts_by_category(
        self, 
        category: FactCategory,
        subcategory: Optional[str] = None,
        min_confidence: float = 0.0,
        include_expired: bool = False
    ) -> List[FactNode]:
        """Get facts in a category."""
        cat_node = self._categories.get(category)
        if not cat_node:
            return []
        
        # Get fact IDs from category or subcategory
        if subcategory and subcategory in cat_node.subcategories:
            fact_ids = cat_node.subcategories[subcategory].fact_ids
        else:
            fact_ids = cat_node.fact_ids
        
        # Filter and collect
        facts = []
        for fid in fact_ids:
            fact = self._facts.get(fid)
            if fact and fact.confidence >= min_confidence:
                if include_expired or fact.is_valid():
                    facts.append(fact)
        
        # Sort by confidence descending
        facts.sort(key=lambda f: f.confidence, reverse=True)
        return facts
    
    def get_facts_by_entity(
        self, 
        entity: str,
        min_confidence: float = 0.0
    ) -> List[FactNode]:
        """Get all facts mentioning an entity."""
        entity_lower = entity.lower()
        fact_ids = self._entity_index.get(entity_lower, set())
        
        facts = []
        for fid in fact_ids:
            fact = self._facts.get(fid)
            if fact and fact.confidence >= min_confidence and fact.is_valid():
                facts.append(fact)
        
        facts.sort(key=lambda f: f.confidence, reverse=True)
        return facts
    
    def search(
        self, 
        query: str,
        limit: int = 10,
        min_confidence: float = 0.0
    ) -> List[FactNode]:
        """Search facts by keyword."""
        words = [w.lower() for w in query.split() if len(w) > 3]
        
        # Find facts matching any keyword
        matching_ids = set()
        for word in words:
            matching_ids.update(self._keyword_index.get(word, set()))
        
        # Score by number of matches
        scored = []
        for fid in matching_ids:
            fact = self._facts.get(fid)
            if fact and fact.confidence >= min_confidence and fact.is_valid():
                # Score by keyword overlap
                fact_words = set(fact.content.lower().split())
                overlap = len(set(words) & fact_words)
                score = overlap / max(len(words), 1)
                scored.append((fact, score))
        
        # Sort by score
        scored.sort(key=lambda x: (x[1], x[0].confidence), reverse=True)
        return [f for f, _ in scored[:limit]]
    
    def link_facts(
        self, 
        fact_id_1: int, 
        fact_id_2: int,
        bidirectional: bool = True
    ):
        """Create a link between two related facts."""
        fact1 = self._facts.get(fact_id_1)
        fact2 = self._facts.get(fact_id_2)
        
        if fact1 and fact2:
            if fact_id_2 not in fact1.related_fact_ids:
                fact1.related_fact_ids.append(fact_id_2)
            
            if bidirectional and fact_id_1 not in fact2.related_fact_ids:
                fact2.related_fact_ids.append(fact_id_1)
    
    def get_related_facts(
        self, 
        fact_id: int,
        depth: int = 1
    ) -> List[FactNode]:
        """Get facts related to a given fact."""
        visited = set()
        to_visit = [(fact_id, 0)]
        related = []
        
        while to_visit:
            current_id, current_depth = to_visit.pop(0)
            
            if current_id in visited:
                continue
            visited.add(current_id)
            
            fact = self._facts.get(current_id)
            if not fact:
                continue
            
            if current_id != fact_id:
                related.append(fact)
            
            if current_depth < depth:
                for related_id in fact.related_fact_ids:
                    if related_id not in visited:
                        to_visit.append((related_id, current_depth + 1))
        
        return related
    
    def get_hierarchy(self) -> Dict[str, Any]:
        """Get the full category hierarchy with fact counts."""
        hierarchy = {}
        
        for cat, node in self._categories.items():
            cat_dict = {
                "name": node.name,
                "description": node.description,
                "fact_count": node.fact_count,
                "subcategories": {}
            }
            
            for subcat_name, subnode in node.subcategories.items():
                cat_dict["subcategories"][subcat_name] = {
                    "name": subnode.name,
                    "fact_count": subnode.fact_count
                }
            
            hierarchy[cat.value] = cat_dict
        
        return hierarchy
    
    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        total_facts = len(self._facts)
        total_entities = len(self._entity_index)
        
        cat_counts = {
            cat.value: node.fact_count 
            for cat, node in self._categories.items()
        }
        
        return {
            "user_id": self.user_id,
            "total_facts": total_facts,
            "total_entities": total_entities,
            "category_counts": cat_counts,
            "avg_confidence": (
                sum(f.confidence for f in self._facts.values()) / total_facts
                if total_facts > 0 else 0.0
            )
        }
    
    def format_for_context(
        self, 
        categories: Optional[List[FactCategory]] = None,
        max_per_category: int = 3,
        min_confidence: float = 0.5
    ) -> str:
        """Format facts for LLM context injection."""
        lines = []
        
        categories = categories or [FactCategory.PREFERENCE, FactCategory.RELATIONSHIP]
        
        for cat in categories:
            facts = self.get_facts_by_category(
                cat, 
                min_confidence=min_confidence
            )[:max_per_category]
            
            if facts:
                lines.append(f"[{cat.value.upper()}]")
                for fact in facts:
                    conf_indicator = "★" if fact.confidence >= 0.8 else "•"
                    lines.append(f"{conf_indicator} {fact.content}")
                lines.append("")
        
        return "\n".join(lines).strip()

    # =========================================================================
    # DATABASE PERSISTENCE
    # =========================================================================

    @staticmethod
    def _map_db_category(db_category: str) -> FactCategory:
        """Map database category string to FactCategory enum."""
        category_map = {
            "preference": FactCategory.PREFERENCE,
            "relationship": FactCategory.RELATIONSHIP,
            "expertise": FactCategory.EXPERTISE,
            "goal": FactCategory.GOAL,
            "domain": FactCategory.DOMAIN,
            "context": FactCategory.CONTEXT,
            "inferred": FactCategory.INFERRED,
            "general": FactCategory.CONTEXT,  # Fallback
            "personal_detail": FactCategory.CONTEXT,
        }
        return category_map.get(db_category.lower(), FactCategory.CONTEXT)

    async def load_from_db(self, db) -> int:
        """
        Load facts from AgentFact database table into the graph.
        
        Args:
            db: AsyncSession from SQLAlchemy
            
        Returns:
            Number of facts loaded
        """
        from sqlalchemy import select
        from src.database.models import AgentFact
        
        try:
            stmt = select(AgentFact).where(AgentFact.user_id == self.user_id)
            result = await db.execute(stmt)
            facts = result.scalars().all()
            
            loaded_count = 0
            for db_fact in facts:
                # Skip if already loaded
                if db_fact.id in self._facts:
                    continue
                
                # Map category
                category = self._map_db_category(db_fact.category or "context")
                
                # Create FactNode
                fact_node = FactNode(
                    id=db_fact.id,
                    content=db_fact.content,
                    category=category,
                    confidence=db_fact.confidence or 1.0,
                    source=db_fact.source or "database",
                    source_type="imported",
                    created_at=db_fact.created_at or datetime.utcnow(),
                )
                
                # Add to storage
                self._facts[db_fact.id] = fact_node
                
                # Update next_id if needed
                if db_fact.id >= self._next_id:
                    self._next_id = db_fact.id + 1
                
                # Add to category
                cat_node = self._categories.get(category)
                if cat_node:
                    cat_node.fact_ids.add(db_fact.id)
                    cat_node.fact_count = len(cat_node.fact_ids)
                
                # Index keywords
                self._index_keywords(db_fact.id, db_fact.content)
                
                loaded_count += 1
            
            logger.info(f"[FactGraph] Loaded {loaded_count} facts from DB for user {self.user_id}")
            return loaded_count
            
        except Exception as e:
            logger.error(f"[FactGraph] Failed to load from DB: {e}")
            return 0

    async def persist_fact(self, db, fact_id: int) -> bool:
        """
        Persist a single fact to the database.
        
        Args:
            db: AsyncSession from SQLAlchemy
            fact_id: ID of the fact to persist
            
        Returns:
            True if persisted successfully
        """
        from sqlalchemy import select
        from src.database.models import AgentFact
        
        fact = self._facts.get(fact_id)
        if not fact:
            return False
        
        try:
            # Check if exists
            stmt = select(AgentFact).where(
                AgentFact.id == fact_id,
                AgentFact.user_id == self.user_id
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                # Update existing
                existing.content = fact.content
                existing.category = fact.category.value
                existing.confidence = fact.confidence
                existing.source = fact.source
            else:
                # Create new
                db_fact = AgentFact(
                    id=fact_id,
                    user_id=self.user_id,
                    content=fact.content,
                    category=fact.category.value,
                    source=fact.source,
                    confidence=fact.confidence,
                )
                db.add(db_fact)
            
            await db.commit()
            logger.debug(f"[FactGraph] Persisted fact {fact_id} to DB")
            return True
            
        except Exception as e:
            logger.error(f"[FactGraph] Failed to persist fact {fact_id}: {e}")
            await db.rollback()
            return False

    async def sync_all_to_db(self, db) -> int:
        """
        Sync all in-memory facts to the database.
        
        Args:
            db: AsyncSession from SQLAlchemy
            
        Returns:
            Number of facts synced
        """
        synced = 0
        for fact_id in self._facts:
            if await self.persist_fact(db, fact_id):
                synced += 1
        logger.info(f"[FactGraph] Synced {synced} facts to DB for user {self.user_id}")
        return synced


class FactGraphManager:
    """Manages FactGraph instances for multiple users."""
    
    def __init__(self):
        self._graphs: Dict[int, FactGraph] = {}
    
    def get_or_create(self, user_id: int) -> FactGraph:
        """Get or create a fact graph for a user."""
        if user_id not in self._graphs:
            self._graphs[user_id] = FactGraph(user_id)
        return self._graphs[user_id]
    
    def get(self, user_id: int) -> Optional[FactGraph]:
        """Get fact graph if it exists."""
        return self._graphs.get(user_id)


# Global instance
_graph_manager: Optional[FactGraphManager] = None


def get_fact_graph_manager() -> Optional[FactGraphManager]:
    """Get the global FactGraphManager instance."""
    return _graph_manager


def init_fact_graph_manager() -> FactGraphManager:
    """Initialize the global FactGraphManager."""
    global _graph_manager
    _graph_manager = FactGraphManager()
    logger.info("[FactGraphManager] Global instance initialized")
    return _graph_manager
