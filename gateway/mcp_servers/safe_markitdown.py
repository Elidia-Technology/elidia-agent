"""Document -> Markdown MCP server, restricted to our own CDN (AIUT-3314).

`markitdown-mcp` resolves whatever URI it is given and runs on the gateway
host, so a prompted agent could read local files and reach loopback services:

    file:///etc/passwd                        -> returned the passwd contents
    http://127.0.0.1:8000/agent-v2/v1/health  -> returned the internal API response

This server exposes the same capability with the URI constrained before
anything is fetched. It uses the markitdown LIBRARY directly, so there is no
second resolver behind it that could be handed a different scheme.

Allowed: https:// URLs whose host is in MARKITDOWN_ALLOWED_HOSTS
         (default: cdn.aiutils.io), which is where the portal uploads every
         attachment.
Refused: every other scheme (file:, data:, ftp:, gopher:), any other host, and
         any URL that resolves to a loopback, link-local, private or reserved
         address — checked after DNS resolution so a hostname that points at
         127.0.0.1 is refused too.
"""
from __future__ import annotations

import ipaddress
import os
import socket
import sys
from typing import Any
from urllib.parse import urlparse

MAX_BYTES = int(os.getenv("MARKITDOWN_MAX_BYTES", str(25 * 1024 * 1024)))
FETCH_TIMEOUT = float(os.getenv("MARKITDOWN_TIMEOUT_SECONDS", "30"))
ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.getenv("MARKITDOWN_ALLOWED_HOSTS", "cdn.aiutils.io").split(",")
    if h.strip()
}


class UriRefused(ValueError):
    """The URI is not one this server is willing to fetch."""


def _resolved_addresses(host: str) -> list[str]:
    """Every address the host resolves to, so none can be smuggled past."""
    infos = socket.getaddrinfo(host, None)
    return [info[4][0] for info in infos]


def check_uri(uri: str) -> str:
    """Return the URI if it is safe to fetch, else raise UriRefused.

    Separated from the fetch so it can be tested without network access.
    """
    if not isinstance(uri, str) or not uri.strip():
        raise UriRefused("A document URL is required.")
    uri = uri.strip()

    parsed = urlparse(uri)
    if parsed.scheme.lower() != "https":
        raise UriRefused(
            f"Only https:// documents can be read (got {parsed.scheme or 'no'} scheme). "
            "Upload the file first and pass the resulting CDN link."
        )

    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise UriRefused(
            f"Only documents on {', '.join(sorted(ALLOWED_HOSTS))} can be read "
            f"(got {host or 'no host'})."
        )

    # A permitted hostname must not point somewhere internal.
    try:
        addresses = _resolved_addresses(host)
    except OSError as exc:
        raise UriRefused(f"Could not resolve {host}: {exc}") from exc
    for addr in addresses:
        ip = ipaddress.ip_address(addr)
        if (ip.is_loopback or ip.is_private or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UriRefused(f"{host} resolves to a non-public address ({addr}).")

    return uri


def convert(uri: str) -> str:
    """Fetch an allowed document and return it as Markdown."""
    import httpx
    from markitdown import MarkItDown

    safe_uri = check_uri(uri)

    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=False) as client:
        resp = client.get(safe_uri)
        resp.raise_for_status()
        body = resp.content
    if len(body) > MAX_BYTES:
        raise UriRefused(f"Document is larger than {MAX_BYTES} bytes.")

    import io

    stream = io.BytesIO(body)
    stream.name = os.path.basename(urlparse(safe_uri).path) or "document"
    result = MarkItDown().convert_stream(stream)
    return result.text_content


def main() -> int:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("safe-markitdown")

    @server.tool()
    def convert_to_markdown(uri: str) -> str:
        """Convert a document (PDF, DOCX, XLSX, PPTX, HTML, CSV) to Markdown.

        `uri` must be an https link on the platform CDN — the link returned
        when a file is uploaded. Local paths and other hosts are refused.
        """
        try:
            return convert(uri)
        except UriRefused as exc:
            return f"Refused: {exc}"
        except Exception as exc:
            return f"Could not convert the document: {exc}"

    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
