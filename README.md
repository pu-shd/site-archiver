# Site Archiver 🌐

Site Archiver is a containerized automation tool designed to create 1-for-1 static mirrors of websites (e.g., CMS-backed sites that need to be archived) and deploy them to GitHub Pages.

## Features

- **Containerized Crawling**: Performs scraping and assets download inside an isolated Docker container, avoiding dependencies pollution on the host system.
- **Path Portability**: Converts all page links and assets to relative paths (`./path/to/asset`), meaning the static archive can be hosted in subfolders (like GitHub Pages) or even run locally by double-clicking `index.html`.
- **Asset Preservation**: Automatically fetches CSS, JS, images, source sets, fonts, and assets hosted on permitted subdomains (e.g. `*.princeton.edu`), preserving full style and layout.
- **Jekyll Bypass**: Automatically configures `.nojekyll` to ensure GitHub Pages serves directories starting with underscores (like `_assets/`).
- **Secrets Management**: Treats bot bypass headers as secrets, accepting them interactively or via environment variables without committing them to repositories.
- **Deployment Monitoring**: Uses the GitHub CLI to enable Pages and monitor the deployment workflow status, reporting when the live site is ready.

## Requirements

Ensure you have the following installed on your host machine:
1. [Docker](https://www.docker.com/) (Must be running)
2. [Git](https://git-scm.com/)
3. [GitHub CLI (`gh`)](https://cli.github.com/) (Must be authenticated: `gh auth login`)

## Usage

### Direct CLI Option
```bash
./archive.sh \
  --url "https://fan60.princeton.edu" \
  --repo "pu-orfe/fan60" \
  --bypass "your-secret-bypass-header-value"
```

### Interactive Mode
Simply run the script with no arguments, and it will prompt you for the required fields:
```bash
./archive.sh
```

If you select `y` for the bypass header prompt, it will hide your input as you type to keep the secret secure.

### Command Line Arguments

| Argument | Shorthand | Description | Default |
|----------|-----------|-------------|---------|
| `--url` | `-u` | The target URL to mirror | (Required) |
| `--repo` | `-r` | GitHub repository format: `owner/repo` | (Required) |
| `--bypass` | `-b` | Bot bypass header value (for `x-wdsoit-bot-bypass`) | Optional |
| `--output` | `-o` | Output directory name for the mirror files | `dist` |
| `--assets` | `-a` | Comma-separated asset domains allowed | `*.princeton.edu` |
