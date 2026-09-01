from __future__ import annotations

import copy
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ..schemas.document_kb import ScopeType
from ..schemas.index import IndexPayload
from .local_index import LocalVectorIndex

LEXICAL_TOKENIZER_VERSION = "nfkc-casefold-ja23-v1"
LEXICAL_SCORING_VERSION = "bm25-v1"
BM25_K1 = 1.2
BM25_B = 0.75
JAPANESE_NGRAM_LENGTHS = (2, 3)

_GROUPED_NUMBER_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_TOKEN_RUN_RE = re.compile(r"[a-z0-9]+|[\u3040-\u30ff\u3400-\u9fff]+")
_CONNECTED_IDENTIFIER_RE = re.compile(r"[a-z0-9]+(?:[-&+._/@]+[a-z0-9]+)+")
_IDENTIFIER_CONNECTOR_RE = re.compile(r"[-&+._/@]+")


class LexicalSearchError(Exception):
    """Base class for deterministic lexical-retrieval failures."""


class LexicalInputError(LexicalSearchError):
    """Raised when a lexical query or top-k value is invalid."""


class LexicalCorpusError(LexicalSearchError):
    """Raised when supplied payload rows do not form a valid ordered corpus."""


class LexicalScoreError(LexicalSearchError):
    """Raised when internal BM25 statistics cannot produce safe finite scores."""


