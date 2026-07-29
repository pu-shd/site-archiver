FROM python:3.11-slim AS base

WORKDIR /app

# Install standard networking and scraping libraries
RUN pip install --no-cache-dir requests beautifulsoup4

# Copy scraper code
COPY scraper.py /app/scraper.py

# Test stage: runs the unit suite inside the container.
#   docker build --target test -t site-archiver-tests . && docker run --rm site-archiver-tests
FROM base AS test
COPY test_scraper.py /app/test_scraper.py
ENTRYPOINT ["python", "-m", "unittest", "discover", "-s", "/app", "-p", "test_*.py", "-v"]

# Runtime stage. Kept last so a plain `docker build` still produces the scraper.
FROM base AS runtime
ENTRYPOINT ["python", "/app/scraper.py"]
