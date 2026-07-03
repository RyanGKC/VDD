# Web Search Tool (`web_search_tool.py`)

## Purpose
`web_search_tool.py` is a specialized, error-resilient search tool designed explicitly for autonomous AI agents. Unlike standard search APIs that just return URLs and short snippets, this tool acts as a complete end-to-end research pipeline. 

Its primary goals are to:
1. **Filter Out Noise:** Enforce a strict domain allowlist so agents are not fed low-quality SEO spam or hallucinated facts from unverified blogs.
2. **Handle Scraping Resiliently:** Automatically bypass broken links or anti-bot protections (like `403 Forbidden` errors) by smoothly moving to the next reliable source until the quota is filled.
3. **Provide Dual-Format Context:** Serve the scraped content to the AI agent in two distinct formats simultaneously: a fast-reading flattened truncation, and a high-level LLM summary.

---

## Architecture Flow

The tool operates on a cohesive, sequential pipeline encapsulated entirely within the `search_web()` orchestrator function.

### 1. The Candidate Pool (Find)
Because DuckDuckGo search requests are blocking (sync) while HTTP scraping is non-blocking (async), the tool begins by running `DDGS().text()` inside a background thread (`asyncio.to_thread`). 
It pulls a large upfront pool of up to 100 candidate search results using the `auto` backend.

### 2. The Filter (Assess)
The tool loops sequentially through the candidate pool. Every URL is immediately passed to `is_reliable(url)` (from `source_reliability.py`).
- If the domain matches the strict allowlist (e.g., `wsj.com`, `reuters.com`) or a high-trust TLD (`.gov`, `.edu`), it proceeds.
- If not, the URL is logged and dropped immediately.

### 3. The Fetch (Scrape)
Once a reliable URL is identified, the `fetch_and_clean_html()` function attempts to download and extract the text:
1. **Request:** It uses `httpx.AsyncClient` with a standard browser User-Agent.
2. **Primary Extraction:** It runs `trafilatura`, which is highly effective at stripping boilerplate and isolating the main article body.
3. **Fallback Extraction:** If `trafilatura` fails, it falls back to `BeautifulSoup` to manually strip `nav`/`footer`/`script` tags and extract text.
4. **Sanitization:** It uses `ftfy` and regex to clean up broken characters and normalize spacing.

*Resiliency Mechanism:* If the server blocks the request (e.g., a `403 Forbidden` or `Timeout`), this function catches the exception and returns `None`. The orchestrator sees this, logs the failure, and seamlessly moves to the next candidate in the pool without crashing.

### 4. The Processing (Truncate & Summarize)
When a scrape is successful, the raw text is processed in two ways to give the downstream AI agent maximum flexibility:
- **Truncated Content:** `flatten_text()` squashes all newlines and truncates the string to 5,000 characters. This is ideal for quick semantic scanning or injecting into prompt context without overflowing token limits.
- **Summarized Content:** `summarize_text()` passes the *entire* raw scraped text to `gemini-2.5-flash-lite`, instructing it to extract concrete facts, numbers, dates, and claims. This handles massive articles cleanly.

### 5. Early Exit & Telemetry
The sequential loop immediately halts the moment `len(enriched_results) == max_results`. 
Before returning the JSON payload to the agent, it appends a `run_statistics` dictionary containing the total execution time, the number of sites searched, dropped, failed, and successfully scraped. This provides total observability for the agent orchestrating the tool.
