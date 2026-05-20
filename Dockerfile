FROM python:3.11-slim

WORKDIR /app

# Install standard networking and scraping libraries
RUN pip install --no-cache-dir requests beautifulsoup4

# Copy scraper code
COPY scraper.py /app/scraper.py

# Run python scraper
ENTRYPOINT ["python", "/app/scraper.py"]
