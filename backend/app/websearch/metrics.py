"""
Context Coherence Metric & Defect Classifier
Rigorous implementation of Coherence Score (C_ctx) from 05_Методика_эксперимента_и_Метрики.md
"""

import re
from typing import List, Dict, Tuple, Optional, Any


D1_PRONOUNS_RU = {"он", "она", "оно", "они", "этот", "эта", "это", "эти", "данный", "данная", "данное", "данные", "его", "ее", "их", "ему", "ей", "им"}
D1_PRONOUNS_EN = {"he", "she", "it", "they", "this", "these", "his", "her", "their", "its"}
ALL_PRONOUNS = D1_PRONOUNS_RU | D1_PRONOUNS_EN

D2_CONJUNCTIONS_RU = {"однако", "тем не менее", "впрочем", "следовательно", "поэтому", "но", "при этом", "таким образом", "вследствие этого"}
D2_CONJUNCTIONS_EN = {"however", "nevertheless", "therefore", "hence", "consequently", "thus", "yet", "furthermore"}
ALL_CONJUNCTIONS = D2_CONJUNCTIONS_RU | D2_CONJUNCTIONS_EN

GENERIC_HEADERS = {
    "", "введение", "обзор", "документация", "источники", "разное", "главная",
    "python tutorial", "the python tutorial", "documentation", "tutorial",
    "sources", "overview", "introduction", "general", "guide", "beginner's guide"
}


def classify_passage_defect(
    passage_text: str,
    header: str = "",
    has_header: Optional[bool] = None
) -> Tuple[Optional[str], str]:
    """
    Classifies context connectivity defects in the opening sentences of a passage
    according to Chapter 5 specification:
    - D1: Anaphora Break
    - D2: Severed Predication
    - D3: Attribute Isolation / TOC fragment / Citation artifact

    :param passage_text: Full reconstructed passage text (may include '[Header]\n').
    :param header: Structural breadcrumb header [H1 > H2].
    :param has_header: Optional flag indicating header presence (backward compatibility).
    :return: (defect_type, reason), where defect_type in {"D1", "D2", "D3", None}.
    """
    lines = [line.strip() for line in passage_text.split("\n") if line.strip()]
    if not lines:
        return "D3", "Empty passage"

    # Extract header and body
    extracted_header = header
    body_lines = lines
    if lines[0].startswith("[") and lines[0].endswith("]"):
        extracted_header = lines[0][1:-1].strip()
        body_lines = lines[1:]
    elif has_header is False:
        extracted_header = ""

    if not body_lines:
        return "D3", "Passage contains only header without body text"

    body_text = " ".join(body_lines)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body_text) if s.strip()]
    if not sentences:
        return "D3", "No sentences found in passage"

    opening_sentence = sentences[0]
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]{2,}", opening_sentence)
    if not words:
        return "D3", "Opening sentence has no alphabetic words"

    first_word = words[0].lower()
    first_two_words = " ".join(words[:2]).lower() if len(words) >= 2 else first_word
    first_three_words = " ".join(words[:3]).lower() if len(words) >= 3 else first_two_words

    # -----------------------------------------------------------------------
    # 1. Defect D2: Severed Predication (contrastive or consequential conjunctions)
    # -----------------------------------------------------------------------
    if (
        first_word in ALL_CONJUNCTIONS
        or first_two_words in ALL_CONJUNCTIONS
        or first_three_words in ALL_CONJUNCTIONS
    ):
        return "D2", f"Severed contrastive or consequential conjunction: '{first_word}'"

    # -----------------------------------------------------------------------
    # 2. Defect D1: Anaphora Break (3rd-person pronoun without resolved antecedent)
    # -----------------------------------------------------------------------
    if first_word in ALL_PRONOUNS:
        # Check if dummy impersonal: 'it is...', 'это было...'
        is_impersonal = first_word in ("it", "это") and len(words) >= 2 and words[1].lower() in ("is", "was", "было", "значит", "означает")
        if not is_impersonal:
            clean_hdr = re.sub(r"[\u00b6#\xa7]+$", "", extracted_header).strip().lower()
            # If no header, or header is generic (does not specify the concrete entity), it's D1
            if not clean_hdr or clean_hdr in GENERIC_HEADERS:
                return "D1", f"Anaphoric opening pronoun '{first_word}' with unresolved antecedent"

    # -----------------------------------------------------------------------
    # 3. Defect D3: Attribute Isolation / Garbage / TOC Fragments / Citations
    # -----------------------------------------------------------------------
    # Starts with bullet, isolated dash, or list marker
    if opening_sentence.startswith(("-", "*", "•", "—")):
        return "D3", f"Isolated bullet/attribute without entity subject: '{opening_sentence[:40]}...'"

    # Raw numbers or specification without subject
    if re.match(r"^(\d+[\.\)]|\d+\s*(?:км|л|кг|мм|см|гб|мб|нм|%|v|w|kw|rpm))\b", opening_sentence, re.IGNORECASE):
        return "D3", f"Isolated numerical specification without entity: '{opening_sentence[:40]}...'"

    # Table of Contents numbering fragments (e.g. '6.1.3. Compiled Python files', '1.1.2')
    if re.search(r"\d+\.\d+\.\d+|[a-zA-Z]\d+\.\d+", opening_sentence):
        return "D3", f"Fragmented table of contents or section index: '{opening_sentence[:40]}...'"

    # Bibliographic citation artifacts (e.g. '↑Kuchling', 'ISBN', 'DOI', 'Retrieved on')
    if opening_sentence.startswith("↑") or re.search(r"\b(?:ISBN|DOI|Retrieved|Archived from)\b", opening_sentence):
        return "D3", f"Bibliographic citation or reference list artifact: '{opening_sentence[:40]}...'"

    # Incomplete fragments (fewer than 4 real words)
    if len(words) < 4:
        return "D3", f"Fragmentary sentence with fewer than 4 words: '{opening_sentence}'"

    return None, "PASS"


def evaluate_coherence(passages: List[str], headers: Optional[List[str]] = None) -> Dict[str, any]:
    """
    Calculates the Coherence Score (C_ctx) over a set of retrieved passages:
        C_ctx = 1 - (N_unresolved / N_total)

    :param passages: List of passage texts passed to LLM.
    :param headers: Optional list of corresponding headers for each passage.
    :return: Summary metrics dict with defect counts and full inspection details.
    """
    total = len(passages)
    if total == 0:
        return {
            "C_ctx": 1.0,
            "total_passages": 0,
            "unresolved_count": 0,
            "pass_count": 0,
            "defects": {"D1": 0, "D2": 0, "D3": 0},
            "details": []
        }

    unresolved = 0
    defect_counts = {"D1": 0, "D2": 0, "D3": 0}
    details = []

    for idx, text in enumerate(passages):
        hdr = headers[idx] if (headers and idx < len(headers)) else ""
        defect, reason = classify_passage_defect(text, header=hdr)
        if defect is not None:
            unresolved += 1
            defect_counts[defect] = defect_counts.get(defect, 0) + 1
            details.append({"index": idx, "verdict": "FAIL", "defect": defect, "reason": reason})
        else:
            details.append({"index": idx, "verdict": "PASS", "defect": None, "reason": reason})

    c_ctx = round(1.0 - (unresolved / total), 4)
    return {
        "C_ctx": c_ctx,
        "total_passages": total,
        "unresolved_count": unresolved,
        "pass_count": total - unresolved,
        "defects": defect_counts,
        "details": details
    }
