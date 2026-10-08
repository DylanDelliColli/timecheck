"""Normalization contract version 1, shared by quotes and snapshots."""
import unicodedata

NORM_VERSION = 1
_FOLD = str.maketrans({**dict.fromkeys('‘’', "'"), **dict.fromkeys('“”', '"'),
                      **dict.fromkeys('‐‑‒–—―−', '-'), '\u00ad': None})


def normalize(text: str) -> str:
    normalized = ' '.join(unicodedata.normalize('NFKC', text).split())
    return normalized.translate(_FOLD).strip()
