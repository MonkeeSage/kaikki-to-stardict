import email.utils
import http.server
import os
import threading

import pytest

from kaikki_to_stardict.download import download

DATA = bytes(range(256)) * 1000
MODIFIED = email.utils.formatdate(1_700_000_000, usegmt=True)


class Handler(http.server.BaseHTTPRequestHandler):
    requests: list[dict[str, str]] = []

    def do_GET(self):
        self.requests.append(dict(self.headers))
        since = self.headers.get("If-Modified-Since")
        if since and email.utils.parsedate_to_datetime(since).timestamp() >= 1_700_000_000:
            self.send_response(304)
            self.end_headers()
            return
        start = 0
        if rng := self.headers.get("Range"):
            start = int(rng.removeprefix("bytes=").rstrip("-"))
            if start >= len(DATA):
                self.send_response(416)
                self.end_headers()
                return
            self.send_response(206)
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(DATA) - start))
        self.send_header("Last-Modified", MODIFIED)
        self.end_headers()
        self.wfile.write(DATA[start:])

    def log_message(self, *args):
        pass


@pytest.fixture
def url():
    Handler.requests = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/raw.jsonl.gz"
    server.shutdown()
    server.server_close()


def test_download_and_up_to_date(tmp_path, url):
    dst = tmp_path / "raw.jsonl.gz"
    assert download(url, dst) is True
    assert dst.read_bytes() == DATA
    assert os.path.getmtime(dst) == 1_700_000_000
    assert download(url, dst) is False  # 304 Not Modified
    assert "If-Modified-Since" in Handler.requests[-1]
    assert download(url, dst, force=True) is True


def test_resume(tmp_path, url):
    dst = tmp_path / "raw.jsonl.gz"
    (tmp_path / "raw.jsonl.gz.part").write_bytes(DATA[:1000])
    assert download(url, dst) is True
    assert Handler.requests[-1]["Range"] == "bytes=1000-"
    assert dst.read_bytes() == DATA
    assert not (tmp_path / "raw.jsonl.gz.part").exists()


def test_resume_complete_part_file(tmp_path, url):
    dst = tmp_path / "raw.jsonl.gz"
    (tmp_path / "raw.jsonl.gz.part").write_bytes(DATA)
    assert download(url, dst) is True
    assert dst.read_bytes() == DATA
