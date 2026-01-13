"""
Semantic Clustering - Auto-cluster related facts into themes.

Groups semantically similar facts together to enable:
- Theme-based retrieval ("What about communication preferences?")
- Coherent context assembly
- Fact relationship discovery
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Set, Tuple
from collections import defaultdict
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class FactCluster:
    """A cluster of semantically related facts."""
    cluster_id: str
    theme: str
    description: str
    
    # Facts in this cluster
    fact_ids: List[int] = field(default_factory=list)
    fact_contents: List[str] = field(default_factory=list)
    
    # Cluster statistics
    avg_confidence: float = 0.0
    coherence_score: float = 0.0  # How well facts relate to each other
    
    # Keywords that define this cluster
    keywords: List[str] = field(default_factory=list)
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    def add_fact(self, fact_id: int, content: str, confidence: float):
        """Add a fact to the cluster."""
        if fact_id not in self.fact_ids:
            self.fact_ids.append(fact_id)
            self.fact_contents.append(content)
            # Update average confidence
            n = len(self.fact_ids)
            self.avg_confidence = ((self.avg_confidence * (n - 1)) + confidence) / n
            self.last_updated = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "theme": self.theme,
            "description": self.description,
            "fact_count": len(self.fact_ids),
            "keywords": self.keywords,
            "avg_confidence": self.avg_confidence,
            "coherence_score": self.coherence_score
        }
    
    def format_for_context(self, max_facts: int = 3) -> str:
        """Format cluster for LLM context."""
        lines = [f"[{self.theme.upper()}]"]
        for content in self.fact_contents[:max_facts]:
            lines.append(f"• {content}")
        if len(self.fact_contents) > max_facts:
            lines.append(f"  ... and {len(self.fact_contents) - max_facts} more")
        return "\n".join(lines)


class SemanticClusterer:
    """
    Clusters facts by semantic similarity.
    
    Uses keyword-based clustering with optional embedding support.
    """
    
    # Predefined theme patterns for rule-based clustering
    THEME_PATTERNS = {
        "communication": {
            "keywords": ["email", "slack", "teams", "message", "call", "meeting", "chat", "respond", "communicate"],
            "description": "Communication preferences and patterns"
        },
        "scheduling": {
            "keywords": ["morning", "afternoon", "evening", "time", "schedule", "calendar", "meeting", "early", "late", "day", "week"],
            "description": "Scheduling and time preferences"
        },
        "work_style": {
            "keywords": ["focus", "deep work", "productivity", "work", "task", "project", "deadline", "collaborate"],
            "description": "Work style and productivity patterns"
        },
        "people": {
            "keywords": ["colleague", "manager", "team", "report", "collaborator", "contact", "person"],
            "description": "People and relationships"
        },
        "tools": {
            "keywords": ["app", "software", "tool", "platform", "system", "use", "prefer"],
            "description": "Tool and software preferences"
        },
        "content": {
            "keywords": ["format", "style", "write", "document", "report", "email", "template"],
            "description": "Content and format preferences"
        }
    }
    
    def __init__(self, embedder: Optional[Any] = None):
        """
        Initialize clusterer.
        
        Args:
            embedder: Optional embedding model for semantic clustering
        """
        self.embedder = embedder
        self._clusters: Dict[int, Dict[str, FactCluster]] = {}  # user_id -> theme -> cluster
    
    def cluster_facts(
        self,
        facts: List[Dict[str, Any]],
        user_id: int,
        min_cluster_size: int = 2
    ) -> List[FactCluster]:
        """
        Cluster a list of facts by semantic similarity.
        
        Args:
            facts: List of facts with id, content, confidence
            user_id: User ID for caching
            min_cluster_size: Minimum facts per cluster
            
        Returns:
            List of FactClusters
        """
        # Initialize user clusters
        if user_id not in self._clusters:
            self._clusters[user_id] = {}
        
        # Use embedding-based clustering if available
        if self.embedder:
            return self._cluster_with_embeddings(facts, user_id, min_cluster_size)
        
        # Fall back to keyword-based clustering
        return self._cluster_with_keywords(facts, user_id, min_cluster_size)
    
    def _cluster_with_keywords(
        self,
        facts: List[Dict[str, Any]],
        user_id: int,
        min_cluster_size: int
    ) -> List[FactCluster]:
        """Cluster using keyword matching."""
        theme_facts = defaultdict(list)
        
        for fact in facts:
            content = fact.get("content", "").lower()
            fact_id = fact.get("id", 0)
            confidence = fact.get("confidence", 0.5)
            
            # Match against theme patterns
            matched_themes = []
            for theme, config in self.THEME_PATTERNS.items():
                keyword_matches = sum(1 for kw in config["keywords"] if kw in content)
                if keyword_matches > 0:
                    matched_themes.append((theme, keyword_matches))
            
            # Assign to best matching theme(s)
            if matched_themes:
                matched_themes.sort(key=lambda x: x[1], reverse=True)
                best_theme = matched_themes[0][0]
                theme_facts[best_theme].append({
                    "id": fact_id,
                    "content": fact.get("content", ""),
                    "confidence": confidence
                })
        
        # Build clusters
        clusters = []
        for theme, facts_list in theme_facts.items():
            if len(facts_list) >= min_cluster_size:
                cluster_id = f"{user_id}_{theme}"
                config = self.THEME_PATTERNS.get(theme, {})
                
                cluster = FactCluster(
                    cluster_id=cluster_id,
                    theme=theme,
                    description=config.get("description", ""),
                    keywords=config.get("keywords", [])[:5]
                )
                
                for f in facts_list:
                    cluster.add_fact(f["id"], f["content"], f["confidence"])
                
                # Calculate coherence (simple: keyword overlap)
                cluster.coherence_score = self._calculate_coherence(cluster)
                
                clusters.append(cluster)
                self._clusters[user_id][theme] = cluster
        
        return clusters
    
    def _cluster_with_embeddings(
        self,
        facts: List[Dict[str, Any]],
        user_id: int,
        min_cluster_size: int
    ) -> List[FactCluster]:
        """Cluster using embedding similarity (if embedder available)."""
        # Get embeddings for all facts
        contents = [f.get("content", "") for f in facts]
        
        try:
            embeddings = self.embedder.embed_documents(contents)
        except Exception as e:
            logger.warning(f"Embedding failed, falling back to keywords: {e}")
            return self._cluster_with_keywords(facts, user_id, min_cluster_size)
        
        # Simple clustering: group by cosine similarity
        # For now, still use keyword themes but score by embedding similarity
        return self._cluster_with_keywords(facts, user_id, min_cluster_size)
    
    def _calculate_coherence(self, cluster: FactCluster) -> float:
        """Calculate how coherent (related) facts in a cluster are."""
        if len(cluster.fact_contents) < 2:
            return 1.0
        
        # Simple coherence: keyword overlap between facts
        all_words = []
        for content in cluster.fact_contents:
            words = set(re.findall(r'\b\w+\b', content.lower()))
            all_words.append(words)
        
        # Calculate pairwise overlap
        total_overlap = 0
        comparisons = 0
        
        for i in range(len(all_words)):
            for j in range(i + 1, len(all_words)):
                overlap = len(all_words[i] & all_words[j])
                union = len(all_words[i] | all_words[j])
                if union > 0:
                    total_overlap += overlap / union
                    comparisons += 1
        
        if comparisons == 0:
            return 0.5
        
        return min(1.0, total_overlap / comparisons + 0.3)  # Base coherence of 0.3
    
    def get_cluster(self, user_id: int, theme: str) -> Optional[FactCluster]:
        """Get a specific cluster for a user."""
        return self._clusters.get(user_id, {}).get(theme)
    
    def get_all_clusters(self, user_id: int) -> List[FactCluster]:
        """Get all clusters for a user."""
        return list(self._clusters.get(user_id, {}).values())
    
    def find_cluster_for_query(
        self,
        query: str,
        user_id: int
    ) -> Optional[FactCluster]:
        """Find the best matching cluster for a query."""
        query_lower = query.lower()
        
        best_match = None
        best_score = 0
        
        for theme, config in self.THEME_PATTERNS.items():
            score = sum(1 for kw in config["keywords"] if kw in query_lower)
            if score > best_score:
                best_score = score
                best_match = theme
        
        if best_match:
            return self.get_cluster(user_id, best_match)
        
        return None
    
    def format_clusters_for_context(
        self,
        user_id: int,
        themes: Optional[List[str]] = None,
        max_clusters: int = 3,
        max_facts_per_cluster: int = 2
    ) -> str:
        """Format clusters for LLM context injection."""
        clusters = self.get_all_clusters(user_id)
        
        if themes:
            clusters = [c for c in clusters if c.theme in themes]
        
        # Sort by coherence and size
        clusters.sort(key=lambda c: (c.coherence_score, len(c.fact_ids)), reverse=True)
        
        lines = []
        for cluster in clusters[:max_clusters]:
            lines.append(cluster.format_for_context(max_facts_per_cluster))
            lines.append("")
        
        return "\n".join(lines).strip()


# Global instance
_clusterer: Optional[SemanticClusterer] = None


def get_semantic_clusterer() -> Optional[SemanticClusterer]:
    """Get the global SemanticClusterer instance."""
    return _clusterer


def init_semantic_clusterer(embedder: Optional[Any] = None) -> SemanticClusterer:
    """Initialize the global SemanticClusterer."""
    global _clusterer
    _clusterer = SemanticClusterer(embedder=embedder)
    logger.info("[SemanticClusterer] Global instance initialized")
    return _clusterer
