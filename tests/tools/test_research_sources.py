"""Domain research sources — DR-7 resource layer (AIUT-2996).

Before this, a clinical or molecular question could reach the open web, arXiv
and the platform corpora, and nothing else. No PubMed, no ClinicalTrials.gov,
no UniProt, no PDB, no citation graph. For "what did the trials actually show",
that is the difference between an answer and a guess.

Network calls are substituted at the HTTP boundary with responses in the SHAPE
the real APIs return — each shape captured from a live call, not invented. What
is tested above that boundary is the behaviour that matters:

  * a source that returned nothing and a source that failed are reported
    separately, because only one of them says anything about the evidence
  * one source being down never loses the others
  * results are normalised so passages from different sources can be compared
  * there is no mapping from question words to sources, and none can creep in
"""
from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture()
def rs():
    import tools.research_sources as module
    importlib.reload(module)
    return module


# Shapes below were taken from live responses, not written from memory.
PUBMED_SEARCH = {"esearchresult": {"count": "3451", "idlist": ["42634480"]}}
PUBMED_SUMMARY = {"result": {
    "uids": ["42634480"],
    "42634480": {
        "title": "Chemical Engineering of Guide RNAs",
        "authors": [{"name": "Gommesen D"}, {"name": "Hjorth S"}],
        "pubdate": "2024 Oct",
        "fulljournalname": "Nucleic Acids Research",
        "articleids": [{"idtype": "doi", "value": "10.1093/nar/gkae123"}],
    }}}
TRIALS = {"studies": [{"protocolSection": {
    "identificationModule": {"nctId": "NCT03114319", "briefTitle": "Dose Finding Study"},
    "statusModule": {"overallStatus": "TERMINATED", "startDateStruct": {"date": "2017-04"}},
    "designModule": {"phases": ["PHASE1"]},
    "conditionsModule": {"conditions": ["Melanoma"]},
}}]}
OPENALEX = {"results": [{
    "id": "https://openalex.org/W2064815984",
    "title": "Multiplex Genome Engineering",
    "authorships": [{"author": {"display_name": "Cong L"}}],
    "publication_date": "2013-01-03",
    # A work located somewhere with NO registered venue — the shape that broke
    # the first implementation.
    "primary_location": {"source": None},
    "cited_by_count": 15901,
    "doi": "https://doi.org/10.1126/science.1231143",
    "open_access": {"is_oa": True},
}]}


def _fake_get(mapping):
    """Route by URL fragment, returning a captured shape or raising."""
    def _get(url, *, params=None):
        for fragment, response in mapping.items():
            if fragment in url:
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"unexpected URL: {url}")
    return _get


# ── the catalog ────────────────────────────────────────────────────────

def test_packs_describe_what_each_source_covers(rs):
    """A name is not enough to choose between PubMed and ClinicalTrials."""
    out = json.loads(rs.handle_research_sources({"action": "packs"}))

    assert set(out["packs"]) == {"biomedical", "molecular", "scholarly"}
    for name, spec in out["sources"].items():
        assert spec["covers"], f"{name} has no description"
        assert "needs_key" in spec


def test_every_pack_names_only_real_sources(rs):
    for name, pack in rs.PACKS.items():
        for source in pack["sources"]:
            assert source in rs.SOURCES, f"pack {name} names unknown source {source}"


# ── searching ──────────────────────────────────────────────────────────

def test_pubmed_results_carry_enough_to_judge_relevance(rs, monkeypatch):
    """Bare PMIDs would give the model nothing to weigh."""
    monkeypatch.setattr(rs, "_get", _fake_get({
        "esearch": PUBMED_SEARCH, "esummary": PUBMED_SUMMARY}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "crispr", "sources": ["pubmed"]}))

    hit = out["results"][0]
    assert hit["title"] == "Chemical Engineering of Guide RNAs"
    assert hit["authors"] == ["Gommesen D", "Hjorth S"]
    assert hit["doi"] == "10.1093/nar/gkae123"
    assert hit["url"] == "https://pubmed.ncbi.nlm.nih.gov/42634480/"


def test_trial_status_and_phase_survive(rs, monkeypatch):
    """A terminated phase-1 and a completed phase-3 are not equal evidence."""
    monkeypatch.setattr(rs, "_get", _fake_get({"clinicaltrials.gov": TRIALS}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "melanoma", "sources": ["clinicaltrials"]}))

    hit = out["results"][0]
    assert hit["status"] == "TERMINATED"
    assert hit["phase"] == ["PHASE1"]
    assert hit["url"] == "https://clinicaltrials.gov/study/NCT03114319"


def test_a_work_with_no_venue_does_not_crash(rs, monkeypatch):
    """Regression: primary_location present with source=None raised AttributeError."""
    monkeypatch.setattr(rs, "_get", _fake_get({"openalex": OPENALEX}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "crispr", "sources": ["openalex"]}))

    hit = out["results"][0]
    assert hit["venue"] is None
    assert hit["cited_by"] == 15901


def test_a_source_returning_nothing_is_reported_separately(rs, monkeypatch):
    monkeypatch.setattr(rs, "_get", _fake_get({
        "esearch": {"esearchresult": {"idlist": []}},
        "clinicaltrials.gov": TRIALS}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "x",
        "sources": ["pubmed", "clinicaltrials"]}))

    assert out["returned_nothing"] == ["pubmed"]
    assert out["failed"] == []
    assert out["count"] == 1, "the working source was lost with the empty one"


