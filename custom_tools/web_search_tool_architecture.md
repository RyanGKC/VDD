# Web Search Tool (`web_search_tool.py`)

## Purpose
`web_search_tool.py` is a specialized, error-resilient search pipeline designed explicitly for autonomous AI agents. Unlike standard search APIs that return only URLs and short snippets, this tool acts as a complete end-to-end research pipeline.

Its primary goals are to:
1. **Filter Out Noise, Without Being Rigid:** Enforce a curated domain allowlist/blocklist for known sources, but route unfamiliar domains through an LLM-based trust evaluation instead of discarding them outright — so a legitimate niche or regional source isn't dropped just for being unlisted, while lookalike/impersonation domains are still caught.
2. **Rank Before Fetching:** Score candidates for relevance (blending an LLM judgment with embedding similarity) before spending time and money scraping them, so scraping effort is spent on the results most likely to matter.
3. **Handle Scraping Resiliently:** Automatically bypass broken links, anti-bot protection, and rate limits by retrying, impersonating a real browser's TLS fingerprint, and optionally escalating to a headless Playwright browser when curl fails.
4. **Handle Both HTML and PDFs:** Extract clean text from ordinary web pages as well as PDF documents, with safeguards for oversized or encrypted files.
5. **Summarize for the Agent:** Condense scraped content with an LLM into a fact-dense summary, rather than handing the agent raw or truncated page text.

---

## Architecture Flow

The pipeline is encapsulated in `search_web()`, which delegates to the `_orchestrate_search()` orchestrator. It is not a simple linear "find → filter → fetch" loop — several stages run concurrently or adaptively.

```
┌─────────────────────────────────────────────────────────┐
│                    _orchestrate_search                  │
│                                                         │
│  0. Load dynamic allow/block from eval_cache (warm start)
│         │                                               │
│  1. ┌───┴────────────────────────────────┐              │
│     │ Fire expand_query as background    │              │
│     │ task (runs concurrently with DDG)  │              │
│     └───┬────────────────────────────────┘              │
│         │                                               │
│  2. Initial DDG search (original query only)            │
│         │                                               │
│  3. Bucket results → allow / unknown / blocked          │
│         │                                               │
│  4. If not enough allowed:                              │
│         └── Await expansion variants → search them      │
│             staggered → bucket again                    │
│                                                         │
│  5. Cap + cheap pre-rank both buckets                   │
│         │                                               │
│  6. Chunk texts → embed concurrently (10/chunk)         │
│         │                                               │
│  7a. Await batch_evaluate_domains (unknown bucket)      │
│         └── Promote accepted unknowns → allowed bucket  │
│  7b. Await batch_score_all_relevance (all allowed)      │
│         (sequential after 7a — see note below)          │
│         │                                               │
│  8. Sort by blended relevance score (60% LLM, 40% cosine)
│         │                                               │
│  9. Fetch + Summarize via as_completed, early exit      │
└─────────────────────────────────────────────────────────┘
```

> **Note on steps 7a and 7b:** Domain evaluation and relevance scoring are **sequential**, not concurrent. Domain evaluation completes first so that newly-accepted unknown domains can be promoted into the allowed list before relevance scoring begins. This means the allowed list scored in 7b includes both originally-allowed snippets and any newly-promoted ones.

---

## Step-by-Step Description

### 0. Load Dynamic Trust Lists (Warm Start)
Before searching, the orchestrator reads previously-cached domain evaluations from `eval_cache` (a `PersistentCache` instance shared with `domain_evaluator.py`, using a 60-day TTL) and splits them into an in-memory `dynamic_allow` and `dynamic_block` set. A domain the LLM evaluator judged trustworthy (or untrustworthy) in a past run is treated like a static allow/block entry for this run — no re-evaluation needed.

### 1. Initial Search + Concurrent Query Expansion Kickoff
The orchestrator fires two things at once:
- A `asyncio.create_task` for `expand_query()` (see below), so LLM-generated query variants are ready by the time they're needed, without adding latency if they turn out not to be needed.
- A DuckDuckGo search for the **original query only** via `_search_and_merge([query])`, pulling a pool of up to `max(15, max_results * 3)` candidates.

