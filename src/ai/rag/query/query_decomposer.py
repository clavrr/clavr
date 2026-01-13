"""
Query Decomposition Module

Breaks complex queries into sub-queries for multi-step RAG retrieval.
Each sub-query can be processed independently, with context passed
between retrieval cycles.

Part of the Advanced RAG architecture for autonomous workflows.
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re

from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class QueryComplexity(Enum):
    """Query complexity levels."""
    SIMPLE = "simple"          # Single direct question
    COMPOUND = "compound"      # Multiple related questions (AND/OR)
    SEQUENTIAL = "sequential"  # Questions with dependencies
    COMPARATIVE = "comparative"  # Comparison between items


class SubQueryType(Enum):
    """Types of sub-queries."""
    SEARCH = "search"          # Standard search query
    FILTER = "filter"          # Filtering/refining previous results
    COMPARE = "compare"        # Comparing two things
    AGGREGATE = "aggregate"    # Summarizing multiple results
    TEMPORAL = "temporal"      # Time-bounded query
    ENTITY = "entity"          # Entity-focused lookup


@dataclass
class SubQuery:
    """A decomposed sub-query."""
    id: str
    query: str
    type: SubQueryType
    priority: int              # Execution order (1 = first)
    depends_on: List[str] = field(default_factory=list)  # IDs of prerequisite queries
    context_keys: List[str] = field(default_factory=list)  # Keys to extract from results
    filters: Dict[str, Any] = field(default_factory=dict)  # Metadata filters to apply


@dataclass
class DecompositionResult:
    """Result of query decomposition."""
    original_query: str
    complexity: QueryComplexity
    sub_queries: List[SubQuery]
    execution_plan: List[str]  # Ordered list of sub-query IDs
    reasoning: str             # Why this decomposition was chosen


class QueryDecomposer:
    """
    Decomposes complex queries into executable sub-queries.
    
    Handles:
    - Multi-part questions ("What did Carol say about the project and when did she say it?")
    - Comparative queries ("Compare the proposals from Alice and Bob")
    - Sequential lookups ("Find the meeting notes, then summarize action items")
    - Temporal+content combinations ("Urgent emails from last week about budgets")
    
    Features:
    - Rule-based decomposition for common patterns
    - LLM-based decomposition for complex queries
    - Dependency tracking between sub-queries
    - Context passing between RAG cycles
    """
    
    # Patterns that indicate compound queries
    COMPOUND_PATTERNS = [
        r'\b(and|also|as well as|plus)\b',
        r'\b(what|when|where|who|how|why)\b.*\b(and|also)\b.*\b(what|when|where|who|how|why)\b',
        r',\s*(and|or)\s*',
    ]
    
    # Patterns that indicate sequential queries
    SEQUENTIAL_PATTERNS = [
        r'\b(then|after that|next|following|subsequently)\b',
        r'\b(find|get|search).*\b(then|and then)\b.*\b(summarize|analyze|compare)\b',
    ]
    
    # Patterns for comparative queries
    COMPARATIVE_PATTERNS = [
        r'\b(compare|comparison|difference|between|versus|vs\.?|vs)\b',
        r'\b(which is better|which one|choose between)\b',
    ]
    
    def __init__(
        self,
        use_llm: bool = False,
        llm_client: Optional[Any] = None,
        max_sub_queries: int = 5
    ):
        """
        Initialize query decomposer.
        
        Args:
            use_llm: Use LLM for complex decomposition
            llm_client: LLM client for advanced decomposition
            max_sub_queries: Maximum sub-queries to generate
        """
        self.use_llm = use_llm
        self.llm_client = llm_client
        self.max_sub_queries = max_sub_queries
        
        logger.info(f"QueryDecomposer initialized (llm={use_llm}, max_sub={max_sub_queries})")
    
    def decompose(self, query: str, intent: Optional[str] = None) -> DecompositionResult:
        """
        Decompose a query into sub-queries.
        
        Args:
            query: The original query
            intent: Optional detected intent
            
        Returns:
            DecompositionResult with sub-queries and execution plan
        """
        query = query.strip()
        
        # Detect complexity
        complexity = self._detect_complexity(query)
        
        # Simple queries don't need decomposition
        if complexity == QueryComplexity.SIMPLE:
            return DecompositionResult(
                original_query=query,
                complexity=complexity,
                sub_queries=[SubQuery(
                    id="q1",
                    query=query,
                    type=SubQueryType.SEARCH,
                    priority=1
                )],
                execution_plan=["q1"],
                reasoning="Simple query - no decomposition needed"
            )
        
        # Decompose based on complexity type
        if complexity == QueryComplexity.COMPOUND:
            return self._decompose_compound(query)
        elif complexity == QueryComplexity.SEQUENTIAL:
            return self._decompose_sequential(query)
        elif complexity == QueryComplexity.COMPARATIVE:
            return self._decompose_comparative(query)
        
        # Fallback to simple
        return DecompositionResult(
            original_query=query,
            complexity=QueryComplexity.SIMPLE,
            sub_queries=[SubQuery(
                id="q1",
                query=query,
                type=SubQueryType.SEARCH,
                priority=1
            )],
            execution_plan=["q1"],
            reasoning="Could not decompose - treating as simple query"
        )
    
    async def decompose_with_llm(
        self,
        query: str,
        intent: Optional[str] = None
    ) -> DecompositionResult:
        """
        Decompose query using LLM for complex cases.
        
        Falls back to rule-based decomposition if LLM unavailable.
        """
        if not self.use_llm or not self.llm_client:
            return self.decompose(query, intent)
        
        try:
            prompt = f"""Decompose this query into sub-queries for search.

