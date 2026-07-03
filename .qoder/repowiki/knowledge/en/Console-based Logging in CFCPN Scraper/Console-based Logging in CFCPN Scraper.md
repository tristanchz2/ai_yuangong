---
kind: logging_system
name: Console-based Logging in CFCPN Scraper
category: logging_system
scope:
    - '**'
source_files:
    - scrape_cfcpn.js
---

The CFCPN Procurement Notice Scraper employs a minimal, ad-hoc logging strategy using Node.js's built-in `console` object. There is no dedicated logging framework (such as `winston`, `pino`, or `bunyan`) or structured logging configuration.

### Approach
- **Standard Output**: Progress updates and success messages are printed to `stdout` using `console.log()` and `process.stdout.write()`.
- **Error Handling**: Errors and warnings are directed to `stderr` using `console.error()` and `console.warn()`.
- **No Persistence**: Logs are ephemeral and displayed only in the terminal during execution. They are not written to log files or external sinks.
- **No Structured Fields**: Log messages are simple strings with embedded variables (e.g., page numbers, counts). There is no JSON formatting, timestamping (beyond manual inclusion if needed), or log level metadata.

### Conventions
- **Progress Tracking**: The script uses a step-based format (e.g., `[1/3]`, `[2/3]`) to indicate major phases of the scraping process.
- **Visual Indicators**: Checkmarks (`✓`) and cross marks (`✗`) are used to visually denote success or failure of individual page requests.
- **Rate Limiting Feedback**: The script logs delays implicitly by showing progress over time, though the `sleep` function itself does not log.

### Developer Guidelines
- **Use `console.log` for Info**: For general progress and data confirmation.
- **Use `console.error` for Failures**: For API errors, parsing failures, or critical exceptions that may halt execution.
- **Use `console.warn` for Non-Critical Issues**: For unexpected but recoverable states, such as empty data pages.
- **Avoid External Dependencies**: The project intentionally avoids external logging libraries to maintain a zero-dependency footprint, relying solely on Node.js core modules (`http`, `fs`, `path`).