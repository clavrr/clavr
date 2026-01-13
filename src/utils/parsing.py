"""
Parsing Utilities - Helper functions for extracting structured data from raw text.
"""
import re
from typing import List, Dict, Any

def parse_gmail_tool_output(gmail_output: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Parse the raw string output from the GmailTool search action into structured email dicts.
    
    Args:
        gmail_output: Raw string from email_tool._run(action="search", ...)
        limit: Max number of results to return
        
    Returns:
        List of dictionaries containing subject, sender, date, and content.
    """
    # Find all [EMAIL] blocks
    email_blocks = re.findall(r'\[EMAIL\]\s*(.*?)(?=\[EMAIL\]|$)', gmail_output, re.DOTALL)
    
    results = []
    for email_text in email_blocks[:limit]:
        subject_match = re.search(r'Subject:\s*(.+?)(?:\n|$)', email_text)
        sender_match = re.search(r'From:\s*(.+?)(?:\n|$)', email_text)
        date_match = re.search(r'Date:\s*(.+?)(?:\n|$)', email_text)
        
        results.append({
            'content': email_text[:500],
            'metadata': {
                'subject': subject_match.group(1) if subject_match else 'No subject',
                'sender': sender_match.group(1) if sender_match else 'Unknown',
                'date': date_match.group(1) if date_match else 'Unknown date'
            },
            'distance': 0.0
        })
    return results