Query: "{query}"

Rules:
1. Break into independent searchable sub-queries
2. Identify dependencies (which sub-query needs results from another)
3. Keep each sub-query simple and focused
4. Maximum {self.max_sub_queries} sub-queries

Return format (one per line):
Q1: [sub-query text] | TYPE: [search/filter/compare/aggregate] | DEPENDS: [none or Q#]
Q2: ...

QUERIES:"""
            
            from google import genai
            
            response = await self.llm_client.models.generate_content_async(
                model="gemini-2.0-flash",
                contents=prompt
            )
            
            sub_queries = self._parse_llm_response(response.text, query)
            
            if sub_queries:
                return DecompositionResult(
                    original_query=query,
                    complexity=self._detect_complexity(query),
                    sub_queries=sub_queries,
                    execution_plan=[sq.id for sq in sorted(sub_queries, key=lambda x: x.priority)],
                    reasoning="LLM-based decomposition"
                )
                
        except Exception as e:
            logger.debug(f"LLM decomposition failed: {e}")
        
        # Fallback to rule-based
        return self.decompose(query, intent)
    
    def _detect_complexity(self, query: str) -> QueryComplexity:
        """Detect the complexity level of a query."""
        query_lower = query.lower()
        
        # Check for sequential patterns first (highest complexity)
        for pattern in self.SEQUENTIAL_PATTERNS:
            if re.search(pattern, query_lower):
                return QueryComplexity.SEQUENTIAL
        
        # Check for comparative patterns
        for pattern in self.COMPARATIVE_PATTERNS:
            if re.search(pattern, query_lower):
                return QueryComplexity.COMPARATIVE
        
        # Check for compound patterns
        for pattern in self.COMPOUND_PATTERNS:
            if re.search(pattern, query_lower):
                # Make sure it's actually compound, not just uses "and"
                # Count question words or distinct topics
                question_words = len(re.findall(r'\b(what|when|where|who|how|why)\b', query_lower))
                if question_words > 1:
                    return QueryComplexity.COMPOUND
        
        return QueryComplexity.SIMPLE
    
    def _decompose_compound(self, query: str) -> DecompositionResult:
        """Decompose a compound query with multiple parts."""
        sub_queries = []
        
        # Split on common conjunctions
        parts = re.split(r'\s+(?:and|also|as well as)\s+', query, flags=re.IGNORECASE)
        
        if len(parts) == 1:
            # Try splitting on commas + and
            parts = re.split(r',\s*(?:and\s+)?', query)
        
        for i, part in enumerate(parts):
            part = part.strip()
            if len(part) > 10:  # Minimum meaningful query length
                sub_queries.append(SubQuery(
                    id=f"q{i+1}",
                    query=self._clean_partial_query(part),
                    type=SubQueryType.SEARCH,
                    priority=i + 1
                ))
        
        # Limit sub-queries
        sub_queries = sub_queries[:self.max_sub_queries]
        
        if not sub_queries:
            sub_queries.append(SubQuery(
                id="q1",
                query=query,
                type=SubQueryType.SEARCH,
                priority=1
            ))
        
        return DecompositionResult(
            original_query=query,
            complexity=QueryComplexity.COMPOUND,
            sub_queries=sub_queries,
            execution_plan=[sq.id for sq in sub_queries],
            reasoning=f"Compound query split into {len(sub_queries)} parallel sub-queries"
        )
    
    def _decompose_sequential(self, query: str) -> DecompositionResult:
        """Decompose a sequential query with dependencies."""
        sub_queries = []
        
        # Split on sequential markers
        parts = re.split(r'\s+(?:then|after that|next|and then)\s+', query, flags=re.IGNORECASE)
        
        for i, part in enumerate(parts):
            part = part.strip()
            if len(part) > 10:
                # Determine type based on content
                query_type = self._detect_sub_query_type(part)
                
                # Each step depends on the previous
                depends_on = [f"q{i}"] if i > 0 else []
                
                # Extract context to pass forward
                context_keys = self._extract_context_keys(part)
                
                sub_queries.append(SubQuery(
                    id=f"q{i+1}",
                    query=self._clean_partial_query(part),
                    type=query_type,
                    priority=i + 1,
                    depends_on=depends_on,
                    context_keys=context_keys
                ))
        
        sub_queries = sub_queries[:self.max_sub_queries]
        
        if not sub_queries:
            sub_queries.append(SubQuery(
                id="q1",
                query=query,
                type=SubQueryType.SEARCH,
                priority=1
            ))
        
        return DecompositionResult(
            original_query=query,
            complexity=QueryComplexity.SEQUENTIAL,
            sub_queries=sub_queries,
            execution_plan=[sq.id for sq in sub_queries],
            reasoning=f"Sequential query with {len(sub_queries)} dependent steps"
        )
    
    def _decompose_comparative(self, query: str) -> DecompositionResult:
        """Decompose a comparative query."""
        sub_queries = []
        
        # Extract items being compared
        # Pattern: "compare X and Y" or "X vs Y" or "difference between X and Y"
        comparison_match = re.search(
            r'(?:compare|between)\s+(.+?)\s+(?:and|vs\.?|versus|with)\s+(.+?)(?:\?|$)',
            query,
            re.IGNORECASE
        )
        
        if comparison_match:
            item1 = comparison_match.group(1).strip()
            item2 = comparison_match.group(2).strip()
            
            # First: search for item 1
            sub_queries.append(SubQuery(
                id="q1",
                query=f"Find information about {item1}",
                type=SubQueryType.SEARCH,
                priority=1,
                context_keys=["item1_info"]
            ))
            
            # Second: search for item 2
            sub_queries.append(SubQuery(
                id="q2",
                query=f"Find information about {item2}",
                type=SubQueryType.SEARCH,
                priority=1,  # Same priority - can run in parallel
                context_keys=["item2_info"]
            ))
            
            # Third: compare (depends on both)
            sub_queries.append(SubQuery(
                id="q3",
                query=f"Compare {item1} and {item2}",
                type=SubQueryType.COMPARE,
                priority=2,
                depends_on=["q1", "q2"]
            ))
        else:
            # Fallback: simple comparison query
            sub_queries.append(SubQuery(
                id="q1",
                query=query,
                type=SubQueryType.COMPARE,
                priority=1
            ))
        
        return DecompositionResult(
            original_query=query,
            complexity=QueryComplexity.COMPARATIVE,
            sub_queries=sub_queries,
            execution_plan=["q1", "q2", "q3"] if len(sub_queries) == 3 else ["q1"],
            reasoning="Comparative query decomposed into search + compare steps"
        )
    
    def _detect_sub_query_type(self, query: str) -> SubQueryType:
        """Detect the type of a sub-query."""
        query_lower = query.lower()
        
        if any(term in query_lower for term in ['summarize', 'aggregate', 'total', 'count', 'list all']):
            return SubQueryType.AGGREGATE
        elif any(term in query_lower for term in ['compare', 'difference', 'versus', 'vs']):
            return SubQueryType.COMPARE
        elif any(term in query_lower for term in ['filter', 'only', 'just', 'exclude', 'include']):
            return SubQueryType.FILTER
        elif any(term in query_lower for term in ['recent', 'today', 'yesterday', 'last week', 'before', 'after']):
            return SubQueryType.TEMPORAL
        elif any(term in query_lower for term in ['who', 'person', 'company', 'from', 'by']):
            return SubQueryType.ENTITY
        else:
            return SubQueryType.SEARCH
    
    def _extract_context_keys(self, query: str) -> List[str]:
        """Identify what context should be extracted from this step's results."""
        keys = []
        query_lower = query.lower()
        
        if 'email' in query_lower or 'message' in query_lower:
            keys.append("emails")
        if 'meeting' in query_lower or 'calendar' in query_lower:
            keys.append("meetings")
        if 'document' in query_lower or 'file' in query_lower:
            keys.append("documents")
        if 'person' in query_lower or 'who' in query_lower:
            keys.append("people")
        if 'action' in query_lower or 'task' in query_lower or 'todo' in query_lower:
            keys.append("actions")
        
        return keys if keys else ["results"]
    
    def _clean_partial_query(self, query: str) -> str:
        """Clean up a partial query extracted from decomposition."""
        # Remove leading conjunctions
        query = re.sub(r'^(?:and|or|but|also|then|next)\s+', '', query, flags=re.IGNORECASE)
        
        # Remove trailing punctuation except ?
        query = query.rstrip('.,;:')
        
        # Capitalize first letter
        if query:
            query = query[0].upper() + query[1:]
        
        return query.strip()
    
    def _parse_llm_response(self, response: str, original_query: str) -> List[SubQuery]:
        """Parse LLM response into SubQuery objects."""
        sub_queries = []
        
        # Pattern: Q1: [query] | TYPE: [type] | DEPENDS: [deps]
        pattern = r'Q(\d+):\s*(.+?)\s*\|\s*TYPE:\s*(\w+)\s*\|\s*DEPENDS:\s*(.+?)(?:\n|$)'
        
        for match in re.finditer(pattern, response, re.IGNORECASE):
            q_num = int(match.group(1))
            query_text = match.group(2).strip()
            query_type = match.group(3).strip().lower()
            depends = match.group(4).strip()
            
            # Map type string to enum
            type_map = {
                'search': SubQueryType.SEARCH,
                'filter': SubQueryType.FILTER,
                'compare': SubQueryType.COMPARE,
                'aggregate': SubQueryType.AGGREGATE,
                'temporal': SubQueryType.TEMPORAL,
                'entity': SubQueryType.ENTITY,
            }
            
            sq_type = type_map.get(query_type, SubQueryType.SEARCH)
            
            # Parse dependencies
            deps = []
            if depends.lower() != 'none':
                dep_matches = re.findall(r'Q(\d+)', depends, re.IGNORECASE)
                deps = [f"q{d}" for d in dep_matches]
            
            sub_queries.append(SubQuery(
                id=f"q{q_num}",
                query=query_text,
                type=sq_type,
                priority=q_num,
                depends_on=deps
            ))
        
        return sub_queries


class DecomposedRAGExecutor:
    """
    Executes decomposed queries with context passing.
    
    Handles:
    - Parallel execution of independent sub-queries
    - Sequential execution with context passing
    - Result aggregation across sub-queries
    """
    
    def __init__(
        self,
        rag_engine: Any,
        decomposer: Optional[QueryDecomposer] = None
    ):
        """
        Initialize executor.
        
        Args:
            rag_engine: The RAG engine for searches
            decomposer: Query decomposer (created if not provided)
        """
        self.rag_engine = rag_engine
        self.decomposer = decomposer or QueryDecomposer()
    
    async def execute(
        self,
        query: str,
        k: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a query with automatic decomposition.
        
        Args:
            query: The user's query
            k: Results per sub-query
            filters: Base filters to apply
            
        Returns:
            Combined results with execution trace
        """
        import asyncio
        
        # Decompose query
        decomposition = self.decomposer.decompose(query)
        
        # If simple query, just run it
        if decomposition.complexity == QueryComplexity.SIMPLE:
            results = await self.rag_engine.asearch(query, k=k, filters=filters)
            return {
                'results': results,
                'decomposition': decomposition,
                'sub_query_results': {},
                'total_results': len(results)
            }
        
        # Execute sub-queries
        sub_results: Dict[str, List[Dict]] = {}
        context: Dict[str, Any] = {}
        
        # Group by priority for parallel execution
        by_priority: Dict[int, List[SubQuery]] = {}
        for sq in decomposition.sub_queries:
            if sq.priority not in by_priority:
                by_priority[sq.priority] = []
            by_priority[sq.priority].append(sq)
        
        # Execute in priority order
        for priority in sorted(by_priority.keys()):
            queries_at_priority = by_priority[priority]
            
            # Check if all dependencies are satisfied
            ready = [sq for sq in queries_at_priority 
                    if all(dep in sub_results for dep in sq.depends_on)]
            
            if not ready:
                logger.warning(f"Skipping priority {priority} - dependencies not met")
                continue
            
            # Execute in parallel
            tasks = []
            for sq in ready:
                # Inject context from dependencies
                sq_context = self._inject_context(sq, sub_results, context)
                tasks.append(self._execute_sub_query(sq, k, filters, sq_context))
            
            results = await asyncio.gather(*tasks)
            
            # Store results
            for sq, result in zip(ready, results):
                sub_results[sq.id] = result
                
                # Extract context for dependent queries
                if sq.context_keys:
                    for key in sq.context_keys:
                        context[f"{sq.id}_{key}"] = result
        
        # Aggregate final results
        all_results = []
        seen_ids = set()
        
        for sq_id in decomposition.execution_plan:
            if sq_id in sub_results:
                for r in sub_results[sq_id]:
                    # Deduplicate
                    rid = r.get('id', r.get('content', '')[:50])
                    if rid not in seen_ids:
                        all_results.append(r)
                        seen_ids.add(rid)
        
        return {
            'results': all_results[:k * 2],  # Cap total results
            'decomposition': decomposition,
            'sub_query_results': sub_results,
            'context': context,
            'total_results': len(all_results)
        }
    
    async def _execute_sub_query(
        self,
        sub_query: SubQuery,
        k: int,
        filters: Optional[Dict[str, Any]],
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Execute a single sub-query."""
        try:
            # Merge filters
            merged_filters = {**(filters or {}), **sub_query.filters}
            
            # For aggregate/compare types, might need special handling
            if sub_query.type == SubQueryType.AGGREGATE:
                # Fetch more for aggregation
                results = await self.rag_engine.asearch(
                    sub_query.query, k=k * 3, filters=merged_filters
                )
            elif sub_query.type == SubQueryType.COMPARE:
                # Comparison might need results from context
                results = await self.rag_engine.asearch(
                    sub_query.query, k=k * 2, filters=merged_filters
                )
            else:
                results = await self.rag_engine.asearch(
                    sub_query.query, k=k, filters=merged_filters
                )
            
            return results
            
        except Exception as e:
            logger.error(f"Sub-query {sub_query.id} failed: {e}")
            return []
    
    def _inject_context(
        self,
        sub_query: SubQuery,
        sub_results: Dict[str, List[Dict]],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Inject context from previous queries."""
        injected = {}
        
        for dep_id in sub_query.depends_on:
            if dep_id in sub_results:
                injected[f"{dep_id}_results"] = sub_results[dep_id]
        
        injected.update(context)
        return injected
