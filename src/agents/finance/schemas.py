
"""
LLM Extraction Schemas for Finance Agent
"""

AGGREGATION_SCHEMA = {
    "merchant": "Name of the store or company (e.g., 'Spotify', 'Chipotle'). Null if not specific.",
    "category": "Broad category like 'food', 'retail', 'gas', 'travel'. Null if not specific.",
    "days": "Number of days back to look. Default to 30 if not specified.",
    "start_date": "Specific start date in YYYY-MM-DD. Priority over 'days' if mentioned.",
    "end_date": "Specific end date in YYYY-MM-DD. Usually today if not specified."
}

LOOKUP_SCHEMA = {
    "merchant": "Merchant name to look up original purchase."
}
