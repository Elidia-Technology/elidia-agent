#!/usr/bin/env python3
"""AiUtils file storage — list, read and download the user's stored files.

Gives the agent access to files the user has put in AiUtils storage: documents,
spreadsheets, text, data, archives. Two kinds live there:

**Vault files** — encrypted under the user's own key and kept indefinitely.
**Ordinary files** — unencrypted and deleted 10 days after upload.

Decryption happens server-side, so the agent receives plaintext and never
handles a key. That is deliberate: the user's key is invisible to them and to
this process, and only AiUtils services can unwrap it.

Reading vs downloading
----------------------
``read`` returns text into the conversation and is what you want for a document
you are about to reason over. ``download`` writes bytes to disk and is for
binaries, or for anything large enough that pulling it into context would be
wasteful. A 40 MB spreadsheet read into a prompt is a mistake this tool should
not make easy, so ``read`` refuses beyond a size cap and points at ``download``.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

# Above this, reading into the conversation costs more than it is worth; the
# agent should download and work with the file on disk instead.
MAX_READ_BYTES = 256 * 1024

# Types whose bytes are meaningful as text. Anything else is offered for
# download rather than decoded into the conversation as mojibake.
_TEXTUAL_PREFIXES = ("text/",)
_TEXTUAL_TYPES = frozenset({
    "application/json", "application/xml", "application/x-ndjson",
    "application/yaml", "image/svg+xml",
})


def _is_textual(content_type: str) -> bool:
    ct = (content_type or "").strip().lower()
    return ct in _TEXTUAL_TYPES or any(ct.startswith(p) for p in _TEXTUAL_PREFIXES)


def _client():
    from tools import aiutils_client
    return aiutils_client.get_client()


def _handle_list(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    vaulted = args.get("vaulted")
    logger.debug(f"Entered into _handle_list: vaulted={vaulted}")
    try:
        records = _client().files.list(
            vaulted=None if vaulted is None else bool(vaulted),
            limit=int(args.get("limit") or 50),
        )
    except Exception as exc:
        logger.warning("aiutils_files list failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="list files")
        return tool_error(handled or f"Could not list files: {exc}")

    return json.dumps({
        "count": len(records),
        "files": [{
            "id": r.get("id"),
            "filename": r.get("filename"),
            "content_type": r.get("content_type"),
            "bytes": r.get("bytes_original"),
            "vaulted": r.get("vaulted"),
            # Present only for unvaulted files; a vault file has no expiry.
            "expires_at": r.get("expires_at"),
            "readable_as_text": _is_textual(r.get("content_type", "")),
        } for r in records],
    }, indent=2, default=str)


def _handle_read(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    file_id = str(args.get("file_id") or "").strip()
    logger.debug(f"Entered into _handle_read: file_id={file_id}")
    if not file_id:
        return tool_error("file_id is required")

    try:
        client = _client()
        meta = client.files.get(file_id)
    except Exception as exc:
        handled = aiutils_client.handle_sdk_error(exc, action="read file")
        return tool_error(handled or f"Could not read file: {exc}")

    content_type = meta.get("content_type", "")
    size = meta.get("bytes_original") or 0

    if not _is_textual(content_type):
        return tool_error(
            f"{meta.get('filename')} is {content_type}, which is not text. "
            f"Use action='download' to write it to disk and open it with a tool "
            f"that understands the format."
        )
    if size > MAX_READ_BYTES:
        return tool_error(
            f"{meta.get('filename')} is {size} bytes, above the {MAX_READ_BYTES}-byte "
            f"read limit. Use action='download' and work with it on disk — pulling "
            f"a file this size into the conversation wastes context without helping."
        )

    try:
        content = client.files.download(file_id)
    except Exception as exc:
        handled = aiutils_client.handle_sdk_error(exc, action="read file")
        return tool_error(handled or f"Could not read file: {exc}")

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return tool_error(
            f"{meta.get('filename')} is declared as {content_type} but is not valid "
            f"UTF-8. Use action='download' to inspect it directly."
        )

    return json.dumps({
        "id": file_id,
        "filename": meta.get("filename"),
        "content_type": content_type,
        "bytes": size,
        "vaulted": meta.get("vaulted"),
        "content": text,
    }, indent=2, default=str)


def _handle_download(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    file_id = str(args.get("file_id") or "").strip()
    destination = str(args.get("destination") or "").strip()
    logger.debug(f"Entered into _handle_download: file_id={file_id}, dest={destination}")
    if not file_id:
        return tool_error("file_id is required")
    if not destination:
        return tool_error("destination is required — a directory or a file path")

    expanded = os.path.expanduser(destination)
    parent = expanded if os.path.isdir(expanded) else os.path.dirname(expanded) or "."
    if not os.path.isdir(parent):
        return tool_error(f"Directory does not exist: {parent}")

    try:
        written = _client().files.download_to(file_id, expanded)
    except Exception as exc:
        logger.warning("aiutils_files download failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="download file")
        return tool_error(handled or f"Could not download file: {exc}")

    return json.dumps({
        "id": file_id,
        "path": written,
        "bytes": os.path.getsize(written),
    }, indent=2)


def _handle_upload(args: Dict[str, Any], **_kw) -> str:
    from tools.registry import tool_error
    from tools import aiutils_client

    path = os.path.expanduser(str(args.get("path") or "").strip())
    logger.debug(f"Entered into _handle_upload: path={path}")
    if not path:
        return tool_error("path is required")
    if not os.path.isfile(path):
        return tool_error(f"No such file: {path}")

    try:
        record = _client().files.upload(path, purpose="general")
    except Exception as exc:
        logger.warning("aiutils_files upload failed: %s", exc)
        handled = aiutils_client.handle_sdk_error(exc, action="upload file")
        return tool_error(handled or f"Could not upload file: {exc}")

    vaulted = record.get("vaulted")
    return json.dumps({
        "id": record.get("id"),
        "filename": record.get("filename"),
        "bytes_original": record.get("bytes_original"),
        "bytes_stored": record.get("bytes_stored"),
        "encrypted": record.get("encrypted"),
        "vaulted": vaulted,
        "expires_at": record.get("expires_at"),
        # Say plainly what happens next. A file that silently disappears in ten
        # days is worse than one the user was told about.
        "retention": (
            "Kept indefinitely — this account has a vault."
            if vaulted else
            "Deleted after 10 days. A vault subscription keeps files permanently "
            "and encrypts them."
        ),
    }, indent=2, default=str)


def handle_aiutils_files(args: Dict[str, Any], **kw) -> str:
    from tools.registry import tool_error

    action = str(args.get("action") or "list").strip().lower()
    logger.debug(f"Entered into handle_aiutils_files: action={action}")

    dispatch = {
        "list": _handle_list,
        "read": _handle_read,
        "download": _handle_download,
        "upload": _handle_upload,
    }
    handler = dispatch.get(action)
    if handler is None:
        return tool_error(
            f"unknown action {action!r}. Valid: list, read, download, upload"
        )
    return handler(args, **kw)


AIUTILS_FILES_SCHEMA = {
    "name": "aiutils_files",
    "description": (
        "The user's files in AiUtils storage — documents, spreadsheets, text, "
        "data, archives. Use it when they refer to something they have stored "
        "rather than a file on this machine.\n\n"
        "Vault files are encrypted under the user's own key and kept "
        "indefinitely. Ordinary files are deleted 10 days after upload; the "
        "listing shows which is which. Decryption happens on the server, so "
        "content arrives as plaintext and no key is handled here.\n\n"
        "read pulls text into the conversation — right for a document you are "
        "about to reason over. download writes bytes to disk — right for "
        "binaries, and for anything large, since reading a big file into "
        "context costs far more than working with it on disk."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "read", "download", "upload"],
                "description": (
                    "list: what the user has stored · read: text content into the "
                    "conversation · download: write to a local path · upload: store "
                    "a local file"
                ),
            },
            "file_id": {
                "type": "string",
                "description": "read/download: the file's id, from action='list'.",
            },
            "destination": {
                "type": "string",
                "description": "download: a directory (keeps the original name) or a full file path.",
            },
            "path": {
                "type": "string",
                "description": "upload: local file to store.",
            },
            "vaulted": {
                "type": "boolean",
                "description": (
                    "list: true for vault files only, false for expiring files only. "
                    "Omit for both."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "list: maximum records (default 50).",
            },
        },
        "required": ["action"],
    },
}


def check_aiutils_files_requirements() -> bool:
    """Available when the AiUtils Developer API is configured.

    Returns a plain bool, which is the registry's contract. It used to be
    annotated Tuple[bool, str] and return a tuple on the failure path — and a
    non-empty tuple is TRUTHY, so `(False, "unavailable")` advertised the tool
    as available at exactly the moment it was not.
    """
    logger.debug("Entered into check_aiutils_files_requirements")
    try:
        from tools import aiutils_client
        return bool(aiutils_client.check_aiutils_requirements())
    except Exception as exc:
        logger.warning("AiUtils file storage unavailable: %s", exc)
        return False


from tools.registry import registry, tool_error  # noqa: E402

registry.register(
    name="aiutils_files",
    toolset="aiutils",
    schema=AIUTILS_FILES_SCHEMA,
    handler=handle_aiutils_files,
    check_fn=check_aiutils_files_requirements,
    emoji="🗄️",
)
