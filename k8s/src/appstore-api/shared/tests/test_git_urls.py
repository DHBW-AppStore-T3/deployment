import pytest

from appstore_shared.git_urls import (
    GitHostNotAllowed,
    checked_https_url,
    parse_allowed_hosts,
    to_https_url,
)


@pytest.mark.parametrize(
    "given, expected",
    [
        ("git@github.com:acme/widgets.git", "https://github.com/acme/widgets.git"),
        ("http://gitlab.com/group/project", "https://gitlab.com/group/project"),
        ("https://github.com/acme/widgets", "https://github.com/acme/widgets"),
        ("  https://github.com/acme/widgets  ", "https://github.com/acme/widgets"),
        # A token pasted into the URL is not passed on.
        ("https://ghp_secret@github.com/acme/widgets", "https://github.com/acme/widgets"),
        ("https://user:pw@example.org/a/b.git", "https://example.org/a/b.git"),
        # An "@" in the path is not a credential separator.
        ("https://example.org/team@x/repo", "https://example.org/team@x/repo"),
    ],
)
def test_to_https_url(given, expected):
    assert to_https_url(given) == expected


ALLOWED = {"github.com", "gitlab.dhbw.de"}


@pytest.mark.parametrize(
    "given, expected",
    [
        ("git@github.com:acme/widgets.git", "https://github.com/acme/widgets.git"),
        ("https://GitHub.com/acme/widgets", "https://github.com/acme/widgets"),
        ("https://gitlab.dhbw.de/group/sub/project", "https://gitlab.dhbw.de/group/sub/project"),
    ],
)
def test_checked_https_url_accepts_allowed_hosts(given, expected):
    assert checked_https_url(given, ALLOWED) == expected


@pytest.mark.parametrize(
    "given",
    [
        "https://evil.example/acme/widgets",
        # Internal addresses are just hosts that are not on the list.
        "http://169.254.169.254/latest/meta-data",
        "https://github.com.evil.example/acme/widgets",
        "https://github.com/../../etc/passwd",
        "https://github.com/onlyowner",
        "https://github.com/acme/widgets?x=--upload-pack=sh",
        "file:///etc/passwd",
    ],
)
def test_checked_https_url_refuses_everything_else(given):
    with pytest.raises(GitHostNotAllowed):
        checked_https_url(given, ALLOWED)


def test_parse_allowed_hosts():
    assert parse_allowed_hosts(" GitHub.com, ,gitlab.dhbw.de ") == {"github.com", "gitlab.dhbw.de"}
