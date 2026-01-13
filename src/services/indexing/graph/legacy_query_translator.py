"""
Legacy Query Translator (Cypher to AQL)

Translates common legacy query patterns (Cypher) to ArangoDB AQL format.
This enables components written with legacy-style queries to work
with the ArangoDB backend.

Supported patterns:
- MATCH (n:Label {prop: $param})
- MATCH (n)-[:REL_TYPE]->(m)
- WHERE conditions
- RETURN projections
- ORDER BY, LIMIT
"""
import re
from typing import Dict, Any, List, Optional, Tuple

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class LegacyQueryTranslator:
    """
    Translates legacy graph queries to ArangoDB AQL.
    
    Handles common patterns used in the insights services.
    """
    
    def __init__(self):
        # Cache commonly used node type to collection mappings
        self.collection_map = {
            "Insight": "Insight",
            "Person": "Person",
            "Contact": "Contact",
            "Email": "Email",
            "Message": "Message",
            "CalendarEvent": "CalendarEvent",
            "Task": "Task",
            "Topic": "Topic",
            "Episode": "Episode",
            "TimeBlock": "TimeBlock",
            "Document": "Document",
            "User": "User",
            "InsightFeedback": "InsightFeedback",
            "ActionItem": "ActionItem",
            "Summary": "Summary",
        }
    
    def translate(self, legacy_query: str, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Translate a legacy query to AQL.
        
        Args:
            legacy_query: Legacy query string (Cypher-style)
            params: Query parameters
            
        Returns:
            Tuple of (aql_query, transformed_params)
        """
        # Clean up the query
        query = legacy_query.strip()
        
        # Check if it's already AQL (starts with FOR)
        if query.upper().startswith("FOR "):
            return query, params
        
        # Try to translate
        try:
            aql, new_params = self._translate_match_query(query, params)
            logger.debug(f"[QueryTranslator] Translated legacy query -> {aql[:50]}...")
            return aql, new_params
        except Exception as e:
            logger.warning(f"[QueryTranslator] Translation failed, returning original: {e}")
            # Return a safe fallback that won't crash
            return self._fallback_query(query, params), params
    
    def _translate_match_query(self, query: str, params: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Translate a MATCH ... RETURN query."""
        
        # Parse the main components
        lines = query.strip().split('\n')
        cleaned_lines = [line.strip() for line in lines if line.strip()]
        full_query = ' '.join(cleaned_lines)
        
        # Extract MATCH, WHERE, RETURN, ORDER BY, LIMIT clauses
        match_pattern = r'MATCH\s+(.+?)(?=\s+(?:WHERE|RETURN|ORDER|LIMIT|$))'
        where_pattern = r'WHERE\s+(.+?)(?=\s+(?:RETURN|ORDER|LIMIT|$))'
        return_pattern = r'RETURN\s+(.+?)(?=\s+(?:ORDER|LIMIT|$))'
        order_pattern = r'ORDER\s+BY\s+(.+?)(?=\s+(?:LIMIT|$))'
        limit_pattern = r'LIMIT\s+(\$?\w+|\d+)'
        
        match_clause = re.search(match_pattern, full_query, re.IGNORECASE | re.DOTALL)
        where_clause = re.search(where_pattern, full_query, re.IGNORECASE | re.DOTALL)
        return_clause = re.search(return_pattern, full_query, re.IGNORECASE | re.DOTALL)
        order_clause = re.search(order_pattern, full_query, re.IGNORECASE | re.DOTALL)
        limit_clause = re.search(limit_pattern, full_query, re.IGNORECASE)
        
        if not match_clause:
            raise ValueError("No MATCH clause found")
        
        match_content = match_clause.group(1).strip()
        
        # Parse the MATCH pattern to extract node/relationship info
        aql_parts = []
        
        # Support multiple node matches separated by comma: (n:Label), (m:Label)
        match_parts = [p.strip() for p in match_content.split(',')]
        
        for part in match_parts:
            # Simple node match: (n:Label {prop: $val})
            simple_node = re.match(r'\((\w+):(\w+)(?:\s*\{([^}]+)\})?\)', part)
            
            if simple_node:
                var_name = simple_node.group(1)
                label = simple_node.group(2)
                props = simple_node.group(3)
                
                collection = self.collection_map.get(label, label)
                aql_parts.append(f"FOR {var_name} IN {collection}")
                
                # Add property filters
                if props:
                    filters = self._parse_property_filters(props, var_name, params)
                    if filters:
                        aql_parts.append(f"FILTER {filters}")
                continue
            
            # Relationship match: (n)-[:REL]->(m) or (n:Label)-[:REL]->(m)
            rel_match = re.match(
                r'\((\w+)(?::(\w+))?\)\s*-\[(?::([A-Z_|]+))?\]->\s*\((\w+)(?::(\w+))?\)',
                part
            )
            
            if rel_match:
                from_var = rel_match.group(1)
                from_label = rel_match.group(2)
                rel_types = rel_match.group(3)
                to_var = rel_match.group(4)
                to_label = rel_match.group(5)
                
                # Build traversal query
                if from_label:
                    from_collection = self.collection_map.get(from_label, from_label)
                    aql_parts.append(f"FOR {from_var} IN {from_collection}")
                
                if rel_types:
                    edge_collections = rel_types.split('|')
                    edge_str = ', '.join(edge_collections)
                    aql_parts.append(
                        f"FOR {to_var} IN 1..1 OUTBOUND {from_var} {edge_str}"
                    )
                else:
                    # Generic edge traversal
                    if to_label:
                        to_collection = self.collection_map.get(to_label, to_label)
                        aql_parts.append(f"FOR {to_var} IN {to_collection}")
        
        # Add WHERE clause
        if where_clause:
            where_content = where_clause.group(1).strip()
            aql_filter = self._translate_where(where_content, params)
            if aql_filter:
                aql_parts.append(f"FILTER {aql_filter}")
        
        # Add RETURN clause
        if return_clause:
            return_content = return_clause.group(1).strip()
            aql_return = self._translate_return(return_content)
            aql_parts.append(f"RETURN {aql_return}")
        else:
            # Default return all matched vars
            aql_parts.append("RETURN { result: true }")
        
        # Add ORDER BY
        if order_clause:
            order_content = order_clause.group(1).strip()
            aql_parts.insert(-1, f"SORT {order_content}")
        
        # Add LIMIT
        if limit_clause:
            limit_val = limit_clause.group(1)
            aql_parts.insert(-1, f"LIMIT {self._translate_param(limit_val)}")
        
        return '\n'.join(aql_parts), params
    
    def _parse_property_filters(self, props: str, var_name: str, params: Dict[str, Any]) -> str:
        """Parse property filters like {id: $id, name: $name}."""
        filters = []
        
        # Parse key: value pairs
        pairs = re.findall(r'(\w+)\s*:\s*(\$?\w+|"[^"]*"|\'[^\']*\')', props)
        
        for key, value in pairs:
            if value.startswith('$'):
                param_name = value[1:]
                filters.append(f"{var_name}.{key} == @{param_name}")
            elif value.startswith('"') or value.startswith("'"):
                filters.append(f"{var_name}.{key} == {value}")
            else:
                filters.append(f"{var_name}.{key} == {value}")
        
        return ' AND '.join(filters)
    
    def _translate_where(self, where_content: str, params: Dict[str, Any]) -> str:
        """Translate WHERE clause conditions."""
        # Replace legacy parameter references with AQL
        result = where_content
        
        # Replace $param with @param
        result = re.sub(r'\$(\w+)', r'@\1', result)
        
        # Replace IS NULL with == null
        result = re.sub(r'\bIS\s+NULL\b', '== null', result, flags=re.IGNORECASE)
        
        # Replace IS NOT NULL with != null
        result = re.sub(r'\bIS\s+NOT\s+NULL\b', '!= null', result, flags=re.IGNORECASE)
        
        # Handle legacy labels in WHERE: (n:Label) -> n.node_type == 'Label'
        result = re.sub(r'\((\w+):(\w+)\)', r"\1.node_type == '\2'", result)
        # Also handle n:Label without parentheses
        result = re.sub(r'\b(\w+):(\w+)\b', r"\1.node_type == '\2'", result)
        
        # Handle toLower(x) -> LOWER(x)
        result = re.sub(r'\btoLower\s*\(', 'LOWER(', result, flags=re.IGNORECASE)
        
        # Handle property access on variables
        result = re.sub(r'(\w+)\.(\w+)\s+IN\s+\[([^\]]+)\]', r'\1.\2 IN [\3]', result)
        
        return result
    
    def _translate_return(self, return_content: str) -> str:
        """Translate RETURN clause."""
        # Handle "x as y" aliases
        parts = []
        
        # Split by comma, handling function calls
        items = self._split_return_items(return_content)
        
        for item in items:
            item = item.strip()
            
            # Handle "expr as alias" pattern
            as_match = re.match(r'(.+?)\s+as\s+(\w+)', item, re.IGNORECASE)
            if as_match:
                expr = as_match.group(1).strip()
                alias = as_match.group(2)
                
                # Translate expressions
                expr = self._translate_expr(expr)
                parts.append(f'"{alias}": {expr}')
            else:
                # Just an expression without alias
                expr = self._translate_expr(item)
                parts.append(expr)
        
        if len(parts) == 1 and not parts[0].startswith('"'):
            return parts[0]
        
        return '{ ' + ', '.join(parts) + ' }'
    
    def _split_return_items(self, content: str) -> List[str]:
        """Split return items by comma, respecting parentheses."""
        items = []
        current = []
        depth = 0
        
        for char in content:
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif char == ',' and depth == 0:
                items.append(''.join(current).strip())
                current = []
                continue
            current.append(char)
        
        if current:
            items.append(''.join(current).strip())
        
        return items
    
    def _translate_expr(self, expr: str) -> str:
        """Translate a legacy expression to AQL."""
        # Replace $param with @param
        expr = re.sub(r'\$(\w+)', r'@\1', expr)
        
        # Handle toLower(x) -> LOWER(x)
        expr = re.sub(r'\btoLower\s*\(([^)]+)\)', r'LOWER(\1)', expr, flags=re.IGNORECASE)
        
        # Handle count(x) -> LENGTH(x) or COUNT
        expr = re.sub(r'\bcount\s*\(([^)]+)\)', r'LENGTH(\1)', expr, flags=re.IGNORECASE)

        
        # Handle collect() -> (array expression)
        expr = re.sub(r'\bcollect\s*\(([^)]+)\)', r'\1', expr, flags=re.IGNORECASE)
        
        # Handle COALESCE(a, b) -> NOT_NULL(a, b) - ArangoDB equivalent
        expr = re.sub(r'\bCOALESCE\s*\(', r'NOT_NULL(', expr, flags=re.IGNORECASE)
        
        # Handle labels(n) -> n.node_type 
        expr = re.sub(r'\blabels\s*\((\w+)\)', r'[\1.node_type]', expr, flags=re.IGNORECASE)
        
        return expr
    
    def _translate_param(self, param: str) -> str:
        """Translate parameter reference."""
        if param.startswith('$'):
            return f"@{param[1:]}"
        return param
    
    def _fallback_query(self, query: str, params: Dict[str, Any]) -> str:
        """Generate a safe fallback query that returns empty results."""
        return "RETURN []"


# Global translator instance
_translator: Optional[LegacyQueryTranslator] = None


def get_translator() -> LegacyQueryTranslator:
    """Get or create the global translator instance."""
    global _translator
    if _translator is None:
        _translator = LegacyQueryTranslator()
    return _translator


def translate_legacy_query(query: str, params: Dict[str, Any] = None) -> Tuple[str, Dict[str, Any]]:
    """
    Convenience function to translate legacy queries to AQL.
    
    Args:
        query: Legacy query string
        params: Query parameters
        
    Returns:
        Tuple of (aql_query, transformed_params)
    """
    params = params or {}
    return get_translator().translate(query, params)
