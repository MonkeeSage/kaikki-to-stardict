"""Download the raw wiktextract dump from kaikki.org, resumably."""

from __future__ import annotations

import email.utils
import os
import urllib.error
import urllib.request
from pathlib import Path

from kaikki_to_stardict import __version__
from kaikki_to_stardict.build import Progress

DEFAULT_URL = "https://kaikki.org/dictionary/raw-wiktextract-data.jsonl.gz"
USER_AGENT = f"kaikki-to-stardict/{__version__}"
BLOCK = 1 << 20


def _request(url: str, headers: dict[str, str]) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})


def download(
    url: str, dst: str | Path, force: bool = False, progress: Progress | None = None
) -> bool:
    """Download ``url`` to ``dst``; returns False if ``dst`` was already current.

    A finished download gets the server's Last-Modified time as its mtime,
    which later runs send back as If-Modified-Since. An interrupted download
    is kept as ``dst``.part and resumed with a Range request.
    """
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    headers = {}
    if dst.exists() and not force:
        headers["If-Modified-Since"] = email.utils.formatdate(dst.stat().st_mtime, usegmt=True)
    have = part.stat().st_size if part.exists() else 0
    if have:
        headers["Range"] = f"bytes={have}-"
    try:
        response = urllib.request.urlopen(_request(url, headers), timeout=60)
    except urllib.error.HTTPError as err:
        if err.code == 304:
            return False
        if err.code == 416 and have:  # the part file is already complete
            response = None
        else:
            raise
    if response is not None:
        with response:
            if response.status != 206:
                have = 0  # server ignored the Range header; start over
            total = response.headers.get("Content-Length")
            total = int(total) + have if total else None
            with open(part, "ab" if have else "wb") as f:
                while block := response.read(BLOCK):
                    f.write(block)
                    have += len(block)
                    if progress:
                        pct = f" ({100 * have / total:.1f}%)" if total else ""
                        progress.update(f"{have / 1e9:.2f} GB{pct}")
            if total is not None and have != total:
                raise OSError(f"incomplete download: got {have} of {total} bytes; rerun to resume")
            modified = response.headers.get("Last-Modified")
    else:
        modified = None
    part.replace(dst)
    if modified:
        stamp = email.utils.parsedate_to_datetime(modified).timestamp()
        os.utime(dst, (stamp, stamp))
    return True
