"""Align corpus sentences/words to audio via faster-whisper word timestamps.

Strategy:
1) Transcribe with word timestamps
2) Locate each sentence start via distinctive anchors (skip title narration)
3) Align words inside each sentence window (between consecutive anchors)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path(__file__).resolve().parents[1]
AUDIO_DIR = ROOT / "pmp_audios"
CORPUS = ROOT / "data" / "corpus.json"
OUT = ROOT / "data" / "timings.json"

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

ALIASES = {
    "drs": "doctors",
    "dr": "doctor",
    "ok": "okay",
    "okay": "okay",
    "gonna": "goingto",
    "wanna": "wantto",
    "gotta": "gotto",
    "cos": "because",
    "cause": "because",
    "till": "until",
    "til": "until",
    "sydney": "sidney",
    "sidney": "sidney",
}

WEAK_START = {"i", "a", "an", "the", "to", "and", "or", "but", "so", "he", "she", "we", "they", "it"}


def normalize_token(text: str) -> str:
    text = text.lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u2014", " ").replace("\u2013", " ")
    text = re.sub(r"[^a-z0-9']+", "", text)
    return text


def cmp_key(text: str) -> str:
    t = normalize_token(text).replace("'", "")
    return ALIASES.get(t, t)


SPEAKER_LABEL_RE = re.compile(r"^[A-Z][A-Za-z.]+(?:\s*\([^)]*\))?:\s*")


def strip_speaker(text: str) -> str:
    """Remove written-only labels: 'MIKE:' / 'MIKE (retelling the conversation):'."""
    return SPEAKER_LABEL_RE.sub("", text)


def extract_words(text: str) -> list[str]:
    # After strip_speaker so label tokens are never timed. Digits: "9:30" -> ["9","30"].
    return re.findall(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?|\d+", strip_speaker(text))


def tokens_equal(a: str, b: str) -> bool:
    a2, b2 = cmp_key(a), cmp_key(b)
    if not a2 or not b2:
        return False
    if a2 == b2:
        return True
    if a2.endswith("s") and a2[:-1] == b2:
        return True
    if b2.endswith("s") and b2[:-1] == a2:
        return True
    if len(a2) >= 6 and len(b2) >= 6 and (a2.startswith(b2[:5]) or b2.startswith(a2[:5])):
        return True
    # Cheap ASR slips: "at a loose end" ↔ "out of loose end"
    if frozenset((a2, b2)) in {frozenset(("at", "out")), frozenset(("a", "of"))}:
        return True
    return False


def whisper_words(model: WhisperModel, audio_path: Path) -> list[tuple[str, float, float]]:
    segments, _ = model.transcribe(
        str(audio_path),
        language="en",
        word_timestamps=True,
        # VAD sometimes drops "asked Adam…" in retell passages — keep full stream
        vad_filter=False,
        beam_size=5,
        condition_on_previous_text=False,
        temperature=0.0,
    )
    words: list[tuple[str, float, float]] = []
    for seg in segments:
        if not seg.words:
            continue
        for w in seg.words:
            tok = normalize_token(w.word or "")
            if tok:
                words.append((tok, float(w.start), float(w.end)))
    return words


def skip_title(asr: list[tuple[str, float, float]]) -> int:
    i = 0
    while i < min(len(asr), 16):
        k = cmp_key(asr[i][0])
        if k in {"conversation", "unit"} or re.fullmatch(r"\d+[a-d]?", k):
            i += 1
            continue
        # title words until first speaker-like content pause; keep skipping short intro nouns
        if i < 8 and k in {
            "making",
            "looking",
            "helping",
            "getting",
            "talking",
            "running",
            "changing",
            "advice",
            "scheduled",
            "plans",
            "long",
            "term",
            "predictions",
            "selecting",
            "traffic",
            "accident",
            "present",
            "perfect",
            "past",
            "future",
            "tenses",
            "tense",
            "living",
            "vegan",
            "daughter",
            "appointment",
            "doctor",
            "classmate",
            "friend",
            "apartment",
            "party",
            "acquainted",
            "roommates",
            "events",
            "officer",
            "company",
            "near",
            "distant",
            "more",
            "very",
            "for",
            "the",
            "a",
            "an",
            "in",
            "with",
            "about",
            "and",
            "to",
            "of",
            "new",
        }:
            i += 1
            continue
        break
    return i


def score_at(asr, pos: int, tokens: list[str], max_take: int = 8) -> float:
    take = tokens[:max_take]
    if not take:
        return 0.0
    matched = 0
    j = pos
    for tok in take:
        found = False
        for look in range(j, min(len(asr), j + 6)):
            if tokens_equal(asr[look][0], tok):
                matched += 1
                j = look + 1
                found = True
                break
        if not found:
            break
    return matched / len(take)


def find_sentence_start(asr, tokens: list[str], cursor: int, hard_limit: int | None = None) -> int:
    if not tokens:
        return cursor
    limit = hard_limit if hard_limit is not None else min(len(asr), cursor + 120)
    limit = min(len(asr), max(limit, cursor + 1))
    min_score = 0.55
    if cmp_key(tokens[0]) in WEAK_START:
        # "I asked…" must match more than a lone "I"
        min_score = 0.65

    best_pos, best_score = cursor, -1.0
    for pos in range(cursor, limit):
        if not tokens_equal(asr[pos][0], tokens[0]):
            continue
        sc = score_at(asr, pos, tokens, max_take=min(10, len(tokens)))
        if sc > best_score:
            best_score, best_pos = sc, pos
            if sc >= 0.8:
                return pos

    if best_score >= min_score:
        return best_pos

    # Fallback: lock onto first distinctive token, then snap back to phrase start
    for ai, tok in enumerate(tokens[:10]):
        key = cmp_key(tok)
        if len(key) < 4 or key in WEAK_START:
            continue
        for pos in range(cursor, limit):
            if not tokens_equal(asr[pos][0], tok):
                continue
            start = max(cursor, pos - ai)
            sc = score_at(asr, start, tokens, max_take=min(10, len(tokens)))
            if sc >= 0.5:
                return start
        break

    return min(cursor, len(asr) - 1)


def align_span(
    expected: list[str], asr, start_j: int, end_j: int
) -> tuple[list[float | None], int]:
    """Semi-global DP (Needleman–Wunsch style).

    Match via tokens_equal; allow skips on both sides. Leading/trailing ASR gaps
    are free so a wide window that spills into the next sentence does not pull
    matches rightward (e.g. repeated \"works\").
    """
    starts: list[float | None] = [None] * len(expected)
    j0 = max(0, min(start_j, len(asr)))
    end_j = min(len(asr), max(end_j, j0))
    if not expected or j0 >= end_j:
        return starts, max(j0 + 1, start_j + 1)

    exp = [normalize_token(w) for w in expected]
    n, m = len(exp), end_j - j0
    MATCH, GAP, MISMATCH = 2, -1, -3

    # dp[i][j]: best score aligning first i expected words with first j ASR tokens
    neg = -10**9
    dp = [[neg] * (m + 1) for _ in range(n + 1)]
    bt = [[0] * (m + 1) for _ in range(n + 1)]  # 1=diag, 2=skip_exp, 3=skip_asr
    dp[0][0] = 0
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + GAP
        bt[i][0] = 2
    for j in range(1, m + 1):
        # Free leading ASR skips (start_j may be slightly early)
        dp[0][j] = 0
        bt[0][j] = 3

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if tokens_equal(exp[i - 1], asr[j0 + j - 1][0]):
                cand = (dp[i - 1][j - 1] + MATCH, 1)
            else:
                cand = (dp[i - 1][j - 1] + MISMATCH, 1)
            skip_e = (dp[i - 1][j] + GAP, 2)
            skip_a = (dp[i][j - 1] + GAP, 3)
            # Tie-break: prefer earlier ASR (diag over skip_asr over skip_exp)
            best = max((cand, skip_a, skip_e), key=lambda x: (x[0], -x[1]))
            dp[i][j], bt[i][j] = best

    # Free trailing ASR: end at best column for full expected sequence
    j = max(range(m + 1), key=lambda jj: (dp[n][jj], -jj))
    i = n
    last_j = j0
    while i > 0 or j > 0:
        if i == 0:
            break  # leading ASR skips — stop
        move = bt[i][j]
        if move == 1:
            if tokens_equal(exp[i - 1], asr[j0 + j - 1][0]):
                starts[i - 1] = asr[j0 + j - 1][1]
                last_j = max(last_j, j0 + j)
            i -= 1
            j -= 1
        elif move == 2:
            i -= 1
        else:
            if j == 0:
                break
            j -= 1

    return starts, max(last_j, start_j + 1)


def fill_gaps(starts: list[float | None], left: float, right: float) -> list[float]:
    n = len(starts)
    out: list[float | None] = [None if s is None else float(s) for s in starts]
    i = 0
    while i < n:
        if out[i] is not None:
            i += 1
            continue
        j = i
        while j < n and out[j] is None:
            j += 1
        lo = out[i - 1] if i > 0 and out[i - 1] is not None else left
        hi = out[j] if j < n and out[j] is not None else right
        if hi <= lo:
            hi = lo + 0.08 * (j - i + 1)
        span = hi - lo
        count = j - i
        for k in range(count):
            out[i + k] = lo + span * (k + 1) / (count + 1)
        i = j
    for i in range(1, n):
        if out[i] is None:
            out[i] = (out[i - 1] or left) + 0.04
        elif out[i - 1] is not None and out[i] <= out[i - 1]:
            out[i] = out[i - 1] + 0.03
    return [float(x if x is not None else left) for x in out]


def corpus_dialogues(corpus: list) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ch in corpus:
        for cv in ch["conversation"]:
            lines = [x["text"] for x in cv["content"] if not x.get("sign")]
            out[cv["title"]] = lines
    return out


def align_dialogue(model: WhisperModel, title: str, lines: list[str]) -> dict:
    path = AUDIO_DIR / f"{title}.mp3"
    # extract_words -> strip_speaker: labels like "MIKE (retelling…):" are never timed
    line_words = [extract_words(line) for line in lines]

    if not path.exists():
        print(f"MISSING {path.name}")
        return {
            "sentences": [0.0] * len(lines),
            "words": [[0.0] * len(ws) for ws in line_words],
        }

    asr = whisper_words(model, path)
    if not asr:
        print("  WARN no ASR words")
        return {
            "sentences": [0.0] * len(lines),
            "words": [[0.0] * len(ws) for ws in line_words],
        }

    # Pass 1: locate each spoken line start (after title narration)
    cursor = skip_title(asr)
    sent_idx: list[int] = []
    for li, words in enumerate(line_words):
        tokens = [normalize_token(w) for w in words]
        remain_words = sum(len(x) for x in line_words[li:])
        hard = min(len(asr), cursor + max(40, remain_words + 20))
        if li == len(line_words) - 1:
            hard = len(asr)
        start_j = find_sentence_start(asr, tokens, cursor, hard)
        if sent_idx and start_j <= sent_idx[-1]:
            start_j = min(len(asr) - 1, sent_idx[-1] + 1)
        sent_idx.append(start_j)
        # Advance past most of this line so the next search doesn't re-lock onto it
        cursor = min(len(asr), start_j + max(1, len(words) * 2 // 3))

    # Pass 2: DP-align each line inside [this_start, next_start)
    words_nested: list[list[float]] = []
    sent_starts: list[float] = []
    matched_total = 0
    expected_total = 0

    for li, words in enumerate(line_words):
        expected_total += len(words)
        start_j = sent_idx[li]
        end_j = sent_idx[li + 1] if li + 1 < len(sent_idx) else len(asr)
        # Give short lines a little slack if the next anchor is tight
        if li + 1 < len(sent_idx):
            end_j = max(end_j, min(len(asr), start_j + len(words) + 8))
            end_j = min(end_j, sent_idx[li + 1] + 2)
        raw, _ = align_span(words, asr, start_j, end_j)
        matched_total += sum(1 for x in raw if x is not None)
        left = asr[start_j][1]
        right = asr[min(end_j, len(asr)) - 1][1]
        filled = fill_gaps(raw, left, right) if words else []
        words_nested.append([round(t, 2) for t in filled])
        sent_starts.append(round(filled[0] if filled else left, 2))

    for i in range(1, len(sent_starts)):
        if sent_starts[i] < sent_starts[i - 1]:
            sent_starts[i] = sent_starts[i - 1]

    # Keep each line's word stamps inside [lineStart, nextLineStart)
    for i in range(len(words_nested) - 1):
        ws = words_nested[i]
        if not ws:
            continue
        limit = sent_starts[i + 1] - 0.03
        if ws[-1] <= limit:
            continue
        lo = ws[0]
        hi = ws[-1]
        if hi <= lo:
            words_nested[i] = [round(min(t, limit), 2) for t in ws]
            continue
        scale = max(0.05, limit - lo) / (hi - lo)
        words_nested[i] = [round(lo + (t - lo) * scale, 2) for t in ws]

    print(
        f"  words {expected_total} matched {matched_total}/{expected_total} "
        f"asr={len(asr)} title_skip={skip_title(asr)} first={sent_idx[0] if sent_idx else '-'}"
    )
    return {"sentences": sent_starts, "words": words_nested}


def main(only: set[str] | None = None) -> None:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dialogues = corpus_dialogues(corpus)
    if only:
        dialogues = {k: v for k, v in dialogues.items() if k in only}
        if not dialogues:
            raise SystemExit(f"No matching dialogues for {only}")

    print("Loading model base.en …")
    model = WhisperModel("base.en", device="cpu", compute_type="int8")

    existing = {}
    if only and OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8"))

    out = existing
    for title, lines in dialogues.items():
        print(f"Aligning: {title}")
        out[title] = align_dialogue(model, title, lines)

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    import sys

    only = set(sys.argv[1:]) or None
    main(only)
