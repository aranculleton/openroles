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
    validators each request sent. Each answer gives its Content-Length, as a server's
    normally does, unless `length` is False."""

    def __init__(self, monkeypatch, body=b'{"jobs": [1]}', headers=None, length=True):
        self.body, self.headers, self.sent = body, dict(headers or {"ETag": '"v1"'}), []
        self.length = length
        monkeypatch.setattr(_http, "_urlopen", self.urlopen)

    def urlopen(self, req, timeout=0):
        asked = (req.get_header("If-none-match"), req.get_header("If-modified-since"))
        self.sent.append(asked)
        etag, modified = self.headers.get("ETag"), self.headers.get("Last-Modified")
        if (etag and asked[0] == etag) or (modified and not etag and asked[1] == modified):
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        headers = dict(self.headers)
        if self.length:
            headers.setdefault("Content-Length", str(len(self.body)))
        return Answer(self.body, headers)


def new_process(monkeypatch):
    """What a fresh run starts with: nothing in memory."""
    monkeypatch.setattr(_http, "_ETAGS", OrderedDict())


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    new_process(monkeypatch)
    monkeypatch.setattr(_http, "_DELAYS", {})
    monkeypatch.setattr(_http, "CACHE_DIR", "", raising=False)
    monkeypatch.setattr(_http, "_TIDY", {}, raising=False)


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


# ------------------------------------------------------------------ a body cut short

JOBS = json.dumps({"jobs": [{"id": i, "title": f"Role {i}"} for i in range(200)]}).encode()


def test_a_body_short_of_its_content_length_is_never_kept(monkeypatch, tmp_path):
    """http.client returns a short read with no error when the connection drops, so the
    only sign is the Content-Length the answer declared."""
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch, body=JOBS[:len(JOBS) // 2],
                  headers={"ETag": '"v1"', "Content-Length": str(len(JOBS))})
    assert _http.request(URL) == (None, "the response was not JSON")
    assert files(tmp_path) == []
    board.body, board.headers = JOBS, {"ETag": '"v1"', "Content-Length": str(len(JOBS))}
    new_process(monkeypatch)
    data, err = _http.request(URL)
    assert err is None and len(data["jobs"]) == 200
    assert board.sent == [(None, None), (None, None)]          # nothing was asked about again


def test_a_gzip_stream_that_stops_before_its_end_is_never_kept(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    zipped = gzip.compress(JOBS)
    board = Board(monkeypatch, body=zipped[:len(zipped) // 2],
                  headers={"ETag": '"v1"', "Content-Encoding": "gzip"})
    assert _http.request(URL) == (None, "the response was not JSON")
    assert files(tmp_path) == []
    board.body = zipped
    data, err = _http.request(URL)
    assert err is None and len(data["jobs"]) == 200
    assert board.sent == [(None, None), (None, None)]


def test_a_body_cut_short_on_a_real_connection_is_never_kept(monkeypatch, tmp_path):
    """The same through http.client itself, against a server on this machine that declares
    the whole length and closes the connection halfway through."""
    import http.server
    import threading
    import urllib.request

    sent = []

    class Cut(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            sent.append(self.headers.get("If-None-Match"))
            self.send_response(200)
            self.send_header("ETag", '"v1"')
            self.send_header("Content-Length", str(len(JOBS)))
            self.end_headers()
            self.wfile.write(JOBS[:len(JOBS) // 2])
            self.close_connection = True

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Cut)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), _http._HandBack)
    monkeypatch.setattr(_http, "_urlopen", lambda req, timeout: direct.open(req, timeout=timeout))
    try:
        openroles.configure(cache_dir=tmp_path)
        url = f"http://127.0.0.1:{server.server_port}/jobs"
        assert _http.request(url) == (None, "the response was not JSON")
        _http.request(url)
    finally:
        server.shutdown()
        server.server_close()
    assert sent == [None, None] and files(tmp_path) == []


def local_board(monkeypatch, answer):
    """A server on this machine whose GET handler is `answer(handler, n)` for the n-th
    request, read through http.client itself. Returns (url, the If-None-Match each request
    sent, a stop function)."""
    import http.server
    import threading
    import urllib.request

    sent = []

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            sent.append(self.headers.get("If-None-Match"))
            answer(self, len(sent))
            self.close_connection = True

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), _http._HandBack)
    monkeypatch.setattr(_http, "_urlopen", lambda req, timeout: direct.open(req, timeout=timeout))

    def stop():
        server.shutdown()
        server.server_close()
    return f"http://127.0.0.1:{server.server_port}/jobs", sent, stop


def test_a_body_that_gives_no_length_and_is_cut_short_is_never_kept(monkeypatch, tmp_path):
    """An answer with no Content-Length that is not chunked ends when the connection
    closes, and one dropped halfway ends the same way: the half was kept and sent back on
    every 304 until the board changed."""
    def answer(handler, n):
        handler.send_response(200)
        handler.send_header("ETag", '"v1"')
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.wfile.write(JOBS if n > 1 else JOBS[:len(JOBS) // 2])
    url, sent, stop = local_board(monkeypatch, answer)
    try:
        openroles.configure(cache_dir=tmp_path)
        assert _http.request_raw(url)[0] == JOBS[:len(JOBS) // 2].decode()
        assert _http.request_raw(url)[0] == JOBS.decode()          # asked afresh
        new_process(monkeypatch)
        assert _http.request_raw(url)[0] == JOBS.decode()
    finally:
        stop()
    assert sent == [None, None, None] and files(tmp_path) == []


def test_a_chunked_answer_and_a_whole_gzip_stream_are_kept_with_no_length(monkeypatch, tmp_path):
    """Both show for themselves that all of the body came: a chunked answer cut short
    raises, and a gzip stream has an end."""
    zipped = gzip.compress(JOBS)

    def answer(handler, n):
        if handler.headers.get("If-None-Match") == '"v1"':
            handler.send_response(304)
            handler.send_header("ETag", '"v1"')
            handler.end_headers()
            return
        handler.send_response(200)
        handler.send_header("ETag", '"v1"')
        if handler.path.endswith("gz"):
            handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.wfile.write(zipped)
        else:
            handler.send_header("Transfer-Encoding", "chunked")
            handler.end_headers()
            handler.wfile.write(b"%x\r\n%s\r\n0\r\n\r\n" % (len(JOBS), JOBS))
    url, sent, stop = local_board(monkeypatch, answer)
    try:
        openroles.configure(cache_dir=tmp_path)
        for address in (url, url + "?gz"):
            assert _http.request_raw(address)[0] == JOBS.decode()
            new_process(monkeypatch)
            assert _http.request_raw(address)[0] == JOBS.decode()
    finally:
        stop()
    assert sent == [None, '"v1"', None, '"v1"'] and len(files(tmp_path)) == 2


def test_a_kept_answer_a_304_sends_back_that_is_not_json_is_read_afresh(monkeypatch, tmp_path):
    """A damaged kept copy would otherwise be served on every 304 until the board changed."""
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch, body=JOBS[:100])                 # damaged, and kept as it came
    _http.request_raw(URL, accept="application/json")
    new_process(monkeypatch)
    board.body = JOBS
    data, err = _http.request(URL)
    assert err is None and len(data["jobs"]) == 200
    assert board.sent[-2:] == [('"v1"', None), (None, None)]
    new_process(monkeypatch)
    assert _http.request(URL)[0] == data                        # the good copy is the one kept
    assert board.sent[-1] == ('"v1"', None)


def test_a_damaged_kept_answer_is_not_kept_alive_by_the_304(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch, body=JOBS[:100])
    _http.request_raw(URL, accept="application/json")
    [kept] = files(tmp_path)
    os.utime(kept, (1_000_000_000, 1_000_000_000))
    new_process(monkeypatch)

    def gone(req, timeout=0):
        board.sent.append((req.get_header("If-none-match"), None))
        if req.get_header("If-none-match"):
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error", {}, None)
    monkeypatch.setattr(_http, "_urlopen", gone)
    assert _http.request(URL) == (None, "HTTP 500")
    assert files(tmp_path) == []                                # dropped, not refreshed


def test_a_file_without_this_release_s_format_is_a_miss(monkeypatch, tmp_path):
    """Files an earlier build wrote may hold a body cut short; this release never trusts them."""
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL)
    [kept] = files(tmp_path)
    with gzip.open(kept, "rt", encoding="utf-8") as fh:
        entry = json.load(fh)
    assert entry.pop("v") == _http.CACHE_FORMAT
    for v in (None, True, _http.CACHE_FORMAT + 1, str(_http.CACHE_FORMAT)):
        if v is not None:
            entry["v"] = v
        with gzip.open(kept, "wt", encoding="utf-8") as fh:
            json.dump(entry, fh)
        new_process(monkeypatch)
        assert _http.request(URL) == ({"jobs": [1]}, None)
        assert board.sent[-1] == (None, None)


def test_a_corrupt_gzip_body_is_a_failed_read_not_an_exception(monkeypatch):
    zipped = gzip.compress(JOBS)
    Board(monkeypatch, body=zipped[:10] + b"\xff" * 20 + zipped[30:],
          headers={"ETag": '"v1"', "Content-Encoding": "gzip"})
    monkeypatch.setattr(_http, "RETRY_PAUSE", 0)
    assert _http.request(URL) == (None, "BadGzipFile")


def test_json_nested_deeper_than_python_can_follow_is_not_json(monkeypatch):
    """It raised RecursionError, which is not a BoardError, so one board's answer lost
    every other board in the same call."""
    from openroles.providers import greenhouse
    Board(monkeypatch, body=b"[" * 100_000)
    assert _http.request(URL) == (None, "the response was not JSON")
    monkeypatch.setattr(_http, "robots_txt", lambda host: (404, ""))
    with pytest.raises(openroles.BoardError):
        greenhouse.fetch("acme")


# ------------------------------------------------------------------ the folder's caps

def folder_bytes(folder) -> int:
    return sum(os.path.getsize(p) for p in files(folder))


def test_the_size_cap_holds_after_every_write_not_only_some(monkeypatch, tmp_path):
    import random
    openroles.configure(cache_dir=tmp_path)
    monkeypatch.setattr(_http, "CACHE_BYTES", 10_000)
    board = Board(monkeypatch)
    for i in range(50):
        board.body = random.Random(i).getrandbits(8 * 2500).to_bytes(2500, "big").hex().encode()
        _http.request_raw(f"{URL}?page={i}")
        assert folder_bytes(tmp_path) <= 10_000


def test_a_full_folder_is_not_looked_at_whole_on_every_write(monkeypatch, tmp_path):
    """Taken down only to its cap, the folder passed it again on the next write, and every
    write after that scanned, stat-ed and sorted the whole folder while reads waited."""
    import random
    openroles.configure(cache_dir=tmp_path)
    monkeypatch.setattr(_http, "CACHE_BYTES", 20_000)
    looks = []
    whole = _http.prune
    monkeypatch.setattr(_http, "prune", lambda folder, now=None: looks.append(folder) or whole(folder, now))
    board = Board(monkeypatch)
    for i in range(200):
        board.body = random.Random(i).getrandbits(8 * 300).to_bytes(300, "big").hex().encode()
        _http.request_raw(f"{URL}?page={i}")
        assert folder_bytes(tmp_path) <= 20_000                 # the cap still holds
        if i == 99:                                             # the folder has long been full
            looks.clear()
    # 100 writes of about 500 bytes each: a look every tenth of the cap, not 100 of them.
    assert 0 < len(looks) <= 30


def test_a_run_of_only_304s_still_keeps_the_folder_to_its_caps(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch)
    _http.request(URL)                                          # the one still in use
    folder = tmp_path / "http"
    old = folder / ("a" * 64 + ".json.gz")                      # one not asked for in 40 days
    old.write_bytes(b"x" * 10)
    os.utime(old, (old.stat().st_mtime - 40 * 86400,) * 2)
    for n in (1, 2, 3):                                         # and more than the folder may hold
        extra = folder / (f"{n}" * 64 + ".json.gz")
        extra.write_bytes(b"x" * 400)
        os.utime(extra, (extra.stat().st_mtime - 86400 * n,) * 2)
    monkeypatch.setattr(_http, "CACHE_BYTES", 900)
    new_process(monkeypatch)
    monkeypatch.setattr(_http, "_TIDY", {}, raising=False)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert board.sent[-1] == ('"v1"', None)                     # a 304: nothing was written
    assert not old.exists() and folder_bytes(tmp_path) <= 900
    assert len(files(tmp_path)) == 2                            # the one in use, and the newest


# ------------------------------------------------------------------ in memory

def test_keeping_an_answer_does_not_add_up_every_kept_one_again(monkeypatch):
    """Each insert added up every body already kept, so a run of n answers cost n squared:
    20,000 answers of 1 kB took 40 seconds."""
    looked = [0]

    class Body(str):
        def __len__(self):
            looked[0] += 1
            return str.__len__(self)
    for i in range(1_000):
        _http._remember((f"{URL}?page={i}", "application/json"), '"v1"', Body("x" * 10))
    assert len(_http._ETAGS) == 1_000
    assert looked[0] <= 3 * 1_000          # a look or two at each body, not one per insert


def test_memory_keeps_to_its_cap_counting_each_body_once(monkeypatch):
    monkeypatch.setattr(_http, "ETAG_BYTES", 100)
    a, b, c, d = ((f"{URL}?{n}", "application/json") for n in "abcd")
    for _ in range(5):
        _http._remember(a, '"v1"', "x" * 60)          # the same answer again is not more of it
    _http._remember(b, '"v1"', "y" * 30)
    assert list(_http._ETAGS) == [a, b]
    _http._forget(a)
    _http._remember(c, '"v1"', "z" * 60)
    assert list(_http._ETAGS) == [b, c]
    _http._remember(d, '"v1"', "w" * 20)                # 110: the oldest goes
    assert list(_http._ETAGS) == [c, d]
    assert sum(len(v[-1]) for v in _http._ETAGS.values()) <= 100


# ------------------------------------------------------------------ what the caller asked for

def test_a_kept_body_longer_than_the_caller_s_limit_is_not_what_it_gets(monkeypatch, tmp_path):
    openroles.configure(cache_dir=tmp_path)
    board = Board(monkeypatch, body=b"x" * 5_000)
    assert len(_http.request_raw(URL, limit=1_000_000)[0]) == 5_000
    body, err = _http.request_raw(URL, limit=100)
    assert err is None and body == "x" * 100                    # as a fresh read cuts it
    assert board.sent[-1] == (None, None)
    assert len(_http.request_raw(URL, limit=1_000_000)[0]) == 5_000
    assert board.sent[-1] == ('"v1"', None)                     # and the whole copy stayed


def test_an_answer_kept_for_one_accept_is_not_given_to_another(monkeypatch, tmp_path):
    """A host that only sends Last-Modified answers 304 whatever was asked for."""
    openroles.configure(cache_dir=tmp_path)
    modified = "Tue, 20 Oct 2026 09:00:00 GMT"
    sent = []

    def urlopen(req, timeout=0):
        sent.append((req.get_header("Accept"), req.get_header("If-modified-since")))
        if req.get_header("If-modified-since") == modified:
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        body = b"<html>page</html>" if "html" in req.get_header("Accept") else b'{"jobs": [1]}'
        return Answer(body, {"Last-Modified": modified, "Content-Length": str(len(body))})
    monkeypatch.setattr(_http, "_urlopen", urlopen)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert _http.request_raw(URL, accept="text/html") == ("<html>page</html>", None)
    new_process(monkeypatch)
    assert _http.request(URL) == ({"jobs": [1]}, None)
    assert _http.request_raw(URL, accept="text/html") == ("<html>page</html>", None)
    assert sent == [("application/json", None), ("text/html", None),
                    ("application/json", modified), ("text/html", modified)]


def test_a_folder_that_is_not_text_or_a_path_is_refused_when_it_is_named(tmp_path):
    class BytesPath:
        def __fspath__(self):
            return b"/tmp/openroles-cache"
    openroles.configure(cache_dir=tmp_path)
    for wrong in (b"/tmp/openroles-cache", BytesPath(), 5, ["/tmp"], True):
        with pytest.raises(ValueError):
            openroles.configure(cache_dir=wrong)
        assert _http.CACHE_DIR == str(tmp_path)                 # left as it was
