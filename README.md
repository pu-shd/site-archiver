# Site Archiver 🌐

Site Archiver is a containerized automation tool designed to create 1-for-1 static mirrors of websites (e.g., CMS-backed sites that need to be archived) and deploy them to GitHub Pages.

## Features

- **Containerized Crawling**: Performs scraping and assets download inside an isolated Docker container, avoiding dependencies pollution on the host system.
- **Path Portability**: Converts all page links and assets to relative paths (`./path/to/asset`), meaning the static archive can be hosted in subfolders (like GitHub Pages) or even run locally by double-clicking `index.html`.
- **Asset Preservation**: Automatically fetches CSS, JS, images, source sets, fonts, and assets hosted on permitted subdomains (e.g. `*.princeton.edu`), preserving full style and layout.
- **Jekyll Bypass**: Automatically configures `.nojekyll` to ensure GitHub Pages serves directories starting with underscores (like `_assets/`).
- **JS Security Hardening**: Rewrites known-vulnerable CMS JavaScript as it is downloaded, so archived sites do not inherit findings that static analysis (CodeQL) reports on the published repository.
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

## JavaScript Security Hardening

The source CMS ships a few behaviours that are fine behind a server that controls its own markup, but that become reportable findings once the output is published as a static repository. Rather than fixing the same alerts by hand in every archived site, the archiver rewrites them as it downloads the JavaScript.

Currently patched:

| File | Finding | Rewrite |
|------|---------|---------|
| `random-image*.js` | DOM text reinterpreted as HTML | `data-src` / `data-srcset` are parsed and only `http(s)` URLs are assigned |
| `image_gallery*.js` | DOM text reinterpreted as HTML | Same URL validation, applied per `srcset` candidate |
| `content_list_a11y_enhancer*.js` | DOM text reinterpreted as HTML | Badge label built with `.text()` instead of string concatenation |
| `enhanced_date_field_formatter*.js` | DOM text reinterpreted as HTML | Link label set with `.text()` instead of string concatenation |
| `main-menu*.js` | DOM text reinterpreted as HTML | Menu label prepended as a text node |
| `core/misc/position.js` | Unsafe jQuery plugin | Plugin option is never passed to `$()` where it could parse as markup |

Patches are deliberately narrow and match specific upstream snippets. If upstream changes, a patch stops matching and the archiver prints a warning naming the file and the sink that survived, for example:

```
[!] WARNING: profiles/ps/.../random-image_x.js still contains a unvalidated lazy-load image URL.
    The upstream code likely changed; update JS_SECURITY_PATCHES.
```

Treat that warning as a build failure: update `JS_SECURITY_PATCHES` in `scraper.py` and add a case to `test_scraper.py` before publishing the archive.

## Running Tests

The suite runs in Docker so the host stays clean and CI matches local runs:

```bash
./run_tests.sh
```

To run in the project `.venv` instead (created on first use):

```bash
./run_tests.sh --local
```

CI runs the same containerized suite on every push and pull request to `main` (`.github/workflows/test.yml`), and additionally asserts that a plain `docker build` still produces the scraper runtime image.