**DDGS concurrency control:** A global `_GLOBAL_DDGS` instance is reused across all searches to share TLS sessions and HTTP connections. A `_ddgs_sem` asyncio semaphore (default: 2, configurable via `WEB_SEARCH_CONCURRENCY_LIMIT` env var) limits how many DDG searches can run concurrently. Each variant's DDG call is run in a background thread via `asyncio.to_thread` since the `duckduckgo_search` library is synchronous.

### 2. Bucket by Trust Tier
Every result from the initial search is passed to `check_tier()` (`source_reliability.py`), which checks the URL's domain against:
- The company's own resolved domain (if provided) — always `allow`.
- High-trust TLDs (`.gov`, `.gov.uk`, `.edu`, `.ac.uk`) — always `allow`.
- The static `ALLOWLIST` / `BLOCKLIST` and the dynamic sets loaded in step 0 — `allow` or `block` accordingly (checked against successive domain suffixes, e.g. `sub.example.co.uk` → `example.co.uk` → `co.uk`).
- Anything matching none of the above → `unknown`.

Results land in an `allowed` bucket, a `blocked` (silently dropped) bucket, or an `unknown` bucket. **Unknown is not dropped** — it's held for LLM evaluation later (step 7a).

### 3. Adaptive Query Expansion (conditional)
If the `allowed` bucket has fewer than `max_results * 2` candidates, the orchestrator awaits the expansion task from step 1. `expand_query()` (`query_expansion.py`) asks Gemini (`gemini-2.5-flash-lite`) for 3 alternative phrasings biased toward how specialist analysis content (industry reports, competitor comparisons, market share breakdowns) is actually titled — not just generic company-profile phrasing. On failure, it fails open and returns just the original query.

Those 3 variants are searched via `_search_and_merge(variants[1:])` (the original query is skipped since it was already searched), which:
- **Staggerers launches** by 1 second between variants (`i * STAGGER_SECONDS`) to avoid DuckDuckGo's burst rate limiter.
- Uses 2 attempts per variant with a flat 2s backoff, so a throttled variant is dropped quickly rather than stalling the pipeline.

New results are bucketed the same way as step 2 and merged into the existing buckets. If expansion wasn't needed, the background task is simply cancelled.

### 4. Cap and Cheap Pre-rank
Before any LLM or embedding calls, both the `allowed` and `unknown` buckets are capped to `max(20, max_results * 4)` candidates each. A cheap, free heuristic (`_cheap_prerank_score`: count of query words appearing in the title/snippet) selects the best candidates within each bucket, bounding how many go through the expensive stages next.

### 5. Concurrent Chunked Embedding
- **All texts** (query + all candidate title/snippet pairs from both `allowed` and `unknown` buckets) are assembled into a single list.
- This list is **chunked into groups of 10** and each chunk is embedded in a separate `gemini.embed_content()` call.
- All chunk calls fire **concurrently via `asyncio.gather`**, then the results are flattened back into a single `all_embeddings` list.
- `all_embeddings[0]` is the query embedding; subsequent entries map 1:1 to candidates by position.
- A `snippet_embedding_map` dict `{url → embedding}` is built for fast lookup during relevance scoring.

Using concurrent chunks instead of a single massive call avoids the sequential-processing bottleneck that Vertex AI applies to very large single-batch embedding requests.

### 6. Domain Evaluation (unknown bucket)
`batch_evaluate_domains()` (`domain_evaluator.py`) processes the unknown bucket:

1. **Cache check first:** For each unknown snippet, the domain is extracted and checked against `eval_cache`. Cache hits bypass the LLM call entirely.
2. **Deduplication:** Multiple snippets from the same domain are collapsed to a single entry before any LLM call — so if 10 snippets share the same unknown domain, only 1 LLM evaluation is made.
3. **Batched LLM evaluation:** Remaining uncached unique domains are chunked into groups of 12 and evaluated concurrently. Each chunk sends the domain, URL, title, and snippet (no page content) to Gemini and asks for: `trust_level` (high/medium/low), `category`, a one-line `rationale`, and whether the domain `resembles_known_entity` (impersonation flag).
4. **Impersonation override:** After each chunk returns, `apply_impersonation_override()` force-sets `trust_level = "low"` for any domain where `resembles_known_entity=True` but the model didn't rate it low (catches cases like `reuters-daily.com` being given medium trust).
5. **Per-chunk fallback:** If a chunk LLM call fails entirely, all domains in that chunk are assigned `trust_level = "low"` (fail-closed), not dropped from the run.
6. **Cache write:** All newly-evaluated domains are cached per-domain (not as a batch blob) at their individual `domain_eval:{domain}` key with a 60-day TTL.
7. **Promotion:** Domains with `trust_level` in (`"high"`, `"medium"`) are added to `dynamic_allow` and their corresponding snippets are appended to `allowed_snippets`. Rejected domains are added to `dynamic_block`.

