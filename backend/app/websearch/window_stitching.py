"""
Core Window Stitching Algorithm
Method for adaptive coherent context extraction from web documents for AI agents.
Formalized in 03_Метод_Window_Stitching_и_Формализация.md
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


BLACKLIST_SECTION_PATTERNS = [
    r"\b(?:список\s+(?:рекомендуемой\s+|использованной\s+)?)?литератур\w*\b",
    r"\b(?:список\s+)?библиограф\w*\b",
    r"(?:\bсписок\s+(?:(?:[\w-]+\s+)+)?(?:[\w-]+-)?источник\w*|\bисточник\w*\s+информации\b|(?:^|[>#«\"'(])\s*(?:перво)?источник(?:и|ов)\s*(?:[»\"')!?:;]|$|>))(?!\s+(?:[\w-]+\s+)*(?:питания|тока|напряжения|энергии|света|тепла|помех|мощности|излучения|эдс|электропитания|потерь|тепловыделения))",
    r"\breferences?\b",
    r"\bкомментари\w*\b",
    r"\bcomments?\b",
    r"\bсмотрите\s+также\b",
    r"\bsee\s+also\b",
    r"\bexternal\s+links?\b",
    r"\bfurther\s+reading\b",
    r"\bпримечани\w*\b",
    r"\b(?:внешние\s+)?(?:ссылк\w*|ссылок)\b",
    r"\bнавигаци\w*\b",
    r"\bсодержани\w*\b",
    r"\bоглавлени\w*\b",
    r"\bchangelog\b",
    r"\brelease\s+notes\b",
    r"\bdownloads?\b",
    r"\bmedia\b",
    r"\bpress\b",
    r"\bpre-?order\w*\b",
    r"\bпредзаказ\w*\b",
    r"\babout\s+the\s+author\b",
    r"\bauthor\s+bio\b",
    r"\bбиографи\w*\b",
    r"\blegal\b",
    r"\bdisclaimer\w*\b",
    r"\bправов\w*\s+информац\w*\b",
    r"\bprivacy\b",
    r"\bterms\s+(?:of\s+(?:service|use)|and\s+conditions)\b",
]
BLACKLIST_SECTION_REGEX = re.compile("|".join(BLACKLIST_SECTION_PATTERNS), re.IGNORECASE)


def is_blacklisted_section(header: str) -> bool:
    """
    Returns True if the structural header represents a service, navigation,
    or bibliographic section to be completely excluded.
    """
    if not header:
        return False
    clean = re.sub(r"[\[\]]", "", header).strip()
    return bool(BLACKLIST_SECTION_REGEX.search(clean))


@dataclass
class Fragment:
    index: int
    score: float = 0.0


@dataclass
class StitchedPassage:
    start_index: int
    end_index: int
    text: str
    recovered_sentences: int
    header: str = ""
    url: str = ""
    score: float = 0.0


def join_passage_sentences(sentences: List[str]) -> str:
    """
    Intelligently joins prose sentences and Markdown tables.
    Prose sentences are separated by spaces.
    Markdown tables are separated from surrounding prose by double newlines (\n\n).
    Consecutive table rows or multi-row tables are preserved with line breaks.
    """
    if not sentences:
        return ""
    result = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if not result:
            result.append(s)
        else:
            prev = result[-1]
            s_is_table = s.startswith("|") and ("|" in s[1:])
            prev_is_table = prev.endswith("|") and ("|" in prev[:-1])

            if s_is_table and prev_is_table:
                if "\n" in s or "\n" in prev:
                    result.append("\n\n" + s)
                else:
                    result.append("\n" + s)
            elif s_is_table or prev_is_table:
                result.append("\n\n" + s)
            else:
                result.append(" " + s)
    return "".join(result)


def window_stitching(
    candidates: List[Fragment],
    document_sentences: List[str],
    breadcrumbs: Optional[Dict[int, str]] = None,
    tau_gap: int = 1,
    delta: int = 1,
    url: str = "",
    max_passage_sentences: Optional[int] = None
) -> List[StitchedPassage]:
    """
    Greedy Interval Stitching with structural anchor preservation, intermediate
    text recovery and structural DOM breadcrumbs injection.

    :param candidates: Scored candidate sentences exceeding threshold theta.
    :param document_sentences: Ordered list of all sentences in the cleaned document D = (s_1, ..., s_N).
    :param breadcrumbs: Mapping of sentence_index to hierarchical heading (e.g. 'H1 > H2').
    :param tau_gap: Maximum allowed gap between sentence indices to merge into a single cluster.
    :param delta: Expansion radius for external cluster boundaries to resolve anaphoric references.
    :param url: Source URL of the document for citation and provenance tracking.
    :param max_passage_sentences: Optional per-passage length budget. When a merged
        cluster spans more sentences than this budget, it is split into sub-windows
        centered on the highest-scored candidates instead of emitting the whole slice.
    :return: List of StitchedPassage objects with coherent text and injected headers.
    """
    if not candidates or not document_sentences:
        return []

    breadcrumbs = breadcrumbs or {}
    n_total = len(document_sentences)

    # 1. Sort candidate indices by document position
    sorted_candidates = sorted(candidates, key=lambda x: x.index)
    clusters: List[List[int]] = []
    curr_cluster = [sorted_candidates[0].index]

    # 2. Greedy clustering of connected components
    for cand in sorted_candidates[1:]:
        if cand.index - curr_cluster[-1] <= tau_gap + 1:
            curr_cluster.append(cand.index)
        else:
            clusters.append(curr_cluster)
            curr_cluster = [cand.index]
    clusters.append(curr_cluster)

    # 3. Reconstruction of continuous passages
    stitched_passages: List[StitchedPassage] = []

    for cl in clusters:
        # Enforce non-negative delta
        d = max(0, delta)

        # Expand left boundary outward from cl[0], stopping at blacklisted boundary
        start_idx = cl[0]
        for step in range(1, d + 1):
            prev_idx = cl[0] - step
            if prev_idx < 0:
                break
            if breadcrumbs and is_blacklisted_section(breadcrumbs.get(prev_idx, "")):
                break
            start_idx = prev_idx

        # Expand right boundary outward from cl[-1], stopping at blacklisted boundary
        end_idx = cl[-1]
        for step in range(1, d + 1):
            next_idx = cl[-1] + step
            if next_idx >= n_total:
                break
            if breadcrumbs and is_blacklisted_section(breadcrumbs.get(next_idx, "")):
                break
            end_idx = next_idx

        # Passage length budget: an oversized cluster (broad query -> most chunks
        # approved) is split into sub-windows centered on the highest-scored
        # candidates, so no single passage swallows the whole article.
        windows: List[Tuple[int, int]] = [(start_idx, end_idx)]
        if max_passage_sentences and (end_idx - start_idx + 1) > max_passage_sentences:
            budget = max_passage_sentences
            half = budget // 2
            windows = []
            covered_until = start_idx - 1
            cl_frags = [c for c in sorted_candidates if cl[0] <= c.index <= cl[-1]]
            for cand in sorted(cl_frags, key=lambda c: -c.score):
                if cand.index <= covered_until:
                    continue
                win_start = max(start_idx, cand.index - half)
                win_end = min(end_idx, win_start + budget - 1)
                win_start = max(start_idx, win_end - budget + 1)
                windows.append((win_start, win_end))
                covered_until = win_end
                if covered_until >= end_idx:
                    break
            if windows and windows[-1][1] < end_idx:
                # Tail not anchored by a candidate: extend the last window if the
                # remainder is small, otherwise emit it as its own window.
                tail = end_idx - windows[-1][1]
                if tail <= half:
                    windows[-1] = (windows[-1][0], end_idx)
                else:
                    windows.append((windows[-1][1] + 1, end_idx))

        cluster_set = set(cl)
        frag_scores = {c.index: c.score for c in sorted_candidates}
        for win_start, win_end in windows:
            # Continuous slice: forcibly recovers all intermediate sentences
            continuous_slice = document_sentences[win_start : win_end + 1]
            body_text = join_passage_sentences(continuous_slice)

            # Structural breadcrumbs injection from nearest preceding heading
            header = breadcrumbs.get(win_start, "")
            formatted_text = f"[{header}]\n{body_text}" if header else body_text

            # Number of recovered sentences = total slice length minus initially scored candidates in this window
            recovered_count = (win_end - win_start + 1) - sum(
                1 for i in cluster_set if win_start <= i <= win_end
            )

            stitched_passages.append(
                StitchedPassage(
                    start_index=win_start,
                    end_index=win_end,
                    text=formatted_text,
                    recovered_sentences=max(0, recovered_count),
                    header=header,
                    url=url,
                    score=round(max(
                        (frag_scores[i] for i in cluster_set if win_start <= i <= win_end),
                        default=0.0
                    ), 3)
                )
            )

    return stitched_passages
