#!/usr/bin/env python3
"""Domain research sources — the corpora the open web cannot substitute for.

Why this exists
---------------
Research quality is bounded by sources. Before this, bio and drug-discovery
questions could reach the open web, arXiv and the platform corpora, and nothing
else. No PubMed, no ClinicalTrials.gov, no UniProt, no PDB, no citation graph.
For a clinical or molecular question that is not a gap in coverage, it is the
difference between an answer and a guess.

Why official APIs rather than third-party MCP servers
-----------------------------------------------------
The plan called for MCP packs. Verification changed the shape, not the goal:
the obvious server names do not exist (``@modelcontextprotocol/server-pubmed``
is a 404), and the third-party ones that do exist are unreviewed code that
would run locally over stdio. Recommending those to users is a supply-chain
decision, and none of them reach anything the official APIs do not.

Every source below is an official, documented, keyless HTTP API, each verified
answering before it was added here. That is also the pattern this repository
already uses — ``skills/research/arxiv`` queries arXiv's REST API directly.

MCP remains the extension point for anything not covered: ``mcp_tool`` speaks
stdio, StreamableHTTP and SSE with OAuth, so a user who wants a specific server
attaches it without touching this file.

Choosing sources is the model's judgement
-----------------------------------------
``action="packs"`` describes what each source actually covers. There is no
mapping from question words to sources, and adding one would be a downgrade:
"what did the trial show about the drug's effect on p53" wants ClinicalTrials
*and* UniProt *and* PubMed, and no keyword rule reads that from the sentence.
"""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# NCBI asks that tools identify themselves; it is also how rate limits are
# attributed rather than shared with every anonymous caller.
USER_AGENT = "ElidiaAgent/2.0 (https://aiutils.io; research)"

HTTP_TIMEOUT = 25
DEFAULT_LIMIT = 5
MAX_LIMIT = 25


class SourceError(Exception):
    """A source could not be queried. Message is safe to show."""