def test_a_failure_is_never_reported_as_an_empty_result(rs, monkeypatch):
    """Absence of evidence and inability to look are different claims."""
    monkeypatch.setattr(rs, "_get", _fake_get({
        "esearch": rs.SourceError("rate limited by the source"),
        "clinicaltrials.gov": TRIALS}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "x",
        "sources": ["pubmed", "clinicaltrials"]}))

    assert out["returned_nothing"] == []
    assert [f["source"] for f in out["failed"]] == ["pubmed"]
    assert "rate limited" in out["failed"][0]["error"]
    assert out["count"] == 1


def test_every_source_failing_is_an_error_not_an_empty_answer(rs, monkeypatch):
    """Returning "no results" here would read as "no evidence exists"."""
    monkeypatch.setattr(rs, "_get", _fake_get({
        "esearch": rs.SourceError("boom")}))

    out = rs.handle_research_sources({
        "action": "search", "query": "x", "sources": ["pubmed"]})

    assert "Every source failed" in out


def test_one_unresolvable_pdb_entry_does_not_lose_the_others(rs, monkeypatch):
    calls = {"n": 0}

    def _get(url, *, params=None):
        if "search.rcsb.org" in url:
            return {"result_set": [{"identifier": "1BAD"}, {"identifier": "1CRN"}]}
        calls["n"] += 1
        if "1BAD" in url:
            raise rs.SourceError("404")
        return {"struct": {"title": "Crambin"},
                "exptl": [{"method": "X-RAY DIFFRACTION"}],
                "rcsb_accession_info": {"initial_release_date": "1981-07-28T00:00:00Z"}}

    monkeypatch.setattr(rs, "_get", _get)
    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "insulin", "sources": ["pdb"]}))

    assert len(out["results"]) == 1
    assert out["results"][0]["id"] == "1CRN"
    assert out["results"][0]["method"] == ["X-RAY DIFFRACTION"]


# ── selection is the model's ───────────────────────────────────────────

def test_a_pack_is_a_starting_point_not_a_constraint(rs, monkeypatch):
    """Sources and a pack combine — a question can span packs."""
    monkeypatch.setattr(rs, "_get", _fake_get({
        "esearch": PUBMED_SEARCH, "esummary": PUBMED_SUMMARY,
        "clinicaltrials.gov": TRIALS,
        "europepmc": {"resultList": {"result": []}},
        "openalex": OPENALEX}))

    out = json.loads(rs.handle_research_sources({
        "action": "search", "query": "x",
        "pack": "biomedical", "sources": ["openalex"]}))

    assert "openalex" in out["searched"]
    assert "pubmed" in out["searched"]


def test_search_without_a_source_says_whose_decision_it_is(rs):
    out = rs.handle_research_sources({"action": "search", "query": "x"})
    assert "Name at least one source" in out
    assert "your call" in out


def test_an_unknown_source_is_refused_by_name(rs):
    out = rs.handle_research_sources({
        "action": "search", "query": "x", "sources": ["definitely_not_real"]})
    assert "unknown source" in out
    assert "pubmed" in out


def test_no_mapping_from_question_words_to_sources(rs):
    """A rule would send "the court ruling on the drug schedule" to medicine.

    Checked against the AST: the tool's own description legitimately discusses
    drugs and courts, and a text search would flag that prose.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(rs))
    source_names = set(rs.SOURCES)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        # A normalised result legitimately tags itself {"source": "pubmed"} —
        # that is provenance on one record, not routing. A lookup table is the
        # different shape: SEVERAL keys each pointing at a source name.
        routed = sum(
            1 for k, v in zip(node.keys, node.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
            and isinstance(v, ast.Constant) and v.value in source_names
        )
        assert routed < 2, (
            f"{routed} keys map to source names in one dict — that is a "
            f"topic-to-source lookup table, and selection must stay the "
            f"model's judgement"
        )


# ── surface ────────────────────────────────────────────────────────────

def test_available_without_any_api_key(rs):
    ok, message = rs.check_research_sources_requirements()
    assert ok is True
    assert "no API key" in message.lower() or "no api key" in message.lower()
    assert all(not spec["needs_key"] for spec in rs.SOURCES.values())


def test_registered_and_in_the_research_toolsets(rs):
    json.dumps(rs.RESEARCH_SOURCES_SCHEMA)

    from tools.registry import discover_builtin_tools, registry
    discover_builtin_tools()
    assert registry.get_schema("research_sources")

    import toolsets
    assert "research_sources" in toolsets.TOOLSETS["deep_research"]["tools"]
    assert "research_sources" in toolsets.TOOLSETS["elidia-cli"]["tools"]


def test_no_surface_exposes_it_beyond_the_cli(rs):
    """The CLI is the superset; every other surface is a strict subset."""
    import toolsets

    cli = set(toolsets.TOOLSETS["elidia-cli"]["tools"])
    for surface in ("elidia-api-server", "elidia-acp"):
        assert set(toolsets.TOOLSETS[surface]["tools"]) <= cli


def test_unknown_action_names_the_valid_ones(rs):
    out = rs.handle_research_sources({"action": "teleport"})
    assert "packs" in out and "search" in out
