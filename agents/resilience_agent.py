# Operational Resilience and Supply Chain Risk.

from __future__ import annotations

from agents.base_agent import BaseResearchAgent
from core.models import (
    AnomalySignal, DDContext, Finding, Severity, SeverityLevel, Source,
    StepName, StepResult, parse_severity,
)
from core.tools import perform_web_search

SYSTEM_INSTRUCTION = """
You are a supply chain risk analyst. Evaluate the vendor's operational resilience, 
supply chain dependencies, and geographic exposure using the provided web search data.

Identify explicit supplier companies (Tier 1 or Tier 2 dependencies, manufacturing partners, logistics partners, etc.) mentioned in the text. 
CRITICAL: You must prioritize identifying the top, most critical suppliers (e.g. highest volume, strategic importance, or largest contracts). Output their details in the 'supply_items' list, ordered by importance.

If you discover a critical dependency on a high-risk or potentially sanctioned 
jurisdiction/entity that was not previously disclosed, set 'high_risk_dependency_found' 
to true and describe it.
"""

class ResilienceAgent(BaseResearchAgent):
    step = StepName.RESILIENCE

    async def research(self, ctx: DDContext) -> StepResult:
        import asyncio
        import json
        import hashlib
        
        company_name = ctx.company_details.company_name
        country = ctx.company_details.country or "unknown country"

        # Pull profile context if available
        profile_context = ""
        profile_result = ctx.results.get(StepName.PROFILE)
        if profile_result and profile_result.rationale:
            profile_context = f"\n\nProfile Agent Summary:\n{profile_result.rationale[:800]}"

        # --- Phase 1: Dual-track query planning ---
        plan_prompt = (
            f"Vendor: {company_name}\n"
            f"Country: {country}"
            f"{profile_context}\n\n"
            "Generate targeted search queries for two independent research tracks:\n"
            "1. SUPPLIER TRACK: Find named Tier-1 suppliers, logistics partners, or critical vendors "
            "for this company. Focus on annual reports, vendor disclosures, procurement news, or "
            "industry-specific supplier databases.\n"
            "2. RISK TRACK: Find operational disruptions, geopolitical risks, supply chain incidents, "
            "or cyber threats relevant to this company's country and industry."
        )

        plan = await self.gemini.generate_structured(
            system_instruction="You are a supply chain research planner. Generate precise, targeted web search queries.",
            prompt=plan_prompt,
            schema=_DualTrackPlan,
            enable_search=False
        )

        # Check if user wants to bypass supplier discovery
        skip_suppliers = ctx.tiers_to_search == 1
        
        if skip_suppliers:
            supplier_queries = []
        else:
            supplier_queries = plan.supplier_queries[:3]
            
        risk_queries = plan.risk_queries[:3]
        all_queries = supplier_queries + risk_queries

        # --- Phase 2: Fire all searches in parallel ---
        ctx.log(f"[RESILIENCE] Executing {len(all_queries)} parallel web searches (dual-track).")
        print(f"[RESILIENCE] Executing {len(all_queries)} parallel web searches (dual-track).")
        search_results = await asyncio.gather(
            *[perform_web_search(ctx, q) for q in all_queries],
            return_exceptions=True
        )

        url_map = {}
        
        def _merge_labelled_results(queries: list[str], results: list) -> str:
            sections = []
            for query, result in zip(queries, results):
                if isinstance(result, Exception) or not result:
                    sections.append(f"Query: {query}\nResult: [No results — search failed]")
                    continue
                try:
                    parsed = json.loads(result)
                    items = parsed.get("results", [])
                    lines = []
                    for r in items:
                        url = r.get("source_url") or r.get("url")
                        if url:
                            sid = f"src_{hashlib.md5(url.encode()).hexdigest()[:8]}"
                            url_map[sid] = url
                            r["source_id"] = sid
                        title = r.get('title', '')
                        content = r.get('content', '')
                        lines.append(f"- [{r.get('source_id', 'unknown')}] {title}: {content[:400]}")
                    text = "\n".join(lines)
                except (json.JSONDecodeError, AttributeError):
                    text = "[Parse error]"
                sections.append(f"Query: {query}\n{text}")
            return "\n\n".join(sections)

        # Label and merge results
        supplier_results_text = _merge_labelled_results(supplier_queries, search_results[:len(supplier_queries)])
        risk_results_text = _merge_labelled_results(risk_queries, search_results[len(supplier_queries):])

        # --- Phase 3: Combined final analysis ---
        analysis_prompt = (
            f"Vendor: {company_name}\n"
            f"Country: {country}\n\n"
            f"=== SUPPLIER DISCOVERY RESULTS ===\n{supplier_results_text}\n\n"
            f"=== RISK ASSESSMENT RESULTS ===\n{risk_results_text}\n\n"
            "Extract any explicitly named manufacturing or software suppliers from the SUPPLIER section. "
            "Assess operational and geopolitical risks from the RISK section.\n"
            "CRITICAL: If no third-party suppliers are explicitly identified, set "
            "has_identifiable_third_party_suppliers to false and leave supply_items EMPTY."
        )

        from rag.rate_limiter import run_foreground_generation
        analysis = await run_foreground_generation(
            lambda: self.gemini.generate_structured(
                system_instruction=SYSTEM_INSTRUCTION,
                prompt=analysis_prompt,
                schema=_ResilienceAnalysis,
                enable_search=False
            )
        )

        findings = [
            Finding(
                summary=f.summary,
                severity=parse_severity(f.severity),
                is_red_flag=f.is_red_flag,
                is_strength=f.is_strength,
                sources=[Source(title=s.title, url=url_map.get(s.source_id), publisher=s.publisher) for s in f.sources],
            )
            for f in analysis.findings
        ]

        current_suppliers = analysis.supply_items
        
        # --- NEW: Reverse Disclosure Loop ---
        max_nodes = getattr(ctx, 'max_suppliers_per_node', 3)
        if not skip_suppliers and len(current_suppliers) < max_nodes:
            attempts = 1
            previously_tried = set()
            while len(current_suppliers) < max_nodes and attempts < 3:
                missing = max_nodes - len(current_suppliers)
                new_suppliers, tried_this_loop = await self._run_reverse_disclosure_loop(ctx, missing, previously_tried)
                previously_tried.update(tried_this_loop)
                
                # Filter out duplicates
                existing_names = {s.supplier_name.lower() for s in current_suppliers}
                added_this_loop = []
                for s in new_suppliers:
                    if s.supplier_name.lower() not in existing_names:
                        current_suppliers.append(s)
                        existing_names.add(s.supplier_name.lower())
                        added_this_loop.append(s.supplier_name)
                        
                # Update rationale to reflect the new findings so it appears accurately in the audit log
                if added_this_loop:
                    analysis.rationale += f"\n\n[Update from Reverse Disclosure Loop]: Successfully identified additional suppliers: {', '.join(added_this_loop)}."
                        
                attempts += 1
                
            # Update the analysis object
            analysis.supply_items = current_suppliers[:max_nodes]
            if current_suppliers:
                analysis.has_identifiable_third_party_suppliers = True

        # --- Track 3: Document Deep-Dive (only if still no suppliers found) ---
        if not skip_suppliers and not current_suppliers:
            ctx.log("[RESILIENCE] Track 3 activated: No suppliers found via web search or reverse disclosure. Attempting document deep-dive.")
            doc_suppliers = await self._run_document_deep_dive(ctx, url_map)
            if doc_suppliers:
                analysis.rationale += f"\n\n[Update from Document Deep-Dive]: Extracted {len(doc_suppliers)} supplier(s) directly from official company documents."
                current_suppliers.extend(doc_suppliers[:max_nodes])
                analysis.supply_items = current_suppliers
                analysis.has_identifiable_third_party_suppliers = True
        # ------------------------------------

        # Derive suppliers from supply_items and inject into structured_data for compatibility
        structured_data = analysis.model_dump()
        structured_data["suppliers"] = [item.supplier_name for item in analysis.supply_items]

        result = StepResult(
            step=self.step,
            findings=findings,
            structured_data=structured_data,
            sources=[s for f in findings for s in f.sources],
            raw_data=None,
            rationale=analysis.rationale,
        )

        if analysis.high_risk_dependency_found and analysis.dependency_details:
            result.anomaly = AnomalySignal(
                raised_by=self.step,
                reason=f"High-risk supply chain dependency found: {analysis.dependency_details}",
                severity=Severity.MEDIUM,
                suggested_revisit=[StepName.SANCTIONS], 
                new_context={"supply_chain_risk": analysis.dependency_details},
            )

        return result

    async def _run_reverse_disclosure_loop(self, ctx: DDContext, missing_count: int, previously_tried: set[str]) -> tuple[list['_SupplierItem'], list[str]]:
        import asyncio
        from core.tools import perform_web_search
        
        exclusions = ""
        if previously_tried:
            exclusions = f" Do NOT list any of these companies, as they have already been evaluated: {', '.join(previously_tried)}."
            
        profile_context = ""
        profile_result = ctx.results.get(StepName.PROFILE)
        if profile_result and profile_result.rationale:
            profile_context = f"\n\nCompany Profile Context:\n{profile_result.rationale[:800]}"
            
        # 1. Ask LLM to brainstorm probable suppliers
        brainstorm_prompt = (
            f"The target company is {ctx.company_details.company_name}. "
            f"{profile_context}\n\n"
            f"Based on this company's profile and likely industry, list {missing_count * 2} highly probable supplier companies (by exact name). "
            f"If it is a retail, B2C, or consumer goods company, list major product brands, FMCG companies, or wholesale food distributors they likely stock. "
            f"If it is a software or B2B company, list cloud providers, critical software vendors, or infrastructure providers. "
            f"Do NOT list the company itself.{exclusions}"
        )
        
        brainstorm_result = await self.gemini.generate_structured(
            prompt=brainstorm_prompt,
            system_instruction="You are a supply chain expert. Provide highly educated guesses for suppliers.",
            schema=_SupplierBrainstorm,
            enable_search=False
        )
        
        if not brainstorm_result.probable_suppliers:
            return [], []
            
        # 2. Formulate concurrent search queries
        search_tasks = []
        from datetime import datetime, timezone
        for i, supplier_name in enumerate(brainstorm_result.probable_suppliers):
            query = f'("{ctx.company_details.company_name}") AND ("{supplier_name}") AND (supplier OR supplies OR distributor OR partner OR vendor OR "available at" OR stocks)'
            ctx.log(f"[{self.step.upper()}] Executing reverse disclosure search {i+1}/{len(brainstorm_result.probable_suppliers)}: '{query}'")
            search_tasks.append(perform_web_search(ctx, query))
            
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)
        
        # 3. Verify the results strictly
        verification_tasks = []
        for supplier_name, search_res in zip(brainstorm_result.probable_suppliers, search_results):
            if isinstance(search_res, Exception) or not search_res:
                continue
                
            # Parse JSON and flatten search results into a text block
            import json
            try:
                parsed_res = json.loads(search_res)
                # Support both 'results' (custom search) and 'search_results' (Exa/Tavily)
                results_list = parsed_res.get("results", parsed_res.get("search_results", []))
            except json.JSONDecodeError:
                continue
            
            # Support both 'content' and 'snippet' keys
            search_text = "\n".join([f"Title: {r.get('title')}\nSnippet: {r.get('content', r.get('snippet'))}" for r in results_list])
            
            verify_prompt = (
                f"Target Company: {ctx.company_details.company_name}\n"
                f"Probable Supplier: {supplier_name}\n"
                f"Search Results:\n{search_text}\n\n"
                "Review these web search results. ONLY confirm the supplier if the text explicitly states a relationship (customer, vendor, partnership, distributor, or a brand stocked/sold by the target). If it is completely ambiguous, reject it."
            )
            
            verification_tasks.append(
                self.gemini.generate_structured(
                    prompt=verify_prompt,
                    system_instruction="You are a strict supply chain auditor.",
                    schema=_SupplierVerification,
                    enable_search=False
                )
            )
            
        validations = await asyncio.gather(*verification_tasks, return_exceptions=True)
        
        confirmed_suppliers = []
        for v in validations:
            if not isinstance(v, Exception) and v.is_confirmed and v.supplier_item:
                confirmed_suppliers.append(v.supplier_item)
                
        return confirmed_suppliers, brainstorm_result.probable_suppliers

    async def _run_document_deep_dive(self, ctx: DDContext, url_map: dict[str, str]) -> list['_SupplierItem']:
        """
        Track 3: Extract suppliers from official company documents (prospectus, annual report).
        Called only when Track 1 + reverse disclosure loop are insufficient.
        """
        import asyncio
        from custom_tools.web_search_tool import fetch_and_clean_html
        from curl_cffi import requests as cffi_requests

        company_name = ctx.company_details.company_name

        # Step A: Find document URLs from existing search results
        # Prioritize PDFs already found in url_map, or run a targeted document search
        pdf_urls = [url for url in url_map.values() if url.lower().endswith(".pdf")]

        if not pdf_urls:
            # Run a targeted document discovery search
            doc_query = f'"{company_name}" (prospectus OR "annual report" OR "supplier disclosure") AND (filetype:pdf OR site:bursamalaysia.com OR site:sec.gov)'
            ctx.log(f"[RESILIENCE] Track 3: Searching for official documents with query: '{doc_query}'")
            from core.tools import perform_web_search
            search_res_str = await perform_web_search(ctx, doc_query)
            import json
            parsed = json.loads(search_res_str)
            results_list = parsed.get("results", parsed.get("search_results", []))
            for r in results_list:
                url = r.get("source_url") or r.get("url")
                if url and (url.lower().endswith(".pdf") or "prospectus" in url.lower() or "annual-report" in url.lower()):
                    pdf_urls.append(url)

        if not pdf_urls:
            ctx.log(f"[RESILIENCE] Track 3: No official documents found.")
            return []

        ctx.log(f"[RESILIENCE] Track 3: Found {len(pdf_urls)} document(s) to deep-dive. Extracting supplier names...")

        # Step B: Fetch and extract from each PDF (up to 2)
        all_suppliers = []
        async with cffi_requests.AsyncSession() as session:
            for url in pdf_urls[:2]:
                try:
                    ctx.log(f"[RESILIENCE] Track 3: Fetching document: {url}")
                    full_text = await fetch_and_clean_html(url, session, timeout=30)
                    if not full_text or full_text.startswith("__PDF_ERROR__"):
                        ctx.log(f"[RESILIENCE] Track 3: Could not extract text from {url}")
                        continue

                    # Step C: Run targeted extraction
                    extract_prompt = (
                        f"Target Company: {company_name}\n\n"
                        f"Document Text (first 25000 characters):\n{full_text[:25000]}\n\n"
                        "This is an official company document (IPO prospectus or annual report). "
                        "Extract every named THIRD-PARTY supplier, logistics provider, FMCG brand, "
                        "or critical vendor that the target company relies upon. "
                        "Do NOT include financial advisors, underwriters, auditors, or the company itself. "
                        "Focus on manufacturing suppliers, distributors, and technology vendors."
                    )
                    result = await self.gemini.generate_structured(
                        prompt=extract_prompt,
                        system_instruction="You are a supply chain data extraction specialist. Extract only concrete, named third-party suppliers.",
                        schema=_SupplierBrainstorm,  # Reuse brainstorm schema for the list of names
                        enable_search=False
                    )
                    all_suppliers.extend(result.probable_suppliers)
                except Exception as e:
                    ctx.log(f"[RESILIENCE] Track 3: Error processing {url}: {e}")

        # Deduplicate and convert to _SupplierItem
        seen = set()
        supplier_items = []
        for name in all_suppliers:
            if name.lower() not in seen:
                seen.add(name.lower())
                supplier_items.append(_SupplierItem(
                    supplier_name=name,
                    category="Identified from official document",
                    description=f"Named as a supplier or vendor in {company_name}'s official company document."
                ))

        ctx.log(f"[RESILIENCE] Track 3: Extracted {len(supplier_items)} unique supplier(s) from documents.")
        return supplier_items