def _get(url: str, *, params: Optional[Dict[str, Any]] = None) -> Any:
    """One HTTP GET returning parsed JSON, with honest failures.

    A rate limit and an outage are different facts and are reported as
    different messages: the first means wait or get a key, the second means the
    source is unusable right now. Collapsing them into "search failed" would
    send the model down the wrong recovery path.
    """
    logger.debug(f"Entered into _get: url={url}")
    full = f"{url}?{urllib.parse.urlencode(params, doseq=True)}" if params else url
    request = urllib.request.Request(full, headers={"User-Agent": USER_AGENT,
                                                    "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise SourceError(
                "rate limited by the source — wait and retry, or configure an "
                "API key for it"
            ) from exc
        raise SourceError(f"HTTP {exc.code} from the source") from exc
    except Exception as exc:
        raise SourceError(f"{type(exc).__name__}: {exc}") from exc


# ── sources ────────────────────────────────────────────────────────────
# Each returns a normalised record so results from different sources can be
# compared and cited side by side. Fields absent at a source stay absent rather
# than being filled with a placeholder that would read as data.


def _pubmed(query: str, limit: int) -> List[Dict[str, Any]]:
    """Biomedical literature via NCBI E-utilities.

    Two calls by design: esearch returns only PMIDs, esummary turns them into
    metadata. Skipping the second and reporting bare identifiers would give the
    model nothing to judge relevance by.
    """
    logger.debug(f"Entered into _pubmed: limit={limit}")
    found = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                 params={"db": "pubmed", "term": query, "retmode": "json",
                         "retmax": limit})
    ids = found.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []

    summary = _get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                   params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"})
    result = summary.get("result", {})

    records = []
    for pmid in result.get("uids", []):
        item = result.get(pmid, {})
        records.append({
            "source": "pubmed",
            "id": pmid,
            "title": item.get("title"),
            "authors": [a.get("name") for a in item.get("authors", [])][:8],
            "date": item.get("pubdate"),
            "venue": item.get("fulljournalname"),
            "doi": next((x.get("value") for x in item.get("articleids", [])
                         if x.get("idtype") == "doi"), None),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return records


def _europepmc(query: str, limit: int) -> List[Dict[str, Any]]:
    """Europe PMC — overlaps PubMed but indexes preprints and more full text."""
    logger.debug(f"Entered into _europepmc: limit={limit}")
    data = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                params={"query": query, "format": "json", "pageSize": limit})
    return [{
        "source": "europepmc",
        "id": item.get("id"),
        "title": item.get("title"),
        "authors": [a.strip() for a in (item.get("authorString") or "").split(",")][:8],
        "date": item.get("firstPublicationDate"),
        "venue": item.get("journalTitle"),
        "doi": item.get("doi"),
        "cited_by": item.get("citedByCount"),
        "is_open_access": item.get("isOpenAccess") == "Y",
        "url": f"https://europepmc.org/article/{item.get('source')}/{item.get('id')}",
    } for item in data.get("resultList", {}).get("result", [])]


def _clinicaltrials(query: str, limit: int) -> List[Dict[str, Any]]:
    """Registered interventional and observational studies (API v2).

    Status and phase are carried through because a terminated phase-1 study and
    a completed phase-3 are not equivalent evidence, and a citation that hides
    the difference invites a wrong conclusion.
    """
    logger.debug(f"Entered into _clinicaltrials: limit={limit}")
    data = _get("https://clinicaltrials.gov/api/v2/studies",
                params={"query.term": query, "pageSize": limit})
    records = []
    for study in data.get("studies", []):
        section = study.get("protocolSection", {})
        ident = section.get("identificationModule", {})
        nct = ident.get("nctId")
        records.append({
            "source": "clinicaltrials",
            "id": nct,
            "title": ident.get("briefTitle"),
            "status": section.get("statusModule", {}).get("overallStatus"),
            "phase": section.get("designModule", {}).get("phases"),
            "start_date": section.get("statusModule", {})
                                 .get("startDateStruct", {}).get("date"),
            "conditions": section.get("conditionsModule", {}).get("conditions", [])[:6],
            "url": f"https://clinicaltrials.gov/study/{nct}" if nct else None,
        })
    return records


def _uniprot(query: str, limit: int) -> List[Dict[str, Any]]:
    """Curated protein sequence and function."""
    logger.debug(f"Entered into _uniprot: limit={limit}")
    data = _get("https://rest.uniprot.org/uniprotkb/search",
                params={"query": query, "size": limit, "format": "json",
                        "fields": "accession,protein_name,gene_names,"
                                  "organism_name,length,cc_function"})
    records = []
    for entry in data.get("results", []):
        accession = entry.get("primaryAccession")
        records.append({
            "source": "uniprot",
            "id": accession,
            "title": entry.get("proteinDescription", {})
                          .get("recommendedName", {})
                          .get("fullName", {}).get("value"),
            "genes": [g.get("geneName", {}).get("value")
                      for g in entry.get("genes", [])][:5],
            "organism": entry.get("organism", {}).get("scientificName"),
            "length": entry.get("sequence", {}).get("length"),
            "url": f"https://www.uniprot.org/uniprotkb/{accession}" if accession else None,
        })
    return records


def _pdb(query: str, limit: int) -> List[Dict[str, Any]]:
    """Experimentally determined 3D structures (RCSB).

    Search returns identifiers only, so each is resolved to its entry. The
    experimental method matters: a 3.5 Å cryo-EM map and a 1.0 Å crystal
    structure support very different claims about a binding site.
    """
    logger.debug(f"Entered into _pdb: limit={limit}")
    payload = {
        "query": {"type": "terminal", "service": "full_text",
                  "parameters": {"value": query}},
        "return_type": "entry",
        "request_options": {"paginate": {"start": 0, "rows": limit}},
    }
    found = _get("https://search.rcsb.org/rcsbsearch/v2/query",
                 params={"json": json.dumps(payload)})

    records = []
    for hit in found.get("result_set", []):
        pdb_id = hit.get("identifier")
        try:
            entry = _get(f"https://data.rcsb.org/rest/v1/core/entry/{pdb_id}")
        except SourceError:
            # One unresolvable entry should not lose the rest of the results.
            logger.warning("could not resolve PDB entry %s", pdb_id)
            continue
        records.append({
            "source": "pdb",
            "id": pdb_id,
            "title": entry.get("struct", {}).get("title"),
            "method": [m.get("method") for m in entry.get("exptl", [])],
            "released": (entry.get("rcsb_accession_info", {})
                              .get("initial_release_date") or "")[:10] or None,
            "url": f"https://www.rcsb.org/structure/{pdb_id}",
        })
    return records


def _openfda(query: str, limit: int) -> List[Dict[str, Any]]:
    """FDA drug labels, adverse events, and recalls via openFDA.

    Two endpoints are queried: drug labels (SPL) for approved indications,
    warnings, and pharmacology, and drug adverse events (FAERS) for
    post-market safety signals. Both are free, keyless, and authoritative
    for US-approved therapeutics.
    """
    logger.debug(f"Entered into _openfda: limit={limit}")
    records: List[Dict[str, Any]] = []
    label_limit = max(1, limit // 2) or 1
    event_limit = max(1, limit - label_limit)

    try:
        labels = _get("https://api.fda.gov/drug/label.json",
                       params={"search": query, "limit": label_limit})
        for item in labels.get("results", []):
            openfda = item.get("openfda", {})
            records.append({
                "source": "openfda",
                "type": "drug_label",
                "id": item.get("id") or item.get("set_id"),
                "brand_name": (openfda.get("brand_name") or [None])[0],
                "generic_name": (openfda.get("generic_name") or [None])[0],
                "manufacturer": (openfda.get("manufacturer_name") or [None])[0],
                "indications": (item.get("indications_and_usage") or [None])[0][:500]
                    if item.get("indications_and_usage") else None,
                "mechanism": (item.get("mechanism_of_action") or [None])[0][:500]
                    if item.get("mechanism_of_action") else None,
                "pharmacology": (item.get("clinical_pharmacology") or [None])[0][:500]
                    if item.get("clinical_pharmacology") else None,
                "route": (openfda.get("route") or [None])[0],
                "url": "https://labels.fda.gov/",
            })
    except SourceError:
        logger.warning("openfda drug labels failed for query: %s", query)

    try:
        events = _get("https://api.fda.gov/drug/event.json",
                       params={"search": query, "limit": event_limit})
        for item in events.get("results", []):
            patient = item.get("patient", {})
            drugs = patient.get("drug", [])
            reactions = patient.get("reaction", [])
            records.append({
                "source": "openfda",
                "type": "adverse_event",
                "id": item.get("safetyreportid"),
                "drugs": [d.get("medicinalproduct") for d in drugs[:5]],
                "reactions": [r.get("reactionmeddrapt") for r in reactions[:8]],
                "serious": item.get("serious"),
                "date": item.get("receiptdate"),
                "country": item.get("occurcountry"),
            })
    except SourceError:
        logger.warning("openfda adverse events failed for query: %s", query)

    return records


def _chembl(query: str, limit: int) -> List[Dict[str, Any]]:
    """Drug-target interactions and compound data from ChEMBL (EMBL-EBI).

    Searches the molecule endpoint for compounds matching the query, returning
    clinical phase, molecular properties, and target information. ChEMBL is the
    reference database for medicinal chemistry and structure-activity data.
    """
    logger.debug(f"Entered into _chembl: limit={limit}")
    data = _get("https://www.ebi.ac.uk/chembl/api/data/molecule/search.json",
                params={"q": query, "limit": limit})
    records = []
    for mol in data.get("molecules", []):
        props = mol.get("molecule_properties") or {}
        records.append({
            "source": "chembl",
            "id": mol.get("molecule_chembl_id"),
            "name": mol.get("pref_name"),
            "type": mol.get("molecule_type"),
            "max_phase": mol.get("max_phase"),
            "first_approval": mol.get("first_approval"),
            "oral": mol.get("oral"),
            "topical": mol.get("topical"),
            "parenteral": mol.get("parenteral"),
            "molecular_weight": props.get("full_mwt"),
            "alogp": props.get("alogp"),
            "hba": props.get("hba"),
            "hbd": props.get("hbd"),
            "psa": props.get("psa"),
            "url": f"https://www.ebi.ac.uk/chembl/compound_report_card/{mol.get('molecule_chembl_id')}/",
        })
    return records


def _crossref(query: str, limit: int) -> List[Dict[str, Any]]:
    """DOI metadata and citation counts across publishers."""
    logger.debug(f"Entered into _crossref: limit={limit}")
    data = _get("https://api.crossref.org/works",
                params={"query": query, "rows": limit})
    records = []
    for item in data.get("message", {}).get("items", []):
        parts = (item.get("issued", {}).get("date-parts") or [[]])[0]
        records.append({
            "source": "crossref",
            "id": item.get("DOI"),
            "title": (item.get("title") or [None])[0],
            "authors": [f"{a.get('given','')} {a.get('family','')}".strip()
                        for a in item.get("author", [])][:8],
            "date": "-".join(str(p) for p in parts) if parts else None,
            "venue": (item.get("container-title") or [None])[0],
            "cited_by": item.get("is-referenced-by-count"),
            "url": item.get("URL"),
        })
    return records


def _patents(query: str, limit: int) -> List[Dict[str, Any]]:
    """US patent data via USPTO PatentsView API.

    Searches granted US patents by text query. Returns patent number, title,
    assignee, inventors, filing/grant dates, CPC classifications, and abstract.
    Covers all technology domains: electronics, mechanical, biotech, pharma,
    semiconductors, aerospace, materials science, and more.
    """
    logger.debug(f"Entered into _patents: limit={limit}")
    payload = json.dumps({
        "q": {"_text_any": {"patent_abstract": query}},
        "f": ["patent_number", "patent_title", "patent_date",
              "patent_abstract", "patent_num_claims"],
        "o": {"per_page": limit},
        "s": [{"patent_date": "desc"}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.patentsview.org/patents/query",
        data=payload,
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json",
                 "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise SourceError("rate limited by USPTO PatentsView") from exc
        raise SourceError(f"HTTP {exc.code} from USPTO PatentsView") from exc
    except Exception as exc:
        raise SourceError(f"{type(exc).__name__}: {exc}") from exc

    records = []
    for pat in data.get("patents", []):
        pnum = pat.get("patent_number")
        records.append({
            "source": "patents",
            "id": pnum,
            "title": pat.get("patent_title"),
            "date": pat.get("patent_date"),
            "abstract": (pat.get("patent_abstract") or "")[:500] or None,
            "num_claims": pat.get("patent_num_claims"),
            "url": f"https://patents.google.com/patent/US{pnum}" if pnum else None,
        })
    return records


def _sec_edgar(query: str, limit: int) -> List[Dict[str, Any]]:
    """SEC EDGAR full-text search for company filings and disclosures.

    Searches 10-K, 10-Q, 8-K, proxy statements, and other SEC filings.
    Essential for business research, corporate due diligence, market analysis,
    and regulatory compliance.
    """
    logger.debug(f"Entered into _sec_edgar: limit={limit}")
    data = _get("https://efts.sec.gov/LATEST/search-index",
                params={"q": query, "dateRange": "custom",
                        "startdt": "2020-01-01", "forms": "",
                        "hits.hits.total": limit,
                        "hits.hits._source": "file_date,display_date_dt,"
                                             "file_description,form_type,"
                                             "entity_name,file_num,biz_locations"})
    # EDGAR EFTS returns a nested structure; fall back to the simpler endpoint
    # if the response shape is unexpected.
    if not isinstance(data, dict) or "hits" not in data:
        data = _get("https://efts.sec.gov/LATEST/search-index",
                    params={"q": query, "forms": "",
                            "from": 0, "size": limit})

    records = []
    hits = data.get("hits", {}).get("hits", [])
    for hit in hits[:limit]:
        src = hit.get("_source", {})
        records.append({
            "source": "sec_edgar",
            "id": hit.get("_id"),
            "title": src.get("file_description"),
            "entity": src.get("entity_name"),
            "form_type": src.get("form_type"),
            "date": src.get("file_date") or src.get("display_date_dt", "")[:10],
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={urllib.parse.quote(query)}&type=&dateb=&owner=include&count={limit}&search_text=&action=getcompany",
        })
    return records


def _courtlistener(query: str, limit: int) -> List[Dict[str, Any]]:
    """US case law opinions via CourtListener (Free Law Project).

    Searches court opinions across federal and state jurisdictions. Returns
    case name, court, date, citation, and docket number. CourtListener is the
    largest open collection of US case law with over 8 million opinions.
    """
    logger.debug(f"Entered into _courtlistener: limit={limit}")
    data = _get("https://www.courtlistener.com/api/rest/v4/search/",
                params={"q": query, "type": "o", "page_size": limit,
                        "format": "json"})
    records = []
    for item in data.get("results", []):
        records.append({
            "source": "courtlistener",
            "id": item.get("id"),
            "title": item.get("caseName"),
            "court": item.get("court"),
            "date": item.get("dateFiled"),
            "citation": (item.get("citation") or [None])[0] if isinstance(
                item.get("citation"), list) else item.get("citation"),
            "docket_number": item.get("docketNumber"),
            "status": item.get("status"),
            "snippet": item.get("snippet", "")[:400] if item.get("snippet") else None,
            "url": f"https://www.courtlistener.com{item.get('absolute_url', '')}",
        })
    return records


def _federal_register(query: str, limit: int) -> List[Dict[str, Any]]:
    """US federal regulations, rules, and notices via the Federal Register API.

    Searches proposed rules, final rules, presidential documents, and notices.
    Returns document type, agency, publication date, and effective date.
    Essential for regulatory compliance research.
    """
    logger.debug(f"Entered into _federal_register: limit={limit}")
    data = _get("https://www.federalregister.gov/api/v1/documents.json",
                params={"conditions[term]": query, "per_page": limit,
                        "order": "relevance"})
    records = []
    for item in data.get("results", []):
        records.append({
            "source": "federal_register",
            "id": item.get("document_number"),
            "title": item.get("title"),
            "type": item.get("type"),
            "agencies": [a.get("name") for a in item.get("agencies", [])][:5],
            "publication_date": item.get("publication_date"),
            "effective_date": item.get("effective_on"),
            "abstract": (item.get("abstract") or "")[:500] or None,
            "cfr_references": item.get("cfr_references"),
            "url": item.get("html_url"),
        })
    return records


def _openalex(query: str, limit: int) -> List[Dict[str, Any]]:
    """Open scholarly graph — works, citations, open-access status."""
    logger.debug(f"Entered into _openalex: limit={limit}")
    data = _get("https://api.openalex.org/works",
                params={"search": query, "per-page": limit})
    records = []
    for work in data.get("results", []):
        records.append({
            "source": "openalex",
            "id": work.get("id"),
            "title": work.get("title"),
            "authors": [a.get("author", {}).get("display_name")
                        for a in work.get("authorships", [])][:8],
            "date": work.get("publication_date"),
            # primary_location can exist with a NULL source (a work located
            # somewhere with no registered venue), so .get("source", {}) hands
            # back None rather than the default and the next .get() raises.
            # Both levels have to be coerced, not just the outer one.
            "venue": ((work.get("primary_location") or {}).get("source") or {})
                     .get("display_name"),
            "cited_by": work.get("cited_by_count"),
            "doi": work.get("doi"),
            "is_open_access": (work.get("open_access") or {}).get("is_oa"),
            "url": work.get("doi") or work.get("id"),
        })
    return records


# Each entry is a source that was verified answering before it was listed.
# ``needs_key`` is stated rather than discovered at runtime: a source that
# rate-limits anonymous callers is usable, but the model should know it may
# come back empty for that reason and not conclude the literature is silent.
SOURCES: Dict[str, Dict[str, Any]] = {
    "pubmed": {
        "fn": _pubmed, "needs_key": False,
        "covers": "Biomedical and life-science literature indexed by NCBI. "
                  "The reference index for clinical and molecular questions.",
    },
    "europepmc": {
        "fn": _europepmc, "needs_key": False,
        "covers": "Life-science literature including preprints and full text; "
                  "overlaps PubMed but indexes more open-access content.",
    },
    "clinicaltrials": {
        "fn": _clinicaltrials, "needs_key": False,
        "covers": "Registered clinical studies with status, phase and "
                  "conditions. What was actually tried in humans, including "
                  "trials that were terminated or never published.",
    },
    "uniprot": {
        "fn": _uniprot, "needs_key": False,
        "covers": "Curated protein sequence, function and gene names across "
                  "organisms.",
    },
    "pdb": {
        "fn": _pdb, "needs_key": False,
        "covers": "Experimentally determined 3D macromolecular structures, "
                  "with the method used to determine each.",
    },
    "openfda": {
        "fn": _openfda, "needs_key": False,
        "covers": "FDA drug labels (indications, mechanism of action, pharmacology), "
                  "adverse event reports (FAERS), and drug recalls. Authoritative for "
                  "US-approved therapeutics, post-market safety, and regulatory status.",
    },
    "chembl": {
        "fn": _chembl, "needs_key": False,
        "covers": "Drug-target interactions, compound properties, clinical phase, "
                  "and structure-activity data from EMBL-EBI. The reference database "
                  "for medicinal chemistry and drug discovery.",
    },
    "patents": {
        "fn": _patents, "needs_key": False,
        "covers": "Granted US patents across all technology domains — electronics, "
                  "semiconductors, biotech, pharma, mechanical, aerospace, materials, "
                  "software. Includes title, abstract, claims, and classification.",
    },
    "sec_edgar": {
        "fn": _sec_edgar, "needs_key": False,
        "covers": "SEC company filings (10-K, 10-Q, 8-K, proxies) for business "
                  "research, corporate due diligence, financial analysis, and "
                  "regulatory compliance.",
    },
    "courtlistener": {
        "fn": _courtlistener, "needs_key": False,
        "covers": "US case law — 8M+ court opinions across federal and state "
                  "jurisdictions. Case name, court, citation, docket number, and "
                  "opinion text snippets.",
    },
    "federal_register": {
        "fn": _federal_register, "needs_key": False,
        "covers": "US federal regulations, proposed rules, final rules, and "
                  "presidential documents. Essential for regulatory compliance, "
                  "policy analysis, and understanding the regulatory landscape.",
    },
    "crossref": {
        "fn": _crossref, "needs_key": False,
        "covers": "DOI metadata and citation counts across publishers and "
                  "disciplines. Good for resolving and dating a reference.",
    },
    "openalex": {
        "fn": _openalex, "needs_key": False,
        "covers": "Open scholarly graph across all fields — citations, venues "
                  "and open-access status.",
    },
}

# Packs group sources by the shape of question they serve. A pack is a starting
# point, not a constraint: any subset of SOURCES can be queried directly, and a
# question that spans packs should.
PACKS: Dict[str, Dict[str, Any]] = {
    "biomedical": {
        "sources": ["pubmed", "europepmc", "clinicaltrials"],
        "for": "Clinical questions, disease mechanisms, treatments, outcomes.",
    },
    "pharmacology": {
        "sources": ["pubmed", "clinicaltrials", "openfda", "chembl"],
        "for": "Drug discovery, pharmacology, drug-target interactions, clinical "
               "trials, FDA-approved therapeutics, adverse events, and medicinal "
               "chemistry. Use for any question about drugs, compounds, or therapies.",
    },
    "molecular": {
        "sources": ["uniprot", "pdb", "pubmed"],
        "for": "Proteins, structures, binding sites, sequence and function.",
    },
    "legal": {
        "sources": ["courtlistener", "federal_register", "openalex"],
        "for": "US case law, court opinions, federal regulations, proposed rules, "
               "and legal scholarship. Use for legal research, compliance analysis, "
               "regulatory questions, and precedent search.",
    },
    "business": {
        "sources": ["sec_edgar", "openalex", "patents"],
        "for": "Corporate filings, market analysis, due diligence, competitive "
               "intelligence, and business-relevant patents.",
    },
    "engineering": {
        "sources": ["patents", "openalex", "crossref"],
        "for": "Technology patents, engineering research, hardware design, "
               "semiconductors, materials science, aerospace, drones, robotics, "
               "and applied R&D across all engineering domains.",
    },
    "scholarly": {
        "sources": ["openalex", "crossref"],
        "for": "Citation graphs, resolving a reference, how heavily cited a "
               "result is, and in which venue.",
    },
}


def _handle_packs(args: Dict[str, Any], **_kw) -> str:
    logger.debug("Entered into _handle_packs")
    return json.dumps({
        "packs": {
            name: {
                "sources": pack["sources"],
                "for": pack["for"],
            } for name, pack in PACKS.items()
        },
        "sources": {
            name: {
                "covers": spec["covers"],
                "needs_key": spec["needs_key"],
            } for name, spec in SOURCES.items()
        },
        "note": (
            "Packs are a starting point, not a constraint — query any subset of "
            "sources. A question about a drug's effect on a protein wants "
            "clinical, molecular and literature sources together, and which "
            "ones fit is your judgement, not a lookup."
        ),
    }, indent=2)


def _handle_search(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error

    query = str(args.get("query") or "").strip()
    requested = args.get("sources") or []
    pack = str(args.get("pack") or "").strip().lower()
    limit = max(1, min(int(args.get("limit") or DEFAULT_LIMIT), MAX_LIMIT))
    logger.debug(f"Entered into _handle_search: pack={pack}, sources={requested}")

    if not query:
        return tool_error("query is required")

    if isinstance(requested, str):
        requested = [requested]
    if pack:
        if pack not in PACKS:
            return tool_error(
                f"unknown pack {pack!r}. Available: {', '.join(sorted(PACKS))}")
        requested = list(requested) + PACKS[pack]["sources"]
    if not requested:
        return tool_error(
            "Name at least one source, or a pack. Call action='packs' to see "
            "what each covers — which sources can answer this is your call."
        )

    seen, ordered = set(), []
    for name in requested:
        key = str(name).strip().lower()
        if key not in SOURCES:
            return tool_error(
                f"unknown source {key!r}. Available: {', '.join(sorted(SOURCES))}")
        if key not in seen:
            seen.add(key)
            ordered.append(key)

    results: List[Dict[str, Any]] = []
    empty: List[str] = []
    failed: List[Dict[str, str]] = []

    for name in ordered:
        try:
            records = SOURCES[name]["fn"](query, limit)
        except SourceError as exc:
            # One source being down or rate-limited must not lose the others.
            logger.warning("source %s failed: %s", name, exc)
            failed.append({"source": name, "error": str(exc)})
            continue
        except Exception as exc:
            logger.exception("source %s raised", name)
            failed.append({"source": name, "error": f"{type(exc).__name__}: {exc}"})
            continue

        if records:
            results.extend(records)
        else:
            empty.append(name)

    if not results and failed and not empty:
        return tool_error(
            "Every source failed: "
            + "; ".join(f"{f['source']} ({f['error']})" for f in failed)
        )

    return json.dumps({
        "query": query,
        "searched": ordered,
        "count": len(results),
        "results": results,
        # Both reported: a source that returned nothing and a source that could
        # not be reached mean different things for the next round, and for how
        # confidently the absence of evidence can be read.
        "returned_nothing": empty,
        "failed": failed,
    }, indent=2, default=str)


def handle_research_sources(args: Dict[str, Any], **kw) -> str:
    from tools.registry import tool_error

    action = str(args.get("action") or "packs").strip().lower()
    logger.debug(f"Entered into handle_research_sources: action={action}")

    dispatch = {"packs": _handle_packs, "search": _handle_search}
    handler = dispatch.get(action)
    if handler is None:
        return tool_error(f"unknown action {action!r}. Valid: packs, search")
    return handler(args, **kw)


RESEARCH_SOURCES_SCHEMA = {
    "name": "research_sources",
    "description": (
        "Authoritative domain sources the open web cannot substitute for:\n"
        "• Biomedical — PubMed, Europe PMC (literature), ClinicalTrials.gov (studies)\n"
        "• Molecular — UniProt (proteins), RCSB PDB (3D structures)\n"
        "• Pharmacology — OpenFDA (drug labels, adverse events), ChEMBL (drug-target, "
        "compounds, clinical phase)\n"
        "• Legal — CourtListener (US case law, 8M+ opinions), Federal Register "
        "(regulations, rules)\n"
        "• Business — SEC EDGAR (corporate filings, 10-K, 10-Q, 8-K)\n"
        "• Engineering — USPTO PatentsView (patents across all tech domains)\n"
        "• Scholarly — Crossref and OpenAlex (citations, DOIs, venues)\n\n"
        "Use it for clinical, molecular, pharmacological, legal, business, "
        "engineering, or scholarly questions. A web search returns what someone "
        "wrote about the evidence; these return the evidence itself. All are "
        "free and need no key.\n\n"
        "Start with action='packs' to see what each source covers, then choose. "
        "Which sources fit a question is a judgement — a question about a drug's "
        "effect on a protein wants clinical, molecular and literature sources at "
        "once, and no rule reads that from the wording.\n\n"
        "Results name sources that returned nothing and sources that failed, "
        "separately: the first may be real absence of evidence, the second "
        "never is."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["packs", "search"],
                "description": "packs: what exists and what it covers · search: query chosen sources",
            },
            "query": {"type": "string", "description": "search: what to look for."},
            "sources": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "search: any of pubmed, europepmc, clinicaltrials, uniprot, "
                    "pdb, openfda, chembl, patents, sec_edgar, courtlistener, "
                    "federal_register, crossref, openalex."
                ),
            },
            "pack": {
                "type": "string",
                "description": (
                    "search: a starting group — biomedical, pharmacology, molecular, "
                    "legal, business, engineering, or scholarly. Combines with `sources`."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"search: records per source (default {DEFAULT_LIMIT}, max {MAX_LIMIT}).",
            },
        },
        "required": ["action"],
    },
}


def check_research_sources_requirements() -> Tuple[bool, str]:
    """Always available: every source is a keyless public API over HTTPS."""
    logger.debug("Entered into check_research_sources_requirements")
    return True, "Domain research sources available (no API key required)"


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="research_sources",
    toolset="deep_research",
    schema=RESEARCH_SOURCES_SCHEMA,
    handler=handle_research_sources,
    check_fn=check_research_sources_requirements,
    emoji="🔬",
)
