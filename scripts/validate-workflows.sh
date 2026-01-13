#!/bin/bash

# GitHub Actions Workflow Validation Script
# Validates all workflow YAML files for syntax errors

set -e

echo "🔍 Validating GitHub Actions Workflows"
echo "======================================="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

WORKFLOW_DIR=".github/workflows"
VALID_COUNT=0
INVALID_COUNT=0

# Check if actionlint is installed
if ! command -v actionlint &> /dev/null; then
    echo -e "${YELLOW}⚠️  actionlint not installed${NC}"
    echo "   Install with: brew install actionlint (macOS)"
    echo "   Or use: https://github.com/rhysd/actionlint"
    echo ""
    echo "Performing basic YAML syntax validation instead..."
    echo ""
    USE_ACTIONLINT=false
else
    echo "✅ actionlint found, performing full validation"
    echo ""
    USE_ACTIONLINT=true
fi

# Function to validate YAML syntax with Python
validate_yaml_python() {
    python3 -c "
import yaml
import sys
try:
    with open('$1', 'r') as f:
        yaml.safe_load(f)
    sys.exit(0)
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
" 2>&1
}

# Iterate through workflow files
for workflow in "$WORKFLOW_DIR"/*.yml; do
    if [ -f "$workflow" ]; then
        filename=$(basename "$workflow")
        echo -n "  Checking $filename... "
        
        if [ "$USE_ACTIONLINT" = true ]; then
            # Use actionlint for full validation
            if actionlint "$workflow" > /dev/null 2>&1; then
                echo -e "${GREEN}✅ Valid${NC}"
                ((VALID_COUNT++))
            else
                echo -e "${RED}❌ Invalid${NC}"
                actionlint "$workflow" 2>&1 | sed 's/^/    /'
                ((INVALID_COUNT++))
            fi
        else
            # Use Python YAML parser for basic syntax check
            if validate_yaml_python "$workflow"; then
                echo -e "${GREEN}✅ Valid YAML${NC}"
                ((VALID_COUNT++))
            else
                echo -e "${RED}❌ Invalid YAML${NC}"
                validate_yaml_python "$workflow" | sed 's/^/    /'
                ((INVALID_COUNT++))
            fi
        fi
    fi
done

echo ""
echo "======================================="
echo "Summary:"
echo "  ✅ Valid workflows: $VALID_COUNT"
echo "  ❌ Invalid workflows: $INVALID_COUNT"
echo "======================================="
echo ""

if [ $INVALID_COUNT -eq 0 ]; then
    echo -e "${GREEN}✅ All workflows are valid!${NC}"
    echo ""
    echo "Workflow files:"
    ls -1 "$WORKFLOW_DIR"/*.yml | while read -r file; do
        echo "  - $(basename "$file")"
    done
    echo ""
    exit 0
else
    echo -e "${RED}❌ Some workflows have errors!${NC}"
    echo "Please fix the errors above."
    echo ""
    exit 1
fi
