---
kind: error_handling
name: Simple Promise-based Error Handling with process.exit
category: error_handling
scope:
    - '**'
source_files:
    - scrape_cfcpn.js
---

The repository contains a single Node.js scraper script (`scrape_cfcpn.js`) with minimal, ad-hoc error handling. There is no dedicated error module, custom error types, or centralized error-handling framework.

**Approach used:**
- Network and parsing errors are handled via `try/catch` blocks around individual operations (e.g., JSON.parse inside `fetchPage`, the page-fetching loop in `main`).
- Rejected promises from `http.request` propagate through the promise chain and are caught by the top-level `main().catch(...)` handler at line 177–180, which logs the message to stderr and calls `process.exit(1)`.
- API-level failures (missing `result` field on the first-page response) are treated as fatal: the script prints an error to stderr and exits with code 1.
- Non-fatal issues (empty pages during pagination) are logged via `console.warn` and cause the loop to break gracefully rather than aborting the entire scrape.
- File I/O errors are not explicitly caught; any write failure would bubble up to the top-level `.catch`.

**Conventions observed:**
- Errors are represented as plain `Error` objects (no sentinel errors, no typed error classes).
- All terminal failures exit the process with `process.exit(1)` after logging to stderr — there is no retry/backoff logic, no structured logging, and no recovery strategy.
- The script uses synchronous `fs.writeFileSync` without error checks, so file-system errors will crash the process.