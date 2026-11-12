FROM python:3.11.18-slim-bookworm AS base

WORKDIR /app

# Install pinned networking, scraping and WARC libraries
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy scraper code
COPY scraper.py /app/scraper.py

# Test stage: runs the unit suite inside the container.
#   docker build --target test -t site-archiver-tests . && docker run --rm site-archiver-tests
FROM base AS test
COPY test_*.py /app/
COPY browsertrix/proxy/bypass_proxy.py /app/browsertrix/proxy/bypass_proxy.py
ENTRYPOINT ["python", "-m", "unittest", "discover", "-s", "/app", "-p", "test_*.py", "-v"]

# Runtime stage. Kept last so a plain `docker build` still produces the scraper.
FROM base AS runtime
ENTRYPOINT ["python", "/app/scraper.py"]
