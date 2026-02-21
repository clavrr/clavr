"""
Tool Converter Utility

Handles conversion of LangChain tools (Pydantic schemas) into JSON schemas
compatible with Voice providers (ElevenLabs, Gemini).
"""
import json
from typing import List, Dict, Any, Type
from langchain.tools import BaseTool
from pydantic import BaseModel
import re

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

def _pydantic_to_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    """
    Convert a Pydantic model to a JSON schema for tool definitions.
    Handles Pydantic v2's anyOf for Optional fields and refines output
    for compatibility with Gemini/ElevenLabs function calling APIs.
    """
    try:
        # Get standard JSON schema
        schema = model.model_json_schema()
        
        # Extract properties and required fields
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        
        # Clean up parameter definitions
        clean_props = {}
        for prop_name, prop_def in properties.items():
            # Resolve type — handle Pydantic v2 Optional fields which emit anyOf
            prop_type = prop_def.get("type")
            
            if prop_type is None and "anyOf" in prop_def:
                # Pydantic v2 emits: {"anyOf": [{"type": "string"}, {"type": "null"}]}
                # Extract the non-null type
                for variant in prop_def["anyOf"]:
                    if variant.get("type") != "null":
                        prop_type = variant.get("type", "string")
                        break
                if prop_type is None:
                    prop_type = "string"  # Fallback
            
            if prop_type is None:
                prop_type = "string"  # Ultimate fallback
            
            clean_def = {"type": prop_type}
            
            if "description" in prop_def:
                clean_def["description"] = prop_def["description"]
                
            if "enum" in prop_def:
                clean_def["enum"] = prop_def["enum"]
                
            if "default" in prop_def:
                # Include default as part of description for APIs that don't support default field
                clean_def["description"] = f"{clean_def.get('description', '')} (Default: {prop_def['default']})".strip()
            
            # Handle array/object types
            if prop_type == "array":
               clean_def["items"] = prop_def.get("items", {})
            
            # Mark nullable for Optional fields (Gemini supports this)
            if "anyOf" in prop_def:
                has_null = any(v.get("type") == "null" for v in prop_def["anyOf"])
                if has_null:
                    clean_def["nullable"] = True
            
            clean_props[prop_name] = clean_def

        result = {
            "type": "object",
            "properties": clean_props,
            "required": required
        }
        
        logger.debug(f"[ToolConverter] Schema for {model.__name__}: {len(clean_props)} properties, {len(required)} required")
        return result
    except Exception as e:
        logger.error(f"Error converting Pydantic schema: {e}", exc_info=True)
        return {"type": "object", "properties": {}}

def convert_to_elevenlabs_tools(tools: List[BaseTool]) -> List[Dict[str, Any]]:
    """
    Convert LangChain tools to ElevenLabs 'client_tools' format.
    
    Structure:
    [
      {
        "name": "tool_name",
        "description": "tool_description",
        "parameters": { ... JSON Schema ... }
      }
    ]
    """
    elevenlabs_tools = []
    
    for tool in tools:
        try:
            tool_def = {
                "type": "client", # ElevenLabs specific: client-side tool
                "name": tool.name,
                "description": tool.description,
                "parameters": {}
            }
            
            # Extract parameters schema
            if tool.args_schema:
                schema = _pydantic_to_json_schema(tool.args_schema)
                tool_def["parameters"] = schema
            else:
                 # Fallback for tools without explicit args_schema
                 # We infer from _run arguments if possible, or provide generic object
                 tool_def["parameters"] = {
                     "type": "object", 
                     "properties": {
                         "query": {"type": "string", "description": "Query or input for the tool"},
                         "action": {"type": "string", "description": "Action to perform"}
                     }
                 }
            
            # IMPORTANT: ElevenLabs requires 'expects_response' (usually true for client tools)
            tool_def["expects_response"] = True
            
            # Attempt to extend server-side timeout (undocumented but follows API pattern)
            tool_def["timeout_ms"] = 12000
            
            elevenlabs_tools.append(tool_def)
            
        except Exception as e:
            logger.error(f"Failed to convert tool {tool.name} for ElevenLabs: {e}")
            
    return elevenlabs_tools

def convert_to_gemini_tools(tools: List[BaseTool]) -> List[Dict[str, Any]]:
    """
    Convert LangChain tools to Gemini 'function_declarations' format.
    Logs each tool conversion for debugging voice tool registration.
    """
    gemini_tools = []
    
    for tool in tools:
        try:
            # Clean name (must be valid identifier)
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', tool.name)
            
            func_decl = {
                "name": safe_name,
                "description": tool.description,
            }
            
            if tool.args_schema:
                schema = _pydantic_to_json_schema(tool.args_schema)
                func_decl["parameters"] = schema
            else:
                 func_decl["parameters"] = {
                     "type": "object", 
                     "properties": {
                         "query": {"type": "string", "description": "Query text"},
                         "action": {"type": "string", "description": "Action"}
                     }
                 }
            
            gemini_tools.append(func_decl)
            param_count = len(func_decl.get("parameters", {}).get("properties", {}))
            logger.info(f"[ToolConverter] ✓ Converted '{safe_name}' for Gemini ({param_count} params)")
            
        except Exception as e:
            logger.error(f"[ToolConverter] ✗ Failed to convert tool {tool.name} for Gemini: {e}", exc_info=True)
    
    logger.info(f"[ToolConverter] Total Gemini tools: {len(gemini_tools)}/{len(tools)}")
    return gemini_tools