@dataclass(frozen=True, slots=True)
class LexicalSearchHit:
    rank: int
    row_index: int
    score: float
    matched_terms: tuple[str, ...]
    document_id: str
    unit_id: str
    fact_id: str
    text: str
    source_pages: tuple[int, ...]
    section_path: tuple[str, ...]
    fact_type: str
    scope_type: ScopeType
    scope_targets: tuple[str, ...]
    parent_college: str | None
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "row_index": self.row_index,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
            "document_id": self.document_id,
            "unit_id": self.unit_id,
            "fact_id": self.fact_id,
            "text": self.text,
            "source_pages": list(self.source_pages),
            "section_path": list(self.section_path),
            "fact_type": self.fact_type,
            "scope_type": self.scope_type,
            "scope_targets": list(self.scope_targets),
            "parent_college": self.parent_college,
            "metadata": _thaw_json(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class LexicalSearchResult:
    tokenizer_version: str
    scoring_version: str
    query_tokens: tuple[str, ...]
    hits: tuple[LexicalSearchHit, ...]


@dataclass(frozen=True, slots=True)
class LexicalSearcher:
    payloads: tuple[IndexPayload, ...]
    term_frequencies: tuple[Mapping[str, int], ...]
    document_lengths: tuple[int, ...]
    document_frequency: Mapping[str, int]
    average_document_length: float

    @property
    def corpus_size(self) -> int:
        return len(self.payloads)

    def search(self, query: str, *, top_k: int = 5) -> LexicalSearchResult:
        return search_lexical(self, query, top_k=top_k)


def tokenize_lexical(value: str) -> tuple[str, ...]:
    """Return deterministic lexical tokens with multiplicity preserved."""

    if not isinstance(value, str):
        raise TypeError("lexical tokenizer input must be a Python string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _GROUPED_NUMBER_COMMA_RE.sub("", normalized)

    tokens: list[str] = []
    for match in _TOKEN_RUN_RE.finditer(normalized):
        run = match.group(0)
        if run.isascii():
            tokens.append(run)
            continue
        for start in range(len(run)):
            for length in JAPANESE_NGRAM_LENGTHS:
                if start + length <= len(run):
                    tokens.append(run[start : start + length])

    for match in _CONNECTED_IDENTIFIER_RE.finditer(normalized):
        collapsed = _IDENTIFIER_CONNECTOR_RE.sub("", match.group(0))
        if collapsed:
            tokens.append(collapsed)
    return tuple(tokens)


def build_lexical_projection(payload: IndexPayload) -> str:
    """Project canonical payload text and explicit structured fields for lexical lookup."""

    if not isinstance(payload, IndexPayload):
        raise TypeError("lexical projection requires an IndexPayload")
    fields = [
        payload.text,
        payload.document_id,
        payload.unit_id,
        payload.fact_id,
        *payload.section_path,
        payload.fact_type,
        payload.scope_type,
        *payload.scope_targets,
    ]
    if payload.parent_college is not None:
        fields.append(payload.parent_college)
    return "\n".join(fields)


def build_lexical_searcher(
    source: LocalVectorIndex | Sequence[IndexPayload],
) -> LexicalSearcher:
    """Build immutable BM25 corpus statistics from validated ordered payload rows."""

    payload_values: Sequence[IndexPayload]
    if isinstance(source, LocalVectorIndex):
        payload_values = source.payloads
    elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
        payload_values = source
    else:
        raise LexicalCorpusError("source must be a LocalVectorIndex or payload sequence")

    payloads = tuple(_copy_payload(payload) for payload in payload_values)
    _validate_payload_rows(payloads)

    term_frequencies: list[Mapping[str, int]] = []
    document_lengths: list[int] = []
    document_frequency: Counter[str] = Counter()
    for payload in payloads:
        tokens = tokenize_lexical(build_lexical_projection(payload))
        frequencies = Counter(tokens)
        term_frequencies.append(MappingProxyType(dict(frequencies)))
        document_lengths.append(len(tokens))
        document_frequency.update(frequencies.keys())

    average_length = (
        math.fsum(document_lengths) / len(document_lengths) if document_lengths else 0.0
    )
    return LexicalSearcher(
        payloads=payloads,
        term_frequencies=tuple(term_frequencies),
        document_lengths=tuple(document_lengths),
        document_frequency=MappingProxyType(dict(document_frequency)),
        average_document_length=average_length,
    )


def search_lexical(
    searcher: LexicalSearcher,
    query: str,
    *,
    top_k: int = 5,
) -> LexicalSearchResult:
    """Run exhaustive deterministic BM25 scoring over a prepared lexical corpus."""

    if not isinstance(searcher, LexicalSearcher):
        raise TypeError("searcher must be a LexicalSearcher")
    _validate_search_inputs(query, top_k)
    query_tokens = tokenize_lexical(query)
    if not query_tokens:
        raise LexicalInputError("query does not contain any lexical tokens")
    _validate_statistics(searcher)

    if searcher.corpus_size == 0:
        return LexicalSearchResult(
            tokenizer_version=LEXICAL_TOKENIZER_VERSION,
            scoring_version=LEXICAL_SCORING_VERSION,
            query_tokens=query_tokens,
            hits=(),
        )

    query_frequencies = Counter(query_tokens)
    scored_rows: list[tuple[float, int, tuple[str, ...]]] = []
    for position, frequencies in enumerate(searcher.term_frequencies):
        contributions: list[float] = []
        for term, query_frequency in query_frequencies.items():
            term_frequency = frequencies.get(term, 0)
            if term_frequency == 0:
                continue
            contributions.append(
                query_frequency
                * _bm25_term_score(
                    term_frequency=term_frequency,
                    document_frequency=searcher.document_frequency[term],
                    document_length=searcher.document_lengths[position],
                    average_document_length=searcher.average_document_length,
                    corpus_size=searcher.corpus_size,
                )
            )
        score = math.fsum(contributions)
        if not math.isfinite(score):
            raise LexicalScoreError("BM25 score became non-finite")
        if score > 0.0:
            matched_terms = tuple(
                term for term in _ordered_unique(query_tokens) if frequencies.get(term, 0) > 0
            )
            scored_rows.append((score, searcher.payloads[position].row_index, matched_terms))

    scored_rows.sort(key=lambda item: (-item[0], item[1]))
    selected = scored_rows[: min(top_k, len(scored_rows))]
    hits = tuple(
        _hit_from_payload(
            rank,
            searcher.payloads[row_index],
            score,
            matched_terms,
        )
        for rank, (score, row_index, matched_terms) in enumerate(selected, start=1)
    )
    return LexicalSearchResult(
        tokenizer_version=LEXICAL_TOKENIZER_VERSION,
        scoring_version=LEXICAL_SCORING_VERSION,
        query_tokens=query_tokens,
        hits=hits,
    )


def _validate_payload_rows(payloads: tuple[IndexPayload, ...]) -> None:
    seen_unit_ids: set[str] = set()
    seen_fact_ids: set[str] = set()
    document_id: str | None = None
    for position, payload in enumerate(payloads):
        if not isinstance(payload, IndexPayload):
            raise LexicalCorpusError("payload corpus contains a non-IndexPayload row")
        if payload.row_index != position:
            raise LexicalCorpusError("payload row_index values must be contiguous and ordered")
        if payload.unit_id in seen_unit_ids or payload.fact_id in seen_fact_ids:
            raise LexicalCorpusError("payload corpus contains duplicate Unit or Fact identity")
        if document_id is None:
            document_id = payload.document_id
        elif payload.document_id != document_id:
            raise LexicalCorpusError("payload corpus mixes document identities")
        seen_unit_ids.add(payload.unit_id)
        seen_fact_ids.add(payload.fact_id)


def _validate_search_inputs(query: object, top_k: object) -> None:
    if not isinstance(query, str) or not query.strip():
        raise LexicalInputError("query must be a non-blank Python string")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise LexicalInputError("top_k must be a positive non-bool integer")


def _validate_statistics(searcher: LexicalSearcher) -> None:
    corpus_size = searcher.corpus_size
    if (
        len(searcher.term_frequencies) != corpus_size
        or len(searcher.document_lengths) != corpus_size
    ):
        raise LexicalScoreError("lexical corpus statistics do not align with payload rows")
    if not math.isfinite(searcher.average_document_length) or searcher.average_document_length < 0:
        raise LexicalScoreError("average document length is invalid")
    if any(length < 0 for length in searcher.document_lengths):
        raise LexicalScoreError("document length is invalid")
    observed_document_frequency: Counter[str] = Counter()
    for frequencies, length in zip(
        searcher.term_frequencies, searcher.document_lengths, strict=True
    ):
        if any(
            not term or isinstance(count, bool) or not isinstance(count, int) or count <= 0
            for term, count in frequencies.items()
        ):
            raise LexicalScoreError("term frequency is invalid")
        if sum(frequencies.values()) != length:
            raise LexicalScoreError("term frequencies do not match document length")
        observed_document_frequency.update(frequencies.keys())
    if any(
        isinstance(frequency, bool)
        or not isinstance(frequency, int)
        or frequency <= 0
        or frequency > corpus_size
        for frequency in searcher.document_frequency.values()
    ):
        raise LexicalScoreError("document frequency is invalid")
    if dict(observed_document_frequency) != dict(searcher.document_frequency):
        raise LexicalScoreError("document frequencies do not match term statistics")
    expected_average = math.fsum(searcher.document_lengths) / corpus_size if corpus_size else 0.0
    if searcher.average_document_length != expected_average:
        raise LexicalScoreError("average document length does not match corpus statistics")


def _bm25_term_score(
    *,
    term_frequency: int,
    document_frequency: int,
    document_length: int,
    average_document_length: float,
    corpus_size: int,
) -> float:
    if average_document_length <= 0.0:
        raise LexicalScoreError("positive lexical matches require positive average length")
    idf = math.log1p((corpus_size - document_frequency + 0.5) / (document_frequency + 0.5))
    length_normalization = 1.0 - BM25_B + BM25_B * (document_length / average_document_length)
    denominator = term_frequency + BM25_K1 * length_normalization
    score = idf * (term_frequency * (BM25_K1 + 1.0)) / denominator
    if not math.isfinite(score) or score <= 0.0:
        raise LexicalScoreError("BM25 term score is invalid")
    return score


def _copy_payload(payload: object) -> IndexPayload:
    if not isinstance(payload, IndexPayload):
        raise LexicalCorpusError("payload corpus contains a non-IndexPayload row")
    return payload.model_copy(deep=True)


def _hit_from_payload(
    rank: int,
    payload: IndexPayload,
    score: float,
    matched_terms: tuple[str, ...],
) -> LexicalSearchHit:
    return LexicalSearchHit(
        rank=rank,
        row_index=payload.row_index,
        score=score,
        matched_terms=matched_terms,
        document_id=payload.document_id,
        unit_id=payload.unit_id,
        fact_id=payload.fact_id,
        text=payload.text,
        source_pages=tuple(payload.source_pages),
        section_path=tuple(payload.section_path),
        fact_type=payload.fact_type,
        scope_type=payload.scope_type,
        scope_targets=tuple(payload.scope_targets),
        parent_college=payload.parent_college,
        metadata=_freeze_json(copy.deepcopy(payload.metadata)),
    )


def _ordered_unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value
