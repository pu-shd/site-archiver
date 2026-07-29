#!/bin/zsh
#
# Runs the Site Archiver unit suite inside a Docker container so the host stays
# clean and CI and local runs behave identically.
#
# Usage:
#   ./run_tests.sh            # run the suite in Docker (default)
#   ./run_tests.sh --local    # run the suite directly with the host python
#
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
IMAGE_NAME="site-archiver-tests"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

MODE="docker"
if [[ "${1:-}" == "--local" ]]; then
  MODE="local"
fi

if [[ "$MODE" == "local" ]]; then
  echo "${YELLOW}[*] Running test suite on the host python...${NC}"
  cd "$SCRIPT_DIR"
  if ! python3 -m unittest discover -s . -p 'test_*.py' -v; then
    echo "${RED}✘ Tests failed.${NC}"
    exit 1
  fi
  echo "${GREEN}✔ All tests passed.${NC}"
  exit 0
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "${RED}Error: docker not found. Use ./run_tests.sh --local to run on the host.${NC}"
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "${RED}Error: Docker is not running. Start Docker and try again.${NC}"
  exit 1
fi

echo "${YELLOW}[*] Building test image...${NC}"
if ! docker build --target test -t "$IMAGE_NAME" "$SCRIPT_DIR"; then
  echo "${RED}✘ Failed to build the test image.${NC}"
  exit 1
fi

echo "${YELLOW}[*] Running test suite in container...${NC}"
if ! docker run --rm "$IMAGE_NAME"; then
  echo "${RED}✘ Tests failed.${NC}"
  exit 1
fi

echo "${GREEN}✔ All tests passed.${NC}"
