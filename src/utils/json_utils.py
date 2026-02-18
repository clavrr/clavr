"""
JSON Utilities - Robust parsing and repair functions for LLM outputs.
"""
import json
import re
import logging
from typing import Any, Dict, Optional, List

logger = logging.getLogger(__name__)

def repair_json(text: str) -> Dict[str, Any]:
    """
    Attempt to parse JSON from text, repairing common LLM errors like 
    truncation, missing closing braces, or markdown blocks.
    
    Args:
        text: Raw text potentially containing JSON
        
    Returns:
        Parsed dictionary. Returns {"insights": []} or {} on failure 
        to ensure downstream code doesn't crash.
    """
    if not text:
        return {}

    # 1. Clean markdown blocks
    clean_text = text.strip()
    clean_text = re.sub(r'^```json\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'^```\s*', '', clean_text, flags=re.MULTILINE)
    clean_text = re.sub(r'```$', '', clean_text, flags=re.MULTILINE)
    clean_text = clean_text.strip()

    # 2. Find the start of the JSON object or array
    start_index = clean_text.find('{')
    array_start = clean_text.find('[')
    
    if start_index == -1 or (array_start != -1 and array_start < start_index):
        start_index = array_start
        
    if start_index == -1:
        return {}
        
    json_str = clean_text[start_index:]

    # 3. Try standard parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 4. Attempt repair for truncated strings or missing braces
    # Remove any trailing junk that's clearly not JSON
    repaired = json_str.strip()
    
    # Simple search for the last valid-looking character
    # (Optional: we could try to find the last closing brace and trim anything after)
    
    # Check for unterminated string
    # A bit more sophisticated: find if the last quote is un-escaped
    if repaired.count('"') % 2 != 0:
        repaired += '"'
        
    # Balance braces/brackets from inside out
    # We should iterate through the string and track stack
    stack = []
    in_string = False
    escaped = False
    
    for char in repaired:
        if escaped:
            escaped = False
            continue
        if char == '\\':
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if not in_string:
            if char == '{' or char == '[':
                stack.append(char)
            elif char == '}':
                if stack and stack[-1] == '{':
                    stack.pop()
            elif char == ']':
                if stack and stack[-1] == '[':
                    stack.pop()
    
    # Close remaining items on stack in reverse order
    while stack:
        opener = stack.pop()
        repaired += '}' if opener == '{' else ']'

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to repair JSON: {e}. Repaired attempt: {repaired[:100]}...")
        
        # 5. Last resort: very aggressive partial extraction for list of insights
        # If we see things like "content": "...", we can try to extract them manually
        # but for now, we return empty structure to prevent crashes.
        if '"insights"' in text:
            return {"insights": []}
        return {}

def extract_json_objects(text: str) -> List[Dict[str, Any]]:
    """Extract all JSON objects found in a text string."""
    results = []
    # Find potential JSON start/end pairs
    pattern = r'\{(?:[^{}]|(?R))*\}'
    # Since Python regex doesn't support recursion (?R) easily with 're', 
    # we use a simpler approach of finding all { } pairs and trying to parse.
    
    # Extract blocks that look like JSON
    potential_blocks = re.findall(r'\{.*?\}', text, re.DOTALL)
    for block in potential_blocks:
        try:
            results.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    return results
