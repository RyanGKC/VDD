# Web Search Tool (`web_search_tool.py`)

## Purpose
`web_search_tool.py` is a specialized, error-resilient search tool designed explicitly for autonomous AI agents. Unlike standard search APIs that just return URLs and short snippets, this tool acts as a complete end-to-end research pipeline.

Its primary goals are to:
1. **Filter Out Noise, Without Being Rigid:** Enforce a curated domain allowlist/blocklist for known sources, but route unfamiliar domains through an LLM-based trust evaluation instead of discarding them outright — so a legitimate niche or regional source isn't dropped just for being unlisted, while lookalike/impersonation domains are still caught.
2. **Rank Before Fetching:** Score candidates for relevance (blending an LLM judgment with embedding similarity) before spending time and money scraping them, so scraping effort is spent on the results most likely to matter.
3. **Handle Scraping Resiliently:** Automatically bypass broken links, anti-bot protection, and rate limits by retrying, impersonating a real browser's TLS fingerprint, and smoothly moving to the next candidate until the quota is filled.
4. **Handle Both HTML and PDFs:** Extract clean text from ordinary web pages as well as PDF documents, with safeguards for oversized or encrypted files.
5. **Summarize for the Agent:** Condense scraped content with an LLM into a fact-dense summary, rather than handing the agent raw or merely truncated page text.

---

## Architecture Flow

The pipeline is encapsulated in `search_web()`, which delegates to the `_orchestrate_search()` orchestrator. It is not a simple linear "find → filter → fetch" loop — several stages run concurrently or adaptively.

### 0. Load Dynamic Trust Lists (Warm Start)
Before searching, the orchestrator reads previously-cached domain evaluations (`eval_cache`, TTL 60 days) and splits them into an in-memory `dynamic_allow` and `dynamic_block` set. This means a domain the LLM evaluator judged trustworthy (or untrustworthy) in a past run doesn't need to be re-evaluated — it's treated like a static allow/block entry for this run too.

