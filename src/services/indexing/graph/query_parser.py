"""
Graph Query Parser for NetworkX

Provides a query language similar to Cypher for NetworkX graphs.
Supports pattern matching, filtering, traversal, and aggregation.

This parser enables the NetworkX backend to support Cypher-like queries,
making it compatible with the Neo4j query interface for development/testing.
"""
import re
from typing import Dict, Any, List, Optional, Set, Callable
from enum import Enum

try:
    import networkx as nx
except ImportError:
    nx = None

from .graph_constants import (
    DEFAULT_TRAVERSAL_DEPTH,
    DEFAULT_MAX_DEPTH,
    DEFAULT_QUERY_LIMIT,
    MAX_QUERY_RESULTS,
)
from ....utils.logger import setup_logger

logger = setup_logger(__name__)


class QueryType(str, Enum):
    """Types of graph queries"""
    MATCH = "MATCH"
    TRAVERSE = "TRAVERSE"
    PATH = "PATH"
    AGGREGATE = "AGGREGATE"
    COUNT = "COUNT"


class QueryParser:
    """
    Parse and execute graph queries on NetworkX graphs
    
    Supports Cypher-like query patterns for compatibility with Neo4j:
    
    1. MATCH queries:
       MATCH (n:NodeType) WHERE n.property = value RETURN n
       MATCH (n:Email)-[r:FROM]->(c:Contact) RETURN n, c
    
    2. Traversal queries:
       TRAVERSE FROM node_id FOLLOW [rel_types] DEPTH 2 RETURN nodes
    
    3. Path queries:
       PATH FROM node1 TO node2 MAX_DEPTH 5 RETURN path
    
    4. Aggregation queries:
       MATCH (n:Receipt) WHERE n.merchant = "Chipotle" RETURN SUM(n.total)
       MATCH (e:Email) RETURN COUNT(e) GROUP BY e.sender
    
    5. Complex filters:
       MATCH (n:Email) WHERE n.date >= "2024-01-01" AND n.sender CONTAINS "@company.com"
    """
    
    def __init__(self, graph, max_results: int = DEFAULT_QUERY_LIMIT):
        """
        Initialize query parser
        
        Args:
            graph: NetworkX graph to query
            max_results: Maximum results to return (prevents memory issues)
        """
        if nx is None:
            raise ImportError("NetworkX is required for query parsing. Install with: pip install networkx")
        
        self.graph = graph
        self.max_results = min(max_results, MAX_QUERY_RESULTS)
        
        logger.info(f"Initialized QueryParser (max_results={self.max_results})")
        
        # Operators for filtering
        self.operators = {
            '=': lambda a, b: a == b,
            '!=': lambda a, b: a != b,
            '>': lambda a, b: a > b,
            '>=': lambda a, b: a >= b,
            '<': lambda a, b: a < b,
            '<=': lambda a, b: a <= b,
            'CONTAINS': lambda a, b: b in str(a),
            'STARTS_WITH': lambda a, b: str(a).startswith(b),
            'ENDS_WITH': lambda a, b: str(a).endswith(b),
            'IN': lambda a, b: a in b,
        }
        
        # Aggregation functions
        self.aggregations = {
            'COUNT': lambda items: len(items),
            'SUM': lambda items: sum(items),
            'AVG': lambda items: sum(items) / len(items) if items else 0,
            'MIN': lambda items: min(items) if items else None,
            'MAX': lambda items: max(items) if items else None,
        }
    
    def parse_and_execute(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Parse and execute a graph query
        
        Args:
            query: Query string
            params: Query parameters for substitution
            
        Returns:
            List of result dictionaries (limited to max_results)
        """
        params = params or {}
        query = query.strip()
        
        logger.debug(f"Executing query: {query[:100]}{'...' if len(query) > 100 else ''}")
        
        try:
            # Determine query type
            if query.upper().startswith('MATCH'):
                results = self._execute_match_query(query, params)
            elif query.upper().startswith('TRAVERSE'):
                results = self._execute_traverse_query(query, params)
            elif query.upper().startswith('PATH'):
                results = self._execute_path_query(query, params)
            else:
                # Fallback to simple parameter-based query
                results = self._execute_simple_query(params)
            
            # Limit results
            if len(results) > self.max_results:
                logger.warning(
                    f"Query returned {len(results)} results, limiting to {self.max_results}"
                )
                results = results[:self.max_results]
            
            logger.debug(f"Query returned {len(results)} results")
            return results
            
        except Exception as e:
            logger.error(f"Query execution failed: {e}", exc_info=True)
            return []
    
    def _execute_match_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute a MATCH query
        
        Examples:
            MATCH (n:Email) RETURN n
            MATCH (n:Email) WHERE n.sender = "john@example.com" RETURN n
            MATCH (n:Email)-[r:FROM]->(c:Contact) RETURN n, c
            MATCH (n:Receipt) WHERE n.total > 10 RETURN SUM(n.total) AS total_spent
        """
        # Parse query components
        node_patterns = self._extract_node_patterns(query)
        rel_patterns = self._extract_relationship_patterns(query)
        where_clause = self._extract_where_clause(query)
        return_clause = self._extract_return_clause(query)
        group_by = self._extract_group_by(query)
        
        # Find matching nodes
        matching_nodes = self._find_matching_nodes(node_patterns, where_clause, params)
        
        # If relationship patterns exist, filter by relationships
        if rel_patterns:
            matching_nodes = self._filter_by_relationships(matching_nodes, rel_patterns)
        
        # Process return clause (aggregation, projection, etc.)
        results = self._process_return_clause(matching_nodes, return_clause, group_by)
        
        return results
    
    def _extract_node_patterns(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract node patterns from MATCH clause
        
        Pattern: (variable:NodeType) or (variable) or (:NodeType)
        """
        patterns = []
        
        # Match patterns like (n:Email) or (n) or (:Email)
        node_pattern = r'\((\w*):?(\w*)\)'
        matches = re.findall(node_pattern, query)
        
        for variable, node_type in matches:
            patterns.append({
                'variable': variable or None,
                'node_type': node_type or None
            })
        
        return patterns
    
    def _extract_relationship_patterns(self, query: str) -> List[Dict[str, Any]]:
        """
        Extract relationship patterns from MATCH clause
        
        Pattern: -[r:REL_TYPE]-> or -[]-> or -[r]->
        """
        patterns = []
        
        # Match patterns like -[r:FROM]-> or -[r]-> or -[]->
        rel_pattern = r'-\[(\w*):?(\w*)\]->'
        matches = re.findall(rel_pattern, query)
        
        for variable, rel_type in matches:
            patterns.append({
                'variable': variable or None,
                'rel_type': rel_type or None,
                'direction': 'outgoing'
            })
        
        # Also check for incoming relationships <-[r:TYPE]-
        incoming_pattern = r'<-\[(\w*):?(\w*)\]-'
        incoming_matches = re.findall(incoming_pattern, query)
        
        for variable, rel_type in incoming_matches:
            patterns.append({
                'variable': variable or None,
                'rel_type': rel_type or None,
                'direction': 'incoming'
            })
        
        return patterns
    
    def _extract_where_clause(self, query: str) -> Optional[str]:
        """Extract WHERE clause from query"""
        where_match = re.search(r'WHERE\s+(.+?)(?:RETURN|GROUP BY|ORDER BY|$)', query, re.IGNORECASE)
        return where_match.group(1).strip() if where_match else None
    
    def _extract_return_clause(self, query: str) -> str:
        """Extract RETURN clause from query"""
        return_match = re.search(r'RETURN\s+(.+?)(?:GROUP BY|ORDER BY|LIMIT|$)', query, re.IGNORECASE)
        return return_match.group(1).strip() if return_match else '*'
    
    def _extract_group_by(self, query: str) -> Optional[str]:
        """Extract GROUP BY clause from query"""
        group_match = re.search(r'GROUP BY\s+(.+?)(?:ORDER BY|LIMIT|$)', query, re.IGNORECASE)
        return group_match.group(1).strip() if group_match else None
    
    def _find_matching_nodes(
        self,
        node_patterns: List[Dict[str, Any]],
        where_clause: Optional[str],
        params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Find nodes matching the patterns and where clause"""
        matching_nodes = []
        
        # Get the primary node pattern (first one)
        if not node_patterns:
            logger.warning("No node patterns provided in query")
            return matching_nodes
        
        primary_pattern = node_patterns[0]
        target_type = primary_pattern.get('node_type')
        
        logger.debug(f"Finding nodes of type: {target_type or 'any'}")
        
        # Iterate through all nodes
        for node_id, node_data in self.graph.nodes(data=True):
            # Check node type if specified
            if target_type and node_data.get('node_type') != target_type:
                continue
            
            # Apply where clause filters
            if where_clause and not self._evaluate_where_clause(node_data, where_clause, params):
                continue
            
            # Node matches!
            matching_nodes.append({
                'node_id': node_id,
                **node_data
            })
        
        logger.debug(f"Found {len(matching_nodes)} matching nodes")
        return matching_nodes
    
    def _evaluate_where_clause(
        self,
        node_data: Dict[str, Any],
        where_clause: str,
        params: Dict[str, Any]
    ) -> bool:
        """
        Evaluate a WHERE clause against node data
        
        Supports:
        - Simple conditions: n.property = value
        - Complex conditions: n.total > 10 AND n.merchant = "Chipotle"
        - Parameter substitution: n.sender = $sender
        """
        # Handle AND/OR logic
        if ' AND ' in where_clause.upper():
            conditions = re.split(r'\s+AND\s+', where_clause, flags=re.IGNORECASE)
            return all(self._evaluate_single_condition(node_data, cond.strip(), params) for cond in conditions)
        
        elif ' OR ' in where_clause.upper():
            conditions = re.split(r'\s+OR\s+', where_clause, flags=re.IGNORECASE)
            return any(self._evaluate_single_condition(node_data, cond.strip(), params) for cond in conditions)
        
        else:
            return self._evaluate_single_condition(node_data, where_clause, params)
    
    def _evaluate_single_condition(
        self,
        node_data: Dict[str, Any],
        condition: str,
        params: Dict[str, Any]
    ) -> bool:
        """Evaluate a single condition"""
        # Parse condition: n.property operator value
        # Support operators: =, !=, >, >=, <, <=, CONTAINS, IN
        
        for op_str, op_func in self.operators.items():
            if op_str in condition:
                parts = condition.split(op_str, 1)
                if len(parts) != 2:
                    continue
                
                left = parts[0].strip()
                right = parts[1].strip()
                
                # Extract property name (e.g., "n.sender" -> "sender")
                if '.' in left:
                    prop_name = left.split('.', 1)[1]
                else:
                    prop_name = left
                
                # Get actual value from node data
                actual_value = node_data.get(prop_name)
                if actual_value is None:
                    return False
                
                # Get expected value (with parameter substitution)
                if right.startswith('$'):
                    # Parameter substitution
                    param_name = right[1:]
                    expected_value = params.get(param_name)
                elif right.startswith('"') or right.startswith("'"):
                    # String literal
                    expected_value = right.strip('"\'')
                else:
                    # Try to parse as number or boolean
                    try:
                        if right.lower() == 'true':
                            expected_value = True
                        elif right.lower() == 'false':
                            expected_value = False
                        elif '.' in right:
                            expected_value = float(right)
                        else:
                            expected_value = int(right)
                    except ValueError:
                        expected_value = right
                
                # Evaluate condition
                try:
                    return op_func(actual_value, expected_value)
                except (TypeError, ValueError):
                    return False
        
        return True
    
    def _filter_by_relationships(
        self,
        nodes: List[Dict[str, Any]],
        rel_patterns: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter nodes by relationship patterns"""
        filtered_nodes = []
        
        for node in nodes:
            node_id = node['node_id']
            
            # Check if node has all required relationships
            has_all_rels = True
            
            for rel_pattern in rel_patterns:
                rel_type = rel_pattern.get('rel_type')
                direction = rel_pattern.get('direction', 'outgoing')
                
                # Get neighbors
                if direction == 'outgoing':
                    neighbors = list(self.graph.successors(node_id))
                else:
                    neighbors = list(self.graph.predecessors(node_id))
                
                # Check if any neighbor matches the relationship type
                has_rel = False
                for neighbor in neighbors:
                    if direction == 'outgoing':
                        edges = self.graph.get_edge_data(node_id, neighbor)
                    else:
                        edges = self.graph.get_edge_data(neighbor, node_id)
                    
                    if edges:
                        for edge_data in edges.values():
                            if rel_type is None or edge_data.get('rel_type') == rel_type:
                                has_rel = True
                                break
                    
                    if has_rel:
                        break
                
                if not has_rel:
                    has_all_rels = False
                    break
            
            if has_all_rels:
                filtered_nodes.append(node)
        
        return filtered_nodes
    
    def _process_return_clause(
        self,
        nodes: List[Dict[str, Any]],
        return_clause: str,
        group_by: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Process RETURN clause (aggregation, projection)"""
        # Check for aggregation functions
        agg_match = re.search(r'(COUNT|SUM|AVG|MIN|MAX)\s*\((.+?)\)', return_clause, re.IGNORECASE)
        
        if agg_match:
            agg_func_name = agg_match.group(1).upper()
            agg_field = agg_match.group(2).strip()
            
            # Extract field name (e.g., "n.total" -> "total")
            if '.' in agg_field:
                field_name = agg_field.split('.', 1)[1]
            else:
                field_name = agg_field
            
            # Get aggregation function
            agg_func = self.aggregations.get(agg_func_name)
            
            if not agg_func:
                # Unknown aggregation function
                return [{"error": f"Unknown aggregation function: {agg_func_name}"}]
            
            if agg_func_name == 'COUNT':
                # COUNT doesn't need field values
                result_value = agg_func(nodes)
            else:
                # Extract field values
                values = [node.get(field_name) for node in nodes if node.get(field_name) is not None]
                result_value = agg_func(values) if values else None
            
            # Check for alias (e.g., "SUM(n.total) AS total_spent")
            alias_match = re.search(r'AS\s+(\w+)', return_clause, re.IGNORECASE)
            alias = alias_match.group(1) if alias_match else f"{agg_func_name.lower()}_{field_name}"
            
            return [{alias: result_value}]
        
        # Group by handling
        elif group_by:
            return self._process_group_by(nodes, return_clause, group_by)
        
        # Simple projection
        else:
            if return_clause == '*' or return_clause.lower() == 'n':
                return nodes
            else:
                # Project specific fields
                fields = [f.strip() for f in return_clause.split(',')]
                projected = []
                
                for node in nodes:
                    proj_node = {}
                    for field in fields:
                        # Extract field name (e.g., "n.sender" -> "sender")
                        if '.' in field:
                            field_name = field.split('.', 1)[1]
                        else:
                            field_name = field
                        
                        proj_node[field_name] = node.get(field_name)
                    
                    projected.append(proj_node)
                
                return projected
    
    def _process_group_by(
        self,
        nodes: List[Dict[str, Any]],
        return_clause: str,
        group_by: str
    ) -> List[Dict[str, Any]]:
        """Process GROUP BY clause"""
        # Extract group field
        if '.' in group_by:
            group_field = group_by.split('.', 1)[1]
        else:
            group_field = group_by
        
        # Group nodes
        groups: Dict[Any, List[Dict[str, Any]]] = {}
        for node in nodes:
            group_value = node.get(group_field)
            if group_value not in groups:
                groups[group_value] = []
            groups[group_value].append(node)
        
        # Apply aggregation to each group
        results = []
        
        for group_value, group_nodes in groups.items():
            result = {group_field: group_value}
            
            # Check for aggregation in return clause
            agg_match = re.search(r'(COUNT|SUM|AVG|MIN|MAX)\s*\((.+?)\)', return_clause, re.IGNORECASE)
            
            if agg_match:
                agg_func_name = agg_match.group(1).upper()
                agg_field = agg_match.group(2).strip()
                
                # Extract field name
                if '.' in agg_field:
                    field_name = agg_field.split('.', 1)[1]
                else:
                    field_name = agg_field
                
                # Get aggregation function
                agg_func = self.aggregations.get(agg_func_name)
                
                if not agg_func:
                    # Unknown aggregation, skip
                    continue
                
                if agg_func_name == 'COUNT':
                    result['count'] = agg_func(group_nodes)
                else:
                    values = [node.get(field_name) for node in group_nodes if node.get(field_name) is not None]
                    result[f"{agg_func_name.lower()}_{field_name}"] = agg_func(values) if values else None
            
            results.append(result)
        
        return results
    
    def _execute_traverse_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute a TRAVERSE query
        
        Example: TRAVERSE FROM node_id FOLLOW [FROM, TO] DEPTH 2 RETURN nodes
        """
        # Extract components
        from_match = re.search(r'FROM\s+(\S+)', query, re.IGNORECASE)
        follow_match = re.search(r'FOLLOW\s+\[([^\]]+)\]', query, re.IGNORECASE)
        depth_match = re.search(r'DEPTH\s+(\d+)', query, re.IGNORECASE)
        
        start_node = from_match.group(1) if from_match else params.get('start_node')
        rel_types = [rt.strip() for rt in follow_match.group(1).split(',')] if follow_match else []
        depth = int(depth_match.group(1)) if depth_match else DEFAULT_TRAVERSAL_DEPTH
        
        if not start_node:
            logger.error("TRAVERSE query missing FROM clause or start_node parameter")
            return []
        
        if not self.graph.has_node(start_node):
            logger.warning(f"Start node '{start_node}' not found in graph")
            return []
        
        logger.debug(f"Traversing from {start_node}, depth={depth}, rel_types={rel_types}")
        
        # BFS traversal
        visited = set()
        results = []
        queue = [(start_node, 0)]
        
        while queue:
            current_node, current_depth = queue.pop(0)
            
            if current_node in visited or current_depth > depth:
                continue
            
            visited.add(current_node)
            node_data = dict(self.graph.nodes[current_node])
            results.append({'node_id': current_node, **node_data})
            
            if current_depth < depth:
                # Get neighbors
                for neighbor in self.graph.successors(current_node):
                    edges = self.graph.get_edge_data(current_node, neighbor)
                    for edge_data in edges.values():
                        if not rel_types or edge_data.get('rel_type') in rel_types:
                            queue.append((neighbor, current_depth + 1))
        
        logger.debug(f"Traversal found {len(results)} nodes")
        return results
    
    def _execute_path_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute a PATH query
        
        Example: PATH FROM node1 TO node2 MAX_DEPTH 5 RETURN path
        """
        from_match = re.search(r'FROM\s+(\S+)', query, re.IGNORECASE)
        to_match = re.search(r'TO\s+(\S+)', query, re.IGNORECASE)
        depth_match = re.search(r'MAX_DEPTH\s+(\d+)', query, re.IGNORECASE)
        
        from_node = from_match.group(1) if from_match else params.get('from_node')
        to_node = to_match.group(1) if to_match else params.get('to_node')
        max_depth = int(depth_match.group(1)) if depth_match else DEFAULT_MAX_DEPTH
        
        if not from_node or not to_node:
            logger.error("PATH query missing FROM or TO clause")
            return []
        
        if not self.graph.has_node(from_node):
            logger.warning(f"Source node '{from_node}' not found in graph")
            return []
        
        if not self.graph.has_node(to_node):
            logger.warning(f"Target node '{to_node}' not found in graph")
            return []
        
        logger.debug(f"Finding path from {from_node} to {to_node}, max_depth={max_depth}")
        
        try:
            path = nx.shortest_path(self.graph, from_node, to_node)
            if len(path) <= max_depth + 1:
                logger.debug(f"Found path of length {len(path) - 1}")
                return [{'path': path, 'length': len(path) - 1}]
            logger.debug(f"Path too long: {len(path) - 1} > {max_depth}")
            return []
        except nx.NetworkXNoPath:
            logger.debug(f"No path found between {from_node} and {to_node}")
            return []
        except nx.NodeNotFound as e:
            logger.error(f"Node not found: {e}")
            return []
    
    def _execute_simple_query(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fallback: simple parameter-based query"""
        logger.debug(f"Executing simple query with params: {params}")
        results = []
        
        # Filter by node_type if provided
        if 'node_type' in params:
            node_type = params['node_type']
            for node_id, data in self.graph.nodes(data=True):
                if data.get('node_type') == node_type:
                    results.append({'node_id': node_id, **data})
        else:
            # No node_type filter, get all nodes
            for node_id, data in self.graph.nodes(data=True):
                results.append({'node_id': node_id, **data})
        
        # Filter by other properties
        for key, value in params.items():
            if key == 'node_type':
                continue
            
            results = [r for r in results if r.get(key) == value]
        
        logger.debug(f"Simple query returned {len(results)} results")
        return results
