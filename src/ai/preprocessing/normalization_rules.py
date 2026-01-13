# --- GLOBAL RULES ---
# Applies regardless of domain context
GLOBAL_TYPOS = {
    'wit': 'with',
    'teh': 'the',
    'adn': 'and',
    'taht': 'that',
    'recieve': 'receive',
    'seperate': 'separate',
    'occured': 'occurred',
    'tomorow': 'tomorrow',
    'tommorow': 'tomorrow',
    'schedul': 'schedule',
    'calender': 'calendar',
}

# --- DOMAIN-SPECIFIC RULES ---
# Only applied when the orchestrator hints at a specific domain
DOMAIN_RULES = {
    'calendar': {
        'book': 'schedule',
        'meeing': 'meeting',
        'calender': 'calendar',
        'appoitment': 'appointment',
        'nex week': 'next week',
        'nex': 'next',
    },
    'tasks': {
        'taks': 'task',
        'takss': 'tasks',
        'set': 'create',
        'make': 'create',
        'add': 'create',
    },
    'email': {
        'emial': 'email',
        'replay': 'reply',
        'foward': 'forward',
        'find': 'search',
        'look': 'search',
    }
}

# --- DIALECT TRANSFORMATIONS ---
# Regex patterns for handling informal or regional English
DIALECT_TRANSFORMATIONS = {
    'indian_english': {
        r'\bdone\s+with\b': 'completed',
        r'\bdo\s+the\s+needful\b': 'handle this',
        r'\bkindly\s+do\b': 'please',
    },
    'singlish': {
        r'\blah\b': '',
        r'\blor\b': '',
        r'\bcan\s+anot\b': 'can',
        r'\balready\b': '',
    },
    'informal': {
        r'\bgonna\b': 'going to',
        r'\bwanna\b': 'want to',
        r'\bgotta\b': 'got to',
        r'\blemme\b': 'let me',
        r'\bcuz\b': 'because',
        r'\bthru\b': 'through',
    }
}

