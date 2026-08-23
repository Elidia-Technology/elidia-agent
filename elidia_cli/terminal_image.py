"""Terminal inline-image rendering for the Elidia brand mark.

The old welcome banner drew a Hermes *caduceus* (the winged staff) on its left
side. That is the wrong brand. This module replaces it with the real Elidia
icon: when the terminal speaks an inline-image protocol (Kitty graphics,
iTerm2/WezTerm OSC-1337) the actual ``elidia-icon-dark.png`` is emitted; every
other terminal (and every non-TTY pipe) gets a Unicode block-art rendering of
the same icon so no Hermes symbol is ever drawn.

Everything here is deliberately dependency-free (no PIL at runtime): the PNG
dimensions are read straight from the file header, and the fallback art is a
pre-computed block rendering embedded as a constant.
"""

from __future__ import annotations

import base64
import logging
import os
import struct
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Brand mark
# ---------------------------------------------------------------------------

# The Elidia brand glyph. Replaces the Hermes caduceus (staff) symbol that
# used to prefix labels like "Elidia" across the CLI.
ELIDIA_MARK = "✦"

# Unicode Braille fallback of assets/elidia-icon-dark.png (the Elidia emblem).
# The icon is a dark mark (for light backgrounds), so it is inverted here — the
# dark mark becomes light Braille dots — for dark terminals. Regenerated from the
# icon so terminals without an image protocol still show the Elidia mark, not Hermes.
ELIDIA_ICON_ART = "\n".join([
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⣀⣠⣤⣶⠶⠾⠿⠛⠛⠛⠛⠛⠻⠶⠶⢦⣤⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⣠⣴⠾⠟⠋⠉⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠉⠙⠳⠶⣄⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⣠⣶⠟⠋⠀⠀⠀⠀⠀⠀⣀⣤⡶⠶⠛⠛⠻⠿⣖⠲⣤⡀⠀⠀⠀⠀⠀⠀⠀⠙⠳⢦⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⣰⡾⠋⠀⠀⠀⠀⠀⠀⢀⣴⣿⠟⣁⡤⠤⢾⣹⡀⠀⠈⠙⢦⡙⠷⣄⠀⠀⠀⠀⠀⠀⠀⠀⠉⠳⢄⡀⠀⠀⠀⠀⠀⠀',
    '⣿⠁⠀⠀⠀⠀⠀⢀⣴⢣⡿⣡⣊⡥⠤⢤⣄⡀⠙⢦⠸⣍⡇⠙⢦⡈⠻⣦⢤⡀⠀⠀⠀⠀⠀⠀⠀⠈⠂⠀⠀⠀⠀⠀',
    '⣿⠀⠀⠀⠀⠀⢠⠋⡇⢸⣿⣫⣤⣄⣀⠀⠈⠻⣆⠈⡇⢸⠀⣠⣄⠉⠂⠑⠾⢧⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⣿⠀⠀⠀⠀⢠⠿⣄⢳⣸⣯⠶⣶⣦⡙⢷⣄⠀⢹⠀⡇⢸⡀⠳⠺⣄⣀⣀⣀⣠⡙⠶⣤⣀⠀⠀⠀⠀⣀⠀⠀⠀⠀⠀',
    '⣿⡆⠀⠀⠀⣾⣤⣾⡟⠉⠃⠀⠀⠙⢯⠀⢿⢦⠘⢦⡙⢦⡙⢦⣀⣈⣉⣩⢭⠉⠙⢦⡀⠉⠙⠛⠒⠺⣭⠇⠀⠀⠀⠀',
    '⢸⡇⠀⠀⠀⡟⢱⣿⠀⠀⠀⠀⠀⠀⠈⢧⠈⣧⠳⣄⠙⣦⡙⠦⠬⠭⢭⡙⠚⠀⠀⠀⠩⠶⣄⣀⣀⣀⣀⣀⣠⠤⡄⠀',
    '⠘⣷⠀⠀⠀⣇⣿⣿⠤⣀⠀⠀⢠⡴⠖⠚⢷⡘⢷⣌⠳⢬⣛⠶⠶⢶⣄⠙⠦⠤⠤⠤⢤⣄⠀⠀⠀⠀⠀⠀⠈⠒⠁⠀',
    '⠀⢻⡆⠀⠀⢻⣏⢿⡶⢮⡆⠀⠀⠴⠿⢿⠖⠙⢾⣿⣷⡲⠬⣉⡓⢦⡙⢧⣤⣤⡔⢲⠀⠙⠷⠤⠤⢴⣛⡆⠀⠀⠀⠀',
    '⠀⠘⣷⠀⠀⠈⢿⡼⡏⠁⠘⠀⠀⠀⠀⠁⠀⠀⠈⢻⡹⣝⠳⣦⣙⠳⣝⢆⣀⣀⡈⠙⢷⣄⣀⣀⣀⣀⣉⣀⣀⣀⡤⢤',
    '⠀⠀⠸⣧⠀⠀⠈⢿⣧⠀⢇⠀⠀⠀⠀⠀⠀⠀⠀⣤⣷⢸⡆⢈⢻⣷⡘⢿⠁⠀⠙⢦⡀⠈⠉⠉⠉⠉⠉⠉⠉⠉⠓⠊',
    '⠀⠀⠀⢹⣆⠀⠀⠀⢻⣆⠠⣤⠤⠄⠀⠀⠀⠀⡼⠁⣿⢸⣿⢸⡆⢿⡿⣌⢷⢤⡀⠀⠙⠛⠛⠓⠒⠒⢾⣹⠆⠀⠀⠀',
    '⠀⠀⠀⠀⠻⣆⠀⠀⠈⢿⣆⠲⠖⠀⠀⠀⣠⠞⠀⠀⣿⣼⣿⣾⠇⢸⣷⢹⡌⣆⠉⠙⠓⠺⣍⠇⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠹⣧⠀⠀⠀⢻⣆⣀⣠⣴⠞⠁⠀⠀⢰⠟⣱⣿⠟⡀⢸⡿⢸⡇⢻⠀⢠⡖⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠘⢷⡄⠀⠀⠹⡟⣏⢿⡇⠀⠀⣠⡴⠟⠋⣡⠞⣡⡿⠃⢸⡇⠈⣴⠟⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠈⠻⣦⡀⠀⠀⢹⢸⡇⢠⡾⠋⣠⡶⠋⣡⡾⠋⠀⢠⡟⣠⡾⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣦⣠⣿⢸⠁⣿⠁⣾⠋⠀⣰⠋⠀⢀⣴⣿⠿⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿⡏⠸⡇⢸⡇⠀⠀⠇⣀⣴⣿⠟⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⠻⣶⣿⡈⢇⣀⣴⣾⠟⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
    '⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠈⠙⠿⡿⠟⠋⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀',
])