### 7. Relevance Scoring (all allowed snippets)
`batch_score_all_relevance()` (`relevance_scorer.py`) processes all allowed snippets (including any newly-promoted ones from step 6):

1. Each snippet is assigned a sequential integer `index` field (used for reconciliation).
2. Snippets are chunked into groups of 12 and sent concurrently to Gemini for LLM scoring. The LLM is instructed to score 0–100 on *how directly* the result answers the specific question asked — penalising generic profiles, stock-quote pages, and tearsheets in favour of specific analysis content.
3. Results are reconciled back to their input chunks by the `index` field (not by list position — the LLM is explicitly prompted to echo the index, preventing silent mis-attribution from reordering). Missing indices fall back to score 50.
4. **Semantic (embedding) scoring** runs concurrently alongside the LLM scoring: cosine similarity between the query embedding and each snippet's embedding, rescaled from the empirically-observed 0.4–0.9 band into 0–100.
5. The final relevance score is a **60/40 blend**: `int((llm_score * 0.6) + (semantic_score * 0.4))`.
6. All scored snippets are sorted descending by blended score.

### 8. Fetch and Summarize
Sorted candidates are processed in batches of `max_results + 2`. A single `curl_cffi.AsyncSession` (with `impersonate="chrome"`, i.e. TLS/JA3 browser fingerprint impersonation) is shared across all fetches for connection pooling. A per-domain `asyncio.Semaphore(2)` limits concurrent requests to any single domain.

For each candidate, `fetch_and_clean_html()`:
1. **Fetches via curl_cffi** with retry logic (`retry_async`).
2. **Size guard:** If `Content-Length` exceeds 10MB, aborts with a `__PDF_ERROR__` marker rather than downloading.
3. **PDFs** (detected via `Content-Type` or `.pdf` extension): parsed with `pypdf` in a background thread. Encrypted PDFs and parse failures return a `__PDF_ERROR__` marker rather than crashing.
4. **HTML**: First checked for bot-wall markers (e.g. "just a moment", "captcha", "access denied"). If the page is too short or contains bot-wall text, a **Playwright escalation** is triggered (if enabled via `PLAYWRIGHT_ESCALATION_ENABLED=true` env flag). Playwright launches a shared headless Chromium instance (managed by `get_browser()` / `shutdown_browser()`) with a semaphore limiting concurrent browser contexts (`PLAYWRIGHT_MAX_CONTEXTS`, default: 4). On success, the rendered page HTML is parsed; on failure, the curl_cffi result is used as fallback.
5. **HTML parsing** (for both curl and Playwright results): `trafilatura` first (best at stripping boilerplate), falling back to `BeautifulSoup` if trafilatura returns nothing. Output is cleaned with `ftfy` (fixes mangled encoding), stray list-marker lines are stripped, and whitespace is normalised. `<noscript>` tags are stripped before parsing to prevent SPA fallback content from polluting results.
6. Any unrecoverable failure returns `None`, which the orchestrator treats as a dropped candidate — logged and skipped without crashing.