### 1. Initial Search + Concurrent Query Expansion Kickoff
The orchestrator fires two things at once:
- A DuckDuckGo search (`DDGS().text()`, run in a background thread via `asyncio.to_thread` since it's blocking) for the **original query only**, pulling a pool of up to 100 candidates (`min(100, max(30, max_results * 10))`).
- A background task calling `expand_query()` (see below), so the LLM-generated query variants are ready by the time they're needed, without adding latency if they turn out not to be needed.

### 2. Bucket by Trust Tier
Every result from the initial search is passed to `check_tier()` (`source_reliability.py`), which checks the URL's domain against:
- The company's own resolved domain (if provided) — always `allow`.
- High-trust TLDs (`.gov`, `.gov.uk`, `.edu`, `.ac.uk`) — always `allow`.
- The static `ALLOWLIST` / `BLOCKLIST`, and the dynamic sets loaded in step 0 — `allow` or `block` accordingly (checked against successive domain suffixes, e.g. `sub.example.co.uk` → `example.co.uk` → `co.uk`).
- Anything matching none of the above → `unknown`.

Results land in an `allowed` bucket, a `block`ed (dropped) bucket, or an `unknown` bucket — **unknown is not dropped**, it's held for LLM evaluation later in the pipeline (step 5).

### 3. Adaptive Query Expansion (conditional)
If the `allowed` bucket has fewer than `max_results * 2` candidates, the orchestrator awaits the query-expansion task kicked off in step 1. `query_expansion.py`'s `expand_query()` asks Gemini (`gemini-2.5-flash-lite`) for 3 alternative phrasings biased toward how specialist analysis content (industry reports, competitor comparisons, market share breakdowns) is actually titled — not just generic company-profile phrasing. On failure, it fails open and returns just the original query.

Those 3 variants are then searched with `_search_and_merge()`, which:
- Runs each variant's DDG search **staggered** by 1 second to avoid DuckDuckGo's burst rate limiter
- Uses a short 15s timeout and a single retry with a flat 2s backoff per variant, so a throttled variant is dropped quickly rather than stalling the whole batch.

New results are bucketed the same way as step 2 and merged in. If expansion wasn't needed, the pending task is simply cancelled.

### 4. Cap and Pre-rank Candidates
Before any LLM calls, both the `allowed` and `unknown` buckets are capped to `max(20, max_results * 4)` candidates each, using a cheap, free heuristic (`_cheap_prerank_score`: count of query words appearing in the title/snippet) to keep the best rough matches. This bounds how many candidates go through the expensive LLM/embedding stages next.

### 5. Batched Embeddings, Then Concurrent Relevance Scoring + Domain Evaluation
- A single batched Gemini embedding call computes embeddings for the query and every remaining candidate's `title + snippet` text at once (avoiding N separate embedding calls).
- Two fan-outs then run **concurrently**:
  - **Relevance scoring** (`relevance_scorer.py`, `score_relevance()`) for every already-`allowed` candidate. Each result gets a score that blends an LLM judgment (60%) — which rates how directly the result answers the *specific* question, not just topical relatedness — with cosine similarity between the pre-computed embeddings (40%, rescaled from an empirically observed 0.4–0.9 similarity band into 0–100).
  - **Domain evaluation** (`domain_evaluator.py`, `evaluate_domain()`) for every `unknown`-tier candidate. Gemini is given only the domain, URL, title, and snippet (no page content) and asked to classify trust level, category, and whether the domain *resembles* a known institution without matching it (a lookalike/impersonation flag). Paywalled report-selling domains are explicitly instructed to be rated low trust. If the model flags impersonation but doesn't rate it low, the code force-overrides the rating to `low`. Results are cached for 60 days (feeding step 0 on future runs), and on evaluation failure the domain fails **closed** (treated as low trust) rather than being let through.
- Domains newly accepted (`trust_level` high or medium) are added to `dynamic_allow`, logged, and relevance-scored using the embeddings already computed in this batch. Rejected domains are added to `dynamic_block`.
- All scored candidates (originally-allowed + newly-accepted) are merged and sorted by relevance score, descending.

### 6. Fetch and Summarize
Sorted candidates are processed in batches of `max_results + 2`, with a per-domain `asyncio.Semaphore(2)` limiting concurrent requests to any single domain. A single `curl_cffi.AsyncSession` (with `impersonate="chrome"`, i.e. TLS/JA3 browser fingerprint impersonation, not just a User-Agent header) is shared across the batch for connection pooling.

For each candidate, `fetch_and_clean_html()`:
- Fetches the URL with retry logic (`retry_async`).
- If `Content-Length` exceeds 10MB, aborts and returns an error marker instead of downloading.
- **PDFs** (detected via `Content-Type` or `.pdf` extension): parsed with `pypdf`, page by page, in a background thread. Encrypted PDFs and parse failures return a distinct `__PDF_ERROR__` marker rather than crashing.
- **HTML**: parsed in a background thread — `trafilatura` first (best at stripping boilerplate), falling back to `BeautifulSoup` (stripping `script`/`style`/`nav`/`footer`/`header`/`aside`) if trafilatura returns nothing. Output is cleaned with `ftfy` (fixes mangled text encoding), stray list-marker lines are stripped, and whitespace is normalized.
- Any exception (403, timeout, connection error, etc.) is caught and returns `None`, which the orchestrator treats as a dropped candidate — it logs the failure and moves to the next one without crashing.

Successfully-extracted text (HTML or PDF) is passed to `summarize_text()`. Because the underlying Gemini LLM has a massive 1-million token context window, the **entire extracted text is sent without any truncation limits**. The LLM is instructed to read the entire document, extract concrete facts, numbers, dates, and claims, and omit boilerplate.

### 7. Early Exit
Within each batch, tasks are consumed via `asyncio.as_completed()` so results are collected as soon as they finish rather than waiting for the slowest one. The moment `len(enriched_results) == max_results`, remaining in-flight tasks in that batch are cancelled and the loop halts — no further batches are started.

### 8. Response and Telemetry
`search_web()` wraps the results in a `WebSearchResponse` (query, list of `{title, source_url, content, relevance_score, trust_tier}`, optional `error`) and returns it as a JSON string. A detailed `stats` dictionary is always computed internally — counts of allowlist/blocklist hits, domains accepted/rejected by LLM evaluation, sites dropped due to fetch errors, sites in final output, candidate counts before/after capping, whether adaptive expansion triggered, and per-phase timings (dynamic list load, initial search, adaptive expansion, embedding batch, LLM fan-out, fetch-and-summarize) — but it's only attached to the response as `debug_stats` **if `search_web()` is called with `debug=True`**; otherwise it's logged but omitted from the returned JSON.

---

## Calling Context: `perform_web_search()` in `real_tools.py`

`web_search_tool.py` is not the agent's only search backend, and nothing in this document runs unless it's actually selected by the caller. The real entry point the rest of the system calls is `perform_web_search(ctx, query)` in `real_tools.py`, which picks between three providers based on the `SEARCH_PROVIDER` environment variable (**default: `"custom"`**):

- **`"custom"`** → routes to this pipeline via a local `_try_custom()` helper, which imports and calls `search_web()`. **Strict failure mode:** if `_try_custom()` raises or returns nothing, `perform_web_search()` returns an error result immediately — it does **not** fall back to Exa or Tavily.
- **`"tavily"`** → calls the Tavily API directly; falls back to Exa on failure.
- Anything else (the catch-all branch, e.g. `"exa"`) → calls the Exa API directly; falls back to Tavily on failure.

Only the `"custom"` provider touches anything described elsewhere in this document. The Exa and Tavily paths bypass `web_search_tool.py`, `source_reliability.py`, `domain_evaluator.py`, `query_expansion.py`, and `relevance_scorer.py` entirely — they're direct third-party API calls with no domain allow/block logic, no LLM trust evaluation, and no relevance scoring.

**Response shape is not normalized across providers.** `real_tools.py` defines its own `WebSearchResponse`/`SearchResultSnippet` models (`search_results: [{title, snippet, url}]`), which is the shape Exa and Tavily are mapped into. The `"custom"` path, however, returns whatever JSON string `search_web()` produced, untouched — `{query, results: [{title, source_url, content, relevance_score, trust_tier}], error, debug_stats}`. That's a materially different schema (different key names, plus relevance/trust metadata Exa/Tavily don't have). Whatever consumes `perform_web_search()`'s output has to handle either shape depending on which provider actually served the request.

