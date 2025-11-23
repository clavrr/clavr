"""
Receipt and Invoice Parser

Extracts structured financial data from receipts, invoices, and payment confirmations.
Supports various formats and merchants.
"""
import re
from collections import Counter
from typing import Dict, Any, Optional, List
from datetime import datetime

from ..logger import setup_logger
from .currency_patterns import (
    ENHANCED_CURRENCY_PATTERNS,
    CurrencyValidationConfig
)

logger = setup_logger(__name__)


class ReceiptParser:
    """
    Parse receipts and invoices to extract structured financial data.
    
    Extracts:
    - Total amount
    - Merchant/vendor name
    - Transaction date
    - Items/purchases
    - Payment method
    - Category (if detectable)
    """
    
    # Use centralized currency patterns
    CURRENCY_PATTERNS = ENHANCED_CURRENCY_PATTERNS
    
    # Date patterns
    DATE_PATTERNS = [
        r'(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})',  # MM/DD/YYYY or DD/MM/YYYY
        r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s+(\d{4})',
        r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})',
    ]
    
    # Common merchant patterns (from subject, sender, or content)
    # Order matters - more specific merchants first
    MERCHANT_KEYWORDS = {
        'google one': ['google one', 'googleone'],
        'google play': ['google play', 'googleplay'],
        'google cloud': ['google cloud'],
        'google': ['google'],
        'spotify': ['spotify'],
        'amazon': ['amazon', 'amzn'],
        'chipotle': ['chipotle'],
        'starbucks': ['starbucks', 'sbux'],
        'uber': ['uber', 'uber eats'],
        'lyft': ['lyft'],
        'doordash': ['doordash'],
        'grubhub': ['grubhub'],
        'apple': ['apple', 'app store', 'itunes'],
        'netflix': ['netflix'],
        'paypal': ['paypal'],
        'stripe': ['stripe'],
    }
    
    def parse(self, subject: str, content: str, sender: str = '', 
              attachment_text: str = '') -> Optional[Dict[str, Any]]:
        """
        Parse receipt/invoice from email content and attachments.
        
        Args:
            subject: Email subject line
            content: Email body content
            sender: Email sender
            attachment_text: Extracted text from attachments (receipts/invoices)
            
        Returns:
            Dictionary with parsed financial data or None if not a receipt/invoice
        """
        # Combine all text sources
        full_text = f"{subject} {content} {attachment_text}".lower()
        
        # Check if this looks like a receipt/invoice/payment email
        receipt_indicators = [
            'receipt', 'invoice', 'payment', 'transaction', 'order confirmation',
            'purchase', 'charge', 'billing', 'statement', 'paid', 'total',
            'amount', 'subtotal', 'tax', 'tip', 'subscription', 'renewal',
            'billed', 'charged', 'processed', 'declined', 'failed', 'successful'
        ]
        
        # Also check sender domain for payment-related emails
        sender_lower = sender.lower()
        payment_domains = ['spotify', 'google', 'apple', 'netflix', 'amazon', 'paypal', 
                          'stripe', 'chipotle', 'starbucks', 'uber', 'lyft']
        
        is_payment_email = any(domain in sender_lower for domain in payment_domains) and \
                          any(indicator in full_text for indicator in ['payment', 'subscription', 'charge', 'billed'])
        
        if not any(indicator in full_text for indicator in receipt_indicators) and not is_payment_email:
            return None
        
        try:
            # Extract amount
            amount = self._extract_amount(full_text)
            
            # Extract merchant
            merchant = self._extract_merchant(subject, sender, full_text)
            
            # Extract date
            transaction_date = self._extract_date(full_text, subject)
            
            # Extract items (if available)
            items = self._extract_items(attachment_text or content)
            
            # Determine category
            category = self._determine_category(merchant, full_text)
            
            # Extract payment method
            payment_method = self._extract_payment_method(full_text)
            
            if amount is None:
                return None  # Can't be a valid receipt without amount
            
            return {
                'amount': amount,
                'merchant': merchant,
                'date': transaction_date,
                'items': items,
                'category': category,
                'payment_method': payment_method,
                'is_receipt': True
            }
            
        except Exception as e:
            logger.debug(f"Failed to parse receipt: {e}")
            return None
    
    def _extract_amount(self, text: str) -> Optional[float]:
        """Extract total amount from text."""
        amounts = []
        
        # Use centralized currency patterns
        # Try all currency patterns
        for pattern in self.CURRENCY_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                try:
                    amount = float(match)
                    amounts.append(amount)
                except ValueError:
                    continue
        
        if not amounts:
            return None
        
        # Filter out very small amounts (< $0.01) and very large amounts (> $100,000) which are likely errors
        valid_amounts = [
            a for a in amounts 
            if CurrencyValidationConfig.MIN_VALID_AMOUNT <= a <= CurrencyValidationConfig.MAX_VALID_AMOUNT
        ]
        
        if not valid_amounts:
            return None
        
        # For subscription/payment emails, prefer amounts in common subscription ranges
        # Common subscription prices: $4.99, $9.99, $14.99, $19.99, etc.
        subscription_amounts = [
            a for a in valid_amounts 
            if CurrencyValidationConfig.MIN_SUBSCRIPTION_AMOUNT <= a <= CurrencyValidationConfig.MAX_SUBSCRIPTION_AMOUNT
        ]
        if subscription_amounts:
            # Return the most common subscription amount (often repeated)
            amount_counts = Counter(subscription_amounts)
            most_common = amount_counts.most_common(1)[0][0]
            return most_common
        
        # Return the largest amount (likely the total)
        return max(valid_amounts)
    
    def _extract_merchant(self, subject: str, sender: str, text: str) -> Optional[str]:
        """Extract merchant/vendor name."""
        # Sort merchants by specificity (longer/more specific first)
        sorted_merchants = sorted(self.MERCHANT_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True)
        
        # Check sender name first (e.g., "Google One <email@domain.com>")
        if '<' in sender:
            sender_name = sender.split('<')[0].strip().lower()
            for merchant, keywords in sorted_merchants:
                if any(kw in sender_name for kw in keywords):
                    return merchant.title()
        
        # Check subject for merchant names (most reliable)
        subject_lower = subject.lower()
        for merchant, keywords in sorted_merchants:
            if any(kw in subject_lower for kw in keywords):
                return merchant.title()
        
        # Check sender domain
        if '@' in sender:
            domain = sender.split('@')[1].lower()
            # Remove common email domains
            if domain not in ['gmail.com', 'yahoo.com', 'outlook.com', 'hotmail.com', 'icloud.com']:
                # Check domain against merchant keywords
                domain_str = domain.replace('.com', '').replace('.net', '').replace('.org', '')
                for merchant, keywords in sorted_merchants:
                    if any(kw in domain_str for kw in keywords):
                        return merchant.title()
                
                # Extract merchant from domain as fallback
                merchant = domain.split('.')[0]
                if merchant not in ['mail', 'noreply', 'no-reply', 'notifications', 'email', 'support']:
                    # Check against known merchants
                    for known_merchant, keywords in self.MERCHANT_KEYWORDS.items():
                        if merchant in keywords or any(kw in merchant for kw in keywords):
                            return known_merchant.title()
        
        # Check text content (check more specific merchants first)
        text_lower = text.lower()
        for merchant, keywords in sorted_merchants:
            if any(kw in text_lower for kw in keywords):
                return merchant.title()
        
        # Try to extract from "from" or "merchant" fields
        merchant_patterns = [
            r'merchant[:\s]+([A-Za-z\s]+)',
            r'vendor[:\s]+([A-Za-z\s]+)',
            r'from[:\s]+([A-Za-z\s]+)',
        ]
        
        for pattern in merchant_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                merchant = match.group(1).strip()
                if len(merchant) > 2 and len(merchant) < 50:
                    return merchant.title()
        
        return None
    
    def _extract_date(self, text: str, subject: str = '') -> Optional[str]:
        """Extract transaction date."""
        # Try date patterns
        for pattern in self.DATE_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    # Try to parse the first match
                    match = matches[0]
                    if isinstance(match, tuple):
                        # Handle different date formats
                        if len(match) == 3:
                            # Try to parse
                            date_str = '/'.join(match)
                            try:
                                parsed = datetime.strptime(date_str, '%m/%d/%Y')
                                return parsed.isoformat()
                            except:
                                try:
                                    parsed = datetime.strptime(date_str, '%d/%m/%Y')
                                    return parsed.isoformat()
                                except:
                                    pass
                except:
                    continue
        
        return None
    
    def _extract_items(self, text: str) -> List[Dict[str, Any]]:
        """Extract line items from receipt."""
        items = []
        
        # Look for item patterns (simplified)
        # This is a basic implementation - can be enhanced with ML
        lines = text.split('\n')
        for line in lines:
            # Look for lines with amounts (potential items)
            amount_match = re.search(r'\$(\d+\.?\d*)', line)
            if amount_match:
                # Try to extract item name (text before the amount)
                item_text = line[:line.find(amount_match.group(0))].strip()
                if item_text and len(item_text) > 2:
                    try:
                        amount = float(amount_match.group(1))
                        items.append({
                            'name': item_text[:CurrencyValidationConfig.MAX_ITEM_NAME_LENGTH],  # Limit length
                            'amount': amount
                        })
                    except (ValueError, TypeError):
                        continue
        
        return items[:20]  # Limit to 20 items
    
    def _determine_category(self, merchant: Optional[str], text: str) -> Optional[str]:
        """Determine spending category."""
        text_lower = text.lower()
        merchant_lower = merchant.lower() if merchant else ''
        
        # Food/restaurant
        if any(kw in text_lower for kw in ['restaurant', 'food', 'dining', 'meal', 'order', 'delivery']):
            return 'food'
        if any(kw in merchant_lower for kw in ['chipotle', 'starbucks', 'doordash', 'grubhub', 'uber eats']):
            return 'food'
        
        # Transportation
        if any(kw in text_lower for kw in ['uber', 'lyft', 'ride', 'taxi', 'transport']):
            return 'transportation'
        
        # Subscription
        if any(kw in text_lower for kw in ['subscription', 'monthly', 'recurring', 'plan']):
            return 'subscription'
        if any(kw in merchant_lower for kw in ['spotify', 'netflix', 'google one', 'apple']):
            return 'subscription'
        
        # Shopping
        if any(kw in text_lower for kw in ['purchase', 'order', 'shipping', 'delivery']):
            return 'shopping'
        if 'amazon' in merchant_lower:
            return 'shopping'
        
        # Utilities/Bills
        if any(kw in text_lower for kw in ['bill', 'utility', 'electric', 'water', 'gas', 'internet']):
            return 'utilities'
        
        return None
    
    def _extract_payment_method(self, text: str) -> Optional[str]:
        """Extract payment method."""
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in ['credit card', 'visa', 'mastercard', 'amex', 'american express']):
            return 'credit_card'
        if any(kw in text_lower for kw in ['debit card', 'debit']):
            return 'debit_card'
        if 'paypal' in text_lower:
            return 'paypal'
        if 'apple pay' in text_lower:
            return 'apple_pay'
        if 'google pay' in text_lower:
            return 'google_pay'
        
        return None

