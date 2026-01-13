"""
Episode-Based Result Boosting

Boosts search results related to currently active episodes (projects,
conversation threads, deadlines) using the EpisodeDetector.

This creates temporal relevance - recent and actively-discussed topics
get priority in search results.

Expected impact: +10% on project-related queries
"""
from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass
from datetime import datetime

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class EpisodeBoostConfig:
    """Configuration for episode boosting."""
    max_boost_factor: float = 1.5      # Maximum score multiplier
    min_boost_factor: float = 1.0      # No boost (neutral)
    activity_weight: float = 0.6       # Weight of activity score
    recency_weight: float = 0.4        # Weight of recency score
    deadline_urgency_bonus: float = 0.3  # Extra boost for deadline episodes


class EpisodeBoostingReranker:
    """
    Boosts search results based on active episode context.
    
    Integrates with EpisodeDetector to:
    - Boost results related to active projects
    - Boost results from recent conversation threads
    - Prioritize content related to upcoming deadlines
    
    Usage:
        from src.ai.memory.episode_detector import EpisodeDetector
        
        detector = EpisodeDetector(graph_manager)
        booster = EpisodeBoostingReranker(detector)
        
        results = await booster.rerank_with_episodes(
            query="budget meeting",
            results=search_results,
            user_id=123
        )
    """
    
    def __init__(
        self,
        episode_detector: Optional[Any] = None,
        config: Optional[EpisodeBoostConfig] = None
    ):
        """
        Initialize episode booster.
        
        Args:
            episode_detector: EpisodeDetector instance
            config: Optional configuration
        """
        self.episode_detector = episode_detector
        self.config = config or EpisodeBoostConfig()
        
        logger.info("EpisodeBoostingReranker initialized")
    
    async def rerank_with_episodes(
        self,
        query: str,
        results: List[Dict[str, Any]],
        user_id: int,
        k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Rerank results based on active episodes.
        
        Args:
            query: Search query
            results: Search results to rerank
            user_id: User ID for episode detection
            k: Number of results to return
            
        Returns:
            Reranked results with episode boost applied
        """
        if not results or not self.episode_detector:
            return results[:k]
        
        try:
            # Get episode context
            context = await self.episode_detector.get_retrieval_context(
                user_id, query, max_episodes=5
            )
            
            if not context or not context.active_episodes:
                return results[:k]
            
            # Get boostable node IDs
            boost_ids = set(context.boostable_node_ids or [])
            boost_factor = context.boost_factor or self.config.max_boost_factor
            
            # Create episode keyword set for content matching
            episode_keywords = self._extract_episode_keywords(context)
            
            # Apply boosts
            boosted = []
            for result in results:
                result_copy = result.copy()
                original_score = result.get('score', result.get('rerank_score', 0.5))
                
                # Check for direct graph node match
                graph_id = result.get('metadata', {}).get('graph_node_id')
                direct_match = graph_id and graph_id in boost_ids
                
                # Check for content keyword match
                content = result.get('content', '')
                keyword_match = self._check_keyword_overlap(content, episode_keywords)
                
                # Calculate boost
                if direct_match:
                    # Strong boost for direct graph matches
                    multiplier = boost_factor
                elif keyword_match > 0.3:
                    # Moderate boost for keyword matches
                    multiplier = 1 + (boost_factor - 1) * keyword_match
                else:
                    multiplier = 1.0
                
                # Apply deadline urgency bonus
                if context.has_upcoming_deadline and (direct_match or keyword_match > 0.2):
                    multiplier += self.config.deadline_urgency_bonus
                
                boosted_score = original_score * multiplier
                
                result_copy['score'] = boosted_score
                result_copy['original_score'] = original_score
                result_copy['episode_boost'] = multiplier
                result_copy['episode_matched'] = direct_match or keyword_match > 0.3
                
                boosted.append(result_copy)
            
            # Sort by boosted score
            boosted.sort(key=lambda x: x.get('score', 0), reverse=True)
            
            logger.debug(
                f"Episode boosting: {len(boost_ids)} nodes, "
                f"{len(episode_keywords)} keywords, boost={boost_factor:.2f}"
            )
            
            return boosted[:k]
            
        except Exception as e:
            logger.error(f"Episode boosting failed: {e}")
            return results[:k]
    
    def _extract_episode_keywords(self, context: Any) -> Set[str]:
        """Extract keywords from active episodes for content matching."""
        keywords = set()
        
        for episode in getattr(context, 'active_episodes', []):
            # Extract from title
            title = getattr(episode, 'title', '') or ''
            keywords.update(self._tokenize(title))
            
            # Extract from entities
            entities = getattr(episode, 'entities', []) or []
            for entity in entities:
                if isinstance(entity, dict):
                    keywords.add(entity.get('name', '').lower())
                elif isinstance(entity, str):
                    keywords.add(entity.lower())
        
        # Remove common words
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for'}
        keywords -= stopwords
        
        return keywords
    
    def _tokenize(self, text: str) -> Set[str]:
        """Simple tokenization for keyword extraction."""
        if not text:
            return set()
        
        # Split and clean
        words = text.lower().split()
        return {w.strip('.,!?()[]{}":;') for w in words if len(w) > 2}
    
    def _check_keyword_overlap(self, content: str, keywords: Set[str]) -> float:
        """Check how much of the content matches episode keywords."""
        if not content or not keywords:
            return 0.0
        
        content_lower = content.lower()
        matches = sum(1 for kw in keywords if kw in content_lower)
        
        return min(1.0, matches / max(1, len(keywords) * 0.3))


async def boost_with_episodes(
    results: List[Dict[str, Any]],
    episode_detector: Any,
    user_id: int,
    query: str,
    k: int = 10
) -> List[Dict[str, Any]]:
    """
    Convenience function to apply episode boosting.
    
    Args:
        results: Search results
        episode_detector: EpisodeDetector instance
        user_id: User ID
        query: Search query
        k: Number to return
        
    Returns:
        Episode-boosted results
    """
    booster = EpisodeBoostingReranker(episode_detector)
    return await booster.rerank_with_episodes(query, results, user_id, k)
