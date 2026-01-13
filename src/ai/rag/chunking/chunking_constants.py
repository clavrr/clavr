import re

# Email Cleaning Regex Patterns
SENT_FROM_PATTERN = re.compile(r'Sent from my (iPhone|iPad|Android|Mobile).*', flags=re.IGNORECASE)
OUTLOOK_FOOTER_PATTERN = re.compile(r'Get Outlook for (iOS|Android).*', flags=re.IGNORECASE)
SIGNATURE_DELIMITER_PATTERN = re.compile(r'(\n--\s*\n.*)|(\n_{3,}\s*\n.*)|(\n-{3,}\s*\n.*)', flags=re.DOTALL)
EXCESSIVE_NEWLINES_PATTERN = re.compile(r'\n{3,}')
WHITESPACE_PATTERN = re.compile(r'[ \t]+')

# Disclaimer Keywords
DISCLAIMER_KEYWORDS = {
    'confidential', 'intended recipient', 'disclaimer', 
    'privileged', 'unauthorized', 'dissemination'
}

# Limits
MAX_METADATA_LENGTH = 500
DEFAULT_CHUNK_SIZE_TOKENS = 512
DEFAULT_CHILD_CHUNK_SIZE_TOKENS = 256
DEFAULT_OVERLAP_TOKENS = 50
