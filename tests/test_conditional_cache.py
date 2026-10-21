"""Asking a board again with what its last answer came with: in memory, and on disk
across runs where the caller names a folder. Every answer here comes from a fake
`_urlopen`; nothing touches the network."""
import gzip
import io
import json
import os
import sys
import urllib.error
from collections import OrderedDict

import pytest

import openroles
from openroles import _http, cli

URL = "https://boards.example/v1/acme/jobs"


class Answer(io.BytesIO):
    def __init__(self, body: bytes, headers: dict):
        super().__init__(body)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Board:
    """One URL's answers: a body, the validators it is served with, and a record of the
    validators each request sent."""

    def __init__(self, monkeypatch, body=b'{"jobs": [1]}', headers=None):
        self.body, self.headers, self.sent = body, dict(headers or {"ETag": '"v1"'}), []
        monkeypatch.setattr(_http, "_urlopen", self.urlopen)

    def urlopen(self, req, timeout=0):
        asked = (req.get_header("If-none-match"), req.get_header("If-modified-since"))
        self.sent.append(asked)
        etag, modified = self.headers.get("ETag"), self.headers.get("Last-Modified")
        if (etag and asked[0] == etag) or (modified and not etag and asked[1] == modified):
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        return Answer(self.body, self.headers)


def new_process(monkeypatch):
    """What a fresh run starts with: nothing in memory."""
    monkeypatch.setattr(_http, "_ETAGS", OrderedDict())


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    new_process(monkeypatch)
    monkeypatch.setattr(_http, "_DELAYS", {})
    monkeypatch.setattr(_http, "CACHE_DIR", "", raising=False)
    monkeypatch.setattr(_http, "_WRITES", {}, raising=False)


def files(folder) -> list:
    out = []
    for root, _dirs, names in os.walk(folder):
        out += [os.path.join(root, n) for n in names]
    return out


def test_a_board_that_sends_only_a_last_modified_date_is_asked_with_it(monkeypatch):
    board = Board(monkeypatch, headers={"Last-Modified": "Tue, 20 Oct 2026 09:00:00 GMT"})
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert board.sent == [(None, None), (None, "Tue, 20 Oct 2026 09:00:00 GMT")]


def test_a_named_folder_keeps_the_answer_for_the_next_run(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    new_process(monkeypatch)
    board.body = b"the board must not be asked to send this"
    assert _http.request(URL) == ({"jobs": [1]}, None)          # 304: nothing sent
    assert board.sent == [(None, None), ('"v1"', None)]


def test_a_folder_named_after_a_read_is_given_that_answer(monkeypatch, tmp_path):
    board = Board(monkeypatch)
    _http.request(URL)
    openroles.configure(cache_dir=tmp_path)
    _http.request(URL)                                         # 304, from memory
    new_process(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert board.sent == [(None, None), ('"v1"', None), ('"v1"', None)]


def test_a_changed_board_replaces_what_was_kept(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL)
    board.body, board.headers = b'{"jobs": [1, 2]}', {"ETag": '"v2"'}
    assert _http.request(URL) == ({"jobs": [1, 2]}, None)
    new_process(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1, 2]}, None)
    assert board.sent[-1] == ('"v2"', None)


def test_an_answer_that_drops_its_validators_is_forgotten(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL)
    board.headers = {}
    _http.request(URL)
    new_process(monkeypatch)
    _http.request(URL)
    assert board.sent[-1] == (None, None) and files(tmp_path) == []


def test_nothing_is_kept_on_disk_unless_a_folder_is_named(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    Board(monkeypatch)
    _http.request(URL)
    assert _http.CACHE_DIR == "" and files(tmp_path) == []


def test_false_turns_the_folder_off(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    openroles.configure(cache_dir=False)
    Board(monkeypatch)
    _http.request(URL)
    assert files(tmp_path) == []
    with pytest.raises(ValueError):
        openroles.configure(cache_dir=True)


def test_a_post_and_a_no_store_answer_are_never_kept(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL, payload={"offset": 0})
    assert files(tmp_path) == []
    board.headers = {"ETag": '"v1"', "Cache-Control": "private, no-store"}
    _http.request(URL)
    _http.request(URL)
    assert board.sent[-1] == (None, None) and files(tmp_path) == []


def test_a_body_cut_at_the_limit_is_not_kept(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch, body=b"x" * 50)
    body, err = _http.request_raw(URL, limit=10)
    assert body == "x" * 10 and err is None
    _http.request_raw(URL, limit=10)
    assert board.sent == [(None, None), (None, None)] and files(tmp_path) == []


def test_an_unreadable_kept_file_is_a_miss_not_an_error(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL)
    [kept] = files(tmp_path)
    with open(kept, "wb") as fh:
        fh.write(b"not gzip")
    new_process(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert board.sent[-1] == (None, None)
    # Another address's file under this one's name is a miss too.
    with gzip.open(kept, "wt", encoding="utf-8") as fh:
        json.dump({"url": "https://elsewhere.example/", "etag": '"v1"', "last_modified": "",
                   "body": "{}"}, fh)
    new_process(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert board.sent[-1] == (None, None)


def test_a_kept_file_is_named_for_a_hash_and_readable_by_its_owner_only(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    Board(monkeypatch)
    _http.request(URL)
    [kept] = files(tmp_path)
    assert "acme" not in kept and "boards.example" not in kept
    if sys.platform != "win32":
        assert oct(os.stat(kept).st_mode & 0o777) == oct(0o600)


def test_the_folder_is_kept_to_its_size_and_age(monkeypatch, tmp_path):
    folder = tmp_path / "http"
    folder.mkdir()
    now = 2_000_000_000.0
    for name, age_days, size in (("old.json.gz", 40, 10), ("a.json.gz", 3, 400),
                                 ("b.json.gz", 2, 400), ("c.json.gz", 1, 400),
                                 ("cut.tmp", 1, 10), ("note.txt", 90, 10)):
        path = folder / name
        path.write_bytes(b"x" * size)
        os.utime(path, (now - age_days * 86400, now - age_days * 86400))
    monkeypatch.setattr(_http, "CACHE_BYTES", 900)
    _http.prune(str(folder), now=now)
    assert sorted(p.name for p in folder.iterdir()) == ["b.json.gz", "c.json.gz", "note.txt"]


def test_the_command_line_takes_a_cache_folder(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "fetch", lambda *a, **k: [])
    assert cli.main(["greenhouse:acme", "--cache", str(tmp_path), "--json"]) == 0
    assert _http.CACHE_DIR == str(tmp_path)
