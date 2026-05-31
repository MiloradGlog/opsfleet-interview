# Retail Data Agent

Ask about sales in plain English; get a written report from read-only SQL.

```mermaid
flowchart LR
    CLI["Python CLI agent"]
    PG[("Postgres + pgvector")]
    BQ[("Google BigQuery")]
    AI["Google AI · Gemini"]
    CLI <--> PG
    CLI --> BQ
    CLI --> AI
```

```mermaid
flowchart TB
    U([User]) --> AG
    subgraph AG["Agent loop"]
        M["Gemini + middleware"] --> T["tools"]
        T --> M
    end
    T -->|query_data| SG
    subgraph SG["Analysis subgraph"]
        R["retrieve trios"] --> G["generate SQL"] --> V["validate"] --> E["execute BigQuery"]
        V -->|invalid| P["repair"]
        E -->|error / empty| P
        P --> V
    end
    AG --> OUT([Report])
```

## Setup

1. A GCP project with the **BigQuery API enabled**.
2. A service-account key with the **BigQuery Job User and BigQuery Data Viewer** roles.
3. Paste your Gemini API key into `.env`: `GOOGLE_API_KEY=...`
4. Drop the service-account key at `secrets/gcp.json`.

```bash
docker compose run --rm agent          # builds, starts Postgres, opens the chat CLI
```

Type your questions at the `you>` prompt; `exit` to quit. Add `--user <name>` to scope a personal report library (e.g. `docker compose run --rm agent --user alice`).
