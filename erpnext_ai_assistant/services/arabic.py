"""Arabic text normalization for keyword RAG and detectors."""

from __future__ import annotations

import re
import unicodedata

_ALEF_RE = re.compile(r"[إأآٱ]")
_YEH_RE = re.compile(r"[ىي]")
_TEH_RE = re.compile(r"ة")
_TATWEEL_RE = re.compile(r"\u0640")
_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")


def normalize_arabic(text: str | None) -> str:
	if not text:
		return ""
	s = unicodedata.normalize("NFKC", str(text))
	s = _DIACRITICS_RE.sub("", s)
	s = _TATWEEL_RE.sub("", s)
	s = _ALEF_RE.sub("ا", s)
	s = _YEH_RE.sub("ي", s)
	s = _TEH_RE.sub("ه", s)
	s = re.sub(r"\s+", " ", s).strip().lower()
	return s


def strip_al(text: str | None) -> str:
	"""Drop a leading definite article from already-normalized Arabic."""
	s = normalize_arabic(text)
	if s.startswith("ال") and len(s) > 2:
		return s[2:].strip()
	return s


def arabic_tokens(text: str | None) -> list[str]:
	norm = normalize_arabic(text)
	if not norm:
		return []
	return [tok for tok in norm.split() if tok]
