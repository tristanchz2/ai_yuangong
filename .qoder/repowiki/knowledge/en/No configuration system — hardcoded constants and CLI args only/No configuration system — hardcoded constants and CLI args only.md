---
kind: configuration_system
name: No configuration system — hardcoded constants and CLI args only
category: configuration_system
scope:
    - '**'
source_files:
    - scrape_cfcpn.js
---

This repository contains a single-purpose Node.js scraper (`scrape_cfcpn.js`) with no dedicated configuration system. All runtime settings are embedded directly in the source as module-level constants:

- `API_URL` — target endpoint URL (line 15)
- `PAGE_SIZE` — number of records per request (line 16)
- `OUTPUT_JSON`, `OUTPUT_CSV` — output file paths, derived from `__dirname` (lines 17–18)
- HTTP headers, form fields, sleep interval (500 ms), and CSV BOM handling are all literal values inside functions.

The only external input mechanism is a positional command-line argument (`process.argv[2]`) controlling how many pages to scrape: an integer for a fixed page count, or the string `all` to paginate through every available page. There is no `.env`, YAML/JSON/TOML config file, environment variable loading, feature-flag system, or secrets management.

Consequently, changing any behavior (endpoint, page size, output location, delay, headers) requires editing the script source and re-running it. The empty `test.py` file contributes nothing to configuration.