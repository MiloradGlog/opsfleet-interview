# Opsfleet — AI Data Analysis Chat Assistant

This repository is my submission for the **Opsfleet AI technical assignment**: design a production-ready data-analysis chat assistant for non-technical retail managers, and build a working prototype.

## What's inside

- **[`design/`](./design)** — the full **High-Level Design**. Start with **[`04_System_Design.md`](./design/04_System_Design.md)** (the production HLD with architecture diagrams and the detailed technical explanation); the brief and the vision / requirements / use-case documents that lead up to it sit alongside it.
- **[`prototype/`](./prototype)** — the working, dockerized **CLI prototype**. Its **setup and run instructions are in [`prototype/README.md`](./prototype/README.md)** (one `docker compose` command, plus the two Google credentials it needs).

## Viewing the design docs with zoomable diagrams (optional)

The design documents are Mermaid-heavy. To browse them in a viewer with pan/zoom, serve this folder and open it in a browser:

```bash
python3 -m http.server 8765
```

Then open **http://localhost:8765/** (it redirects to the design viewer). Pick any free port if 8765 is taken.
