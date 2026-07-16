#!/bin/bash

# ==============================================================================
# Site Archiver - Automated Website Mirroring & Deployment Tool
# Bash 3.2+ Compatible (macOS default compliant)
# ==============================================================================

# ANSI Color Codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Script Directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default Configs
TARGET_URL=""
OUTPUT_DIR=""
REPO_PATH=""
ALLOWED_ASSETS="*.princeton.edu"
BYPASS_HEADER_VAL=""

# Show Banner
show_banner() {
    echo -e "${CYAN}${BOLD}"
    echo "======================================================================="
    echo "                     🌐  SITE ARCHIVER AUTOMATION  🌐"
    echo "======================================================================="
    echo -e "${NC}"
}

# Show Help
show_help() {
    show_banner
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -u, --url <url>        Target URL to crawl (e.g., https://fan60.princeton.edu)"
    echo "  -o, --output <dir>     Output directory for mirrored site (default: dist)"
    echo "  -r, --repo <org/repo>  GitHub Repository (e.g., pu-orfe/fan60)"
    echo "  -a, --assets <doms>    Comma-separated asset domains allowed (default: *.princeton.edu)"
    echo "  -b, --bypass <val>     Value of x-wdsoit-bot-bypass header (Treat as secret)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --url https://fan60.princeton.edu --repo pu-orfe/fan60 --bypass secret_bypass_value"
    echo ""
}

# Parse Command Line Arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -u|--url)
            TARGET_URL="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -r|--repo)
            REPO_PATH="$2"
            shift 2
            ;;
        -a|--assets)
            ALLOWED_ASSETS="$2"
            shift 2
            ;;
        -b|--bypass)
            BYPASS_HEADER_VAL="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            show_help
            exit 1
            ;;
    esac
done

show_banner

# 1. Dependency Checks
echo -e "${BLUE}[*] Checking system dependencies...${NC}"
DEPENDENCIES=("docker" "git" "gh")
for dep in "${DEPENDENCIES[@]}"; do
    if ! command -v "$dep" &>/dev/null; then
        echo -e "${RED}Error: Required dependency '$dep' is not installed or not in PATH.${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✔ All core dependencies found! (docker, git, gh)${NC}"

# Verify GitHub CLI authentication
if ! gh auth status &>/dev/null; then
    echo -e "${RED}Error: GitHub CLI (gh) is not authenticated. Please run 'gh auth login' first.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ GitHub CLI is authenticated.${NC}"

# 2. Interactive Prompts (if parameters are missing)
if [ -z "$TARGET_URL" ]; then
    echo -e "${BLUE}Enter the Target URL to crawl:${NC}"
    read -r TARGET_URL
fi

if [ -z "$REPO_PATH" ]; then
    echo -e "${BLUE}Enter the target GitHub repository (format: OWNER/REPO, e.g. pu-orfe/fan60):${NC}"
    read -r REPO_PATH
fi