# --- Inline response schema for Gemini --- #
from pydantic import BaseModel, Field

class _SourceModel(BaseModel):
    title: str = Field(description="The title of the source or document.")
    source_id: str | None = Field(default=None, description="The unique source_id from the web search results.")
    publisher: str | None = Field(default=None, description="The publisher or author of the source.")

class _FindingModel(BaseModel):
    summary: str = Field(description="A concise summary of the finding.")
    spof_analysis: str = Field(description="Explicitly map any Single-Points-of-Failure (SPOFs) related to this finding (e.g., reliance on a single vendor or region).")
    geopolitical_risk_weighting: str = Field(description="Assess the geopolitical stability (tariffs, conflict zones) of the region associated with this finding.")
    severity: SeverityLevel = Field(description="Grade severity based on the combination of a mapped SPOF and a high-risk geopolitical climate (INFO, LOW, MEDIUM, HIGH, CRITICAL).")
    is_red_flag: bool = Field(description="Set to true ONLY if severity is HIGH or CRITICAL.")
    is_strength: bool = Field(default=False, description="Set to true if the finding indicates a highly resilient and diversified supply chain.")
    sources: list[_SourceModel] = Field(default_factory=list, description="The sources that support this finding.")

class _SupplierItem(BaseModel):
    supplier_name: str = Field(description="Exact registered name of the supplier company.")
    category: str = Field(description="Short category label, e.g. 'Semiconductors', 'Cloud Services', 'Logistics'.")
    description: str = Field(description="One sentence describing the specific product or service supplied and its strategic importance.")

