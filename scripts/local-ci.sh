#!/bin/bash

# Local CI Simulation Script
# Runs the same checks that GitHub Actions will run

set -e  # Exit on error

echo "🚀 Starting Local CI Simulation..."
echo "=================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print status
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2${NC}"
    else
        echo -e "${RED}❌ $2${NC}"
    fi
}

# Track overall status
OVERALL_STATUS=0

# ============================================
# 1. CODE QUALITY CHECKS
# ============================================
echo "📋 Step 1: Code Quality Checks"
echo "--------------------------------"

# Black formatting check
echo "  Checking code formatting (Black)..."
if black --check --diff src/ api/ tests/ > /dev/null 2>&1; then
    print_status 0 "Black formatting"
else
    print_status 1 "Black formatting (run: black src/ api/ tests/)"
    OVERALL_STATUS=1
fi

# isort import sorting check
echo "  Checking import sorting (isort)..."
if isort --check-only --diff src/ api/ tests/ > /dev/null 2>&1; then
    print_status 0 "isort import sorting"
else
    print_status 1 "isort import sorting (run: isort src/ api/ tests/)"
    OVERALL_STATUS=1
fi

# Flake8 linting
echo "  Running linter (Flake8)..."
if flake8 src/ api/ tests/ --count --statistics > /dev/null 2>&1; then
    print_status 0 "Flake8 linting"
else
    print_status 1 "Flake8 linting"
    OVERALL_STATUS=1
fi

echo ""

# ============================================
# 2. SECURITY CHECKS
# ============================================
echo "🔒 Step 2: Security Checks"
echo "--------------------------------"

# Bandit security scan
echo "  Running security scan (Bandit)..."
if bandit -r src/ api/ -ll > /dev/null 2>&1; then
    print_status 0 "Bandit security scan"
else
    print_status 1 "Bandit security scan (warnings found)"
    # Don't fail on security warnings, just inform
fi

# Safety dependency check
echo "  Checking dependencies (Safety)..."
if safety check > /dev/null 2>&1; then
    print_status 0 "Safety dependency check"
else
    print_status 1 "Safety dependency check (vulnerabilities found)"
    # Don't fail on vulnerabilities in development, just inform
fi

echo ""

# ============================================
# 3. IMPORT CHECKS
# ============================================
echo "🔗 Step 3: Import Verification"
echo "--------------------------------"

# Check critical imports
echo "  Testing critical imports..."
python -c "from src.utils import QueryClassifier" 2>/dev/null && \
python -c "from src.ai.rag import RAGEngine" 2>/dev/null && \
python -c "from src.services import RAGService" 2>/dev/null && \
python -c "from src.database import init_db, get_session" 2>/dev/null && \
python -c "from api.main import app" 2>/dev/null
if [ $? -eq 0 ]; then
    print_status 0 "Critical imports"
else
    print_status 1 "Critical imports"
    OVERALL_STATUS=1
fi

# Check webhook imports
echo "  Testing webhook imports..."
python -c "from src.database.webhook_models import WebhookEventType, WebhookSubscription" 2>/dev/null && \
python -c "from src.features.webhook_service import WebhookService" 2>/dev/null && \
python -c "from api.routers.webhooks import router" 2>/dev/null && \
python -c "from src.workers.tasks.webhook_tasks import deliver_webhook_task" 2>/dev/null
if [ $? -eq 0 ]; then
    print_status 0 "Webhook imports"
else
    print_status 1 "Webhook imports"
    OVERALL_STATUS=1
fi

# Check for circular imports
echo "  Checking for circular imports..."
if [ -f "scripts/check_circular_imports.py" ]; then
    if python scripts/check_circular_imports.py > /dev/null 2>&1; then
        print_status 0 "Circular import check"
    else
        print_status 1 "Circular import check"
        OVERALL_STATUS=1
    fi
else
    echo -e "${YELLOW}⚠️  Circular import check script not found${NC}"
fi

echo ""

# ============================================
# 4. UNIT TESTS
# ============================================
echo "🧪 Step 4: Unit Tests"
echo "--------------------------------"

echo "  Running unit tests with coverage..."
if pytest tests/ -v -m "unit or not integration" --cov=src --cov=api --cov-report=term-missing --cov-report=html 2>&1 | tail -n 20; then
    print_status 0 "Unit tests"
else
    print_status 1 "Unit tests"
    OVERALL_STATUS=1
fi

echo ""

# ============================================
# 5. WEBHOOK TESTS
# ============================================
echo "🪝 Step 5: Webhook Tests"
echo "--------------------------------"

echo "  Running webhook-specific tests..."
if pytest tests/test_webhooks.py -v 2>&1 | tail -n 10; then
    print_status 0 "Webhook tests (26 tests)"
else
    print_status 1 "Webhook tests"
    OVERALL_STATUS=1
fi

echo ""

# ============================================
# 6. COVERAGE CHECK
# ============================================
echo "📊 Step 6: Coverage Analysis"
echo "--------------------------------"

# Generate coverage report
coverage_percent=$(coverage report --format=markdown 2>/dev/null | grep TOTAL | awk '{print $NF}' | tr -d '%' || echo "0")
echo "  Current coverage: ${coverage_percent}%"

threshold=70
if (( $(echo "$coverage_percent >= $threshold" | bc -l) )); then
    print_status 0 "Coverage threshold (>= ${threshold}%)"
else
    echo -e "${YELLOW}⚠️  Coverage ${coverage_percent}% is below threshold ${threshold}%${NC}"
fi

echo ""

# ============================================
# SUMMARY
# ============================================
echo "=================================="
echo "📈 CI Simulation Summary"
echo "=================================="
echo ""

if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "${GREEN}✅ All critical checks passed!${NC}"
    echo ""
    echo "Your code is ready to push. CI pipeline should pass."
    echo ""
    echo "Next steps:"
    echo "  1. git add ."
    echo "  2. git commit -m \"your message\""
    echo "  3. git push"
    echo ""
else
    echo -e "${RED}❌ Some checks failed!${NC}"
    echo ""
    echo "Please fix the issues above before pushing."
    echo ""
    echo "Quick fixes:"
    echo "  - Format code: black src/ api/ tests/"
    echo "  - Sort imports: isort src/ api/ tests/"
    echo "  - Run tests: pytest tests/ -v"
    echo ""
fi

# Generate HTML coverage report location
if [ -f "htmlcov/index.html" ]; then
    echo "📊 Coverage report: htmlcov/index.html"
    echo "   Open with: open htmlcov/index.html"
    echo ""
fi

exit $OVERALL_STATUS
