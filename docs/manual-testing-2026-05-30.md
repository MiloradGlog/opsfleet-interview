# Manual CLI Testing Report — 2026-05-30

**Subject:** `prototype/` Retail Data Analysis chat assistant
**Method:** the real CLI (`python -m retail_agent.cli`) driven over stdin with scripted keystrokes — i.e. exactly what a user types, including the deletion confirmation token entered at the interrupt prompt. Run live against **Gemini 3.5 Flash + BigQuery** (`thelook_ecommerce`), project `sila-394417`.
**Result:** ✅ all scenarios passed; no crashes, no stack traces, no unexpected behavior.

This complements the automated layers: 94 offline unit/integration tests (81% coverage) and a 7-category live API battery. This report covers **interactive CLI / user-experience** behaviors specifically.

## Scenario matrix

| # | Scenario | Session | Expected | Observed | Result |
|---|---|---|---|---|---|
| 1 | `/help` command | A | Prints usage banner | Banner shown | ✅ |
| 2 | Schema discovery ("what data can I ask about?") | A | Business-language answer, no SQL | Listed orders/customers/products/revenue areas | ✅ |
| 3 | Analytical ("top 5 products by revenue") | A | Ranked report from live data | Canada Goose Chateau Jacket $12,225 … | ✅ |
| 4 | Contextual save ("save **that** as 'Top products'") | A | Resolves "that" to prior report; saves | Saved #1 "Top products" | ✅ |
| 5 | `list my reports` | A | Shows #1 | Listed #1 | ✅ |
| 6 | Contextual follow-up ("what about **by category**?") | A | Uses thread memory; category breakdown | Full revenue-by-category report | ✅ |
| 7 | Delete with **approve** ("delete my reports about products" → token) | A | Interrupt → token `CONFIRM-DELETE-1` → soft-delete | Interrupt fired (`delete reports [1]`); token accepted; deleted | ✅ |
| 8 | `list` after delete | A | Empty | "no saved reports" | ✅ |
| 9 | Off-topic ("tell me a joke about dogs") | B | Polite decline + examples | Declined, offered valid questions | ✅ |
| 10 | Empty/nonexistent category revenue | B | Graceful "no data", no crash | "$0.00 … does not appear to have any sales" | ✅ |
| 11 | Save report ("Keep me") | B | Saved | Saved #2 "Keep me" | ✅ |
| 12 | Delete with **reject** (type `reject` at prompt) | B | Cancelled; nothing deleted | "Cancelled — no reports were deleted"; report retained | ✅ |
| 13 | `list` after reject | B | "Keep me" still present | Listed #2 "Keep me" | ✅ |
| 14 | Ownership on read — manager_b `list` | C | b sees none (a owns "Keep me") | "no saved reports" | ✅ |
| 15 | Ownership on delete — manager_b "delete … keep" | C | No match for b; **no interrupt**; nothing deleted | "couldn't find any reports matching keep" | ✅ |
| 16 | Persistence across restart + one-shot `--question` (manager_a) | C | "Keep me" still there in a new process | Returned #2 "Keep me" | ✅ |
| 17 | `--help` | C | argparse usage | Usage printed | ✅ |
| 18 | Empty line + EOF (Ctrl-D) | C | Blank ignored; clean exit | Exited cleanly, no error | ✅ |

## Behaviors specifically verified

- **Multi-turn thread memory** within a session: "save *that*" and "what about *by category*" both resolved against earlier turns (scenarios 4, 6).
- **HITL interrupt over the CLI**: the deletion pauses, the preview is rendered from the interrupt payload, and the typed `CONFIRM-DELETE-N` token is consumed from stdin like a real keystroke — both **approve** (7) and **reject** (12) paths.
- **Ownership scoping is real, not cosmetic**: manager_b cannot see (14) or delete (15) manager_a's report; the agent correctly does *not* even raise a confirmation when nothing matches the caller's own reports.
- **Persistence**: saved reports survive process restarts (SQLite), while conversation context correctly resets per process/thread (16). Autoincrement IDs continue past deleted rows (#1 deleted → next save is #2), confirming soft-delete rather than reuse.
- **Safety/scope**: off-topic requests are declined with guidance (9); earlier battery also confirmed prompt-injection ("say HACKED") and destructive-SQL ("delete all orders") are refused.
- **Robustness**: `/help`, `--help`, one-shot `--question`, empty input, and EOF all behave; no path produced a stack trace.

## Notes / limitations (by design)

- PII masking is intentionally out of scope for this prototype (documented in the README); customer names appear in "top customers" output. Re-enabling is a one-line `PIIMiddleware` addition.
- Free-tier Gemini rate limits can occasionally surface transient 429s; these are absorbed by `ModelRetryMiddleware` and were not observed to affect any scenario in this run.
