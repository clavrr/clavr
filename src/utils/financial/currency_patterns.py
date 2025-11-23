"""
Currency Pattern Constants

Centralized currency extraction patterns to avoid duplication
across receipt_parser and financial_aggregator.
"""
from typing import List


# ============================================
# CURRENCY VALIDATION CONSTANTS
# ============================================

class CurrencyValidationConfig:
    """Configuration constants for currency amount validation"""
    
    # Minimum valid amount (exclude amounts less than $0.01)
    MIN_VALID_AMOUNT = 0.01
    
    # Maximum valid amount (exclude amounts greater than $100,000 - likely errors)
    MAX_VALID_AMOUNT = 100000.0
    
    # Subscription amount range (common subscription prices: $4.99, $9.99, $14.99, $19.99, etc.)
    MIN_SUBSCRIPTION_AMOUNT = 4.99
    MAX_SUBSCRIPTION_AMOUNT = 50.00
    
    # Item name length limit (for receipt items)
    MAX_ITEM_NAME_LENGTH = 100


# ============================================
# CURRENCY PATTERN DEFINITIONS
# ============================================

# Base currency patterns (common across all use cases)
BASE_CURRENCY_PATTERNS: List[str] = [
    r'\$(\d+\.?\d*)',  # $123.45
    r'USD\s*(\d+\.?\d*)',  # USD 123.45
    r'(\d+\.?\d*)\s*USD',  # 123.45 USD
    r'(\d+\.?\d*)\s*dollars?',  # 123.45 dollars
]

# Common payment-related patterns
PAYMENT_PATTERNS: List[str] = [
    r'Total[:\s]*\$?(\d+\.?\d*)',  # Total: $123.45
    r'Amount[:\s]*\$?(\d+\.?\d*)',  # Amount: $123.45
    r'Paid[:\s]*\$?(\d+\.?\d*)',  # Paid: $123.45
    r'Charge[:\s]*\$?(\d+\.?\d*)',  # Charge: $123.45
    r'Subtotal[:\s]*\$?(\d+\.?\d*)',  # Subtotal: $123.45
]

# Subscription-specific patterns
SUBSCRIPTION_PATTERNS: List[str] = [
    r'Price[:\s]*\$?(\d+\.?\d*)',  # Price: $123.45
    r'Cost[:\s]*\$?(\d+\.?\d*)',  # Cost: $123.45
    r'Payment[:\s]*of\s*\$?(\d+\.?\d*)',  # Payment of $123.45
    r'Billed[:\s]*\$?(\d+\.?\d*)',  # Billed: $123.45
    r'Subscription[:\s]*\$?(\d+\.?\d*)',  # Subscription: $123.45
    r'Plan[:\s]*\$?(\d+\.?\d*)',  # Plan: $123.45
    r'Monthly[:\s]*\$?(\d+\.?\d*)',  # Monthly: $123.45
    r'Yearly[:\s]*\$?(\d+\.?\d*)',  # Yearly: $123.45
    r'(\d+\.?\d*)\s*per\s+month',  # 9.99 per month
    r'(\d+\.?\d*)\s*per\s+year',  # 99.99 per year
]

# Combined patterns for different use cases
CURRENCY_PATTERNS: List[str] = BASE_CURRENCY_PATTERNS + PAYMENT_PATTERNS

ENHANCED_CURRENCY_PATTERNS: List[str] = (
    BASE_CURRENCY_PATTERNS + 
    PAYMENT_PATTERNS + 
    SUBSCRIPTION_PATTERNS
)


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Validation constants
    'CurrencyValidationConfig',
    # Pattern lists
    'BASE_CURRENCY_PATTERNS',
    'PAYMENT_PATTERNS',
    'SUBSCRIPTION_PATTERNS',
    'CURRENCY_PATTERNS',
    'ENHANCED_CURRENCY_PATTERNS',
]