# Cells the inline image is sized to (width x height, in terminal cells). The
# icon is square so a square box avoids distortion.
_ICON_CELLS_W = 16
_ICON_CELLS_H = 16


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

def detect_image_protocol() -> str | None:
    """Return the inline-image protocol the terminal supports, or ``None``.

    Returns one of ``"kitty"``, ``"iterm"``, ``"wezterm"``. WezTerm is routed
    to the iTerm2 encoder because its OSC-1337 (inline image) support is more
    reliable than its partial Kitty graphics implementation.
    """
    term_program = os.environ.get("TERM_PROGRAM", "") or ""
    term = os.environ.get("TERM", "") or ""

    if os.environ.get("KITTY_WINDOW_ID") or term == "xterm-kitty" or "kitty" in term_program.lower():
        return "kitty"

    if term_program == "WezTerm" or os.environ.get("WEZTERM_PANE") or os.environ.get("WEZTERM_EXECUTABLE"):
        return "wezterm"

    if term_program in ("iTerm.app", "iTerm2") or os.environ.get("ITERM_SESSION_ID"):
        return "iterm"

    return None


# ---------------------------------------------------------------------------
# Icon location
# ---------------------------------------------------------------------------

def _find_icon() -> Path | None:
    """Locate ``elidia-icon-dark.png``.

    Checks, in order: an explicit env override, the copy shipped inside the
    ``elidia_cli`` package (wheel install), then the git checkout's ``assets/``
    directory (dev install).
    """
    for env in ("ELIDIA_ICON", "ELIDIA_LOGO"):
        value = os.environ.get(env)
        if value:
            candidate = Path(value)
            if candidate.is_file():
                return candidate

    try:
        from importlib import resources
        packaged = resources.files("elidia_cli") / "assets" / "elidia-icon-dark.png"
        if packaged.is_file():
            return Path(packaged)
    except Exception:  # pragma: no cover - importlib.resources edge cases
        pass

    checkout = Path(__file__).resolve().parents[1] / "assets" / "elidia-icon-dark.png"
    if checkout.is_file():
        return checkout

    return None


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Read (width, height) from a PNG IHDR header, or ``(0, 0)``."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return 0, 0
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    return width, height


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------

