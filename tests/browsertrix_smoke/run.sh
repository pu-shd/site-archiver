#!/bin/zsh
#
# End-to-end smoke test for the browsertrix engine: crawls a local HTTPS origin
# that returns 403 without the bypass header, through the real proxy and the
# pinned browsertrix-crawler image, then checks the WACZ and the origin log.
#
# Usage: tests/browsertrix_smoke/run.sh
set -euo pipefail

SMOKE_DIR="${0:A:h}"
REPO_DIR="${SMOKE_DIR:h:h}"
OUT_DIR="$REPO_DIR/.smoke-output"
PROJECT="site-archiver-smoke"
DELAY=1
SECRET="smoke-secret-$RANDOM$RANDOM"

for dep in docker docker-compose openssl python3; do
  command -v "$dep" >/dev/null 2>&1 || { echo "Error: $dep not found" >&2; exit 1; }
done

# browsertrix writes as root; on Linux hosts only a container can remove that.
if [[ -d "$OUT_DIR" ]]; then
  docker run --rm -v "$OUT_DIR:/out" python:3.11.18-slim-bookworm sh -c 'rm -rf /out/crawls /out/certs /out/origin.log'
fi
mkdir -p "$OUT_DIR/certs" "$OUT_DIR/crawls"

# Throwaway CA and an origin certificate for the hostname "origin".
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=site-archiver smoke CA" \
  -keyout "$OUT_DIR/certs/ca.key" -out "$OUT_DIR/certs/ca.pem" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=origin" \
  -keyout "$OUT_DIR/certs/origin.key" -out "$OUT_DIR/certs/origin.csr" 2>/dev/null
print "subjectAltName=DNS:origin" > "$OUT_DIR/certs/ext.cnf"
openssl x509 -req -days 1 -in "$OUT_DIR/certs/origin.csr" -CA "$OUT_DIR/certs/ca.pem" \
  -CAkey "$OUT_DIR/certs/ca.key" -CAcreateserial -extfile "$OUT_DIR/certs/ext.cnf" \
  -out "$OUT_DIR/certs/origin.pem" 2>/dev/null
chmod 644 "$OUT_DIR/certs/"*

export SMOKE_DIR SMOKE_CERTS="$OUT_DIR/certs"
export ARCHIVE_DIR="$OUT_DIR/crawls" COLLECTION="smoke" CRAWL_URL="https://origin:8443/"
export BYPASS_HOSTS="origin" CRAWL_DELAY="$DELAY" PAGE_LIMIT="5" BYPASS_HEADER_VALUE="$SECRET"

compose=(docker-compose -p "$PROJECT" -f "$REPO_DIR/browsertrix/docker-compose.yml" -f "$SMOKE_DIR/docker-compose.smoke.yml")
cleanup() { "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

"${compose[@]}" build --quiet
"${compose[@]}" run --rm crawler
"${compose[@]}" logs --no-color origin > "$OUT_DIR/origin.log"

WACZ="$ARCHIVE_DIR/collections/$COLLECTION/$COLLECTION.wacz"
[[ -f "$WACZ" ]] || { echo "FAIL: no WACZ at $WACZ" >&2; exit 1; }
python3 -I "$SMOKE_DIR/check_wacz.py" "$WACZ" "$OUT_DIR/origin.log" "$SECRET" "$DELAY"
