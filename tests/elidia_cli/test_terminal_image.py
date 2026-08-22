"""Tests for elidia_cli.terminal_image — the Elidia brand mark + inline-image
renderer that replaced the Hermes caduceus banner art and the ⚕ glyph."""

import struct

import pytest

from elidia_cli.terminal_image import (
    ELIDIA_ICON_ART,
    ELIDIA_MARK,
    _png_dimensions,
    detect_image_protocol,
    encode_iterm_image,
    encode_kitty_image,
    render_icon,
)


def _fake_png(width: int, height: int) -> bytes:
    """Build just enough of a PNG for _png_dimensions (sig + IHDR width/height)."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = (
        struct.pack(">I", 13)           # IHDR chunk length
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"       # bit depth 8, colour type 6, rest
    )
    return sig + ihdr


class TestBrandMark:
    def test_mark_is_not_hermes(self):
        assert ELIDIA_MARK == "✦"
        assert "⚕" not in ELIDIA_MARK and "☤" not in ELIDIA_MARK

    def test_fallback_art_is_elidia_braille_not_hermes(self):
        assert ELIDIA_ICON_ART.strip()
        # Braille characters (U+2800–U+28FF), not the old half-block ▀▄█ art.
        assert any("⠀" <= ch <= "⣿" for ch in ELIDIA_ICON_ART)
        # No Hermes caduceus glyph may appear in the fallback.
        assert "⚕" not in ELIDIA_ICON_ART and "☤" not in ELIDIA_ICON_ART


class TestProtocolDetection:
    def test_none_by_default(self, monkeypatch):
        for var in ("KITTY_WINDOW_ID", "TERM_PROGRAM", "TERM", "WEZTERM_PANE", "ITERM_SESSION_ID"):
            monkeypatch.delenv(var, raising=False)
        assert detect_image_protocol() is None

    def test_kitty(self, monkeypatch):
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.delenv("TERM", raising=False)
        monkeypatch.setenv("KITTY_WINDOW_ID", "1")
        assert detect_image_protocol() == "kitty"

    def test_wezterm(self, monkeypatch):
        monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.setenv("WEZTERM_PANE", "0")
        assert detect_image_protocol() == "wezterm"

    def test_iterm(self, monkeypatch):
        monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
        monkeypatch.delenv("WEZTERM_PANE", raising=False)
        monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
        assert detect_image_protocol() == "iterm"


class TestPngDimensions:
    def test_reads_width_height(self):
        assert _png_dimensions(_fake_png(512, 512)) == (512, 512)

    def test_rejects_non_png(self):
        assert _png_dimensions(b"not a png at all") == (0, 0)


class TestEncoders:
    def test_kitty_escape_shape(self, tmp_path):
        png = tmp_path / "icon.png"
        png.write_bytes(_fake_png(16, 16))
        out = encode_kitty_image(png, cells_w=16, cells_h=16)
        assert out.startswith("\x1b_G")
        assert out.endswith("\x1b\\")
        assert "\x1b_Ga=p" in out  # place command present
        assert ",c=16,r=16," in out
        # every graphics escape stays under Kitty's 4096-byte cap
        for chunk in out.split("\x1b\\")[:-1]:
            assert len(chunk) + 3 <= 4096

    def test_iterm_escape_shape(self, tmp_path):
        png = tmp_path / "icon.png"
        png.write_bytes(_fake_png(16, 16))
        out = encode_iterm_image(png, cells_w=16, cells_h=16)
        assert out.startswith("\x1b]1337;File=inline=1;")
        assert out.endswith("\x07")
        assert "width=16;height=16" in out
        assert "preserveAspectRatio=1" in out


class TestRenderIcon:
    def test_returns_none_when_not_a_tty(self, monkeypatch, tmp_path):
        # Force a protocol + a findable icon, but stdout is not a TTY.
        monkeypatch.setenv("KITTY_WINDOW_ID", "1")
        icon = tmp_path / "elidia-icon-dark.png"
        icon.write_bytes(_fake_png(16, 16))
        monkeypatch.setenv("ELIDIA_ICON", str(icon))
        import sys

        class _NonTty:
            def isatty(self):
                return False

        monkeypatch.setattr(sys, "stdout", _NonTty())
        assert render_icon() is None

    def test_returns_none_without_protocol(self, monkeypatch, tmp_path):
        monkeypatch.delenv("KITTY_WINDOW_ID", raising=False)
        monkeypatch.delenv("TERM_PROGRAM", raising=False)
        monkeypatch.delenv("WEZTERM_PANE", raising=False)
        monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
        assert render_icon() is None
