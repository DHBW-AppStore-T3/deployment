"""Upload names are reduced to plain file names (plan E8)."""

import pytest

from appstore_api.utils.filenames import FALLBACK, content_disposition, safe_filename


@pytest.mark.parametrize(
    "given, expected",
    [
        ("aufgabe.pdf", "aufgabe.pdf"),
        ("Übung 1 (Lösung).tex", "Übung 1 (Lösung).tex"),
        ("../../etc/cron.d/evil", "evil"),
        ("C:\\Users\\x\\notes.txt", "notes.txt"),
        ('a"b\r\nSet-Cookie: x=1.txt', "a_bSet-Cookie_ x_1.txt"),
        ("$(rm -rf ~).sh", "_(rm -rf _).sh"),
        (".bashrc", "bashrc"),
        ("...", FALLBACK),
        ("", FALLBACK),
        (None, FALLBACK),
    ],
)
def test_safe_filename(given, expected):
    assert safe_filename(given) == expected


def test_long_names_keep_their_extension():
    name = safe_filename("x" * 300 + ".pdf")
    assert len(name) <= 120 and name.endswith(".pdf")


def test_content_disposition_has_no_raw_quotes_or_line_breaks():
    header = content_disposition('bö"se\r\n.txt')
    assert "\r" not in header and "\n" not in header
    assert header.count('"') == 2
    assert "filename*=UTF-8''b%C3%B6_se.txt" in header