class _SupplierBrainstorm(BaseModel):
    probable_suppliers: list[str] = Field(description="List of highly probable supplier company names.")

class _SupplierVerification(BaseModel):
    rationale: str = Field(description="Explain if the text explicitly confirms the relationship.")
    is_confirmed: bool = Field(description="True ONLY if the text explicitly states a customer, vendor, or partnership relationship. If ambiguous, set to false.")
    supplier_item: _SupplierItem | None = Field(default=None, description="If confirmed, populate the supplier details. Otherwise null.")

class _ResilienceAnalysis(BaseModel):
    rationale: str = Field(description="Detailed explanation of your reasoning. MUST be generated first.")
    findings: list[_FindingModel] = Field(description="List of specific findings.")
    supply_items: list[_SupplierItem] = Field(default_factory=list, description="Structured list of suppliers and what they supply.")
    has_identifiable_third_party_suppliers: bool = Field(default=True, description="Set to false if no specific third-party suppliers are explicitly named in the text.")
    high_risk_dependency_found: bool = False
    dependency_details: str | None = None

class _DualTrackPlan(BaseModel):
    supplier_queries: list[str] = Field(
        max_length=3,
        description="Up to 3 search queries targeting named supplier discovery "
                    "(e.g. vendor contracts, annual report supplier disclosures, procurement news)."
    )
    risk_queries: list[str] = Field(
        max_length=3,
        description="Up to 3 search queries targeting operational, geopolitical, "
                    "or supply chain disruption events."
    )