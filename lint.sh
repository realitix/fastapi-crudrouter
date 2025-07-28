#!/bin/bash
# Simplest lint script for fastapi-crudrouter

set -e

echo "🚀 Running linting for fastapi-crudrouter..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m' 
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ $2 passed${NC}"
    else
        echo -e "${RED}❌ $2 failed${NC}"
    fi
}

# Export PATH to include uv
export PATH="$HOME/.local/bin:$PATH"

# Check if uv is available
if ! command -v uv &> /dev/null; then
    echo -e "${RED}❌ uv is not installed or not in PATH${NC}"
    exit 1
fi

echo -e "${YELLOW}🔍 Running Ruff (linting)...${NC}"
uv run ruff check fastapi_crudrouter tests
ruff_check_status=$?
print_status $ruff_check_status "Ruff check"

echo -e "${YELLOW}🎨 Running Ruff (formatting)...${NC}"
uv run ruff format --check fastapi_crudrouter tests  
ruff_format_status=$?
print_status $ruff_format_status "Ruff format"

echo -e "${YELLOW}🔍 Running MyPy...${NC}"
uv run mypy fastapi_crudrouter tests
mypy_status=$?
print_status $mypy_status "MyPy"

echo -e "${YELLOW}🔍 Running Pylint...${NC}"
uv run pylint fastapi_crudrouter tests
pylint_status=$?
print_status $pylint_status "Pylint"

# Summary
echo ""
echo "==============================================="
echo "📊 LINTING SUMMARY"
echo "==============================================="

total_failures=0

if [ $ruff_check_status -ne 0 ]; then
    echo -e "Ruff Check:  ${RED}FAILED${NC}"
    ((total_failures++))
else
    echo -e "Ruff Check:  ${GREEN}PASSED${NC}"
fi

if [ $ruff_format_status -ne 0 ]; then
    echo -e "Ruff Format: ${RED}FAILED${NC}"
    ((total_failures++))
else
    echo -e "Ruff Format: ${GREEN}PASSED${NC}"
fi

if [ $mypy_status -ne 0 ]; then
    echo -e "MyPy:        ${RED}FAILED${NC}"
    ((total_failures++))
else
    echo -e "MyPy:        ${GREEN}PASSED${NC}"
fi

if [ $pylint_status -ne 0 ]; then
    echo -e "Pylint:      ${RED}FAILED${NC}"
    ((total_failures++))
else
    echo -e "Pylint:      ${GREEN}PASSED${NC}"
fi

if [ $total_failures -eq 0 ]; then
    echo ""
    echo -e "${GREEN}🎉 All linting checks passed!${NC}"
    exit 0
else
    echo ""
    echo -e "${RED}💥 $total_failures linting check(s) failed!${NC}"
    echo ""
    echo "To auto-fix some issues, run:"
    echo "  uv run ruff check --fix fastapi_crudrouter tests"
    echo "  uv run ruff format fastapi_crudrouter tests"
    exit 1
fi