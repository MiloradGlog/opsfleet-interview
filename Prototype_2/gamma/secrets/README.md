# secrets/

Drop your **BigQuery service-account JSON key** here as `gcp.json`.

This folder's contents are gitignored (`.gitignore`) and excluded from the Docker
image (`.dockerignore`). Compose mounts it read-only at `/app/secrets:ro`, and the
agent reads it via `GOOGLE_APPLICATION_CREDENTIALS=/app/secrets/gcp.json`.

The service account needs `roles/bigquery.user` (or `roles/bigquery.jobUser`) on
the billing project so BigQuery jobs can run; the source dataset is the public
`bigquery-public-data.thelook_ecommerce`.
