#!/bin/bash

# Agent Builder Platform - API Server Startup Script
# This script ensures the API server starts correctly with all dependencies

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}   Agent Builder API Server${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
API_DIR="${SCRIPT_DIR}"
REPO_DIR="$( cd "${API_DIR}/../.." && pwd )"

# Change to API directory
cd "${API_DIR}"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}✗ Virtual environment not found${NC}"
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    python3 -m venv .venv
fi

# Activate virtual environment
echo -e "${GREEN}✓ Activating virtual environment${NC}"
source .venv/bin/activate

# Check if requirements are installed
echo -e "${YELLOW}⚙ Checking dependencies...${NC}"
if ! pip show fastapi > /dev/null 2>&1; then
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -r requirements.txt
else
    echo -e "${GREEN}✓ Dependencies already installed${NC}"
fi

# Check for .env file. app.config loads the root .env by default.
if [ ! -f ".env" ] && [ ! -f "${REPO_DIR}/.env" ]; then
    echo -e "${RED}✗ .env file not found${NC}"
    echo -e "${YELLOW}Please create ${REPO_DIR}/.env or ${API_DIR}/.env from .env.example${NC}"
    exit 1
else
    echo -e "${GREEN}✓ Environment configuration found${NC}"
fi

# Set PYTHONPATH for the canonical monorepo packages. requirements.txt only
# installs third-party dependencies; shared application code lives exclusively
# under the repository-root packages/ tree.
PACKAGE_PATHS=""
for package in commons llm memory retrieval tools agent_runtime; do
    if [ -d "${REPO_DIR}/packages/${package}/src" ]; then
        PACKAGE_PATHS="${PACKAGE_PATHS}:${REPO_DIR}/packages/${package}/src"
    else
        echo -e "${RED}✗ Canonical package missing: ${REPO_DIR}/packages/${package}${NC}"
        exit 1
    fi
done
export PYTHONPATH="${API_DIR}${PACKAGE_PATHS}:${PYTHONPATH:-}"

# Start the server
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}🚀 Starting API server on http://0.0.0.0:8000${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}📡 API Docs: http://localhost:8000/docs${NC}"
echo -e "${BLUE}📊 Health: http://localhost:8000/health${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Run uvicorn
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
