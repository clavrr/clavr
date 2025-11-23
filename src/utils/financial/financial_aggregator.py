"""
Financial Query Aggregator

Handles financial queries by aggregating receipt/invoice data from emails.
Supports queries like:
- "How much did I spend on X last month?"
- "Total spending on Chipotle in last 5 days"
- "What did I pay for Google One?"
"""
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from dateutil import parser

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    relativedelta = None

from ..logger import setup_logger
from .currency_patterns import (
    CURRENCY_PATTERNS,
    CurrencyValidationConfig
)

logger = setup_logger(__name__)


class FinancialAggregator:
    """
    Aggregate financial data from email receipts/invoices.
    
    Features:
    - Extract spending amounts from search results
    - Filter by merchant, category, time period
    - Sum totals
    - Provide detailed breakdowns
    """
    
    def aggregate_spending(self, results: List[Dict[str, Any]], 
                          merchant: Optional[str] = None,
                          category: Optional[str] = None,
                          time_period: Optional[str] = None,
                          query: Optional[str] = None) -> Dict[str, Any]:
        """
        Aggregate spending from email search results.
        
        Args:
            results: List of email search results (from RAG)
            merchant: Optional merchant name to filter by
            category: Optional category to filter by
            time_period: Optional time period (e.g., "last month", "last week", "last 5 days", "last 8 months")
            query: Optional original query string (used to extract merchant/time if not provided)
            
        Returns:
            Dictionary with:
            - total: Total amount spent
            - count: Number of transactions
            - transactions: List of transaction details
            - breakdown: Breakdown by merchant/category
        """
        transactions = []
        total = 0.0
        
        # Extract merchant and time period from query if not provided
        if query and not merchant:
            merchant = self._extract_merchant_from_query(query)
        if query and not time_period:
            time_period = self._extract_time_period_from_query(query)
        
        # Parse time period if provided
        start_date = None
        end_date = None
        if time_period:
            start_date, end_date = self._parse_time_period(time_period)
        
        for result in results:
            metadata = result.get('metadata', {})
            content = result.get('content', '')
            
            # Check if this is a receipt
            if not metadata.get('is_receipt'):
                # Try to extract amount from content if not marked as receipt
                amount = self._extract_amount_from_content(content, metadata)
                if amount:
                    metadata['receipt_amount'] = str(amount)
                    metadata['is_receipt'] = True
                else:
                    continue
            
            # Extract receipt data
            amount_str = metadata.get('receipt_amount')
            if not amount_str:
                continue
            
            try:
                amount = float(amount_str)
            except (ValueError, TypeError):
                continue
            
            # Filter by merchant
            if merchant:
                receipt_merchant = metadata.get('receipt_merchant', '').lower()
                sender = metadata.get('sender', '').lower()
                subject = metadata.get('subject', '').lower()
                
                merchant_lower = merchant.lower()
                if (merchant_lower not in receipt_merchant and 
                    merchant_lower not in sender and 
                    merchant_lower not in subject):
                    continue
            
            # Filter by category
            if category:
                receipt_category = metadata.get('receipt_category', '').lower()
                if category.lower() not in receipt_category:
                    continue
            
            # Filter by time period
            if start_date and end_date:
                email_timestamp = metadata.get('timestamp') or metadata.get('receipt_date')
                if email_timestamp:
                    try:
                        email_date = parser.parse(email_timestamp)
                        if not (start_date <= email_date <= end_date):
                            continue
                    except:
                        pass
            
            # Add transaction
            transaction = {
                'amount': amount,
                'merchant': metadata.get('receipt_merchant'),
                'date': metadata.get('timestamp') or metadata.get('receipt_date'),
                'category': metadata.get('receipt_category'),
                'subject': metadata.get('subject'),
                'message_id': metadata.get('message_id')
            }
            
            transactions.append(transaction)
            total += amount
        
        # Create breakdown
        breakdown = self._create_breakdown(transactions)
        
        return {
            'total': round(total, 2),
            'count': len(transactions),
            'transactions': transactions,
            'breakdown': breakdown,
            'merchant_filter': merchant,
            'category_filter': category,
            'time_period': time_period
        }
    
    def _parse_time_period(self, time_period: str) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Parse time period string into start and end dates."""
        time_period_lower = time_period.lower()
        now = datetime.now()
        
        # "last X months" (e.g., "last 8 months")
        months_match = re.search(r'last\s+(\d+)\s+months?', time_period_lower)
        if months_match:
            months = int(months_match.group(1))
            # Use relativedelta for accurate month calculations
            if relativedelta:
                start_date = now - relativedelta(months=months)
                return start_date.replace(hour=0, minute=0, second=0, microsecond=0), \
                       now.replace(hour=23, minute=59, second=59, microsecond=0)
            else:
                # Fallback to approximate calculation (30 days per month)
                days = months * 30
                start_date = now - timedelta(days=days)
                return start_date.replace(hour=0, minute=0, second=0), \
                       now.replace(hour=23, minute=59, second=59)
        
        # "last X weeks"
        weeks_match = re.search(r'last\s+(\d+)\s+weeks?', time_period_lower)
        if weeks_match:
            weeks = int(weeks_match.group(1))
            days = weeks * 7
            start_date = now - timedelta(days=days)
            return start_date.replace(hour=0, minute=0, second=0), \
                   now.replace(hour=23, minute=59, second=59)
        
        # "last X years"
        years_match = re.search(r'last\s+(\d+)\s+years?', time_period_lower)
        if years_match:
            years = int(years_match.group(1))
            if relativedelta:
                start_date = now - relativedelta(years=years)
                return start_date.replace(hour=0, minute=0, second=0, microsecond=0), \
                       now.replace(hour=23, minute=59, second=59, microsecond=0)
            else:
                # Fallback to approximate calculation (365 days per year)
                days = years * 365
                start_date = now - timedelta(days=days)
                return start_date.replace(hour=0, minute=0, second=0), \
                       now.replace(hour=23, minute=59, second=59)
        
        # "last month" (singular)
        if 'last month' in time_period_lower or 'previous month' in time_period_lower:
            first_day_this_month = now.replace(day=1)
            if relativedelta:
                last_month = first_day_this_month - relativedelta(months=1)
                first_day_last_month = last_month.replace(day=1)
                # Get last day of last month
                next_month = first_day_last_month + relativedelta(months=1)
                last_day_last_month = next_month - timedelta(days=1)
            else:
                # Fallback
                last_day_last_month = first_day_this_month - timedelta(days=1)
                first_day_last_month = last_day_last_month.replace(day=1)
            return first_day_last_month.replace(hour=0, minute=0, second=0), \
                   last_day_last_month.replace(hour=23, minute=59, second=59)
        
        # "last week" (singular)
        if 'last week' in time_period_lower or 'previous week' in time_period_lower:
            days_since_monday = now.weekday()
            last_monday = now - timedelta(days=days_since_monday + 7)
            last_sunday = last_monday + timedelta(days=6)
            return last_monday.replace(hour=0, minute=0, second=0), \
                   last_sunday.replace(hour=23, minute=59, second=59)
        
        # "last X days"
        days_match = re.search(r'last\s+(\d+)\s+days?', time_period_lower)
        if days_match:
            days = int(days_match.group(1))
            start_date = now - timedelta(days=days)
            return start_date.replace(hour=0, minute=0, second=0), \
                   now.replace(hour=23, minute=59, second=59)
        
        # "this week"
        if 'this week' in time_period_lower:
            days_since_monday = now.weekday()
            this_monday = now - timedelta(days=days_since_monday)
            return this_monday.replace(hour=0, minute=0, second=0), \
                   now.replace(hour=23, minute=59, second=59)
        
        # "this month"
        if 'this month' in time_period_lower:
            first_day_this_month = now.replace(day=1, hour=0, minute=0, second=0)
            return first_day_this_month, now.replace(hour=23, minute=59, second=59)
        
        # "this year"
        if 'this year' in time_period_lower:
            first_day_this_year = now.replace(month=1, day=1, hour=0, minute=0, second=0)
            return first_day_this_year, now.replace(hour=23, minute=59, second=59)
        
        return None, None
    
    def _extract_amount_from_content(self, content: str, metadata: Dict[str, Any]) -> Optional[float]:
        """Try to extract amount from email content if not already parsed."""
        # Use centralized currency patterns
        for pattern in CURRENCY_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            if matches:
                try:
                    # Return the largest amount found
                    amounts = [float(m) for m in matches]
                    valid_amounts = [a for a in amounts if a >= CurrencyValidationConfig.MIN_VALID_AMOUNT]
                    if valid_amounts:
                        return max(valid_amounts)
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _create_breakdown(self, transactions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create breakdown by merchant and category."""
        merchant_totals = {}
        category_totals = {}
        
        for trans in transactions:
            merchant = trans.get('merchant') or 'Unknown'
            category = trans.get('category') or 'Other'
            amount = trans.get('amount', 0)
            
            merchant_totals[merchant] = merchant_totals.get(merchant, 0) + amount
            category_totals[category] = category_totals.get(category, 0) + amount
        
        return {
            'by_merchant': {k: round(v, 2) for k, v in sorted(merchant_totals.items(), 
                                                              key=lambda x: x[1], reverse=True)},
            'by_category': {k: round(v, 2) for k, v in sorted(category_totals.items(), 
                                                               key=lambda x: x[1], reverse=True)}
        }
    
    def _extract_merchant_from_query(self, query: str) -> Optional[str]:
        """Extract merchant name from query."""
        query_lower = query.lower()
        
        # Common merchants
        merchants = {
            'spotify', 'google', 'google one', 'chipotle', 'starbucks', 'amazon',
            'uber', 'lyft', 'doordash', 'grubhub', 'netflix', 'apple', 'paypal',
            'stripe', 'microsoft', 'github', 'dropbox', 'slack', 'zoom'
        }
        
        for merchant in merchants:
            if merchant in query_lower:
                return merchant.title()
        
        # Try to extract merchant after "on" or "for"
        patterns = [
            r'(?:spent|spend|paid|pay)\s+(?:on|for)\s+([a-z\s]+?)(?:\s+in|\s+last|\s+this|$)',
            r'(?:on|for)\s+([a-z\s]+?)(?:\s+in|\s+last|\s+this|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower)
            if match:
                merchant = match.group(1).strip()
                # Filter out common words
                if merchant and merchant not in ['the', 'a', 'an', 'my', 'me', 'i']:
                    return merchant.title()
        
        return None
    
    def _extract_time_period_from_query(self, query: str) -> Optional[str]:
        """Extract time period from query."""
        query_lower = query.lower()
        
        # Look for time period patterns
        time_patterns = [
            r'last\s+(\d+)\s+months?',
            r'last\s+(\d+)\s+weeks?',
            r'last\s+(\d+)\s+days?',
            r'last\s+(\d+)\s+years?',
            r'last\s+month',
            r'last\s+week',
            r'this\s+month',
            r'this\s+week',
            r'this\s+year',
        ]
        
        for pattern in time_patterns:
            match = re.search(pattern, query_lower)
            if match:
                return match.group(0) if match.groups() else match.group(0)
        
        return None

