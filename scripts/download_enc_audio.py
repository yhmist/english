"""Download all conversation MP3s from MHE Language Lab (ISBN 1259643271)."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIO_DIR = ROOT / "pmp_audios"
S3 = "https://mhelanguagelab.s3.amazonaws.com/1259643271/"

# Unit section -> dialogue title (conversation tracks only, not exercises).
# Pattern confirmed by user: ENC_01-02-01 first, ENC_02-02-01 second.
MAPPING = [
    ("Meeting at a party", "ENC_01-02-01.mp3"),
    ("Getting acquainted", "ENC_02-02-01.mp3"),
    ("Talking about roommates", "ENC_03-02-01.mp3"),
    ("Running into a friend", "ENC_04-02-01.mp3"),
    ("Making an appointment with a doctor", "ENC_05-02-01.mp3"),
    ("Changing a lunch date", "ENC_05-04-01.mp3"),
    ("Looking for a new apartment", "ENC_06-02-01.mp3"),
    ("Helping a classmate", "ENC_07-02-01.mp3"),
    ("Advice to a friend", "ENC_08-02-01.mp3"),
    ("Scheduled events", "ENC_09-02-01.mp3"),
    ("Plans for the very near future", "ENC_09-04-01.mp3"),
    ("Long-term plans", "ENC_09-06-01.mp3"),
    ("Predictions for the more distant future", "ENC_09-08-01.mp3"),
    ("Selecting a company officer", "ENC_10-02-01.mp3"),
    ("A traffic accident", "ENC_11-02-01.mp3"),
    ("In the present tense", "ENC_12-02-01.mp3"),
    ("In the present perfect tense", "ENC_12-04-01.mp3"),
    ("In the past tense", "ENC_12-06-01.mp3"),
    ("In future tenses", "ENC_12-08-01.mp3"),
    ("Living with a vegan daughter", "ENC_13-02-01.mp3"),
]

proxy = urllib.request.ProxyHandler(
    {"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"}
)
urllib.request.install_opener(urllib.request.build_opener(proxy))


def head(url: str):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("Content-Length") or 0)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def md5_bytes(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def resolve_missing():
    """If guessed -08- tracks 404, probe nearby section numbers by size target."""
    targets = {
        "Predictions for the more distant future": 910856,
        "In future tenses": 1086830,
    }
    extras = {}
    for unit, section_guess in ((9, range(7, 12)), (12, range(7, 12))):
        for sec in section_guess:
            name = f"ENC_{unit:02d}-{sec:02d}-01.mp3"
            url = S3 + name
            try:
                length = head(url)
            except Exception:
                continue
            print(f"PROBE {name} {length}")
            for title, want in targets.items():
                if abs(length - want) < 2000:
                    extras[title] = name
    return extras


def main():
    AUDIO_DIR.mkdir(exist_ok=True)
    mapping = list(MAPPING)
    # Fix missing remote names if needed
    by_title = {t: r for t, r in mapping}
    for title, remote in list(by_title.items()):
        url = S3 + remote
        try:
            head(url)
        except Exception:
            print(f"MISSING {remote} for {title}")
            by_title[title] = None

    if any(v is None for v in by_title.values()):
        found = resolve_missing()
        for title, remote in found.items():
            if by_title.get(title) is None:
                by_title[title] = remote
                print(f"RESOLVED {title} -> {remote}")

    results = []
    for title, remote in [(t, by_title[t]) for t, _ in MAPPING]:
        if not remote:
            raise SystemExit(f"Could not resolve remote for {title}")
        url = S3 + remote
        dest = AUDIO_DIR / f"{title}.mp3"
        old = dest.read_bytes() if dest.exists() else b""
        print(f"GET {remote} -> {title}.mp3")
        data = download(url)
        dest.write_bytes(data)
        same = old and md5_bytes(old) == md5_bytes(data)
        print(f"  {len(data)} bytes" + (" unchanged" if same else " UPDATED"))
        results.append(
            {
                "title": title,
                "remote": remote,
                "url": url,
                "size": len(data),
                "md5": md5_bytes(data),
                "unchanged": bool(same),
            }
        )

    out = ROOT / "_enc_mapping.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nchanged {sum(1 for r in results if not r['unchanged'])}/{len(results)}")


if __name__ == "__main__":
    main()
