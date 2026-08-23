"""Tests for domain routing (B8, AIUT-2954 track).

The load-bearing property is the one the codebase has been burned by before:
this must NOT classify user text. task_kind comes from the model via a fixed
enum; the router only resolves that choice onto candidates. A test asserts the
module contains no keyword matching against user input.
"""

import json
import types

import pytest

from tools import aiutils_client, aiutils_model_router as router


def _model(mid, category="text", dt=None, free=False, vision=False):
    return types.SimpleNamespace(
        id=mid, label=mid, name=mid, vendor="v", modality=category,
        pricing=types.SimpleNamespace(dt_cost=dt, free=free),
        capabilities=types.SimpleNamespace(vision=vision),
    )


class _FakeModels:
    def __init__(self, models):
        self.models = models
        self.calls = []

    def list(self, category=None, vendor=None, search=None, page_size=50):
        self.calls.append({"category": category, "page_size": page_size})
        return types.SimpleNamespace(data=self.models, total=len(self.models))


@pytest.fixture
def client(monkeypatch):
    fake = types.SimpleNamespace(models=_FakeModels([
        _model("cheap", dt=1),
        _model("mid", dt=20),
        _model("frontier", dt=200),
        _model("free-one", dt=0, free=True),
        _model("seeing", dt=50, vision=True),
    ]))
    monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)
    return fake


def _parse(r):
    return json.loads(r)


class TestRouting:
    def test_cheap_task_ranks_free_and_low_cost_first(self, client):
        out = _parse(router._handle_route({"task_kind": "text_fast_cheap"}))
        assert out["ranked_by"] == "cost"
        assert out["suggestions"][0]["id"] == "free-one"

    def test_quality_task_ranks_capable_first(self, client):
        out = _parse(router._handle_route({"task_kind": "text_reasoning"}))
        assert out["ranked_by"] == "quality"
        assert out["suggestions"][0]["id"] == "frontier"

    def test_vision_filters_to_vision_capable_models(self, client):
        out = _parse(router._handle_route({"task_kind": "vision"}))
        assert [s["id"] for s in out["suggestions"]] == ["seeing"]

    def test_free_only_excludes_paid(self, client):
        out = _parse(router._handle_route({"task_kind": "text_reasoning", "free_only": True}))
        assert all(s["free"] for s in out["suggestions"])

    def test_image_task_queries_the_image_category(self, client):
        router._handle_route({"task_kind": "image_generation"})
        assert client.models.calls[-1]["category"] == "image"

    def test_unknown_task_kind_lists_valid_options(self, client):
        out = _parse(router._handle_route({"task_kind": "telepathy"}))
        assert "Unknown task_kind" in out["error"]
        assert "image_generation" in out["error"]

    def test_limit_is_clamped(self, client):
        out = _parse(router._handle_route({"task_kind": "text_reasoning", "limit": 999}))
        assert out["count"] <= router.MAX_SUGGESTIONS

    def test_no_match_explains_the_next_step(self, client, monkeypatch):
        monkeypatch.setattr(client.models, "list",
                            lambda **kw: types.SimpleNamespace(data=[], total=0))
        out = _parse(router._handle_route({"task_kind": "video_generation"}))
        assert out["count"] == 0
        assert "aiutils_model_catalog" in out["note"]

    def test_catalog_failure_is_reported_not_raised(self, client, monkeypatch):
        def _boom(**kw):
            raise RuntimeError("gateway down")

        monkeypatch.setattr(client.models, "list", _boom)
        assert "Could not load" in _parse(router._handle_route({"task_kind": "code"}))["error"]


class TestRankingEdgeCases:
    def test_unpriced_model_does_not_masquerade_as_free(self, client, monkeypatch):
        """dt_cost=None must not sort ahead of a genuinely cheap model."""
        monkeypatch.setattr(client.models, "list", lambda **kw: types.SimpleNamespace(
            data=[_model("unpriced", dt=None), _model("cheap", dt=2)], total=2))
        out = _parse(router._handle_route({"task_kind": "text_fast_cheap"}))
        assert out["suggestions"][0]["id"] == "cheap"


class TestDoesNotClassifyUserText:
    """The binding rule: intent stays with the LLM. Cue-list routing has already
    caused real failures here — an enterprise 'AI transformation platform'
    request hijacked to image editing by the substring 'transform'."""

    def test_schema_makes_the_model_choose_the_task_kind(self):
        prop = router.ROUTER_SCHEMA["parameters"]["properties"]["task_kind"]
        assert "enum" in prop, "task_kind must be a model-selected enum, not free text"
        assert set(prop["enum"]) == set(router.TASK_PROFILES)

    def test_no_free_text_prompt_parameter_exists(self):
        params = router.ROUTER_SCHEMA["parameters"]["properties"]
        for banned in ("prompt", "message", "query", "text", "request"):
            assert banned not in params, (
                f"{banned!r} would invite classifying user wording in this tool"
            )

    def test_module_imports_no_regex_engine(self):
        """Checked via AST, not substring search — `import registry` contains
        the literal "import re", which a naive check flags. Fitting mistake for
        a test about not matching on substrings."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(router))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert "re" not in imported, "regex has no place in routing"

    def test_selection_is_driven_only_by_the_task_kind_lookup(self):
        """The only thing steering the result should be TASK_PROFILES[task_kind].
        An unknown kind must be refused outright rather than guessed at."""
        import json as _json

        out = _json.loads(router._handle_route({"task_kind": "something_invented"}))
        assert "Unknown task_kind" in out["error"], (
            "an unrecognised kind must be refused, never inferred"
        )
