"""The document reader must refuse everything except our own CDN (AIUT-3314).

The upstream `markitdown-mcp` resolved whatever URI it was handed and ran on
the gateway host, so a prompted agent could read local files and reach
loopback services. Verified against it on production before it was disabled:

    file:///etc/passwd                        -> returned the passwd contents
    http://127.0.0.1:8000/agent-v2/v1/health  -> returned the internal API response

This replacement validates the URI before anything is fetched.
"""
from __future__ import annotations

import pytest

from gateway.mcp_servers.safe_markitdown import UriRefused, check_uri


class TestRefusedSchemes:
    """The two exploits that made the original unsafe."""

    def test_file_scheme_is_refused(self):
        with pytest.raises(UriRefused):
            check_uri("file:///etc/passwd")

    def test_loopback_http_is_refused(self):
        with pytest.raises(UriRefused):
            check_uri("http://127.0.0.1:8000/agent-v2/v1/health")

    @pytest.mark.parametrize("uri", [
        "http://cdn.aiutils.io/a.pdf",          # plain http, even on the right host
        "ftp://cdn.aiutils.io/a.pdf",
        "data:text/plain;base64,AAAA",
        "gopher://cdn.aiutils.io/a",
        "file://localhost/etc/hosts",
    ])
    def test_non_https_schemes_are_refused(self, uri):
        with pytest.raises(UriRefused):
            check_uri(uri)


class TestRefusedHosts:

    @pytest.mark.parametrize("uri", [
        "https://evil.example.com/a.pdf",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/a.pdf",
        "https://aiutils.io/api/v1/agent-v2/status",   # our own app, still not the CDN
    ])
    def test_other_hosts_are_refused(self, uri):
        with pytest.raises(UriRefused):
            check_uri(uri)

    def test_a_lookalike_host_is_refused(self):
        """Suffix matching would let cdn.aiutils.io.evil.com through."""
        with pytest.raises(UriRefused):
            check_uri("https://cdn.aiutils.io.evil.com/a.pdf")


class TestEmptyInput:

    @pytest.mark.parametrize("bad", ["", "   ", None, 123])
    def test_missing_uri_is_refused(self, bad):
        with pytest.raises(UriRefused):
            check_uri(bad)


class TestAllowedHost:

    def test_the_cdn_is_allowed(self, monkeypatch):
        import gateway.mcp_servers.safe_markitdown as m

        monkeypatch.setattr(m, "_resolved_addresses", lambda host: ["93.184.216.34"])
        assert check_uri("https://cdn.aiutils.io/user_4/generated/a.pdf") == \
            "https://cdn.aiutils.io/user_4/generated/a.pdf"

    def test_an_allowed_host_pointing_at_loopback_is_still_refused(self, monkeypatch):
        """DNS rebinding: the name is on the allowlist, the address is not."""
        import gateway.mcp_servers.safe_markitdown as m

        monkeypatch.setattr(m, "_resolved_addresses", lambda host: ["127.0.0.1"])
        with pytest.raises(UriRefused):
            check_uri("https://cdn.aiutils.io/a.pdf")

    @pytest.mark.parametrize("addr", [
        "10.0.0.5", "192.168.1.20", "172.16.0.9", "169.254.169.254", "::1",
    ])
    def test_private_and_link_local_targets_are_refused(self, monkeypatch, addr):
        import gateway.mcp_servers.safe_markitdown as m

        monkeypatch.setattr(m, "_resolved_addresses", lambda host: [addr])
        with pytest.raises(UriRefused):
            check_uri("https://cdn.aiutils.io/a.pdf")

    def test_refusal_if_any_resolved_address_is_internal(self, monkeypatch):
        """One public answer must not excuse a second, internal one."""
        import gateway.mcp_servers.safe_markitdown as m

        monkeypatch.setattr(m, "_resolved_addresses", lambda host: ["93.184.216.34", "127.0.0.1"])
        with pytest.raises(UriRefused):
            check_uri("https://cdn.aiutils.io/a.pdf")