if [ -z "$BYPASS_HEADER_VAL" ]; then
    echo -e "${BLUE}Does the site require a bot bypass header? (y/n, default: n):${NC}"
    read -r REQUIRES_BYPASS
    if [[ "$REQUIRES_BYPASS" =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}Enter x-wdsoit-bot-bypass header value (input will be hidden):${NC}"
        # Hide password input for secret bypass key
        stty -echo
        read -r BYPASS_HEADER_VAL
        stty echo
        echo ""
    fi
fi

# Clean up input URLs
if [[ ! "$TARGET_URL" =~ ^https?:// ]]; then
    TARGET_URL="https://$TARGET_URL"
fi

# Resolve output path
if [ -z "$OUTPUT_DIR" ]; then
    if [ -n "$REPO_PATH" ]; then
        # Default to a repo-specific subdirectory to avoid collisions
        OUTPUT_DIR="dist/$REPO_PATH"
    else
        OUTPUT_DIR="dist"
    fi
fi

mkdir -p "$OUTPUT_DIR"
ABS_OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"

echo -e "\n${CYAN}Configuration Summary:${NC}"
echo -e "  - Target URL:       ${BOLD}$TARGET_URL${NC}"
echo -e "  - Allowed Assets:   ${BOLD}$ALLOWED_ASSETS${NC}"
echo -e "  - Local Output Dir: ${BOLD}$ABS_OUTPUT_DIR${NC}"
echo -e "  - GitHub Repo:      ${BOLD}$REPO_PATH${NC}"
if [ -n "$BYPASS_HEADER_VAL" ]; then
    echo -e "  - Bypass Header:    ${YELLOW}[SET (HIDDEN)]${NC}"
else
    echo -e "  - Bypass Header:    ${YELLOW}[NONE]${NC}"
fi
echo ""

# 3. Create temp config file for crawler
CONFIG_FILE="$SCRIPT_DIR/config.json"
echo -e "${BLUE}[*] Preparing scraper configuration...${NC}"

# Build request headers JSON
HEADERS_JSON="{}"
if [ -n "$BYPASS_HEADER_VAL" ]; then
    HEADERS_JSON="{\"x-wdsoit-bot-bypass\": \"$BYPASS_HEADER_VAL\"}"
fi

# Write config.json
cat <<EOF > "$CONFIG_FILE"
{
  "url": "$TARGET_URL",
  "output_dir": "/output",
  "allowed_asset_domains": "$ALLOWED_ASSETS",
  "headers": $HEADERS_JSON
}
EOF

# Ensure config.json is deleted on script exit to protect secrets
cleanup() {
    if [ -f "$CONFIG_FILE" ]; then
        rm -f "$CONFIG_FILE"
        echo -e "${BLUE}[*] Cleaned up temporary configuration file.${NC}"
    fi
}
trap cleanup EXIT INT TERM

# 4. Build Scraper Docker Image
echo -e "${BLUE}[*] Building crawler Docker image...${NC}"
if ! docker build -t site-archiver-scraper "$SCRIPT_DIR"; then
    echo -e "${RED}Error: Failed to build Docker image.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Docker image built successfully!${NC}"

# 5. Run Crawler Container
echo -e "${BLUE}[*] Launching containerized crawler...${NC}"
echo -e "${YELLOW}Please wait, crawling may take some time depending on site size...${NC}"
if ! docker run --rm \
    -v "$ABS_OUTPUT_DIR:/output" \
    -v "$CONFIG_FILE:/app/config.json" \
    site-archiver-scraper config.json; then
    echo -e "${RED}Error: Scraper encountered an error during crawl.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Scrape completed successfully! Assets downloaded and paths rewritten.${NC}"

# Clean up configuration file now that we are done crawling
cleanup
trap - EXIT INT TERM

# 6. Initialize Git and Commit Mirrored Site
echo -e "${BLUE}[*] Initializing local Git repository inside output folder...${NC}"
cd "$ABS_OUTPUT_DIR" || exit 1

if [ ! -d ".git" ]; then
    git init -b main
    # Configure user identity locally for this repo if none exists
    if ! git config user.name &>/dev/null; then
        git config user.name "Site Archiver Bot"
    fi
    if ! git config user.email &>/dev/null; then
        git config user.email "site-archiver@github.com"
    fi
fi

# Create .nojekyll file to ensure GitHub Pages serves underscore folders
touch .nojekyll

# Create .github/workflows directory and codeql.yml to disable JavaScript scanning
mkdir -p .github/workflows
cat <<'EOF' > .github/workflows/codeql.yml
name: "CodeQL"

on:
  push:
    branches: [ "main" ]
  pull_request:
    branches: [ "main" ]
  schedule:
    - cron: '0 0 * * 0'

jobs:
  analyze:
    name: Analyze
    runs-on: ubuntu-latest
    permissions:
      actions: read
      contents: read
      security-events: write

    steps:
    - name: Checkout repository
      uses: actions/checkout@v4

    - name: Initialize CodeQL
      uses: github/codeql-action/init@v3
      with:
        languages: 'actions'
        config-file: ./.github/codeql/codeql-config.yml

    - name: Perform CodeQL Analysis
      uses: github/codeql-action/analyze@v3
EOF

# Create CodeQL configuration file to ignore JavaScript and vendor paths
mkdir -p .github/codeql
cat <<'EOF' > .github/codeql/codeql-config.yml
name: "CodeQL Ignore Config"

paths-ignore:
  - '**/*.js'
  - '**/node_modules/**'
  - '**/bower_components/**'
EOF

git add .
git commit -m "Mirror of $TARGET_URL on $(date)"


# 7. Create Repo on GitHub and Push
# Ensure the local remote 'origin' is synchronized with our target $REPO_PATH
TARGET_REMOTE="git@github.com:$REPO_PATH.git"
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null)

if [ -z "$CURRENT_REMOTE" ]; then
    git remote add origin "$TARGET_REMOTE"
elif [ "$CURRENT_REMOTE" != "$TARGET_REMOTE" ]; then
    echo -e "${YELLOW}[!] Updating local 'origin' remote to $TARGET_REMOTE${NC}"
    git remote set-url origin "$TARGET_REMOTE"
fi

echo -e "${BLUE}[*] Checking GitHub repository status for '$REPO_PATH'...${NC}"
REPO_EXISTS=true
if ! gh repo view "$REPO_PATH" &>/dev/null; then
    REPO_EXISTS=false
fi

if [ "$REPO_EXISTS" = false ]; then
    echo -e "${BLUE}[*] Repository '$REPO_PATH' does not exist. Creating public repository...${NC}"
    # Just create the repo on GitHub, we handle remotes and pushing ourselves for robustness
    if ! gh repo create "$REPO_PATH" --public; then
        echo -e "${RED}Error: Failed to create GitHub repository.${NC}"
        exit 1
    fi
else
    echo -e "${YELLOW}[!] Repository '$REPO_PATH' already exists.${NC}"
fi

echo -e "${BLUE}[*] Pushing mirrored site to GitHub...${NC}"
# Force push to reset pages to mirror
if ! git push -u origin main --force; then
    echo -e "${RED}Error: Failed to push to repository '$REPO_PATH'.${NC}"
    exit 1
fi
echo -e "${GREEN}✔ Successfully pushed site to GitHub!${NC}"

# 8. Enable GitHub Pages
echo -e "${BLUE}[*] Configuring GitHub Pages on branch 'main'...${NC}"
if gh api "repos/$REPO_PATH/pages" &>/dev/null; then
    echo -e "${YELLOW}[!] Pages is already enabled. Re-requesting page builds...${NC}"
    # Re-trigger deployment if Pages is already configured
    gh api -X POST "repos/$REPO_PATH/pages/builds" &>/dev/null
else
    # Enable Pages via GitHub REST API
    # Pass the source branch configuration as a JSON payload via stdin
    if ! echo '{"source":{"branch":"main","path":"/"}}' | gh api "repos/$REPO_PATH/pages" --input - &>/dev/null; then
        # Try fallback using source[branch]=main format if --input fails
        if ! gh api -X POST "repos/$REPO_PATH/pages" -f "source[branch]=main" -f "source[path]=/" &>/dev/null; then
            echo -e "${YELLOW}[!] Pages creation via API returned an error, it might already be enabled or configuring. Retrying...${NC}"
        fi
    fi
fi

# Retrieve Pages URL
PAGES_URL=$(gh api "repos/$REPO_PATH/pages" --jq '.html_url' 2>/dev/null)
if [ $? -ne 0 ] || [ -z "$PAGES_URL" ] || [[ "$PAGES_URL" != http* ]]; then
    # Fallback guess of the standard URL
    ORG_NAME=$(echo "$REPO_PATH" | cut -d'/' -f1)
    REPO_NAME=$(echo "$REPO_PATH" | cut -d'/' -f2)
    PAGES_URL="https://$ORG_NAME.github.io/$REPO_NAME/"
fi

echo -e "${GREEN}✔ GitHub Pages configured!${NC}"
echo -e "Target URL: ${BOLD}$PAGES_URL${NC}"

# 9. Poll GitHub Actions deployment status
echo -e "${BLUE}[*] Waiting for GitHub Pages deployment to complete...${NC}"
echo -e "${YELLOW}(This can take 30-90 seconds. Checking status every 10 seconds...)${NC}"

MAX_ATTEMPTS=20
ATTEMPT=0
DEPLOYED=false

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    
    # Get latest pages-build-deployment workflow run status
    RUN_INFO=$(gh api "repos/$REPO_PATH/actions/runs" --jq '.workflow_runs[] | select(.name | ascii_downcase | contains("pages")) | "\(.status),\(.conclusion)"' 2>/dev/null | head -n 1)
    
    if [ -n "$RUN_INFO" ] && [ "$RUN_INFO" != "," ] && [ "$RUN_INFO" != "null,null" ]; then
        STATUS=$(echo "$RUN_INFO" | cut -d',' -f1)
        CONCLUSION=$(echo "$RUN_INFO" | cut -d',' -f2)
        
        if [ "$STATUS" = "null" ]; then
            echo -e "  - Attempt $ATTEMPT/$MAX_ATTEMPTS: Waiting for deployment workflow to start..."
        else
            echo -e "  - Attempt $ATTEMPT/$MAX_ATTEMPTS: Deployment is ${BOLD}$STATUS${NC}... (Conclusion: ${BOLD}${CONCLUSION:-NONE}${NC})"
            
            if [ "$STATUS" = "completed" ]; then
                if [ "$CONCLUSION" = "success" ]; then
                    DEPLOYED=true
                    break
                elif [ "$CONCLUSION" = "failure" ] || [ "$CONCLUSION" = "cancelled" ]; then
                    echo -e "${RED}❌ GitHub Pages deployment workflow failed or was cancelled.${NC}"
                    exit 1
                fi
            fi
        fi
    else
        echo -e "  - Attempt $ATTEMPT/$MAX_ATTEMPTS: Waiting for deployment workflow to start..."
    fi
    
    sleep 10
done

if [ "$DEPLOYED" = true ]; then
    echo -e "\n${GREEN}${BOLD}======================================================================="
    echo "🎉 SUCCESS: Website mirrored and deployed successfully!"
    echo "=======================================================================${NC}"
    echo -e "The static archive is now LIVE and ready for human inspection:"
    echo -e "🔗 ${BOLD}${PAGES_URL}${NC}"
    echo ""
else
    echo -e "\n${YELLOW}[!] Timeout waiting for deployment workflow, but files were successfully pushed.${NC}"
    echo -e "Please check the status manually at: https://github.com/$REPO_PATH/deployments"
    echo -e "Expected URL: 🔗 ${BOLD}${PAGES_URL}${NC}"
    echo ""
fi
