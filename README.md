# Site Archiver 🌐

Site Archiver is a containerized automation tool designed to create 1-for-1 static mirrors of websites (e.g., CMS-backed sites that need to be archived) and deploy them to GitHub Pages.

## Features

- **Containerized Crawling**: Performs scraping and assets download inside an isolated Docker container, avoiding dependencies pollution on the host system.
- **Path Portability**: Converts all page links and assets to relative paths (`./path/to/asset`), meaning the static archive can be hosted in subfolders (like GitHub Pages) or even run locally by double-clicking `index.html`.
- **Asset Preservation**: Automatically fetches CSS, JS, images, source sets, fonts, and assets hosted on permitted subdomains (e.g. `*.princeton.edu`), preserving full style and layout.
- **Jekyll Bypass**: Automatically configures `.nojekyll` to ensure GitHub Pages serves directories starting with underscores (like `_assets/`).
- **JS Security Hardening**: Rewrites known-vulnerable CMS JavaScript as it is downloaded, so archived sites do not inherit findings that static analysis (CodeQL) reports on the published repository.
- **Polite Crawling**: Spaces requests to the crawled site by a configurable delay (1 second by default).
- **Preservation Copies (optional)**: Records the raw crawl as a WARC (`--warc`) and/or captures a WACZ with headless Chromium via browsertrix-crawler (`--browsertrix`). Both play back in [ReplayWeb.page](https://replayweb.page/). The bypass header is never written into either.
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
| `--self-contain` | `-s` | Host jQuery/Bootstrap locally instead of using public CDNs | Off |
| `--delay` | `-d` | Minimum seconds between requests to the site (0-60) | `1` |
| `--warc` | `-w` | Also record the requests crawl as a `.warc.gz` | Off |
| `--browsertrix` | | Also capture a `.wacz` with browsertrix-crawler | Off |
| `--page-limit` | | Max pages for `--browsertrix` (`0` = unlimited) | `0` |
| `--archive-dir` | | Where WARC/WACZ files are written (never inside `--output`) | `archives/<repo>` |

## Crawl Throttling

Every request to the crawled site and its allowed asset domains waits until at least `--delay` seconds have passed since the previous one finished. The default of 1 second matches the common `wget --wait=1` convention; `--delay 0` disables throttling. Third-party CDN fetches are not throttled.

## Preservation Copies (WARC / WACZ)

The published mirror is an *access copy*: links are rewritten and JavaScript is hardened. The optional preservation copies keep what the server actually sent, so the site can be replayed or the mirror rebuilt after the original is gone. They are written to `--archive-dir`, outside the published repository.

### `--warc`: record the requests crawl

The crawler's own traffic is recorded with [warcio](https://github.com/webrecorder/warcio) to `<archive-dir>/<name>-<UTC timestamp>.warc.gz`. Every header supplied in the crawl configuration (such as the bypass header) is replaced with `[REDACTED]` in the request records, and the record digests are recomputed so the WARC stays valid.

### `--browsertrix`: capture with headless Chromium

For JavaScript-heavy sites, [browsertrix-crawler](https://github.com/webrecorder/browsertrix-crawler) (pinned to 1.15.4) captures a WACZ to `<archive-dir>/browsertrix/collections/<name>/<name>.wacz`. Requires `docker-compose`. It runs in addition to the normal mirror crawl, since GitHub Pages still needs the static mirror.

browsertrix-crawler has no option for custom request headers, so `browsertrix/docker-compose.yml` routes the browser through a small mitmproxy sidecar (`browsertrix/proxy/bypass_proxy.py`) that:

- adds the bypass header only to the target host and `--assets` domains, never to third parties;
- applies `--delay` to every request to those hosts; and
- validates its configuration before starting, so a bad setting stops the crawl.

The proxy adds the header after the browser has recorded the request, so it never appears in the WACZ. The value reaches the proxy as a Compose secret file, not an environment variable. Upstream TLS certificates are verified by the proxy.

Because the throttle applies to every asset, a page with ~100 assets takes a couple of minutes at the default delay. Use `--page-limit` for a quick test capture.

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

To also run the browsertrix end-to-end smoke test, which crawls a local HTTPS origin that returns 403 without the bypass header and checks the WACZ, the header delivery and the request spacing:

```bash
./run_tests.sh --integration
```

CI runs the same containerized suite on every push and pull request to `main` (`.github/workflows/test.yml`), and additionally asserts that a plain `docker build` still produces the scraper runtime image. A separate job runs the browsertrix smoke test.