**Parameters actually used in production:** `_try_custom()` calls `search_web(query, max_results=5, company_domain=company_domain)`. `max_results` is hardcoded to 5 at this call site, and `debug` is never passed — so despite `search_web()` always computing the detailed stats dictionary internally, `debug_stats` comes back `None` on every real call through this path.

### How `company_domain` is actually populated — `website_resolver.py`'s real role
This is where `website_resolver.py` is actually used. It is **not** called from inside `web_search_tool.py`; it's called from `_try_custom()` in `real_tools.py`, one layer up:

1. If `ctx.company_details.website` isn't already set on the shared due-diligence context (`DDContext`), `_try_custom()` calls `resolve_company_website_with_overrides(company_name)` from `website_resolver.py`.
2. That function checks the hand-maintained `KNOWN_COMPANY_DOMAINS` override dict first; otherwise it searches `"{company_name} official website"` via DDG and scores candidates by name/domain similarity, TLD, and an aggregator blocklist (Bloomberg, Crunchbase, LinkedIn, Wikipedia, etc. — informative *about* a company, but never the company's own site) — returning a domain plus a confidence level (`high`/`low`/`none`).
3. **Only `"high"` confidence is trusted.** It's the only case that sets `ctx.company_details.website` (as `https://{domain}`). A `"low"` confidence result is logged along with its full candidate list and then discarded — it's never used to scope the search. A `"none"` result is just logged. This means an ambiguous or wrong domain can never make it into the trust pipeline.
4. Once `ctx.company_details.website` is set — from this call or a prior one, since it's cached on `ctx` for the rest of the run — `get_domain()` (`source_reliability.py`) extracts the bare domain from it.
5. That domain is passed as `search_web(..., company_domain=domain)`, where, per `check_tier()`, it is auto-`allow`ed in the trust-tiering step (Architecture Flow, step 2).
6. If resolution throws for any reason, the exception is caught and logged, and the search proceeds with `company_domain=None` — a failed resolution degrades gracefully rather than blocking or failing the search.

Because step 1 is gated on `ctx.company_details.website` being unset, `website_resolver.py` effectively runs **at most once per company per due-diligence run**, not once per individual search query.