Successfully-extracted text is passed to `summarize_text()`. The **entire extracted text is sent without truncation** (Gemini's 1M-token context window). The model is instructed to extract concrete facts, numbers, dates, and claims while omitting boilerplate.

### 9. Early Exit
Within each batch, tasks are consumed via `asyncio.as_completed()` so results are collected as soon as they finish. The moment `len(enriched_results) == max_results`, remaining in-flight tasks in that batch are cancelled and the loop halts — no further batches are started.

### 10. Response and Telemetry
`search_web()` wraps results in a `WebSearchResponse` (query, list of `{title, source_url, content, relevance_score, trust_tier}`, optional `error`) and returns it as a JSON string.

A detailed `stats` dict is always computed internally — counts of allowlist/blocklist hits, domains accepted/rejected by evaluation, sites dropped due to errors, sites in final output, candidate counts before/after capping, whether adaptive expansion triggered, and per-phase timings — but it is only attached to the response as `debug_stats` if `search_web()` is called with `debug=True`. Otherwise it is logged but omitted from the JSON.

---

## Calling Context: `perform_web_search()` in `real_tools.py`

`web_search_tool.py` is not the agent's only search backend. The real entry point the rest of the system calls is `perform_web_search(ctx, query)` in `real_tools.py`, which picks between three providers based on the `SEARCH_PROVIDER` environment variable (**default: `"custom"`**):

- **`"custom"`** → routes to this pipeline via a local `_try_custom()` helper. **Strict failure mode:** if `_try_custom()` raises or returns nothing, `perform_web_search()` returns an error result immediately — it does **not** fall back to Exa or Tavily.
- **`"tavily"`** → calls the Tavily API directly; falls back to Exa on failure.
- Anything else (e.g. `"exa"`) → calls the Exa API directly; falls back to Tavily on failure.

Only the `"custom"` provider touches `web_search_tool.py`, `source_reliability.py`, `domain_evaluator.py`, `query_expansion.py`, and `relevance_scorer.py`. The Exa and Tavily paths bypass all of this entirely.

**Response shape is not normalised across providers.** `real_tools.py` defines `WebSearchResponse`/`SearchResultSnippet` models (`search_results: [{title, snippet, url}]`). The `"custom"` path returns whatever JSON string `search_web()` produced, untouched — `{query, results: [{title, source_url, content, relevance_score, trust_tier}], error, debug_stats}` — which is a materially different schema. Whatever consumes `perform_web_search()`'s output has to handle either shape depending on which provider served the request.

**Parameters in production:** `_try_custom()` calls `search_web(query, max_results=5, company_domain=company_domain)`. `max_results` is hardcoded to 5, and `debug` is never passed — so `debug_stats` is always `None` in real agent calls.

### How `company_domain` is populated — `website_resolver.py`

`website_resolver.py` is called from `_try_custom()` in `real_tools.py`, one layer above this pipeline:

1. If `ctx.company_details.website` is not set, `_try_custom()` calls `resolve_company_website_with_overrides(company_name)`.
2. That function checks a hand-maintained `KNOWN_COMPANY_DOMAINS` dict first; otherwise it searches `"{company_name} official website"` via DDG and scores candidates by name/domain similarity, TLD, and an aggregator blocklist (Bloomberg, LinkedIn, Wikipedia, etc.).
3. **Only `"high"` confidence results are used.** A `"low"` confidence result is logged and discarded — never used to scope the search. A `"none"` result is just logged.
4. Once `ctx.company_details.website` is set, `get_domain()` extracts the bare domain, which is passed as `company_domain` to `search_web()`, where `check_tier()` auto-allows it.
5. Resolution failures are caught and logged — the search proceeds with `company_domain=None`.
6. Because step 1 is gated on `ctx.company_details.website` being unset, `website_resolver.py` runs **at most once per company per due-diligence run**.

---

## Key Configuration (Environment Variables)

| Variable | Default | Effect |
|---|---|---|
| `SEARCH_PROVIDER` | `"custom"` | Selects search backend in `real_tools.py` |
| `WEB_SEARCH_CONCURRENCY_LIMIT` | `2` | Max concurrent DDG searches (`_ddgs_sem`) |
| `PLAYWRIGHT_ESCALATION_ENABLED` | `"false"` | Enable headless browser fallback for bot-walled pages |
| `PLAYWRIGHT_MAX_CONTEXTS` | `4` | Max concurrent Playwright browser contexts |

---

## Module Map

| Module | Role |
|---|---|
| `web_search_tool.py` | Orchestrator, fetch/parse logic, Playwright escalation |
| `query_expansion.py` | LLM-based query variant generation |
| `source_reliability.py` | Static allow/block lists, `check_tier()`, `get_domain()` |
| `domain_evaluator.py` | LLM-based domain trust evaluation, 60-day cache |
| `relevance_scorer.py` | Batched LLM + cosine similarity relevance scoring (60/40 blend) |
| `website_resolver.py` | Company official website resolution (called from `real_tools.py`) |
| `core/gemini_client.py` | Shared Gemini API client, semaphore-based rate limiting, token refresh |
| `core/cache.py` | Persistent SQLite-backed cache used by `domain_evaluator` and `gemini_client` |