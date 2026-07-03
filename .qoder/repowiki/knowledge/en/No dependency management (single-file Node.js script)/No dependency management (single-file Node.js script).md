---
kind: dependency_management
name: No dependency management (single-file Node.js script)
category: dependency_management
scope:
    - '**'
source_files:
    - scrape_cfcpn.js
---

This repository contains a single self-contained Node.js script (`scrape_cfcpn.js`) that performs HTTP requests using only the Node.js built-in `http`, `fs`, and `path` modules. There is no `package.json`, `yarn.lock`, `pnpm-lock.yaml`, or any other dependency manifest, nor any vendoring strategy, private registry configuration, or lockfile. The Python file `test.py` is empty. Consequently, there is no third-party dependency management system in place — all functionality relies exclusively on Node.js core APIs.