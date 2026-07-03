---
kind: build_system
name: No build system present
category: build_system
scope:
    - '**'
---

This repository contains no build system, packaging, or deployment configuration. It is a minimal Node.js scraper consisting of a single script (`scrape_cfcpn.js`) and an empty `test.py`, with no Makefile, Dockerfile, CI pipeline, package manifest (package.json), requirements file, or any other build/automation artifacts. The project is intended to be run directly via `node scrape_cfcpn.js` without compilation, bundling, or containerization.