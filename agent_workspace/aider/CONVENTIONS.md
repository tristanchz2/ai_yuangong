# Aider Conventions — Scraper Development

## Editing Scope (STRICT)

You are ONLY allowed to:
1. **CREATE** a new scraper file: `scrapers/scrape_<site_name>.js`
2. **EDIT** `run.py` — to register the new scraper (add a `register()` call and a `<site>_run()` function)

You MUST NOT edit any other files. Treat all existing scrapers, utilities, and configs as **read-only references**.

---

## Scraper Architecture Pattern

Every scraper MUST follow this structure (study existing scrapers in `scrapers/` for reference):

### File location
- `scrapers/scrape_<site_name>.js` — one file per website

### Required utilities
```js
const { stripHtml } = require('./utility/stripHtml');
const { JsonWriter } = require('./utility/JsonWriter');
```

### Output path
```js
const OUTPUT_JSON = path.join(__dirname, '..', '..', 'raw_data', '<site_name>_data.json');
```

### CLI arguments (must support all three)
- `--latest N` — scrape the latest N items (default 5, for testing)
- `--yesterday` — scrape items published yesterday (production mode)
- `--date YYYY-MM-DD` — scrape items for a specific date

### Output schema (each row passed to `writer.addRow()`)
```js
{
  publishTime: '...',   // formatted publish time string
  title: '...',         // announcement title
  content: '...',       // plain text (use stripHtml on HTML content)
  sourceUrl: '...',     // link to the original page
  // additional fields as needed (branch, projType, status, etc.)
}
```

### JsonWriter usage
```js
const writer = new JsonWriter(OUTPUT_JSON, {
  source: '网站名称',
  scrapeTime: new Date().toISOString(),
});
writer.addRow({ ... });  // writes to disk immediately — crash-safe
```

### Required patterns
- **Retry with backoff**: wrap API calls in a `requestWithBackoff()` function
- **Sleep between requests**: `await sleep(1500)` between detail fetches
- **Incremental writes**: use `JsonWriter` so data is saved as each item is scraped

---

## Registering in run.py

After creating the scraper, add to `run.py`:

1. A `<site>_run()` function following the existing pattern:
```python
def <site>_run(args, capture=False):
    cmd = build_node_cmd('scrape_<site_name>.js')
    if args.yesterday:
        cmd.append('--yesterday')
    else:
        cmd += ['--latest', str(args.latest)]
    return run_script(cmd, '<site_name>', capture=capture)
```

2. A `register()` call:
```python
register('<site_name>', '网站中文名 (SITE_NAME) 公告类型爬虫', <site>_run)
```

Place both **above** the `# ---- 新增爬虫在此处添加 ----` comment (or replace it).

---

## Browser Recon Workflow

Before writing code, use the `browser_recon` tool to explore the target website:

1. Write a prompt to a temp file describing what to observe (page structure, API calls, pagination, data fields)
2. Call `browser_recon` with `prompt_file` and `output_file`
3. Read the output to understand the site structure
4. Look at network requests to find API endpoints — prefer API-based scraping over HTML parsing

### Example recon prompt
```
Go to https://example.com/announcements
1. Observe the page structure — how are announcements listed?
2. Open browser DevTools Network tab and look for API/XHR requests
3. Click "next page" or scroll down to trigger pagination requests
4. Click on one announcement to see the detail page
5. Report: API endpoints found, request methods, request/response schemas, pagination logic, and the data fields available
```

---

## Reference Files (read-only)

Study these before writing your scraper:
- `scrapers/scrape_icbc.js` — clean API-based scraper example
- `scrapers/utility/JsonWriter.js` — incremental JSON writer
- `scrapers/utility/stripHtml.js` — HTML to plain text converter
- `run.py` — scraper registration and CLI entry point
