"""Tests for the AiUtils API-knowledge layer (B3).

Handlers are exercised directly against a fake client; no network involved.
Two properties matter most here: the catalog is cached (it is consulted several
times per turn), and these reads are NOT credit-guarded — they are unbilled,
and refusing discovery on an empty wallet would be exactly backwards.
"""

import json
import types

import pytest

from tools import aiutils_client, aiutils_models


def _model(model_id="fal:flux/dev", **over):
    data = dict(
        id=model_id,
        label="FLUX dev",
        name="flux-dev",
        vendor="fal",
        modality="image",
        category="image",
        description="Text to image",
        is_async=False,
        pricing=types.SimpleNamespace(dt_cost=7, free=False),
        capabilities=types.SimpleNamespace(vision=False),
        input_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What to draw"},
                "size": {"type": "string", "enum": ["512", "1024"]},
            },
            "required": ["prompt"],
        },
        output_schema={"type": "object"},
    )
    data.update(over)
    return types.SimpleNamespace(**data)


class _FakeModels:
    def __init__(self):
        self.list_calls = 0
        self.info_calls = 0

    def list(self, category=None, vendor=None, search=None, page_size=50):
        self.list_calls += 1
        return types.SimpleNamespace(data=[_model()], total=1)

    def get_info(self, model_id):
        self.info_calls += 1
        return _model(model_id)


class _FakeClient:
    def __init__(self):
        self.models = _FakeModels()


@pytest.fixture
def client(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(aiutils_client, "get_client", lambda base_url=None: fake)
    aiutils_models._clear_cache()
    return fake


def _parse(result):
    return json.loads(result)


class TestCatalogDiscovery:
    def test_returns_compact_entries(self, client):
        out = _parse(aiutils_models._handle_catalog({}))
        assert out["returned"] == 1
        entry = out["models"][0]
        assert entry["id"] == "fal:flux/dev"
        assert entry["dt_cost"] == 7
        assert entry["modality"] == "image"

    def test_limit_is_clamped_to_max(self, client, monkeypatch):
        captured = {}

        def _list(category=None, vendor=None, search=None, page_size=50):
            captured["page_size"] = page_size
            return types.SimpleNamespace(data=[], total=0)

        client.models.list = _list
        aiutils_models._handle_catalog({"limit": 100000})
        assert captured["page_size"] == aiutils_models.MAX_LIMIT

    def test_repeated_identical_calls_hit_the_cache(self, client):
        aiutils_models._handle_catalog({"category": "image"})
        aiutils_models._handle_catalog({"category": "image"})
        assert client.models.list_calls == 1, "second identical call must be served from cache"

    def test_different_filters_are_cached_separately(self, client):
        aiutils_models._handle_catalog({"category": "image"})
        aiutils_models._handle_catalog({"category": "video"})
        assert client.models.list_calls == 2

    def test_backend_failure_is_reported_not_raised(self, client):
        def _boom(**kw):
            raise RuntimeError("gateway down")

        client.models.list = _boom
        out = _parse(aiutils_models._handle_catalog({}))
        assert "error" in out
        assert "Could not load the model catalog" in out["error"]


class TestModelInfoDrivesInputCollection:
    def test_missing_model_id(self, client):
        out = _parse(aiutils_models._handle_model_info({"model_id": ""}))
        assert "model_id is required" in out["error"]

    def test_exposes_input_schema(self, client):
        out = _parse(aiutils_models._handle_model_info({"model_id": "fal:flux/dev"}))
        assert out["input_schema"]["required"] == ["prompt"]

    def test_maps_schema_into_clarify_widgets(self, client):
        """This is the B4 mapper's first production call site (AIUT-2950)."""
        out = _parse(aiutils_models._handle_model_info({"model_id": "fal:flux/dev"}))
        by_field = {w["field"]: w for w in out["widgets"]}
        assert by_field["prompt"]["required"] is True
        assert by_field["prompt"]["question"] == "What to draw"
        assert by_field["size"]["choices"] == ["512", "1024"]

    def test_required_prompts_cover_only_required_fields(self, client):
        out = _parse(aiutils_models._handle_model_info({"model_id": "fal:flux/dev"}))
        assert [p["field"] for p in out["required_prompts"]] == ["prompt"]

    def test_info_is_cached_per_model(self, client):
        aiutils_models._handle_model_info({"model_id": "fal:flux/dev"})
        aiutils_models._handle_model_info({"model_id": "fal:flux/dev"})
        assert client.models.info_calls == 1


class TestCatalogReadsAreNotCreditGuarded:
    """GET /v1/models is unbilled. Guarding it would refuse discovery exactly
    when an empty wallet makes knowing the prices most useful."""

    def test_catalog_works_with_an_empty_wallet(self, client, monkeypatch):
        def _refuse(*a, **kw):
            raise AssertionError("catalog reads must not consult the credit guard")

        monkeypatch.setattr(aiutils_client, "check_spend_allowed", _refuse)
        monkeypatch.setattr(aiutils_client, "check_credit_before_spend", _refuse)

        out = _parse(aiutils_models._handle_catalog({}))
        assert out["returned"] == 1

    def test_model_info_works_with_an_empty_wallet(self, client, monkeypatch):
        def _refuse(*a, **kw):
            raise AssertionError("catalog reads must not consult the credit guard")

        monkeypatch.setattr(aiutils_client, "check_spend_allowed", _refuse)
        out = _parse(aiutils_models._handle_model_info({"model_id": "m"}))
        assert out["id"] == "m"
