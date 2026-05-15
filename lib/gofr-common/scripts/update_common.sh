#!/bin/bash
# Update gofr-common submodule to latest from main branch
# Run this from a project that contains gofr-common as a submodule
#
# Usage:
#   ./lib/gofr-common/scripts/update_common.sh              # Update to latest main
#   ./lib/gofr-common/scripts/update_common.sh --commit     # Update and commit the change
#   ./lib/gofr-common/scripts/update_common.sh --status     # Just show current status

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect if we're inside the submodule (lib/gofr-common/scripts)
# or in a project's own scripts directory
if [[ "$SCRIPT_DIR" == */lib/gofr-common/scripts ]]; then
    # Running from inside the submodule - go up 3 levels
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
    COMMON_PATH="${PROJECT_ROOT}/lib/gofr-common"
elif [[ "$SCRIPT_DIR" == */scripts ]]; then
    # Running from project's scripts directory - go up 1 level
    PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
    COMMON_PATH="${PROJECT_ROOT}/lib/gofr-common"
else
    # Unknown location - try current directory
    PROJECT_ROOT="$(pwd)"
    COMMON_PATH="${PROJECT_ROOT}/lib/gofr-common"
fi

# Parse arguments
DO_COMMIT=false
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --commit)
            DO_COMMIT=true
            shift
            ;;
        --status)
            STATUS_ONLY=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Update gofr-common submodule to latest from main branch"
            echo ""
            echo "Options:"
            echo "  --commit    Update and commit the submodule change"
            echo "  --status    Just show current submodule status"
            echo "  --help, -h  Show this help message"
            echo ""
            echo "REQUIREMENTS:"
            echo "  - Must be run from a project with gofr-common as a submodule"
            echo "  - Git must be installed"
            echo "  - Working directory must be clean (for --commit)"
            echo "  - Network access to GitHub (to fetch updates)"
            echo ""
            echo "This script updates lib/gofr-common to the latest main branch."
            echo "Run from project root or from lib/gofr-common/scripts/."
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Check if submodule exists
if [[ ! -d "${COMMON_PATH}" ]]; then
    echo -e "${RED}Error: gofr-common submodule not found at ${COMMON_PATH}${NC}"
    echo ""
    echo "Make sure you're running this from a project with gofr-common as a submodule."
    echo "Expected location: lib/gofr-common"
    exit 1
fi

# Check if it's a git submodule
if [[ ! -f "${COMMON_PATH}/.git" ]] && [[ ! -d "${COMMON_PATH}/.git" ]]; then
    echo -e "${RED}Error: ${COMMON_PATH} is not a git repository/submodule${NC}"
    exit 1
fi

PROJECT_NAME=$(basename "${PROJECT_ROOT}")
echo -e "${GREEN}=== Update gofr-common for ${PROJECT_NAME} ===${NC}"
echo "Project root: ${PROJECT_ROOT}"
echo "Submodule path: ${COMMON_PATH}"
echo ""

# Show current status
cd "${COMMON_PATH}"
CURRENT_COMMIT=$(git rev-parse --short HEAD)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "detached")

echo -e "${BLUE}Current state:${NC}"
echo "  Commit: ${CURRENT_COMMIT}"
echo "  Branch: ${CURRENT_BRANCH}"
echo ""

if [[ "$STATUS_ONLY" == "true" ]]; then
    # Fetch to see what's available
    echo -e "${YELLOW}Fetching from origin...${NC}"
    git fetch origin main --quiet
    
    REMOTE_COMMIT=$(git rev-parse --short origin/main)
    if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
        echo -e "${GREEN}✓ Already up to date with origin/main${NC}"
    else
        BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo "?")
        AHEAD=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
        echo -e "${YELLOW}origin/main is at: ${REMOTE_COMMIT}${NC}"
        echo "  Behind: ${BEHIND} commits"
        echo "  Ahead: ${AHEAD} commits"
    fi
    exit 0
fi

# Fetch and update
echo -e "${YELLOW}Fetching latest from origin...${NC}"
git fetch origin main

# Check if there are changes
REMOTE_COMMIT=$(git rev-parse --short origin/main)
if [[ "$CURRENT_COMMIT" == "$REMOTE_COMMIT" ]]; then
    echo -e "${GREEN}✓ Already up to date with origin/main (${CURRENT_COMMIT})${NC}"
    exit 0
fi

# Show what will change
echo ""
echo -e "${BLUE}Changes to be pulled:${NC}"
git log --oneline HEAD..origin/main | head -20
COMMIT_COUNT=$(git rev-list --count HEAD..origin/main)
if [[ $COMMIT_COUNT -gt 20 ]]; then
    echo "  ... and $((COMMIT_COUNT - 20)) more commits"
fi
echo ""

# Update to latest
echo -e "${YELLOW}Updating to origin/main (${REMOTE_COMMIT})...${NC}"
git checkout main 2>/dev/null || git checkout -b main origin/main
git pull origin main

NEW_COMMIT=$(git rev-parse --short HEAD)
echo -e "${GREEN}✓ Updated to ${NEW_COMMIT}${NC}"
echo ""

# Go back to project root
cd "${PROJECT_ROOT}"

# Show submodule status in parent project
echo -e "${BLUE}Submodule status in ${PROJECT_NAME}:${NC}"
git submodule status lib/gofr-common

if [[ "$DO_COMMIT" == "true" ]]; then
    echo ""
    echo -e "${YELLOW}Staging and committing submodule update...${NC}"
    git add lib/gofr-common
    git commit -m "chore: update gofr-common submodule to ${NEW_COMMIT}"
    echo -e "${GREEN}✓ Committed submodule update${NC}"
else
    echo ""
    echo -e "${YELLOW}To commit this update, run:${NC}"
    echo "  cd ${PROJECT_ROOT}"
    echo "  git add lib/gofr-common"
    echo "  git commit -m 'chore: update gofr-common submodule to ${NEW_COMMIT}'"
    echo ""
    echo "Or run this script with --commit flag:"
    echo "  $0 --commit"
fi