# Kitty caps each graphics escape at 4096 bytes; stay well under.
_KITTY_CHUNK = 3000


def encode_kitty_image(path: Path, cells_w: int, cells_h: int) -> str:
    """Encode *path* (a PNG) as a Kitty graphics-protocol inline image."""
    data = path.read_bytes()
    width, height = _png_dimensions(data)
    b64 = base64.b64encode(data).decode("ascii")
    chunks = [b64[i:i + _KITTY_CHUNK] for i in range(0, len(b64), _KITTY_CHUNK)]

    image_id = 1
    out: list[str] = []
    for index, chunk in enumerate(chunks):
        more = 1 if index < len(chunks) - 1 else 0
        if index == 0:
            # First chunk carries the transmit action + format + dimensions.
            out.append(
                f"\x1b_Ga=T,f=100,i={image_id},s={width},v={height},m={more};{chunk}\x1b\\"
            )
        else:
            out.append(f"\x1b_Gm={more};{chunk}\x1b\\")

    # Place at the cursor sized to the requested cell box, quietly.
    out.append(f"\x1b_Ga=p,i={image_id},c={cells_w},r={cells_h},q=1\x1b\\")
    return "".join(out)


def encode_iterm_image(path: Path, cells_w: int, cells_h: int) -> str:
    """Encode *path* (a PNG) as an iTerm2/WezTerm OSC-1337 inline image."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    name = base64.b64encode(b"elidia-icon.png").decode("ascii")
    return (
        f"\x1b]1337;File=inline=1;name={name};size={len(data)};"
        f"width={cells_w};height={cells_h};preserveAspectRatio=1:{b64}\x07"
    )


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------

def render_icon(cells_w: int = _ICON_CELLS_W, cells_h: int = _ICON_CELLS_H) -> str | None:
    """Return an inline-image escape sequence for the Elidia icon, or ``None``.

    Returns ``None`` (so the caller falls back to :data:`ELIDIA_ICON_ART`) when
    the terminal has no inline-image protocol, stdout is not a TTY, the icon
    cannot be found, or encoding fails. Never raises.
    """
    try:
        protocol = detect_image_protocol()
        if protocol is None:
            return None
        if not sys.stdout.isatty():
            return None
        icon = _find_icon()
        if icon is None:
            return None
        if protocol == "kitty":
            return encode_kitty_image(icon, cells_w, cells_h)
        return encode_iterm_image(icon, cells_w, cells_h)
    except Exception:
        logger.debug("Entered into render_icon: failed to encode Elidia icon", exc_info=True)
        return None
