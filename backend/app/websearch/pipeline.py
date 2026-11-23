"""
End-to-End Context Extraction Pipeline
Implementation based on 04_Экспериментальный_стенд_и_Реализация.md
"""

import re
import time
import asyncio
from collections import Counter
from typing import List, Dict, Optional, Tuple, Callable

import httpx
import numpy as np
from selectolax.parser import HTMLParser
from markdownify import markdownify as md
from datasketch import MinHash, MinHashLSH
from sklearn.feature_extraction.text import TfidfVectorizer

from .config import CONFIG

from .window_stitching import (
    Fragment,
    StitchedPassage,
    window_stitching,
    is_blacklisted_section,
    BLACKLIST_SECTION_PATTERNS,
    BLACKLIST_SECTION_REGEX
)
from .metrics import evaluate_coherence


SKIP_SECTIONS = {
    "references", "reference", "further reading", "external links", "see also",
    "notes", "bibliography", "примечания", "литература", "ссылки", "источники",
    "navigation", "навигация", "contents", "содержание", "оглавление",
    "release notes", "changelog", "want to contribute?", "sister projects",
    "download", "downloads"
}


# ---------------------------------------------------------------------------
# 1. 4get Metasearch Client
# ---------------------------------------------------------------------------

def search_4get(
    query: str,
    endpoint: str = "http://localhost/web",
    timeout: float = 6.0,
    scraper: str = "google_cse"
) -> List[Dict[str, str]]:
    """
    Queries local 4get metasearch engine and extracts search result snippets.
    Uses scraper='google_cse' by default to avoid DuckDuckGo JS challenge anomalies.
    Bypasses local loopback proxy conflicts via trust_env=False.
    Returns: List of {'title': str, 'snippet': str, 'url': str}
    """
    try:
        params = {"s": query}
        if scraper:
            params["scraper"] = scraper
        with httpx.Client(trust_env=False) as client:
            response = client.get(endpoint, params=params, timeout=timeout)
            response.raise_for_status()
        html = response.text
    except Exception:
        return []

    tree = HTMLParser(html)
    results: List[Dict[str, str]] = []

    for el in tree.css(".text-result"):
        link_el = el.css_first("a.hover")
        if not link_el:
            continue
        url = link_el.attributes.get("href", "")
        title_el = link_el.css_first(".title")
        title = title_el.text(deep=True, separator=" ").strip() if title_el else ""
        desc_el = link_el.css_first(".description")
        snippet = desc_el.text(deep=True, separator=" ").strip() if desc_el else ""

        if url and (title or snippet):
            results.append({"title": title, "snippet": snippet, "url": url})

    return results


# ---------------------------------------------------------------------------
# 2. L1 Deduplication (MinHash LSH, h=64, threshold=0.6)
# ---------------------------------------------------------------------------

def deduplicate_snippets(snippets: List[Dict[str, str]], threshold: float = 0.6, num_perm: int = 64) -> List[Dict[str, str]]:
    """
    Filters out domain mirrors and syndicated copies via MinHash LSH.
    """
    if not snippets:
        return []

    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    unique: List[Dict[str, str]] = []

    for idx, s in enumerate(snippets):
        text = f"{s.get('title', '')} {s.get('snippet', '')}".lower()
        tokens = set(re.findall(r"\w+", text))
        if not tokens:
            continue

        m = MinHash(num_perm=num_perm)
        for t in tokens:
            m.update(t.encode("utf8"))

        if not lsh.query(m):
            lsh.insert(f"s_{idx}", m)
            unique.append(s)

    return unique


# ---------------------------------------------------------------------------
# 3. L2 Diversification (MMR)
# ---------------------------------------------------------------------------

def diversify_mmr(
    snippets: List[Dict[str, str]],
    query: str,
    top_k: int = 4,
    lambda_param: float = 0.7,
    rel_scores: Optional[List[float]] = None
) -> List[Dict[str, str]]:
    """
    Maximal Marginal Relevance (MMR) diversification to select diverse source URLs.
    MMR(d) = lambda * rel(d) - (1 - lambda) * max_{d' in S} cos(E(d), E(d'))
    rel(d) is cosine TF-IDF similarity to the query by default; if `rel_scores`
    is provided (e.g. NanoJev scrape probabilities), it is used instead.
    """
    if len(snippets) <= top_k:
        return snippets

    docs = [f"{s.get('title', '')} {s.get('snippet', '')}" for s in snippets]
    all_texts = [query] + docs

    vectorizer = TfidfVectorizer(max_features=500, stop_words=None)
    tfidf_matrix = vectorizer.fit_transform(all_texts).toarray()

    q_vec = tfidf_matrix[0]
    doc_vecs = tfidf_matrix[1:]

    # Compute cosine similarities with query
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return snippets[:top_k]

    doc_norms = np.linalg.norm(doc_vecs, axis=1)
    doc_norms[doc_norms == 0] = 1e-9

    sim_to_q = np.dot(doc_vecs, q_vec) / (doc_norms * q_norm)
    if rel_scores is not None and len(rel_scores) == len(snippets):
        sim_to_q = np.asarray(rel_scores, dtype=float)

    # Inter-document cosine similarity matrix
    pairwise_sim = np.dot(doc_vecs, doc_vecs.T) / (doc_norms[:, None] * doc_norms[None, :])

    selected_indices: List[int] = []
    unselected = list(range(len(snippets)))

    for _ in range(top_k):
        if not unselected:
            break

        if not selected_indices:
            best_idx = int(unselected[np.argmax(sim_to_q[unselected])])
        else:
            mmr_scores = []
            for candidate in unselected:
                rel = sim_to_q[candidate]
                max_div = max(pairwise_sim[candidate, s] for s in selected_indices)
                score = lambda_param * rel - (1.0 - lambda_param) * max_div
                mmr_scores.append((score, candidate))

            mmr_scores.sort(key=lambda x: x[0], reverse=True)
            best_idx = mmr_scores[0][1]

        selected_indices.append(best_idx)
        unselected.remove(best_idx)

    return [snippets[i] for i in selected_indices]


# ---------------------------------------------------------------------------
# 4. Asynchronous Scraping & Clean DOM Hierarchy Extraction (selectolax)
# ---------------------------------------------------------------------------

def clean_header_text(text: str) -> str:
    """Removes anchor badges, edit markers and pilcrows from headings."""
    t = re.sub(r"\[edit\]$", "", text).strip()
    t = re.sub(r"[\u00b6#\xa7]+$", "", t).strip()
    return t


def is_valid_sentence(text: str) -> bool:
    """
    Strict validation to ensure only substantive human sentences are indexed,
    filtering out table-of-contents fragments, citations, download rows, and noise.
    Supports structured Markdown tables (| col | col |).
    """
    t = text.strip()
    # Markdown table validation (single row or multi-row table block)
    if "|" in t and (t.startswith("|") or "\n|" in t):
        words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]{2,}", t)
        return len(words) >= 3 and len(t) >= 15

    if len(t) < 25:
        return False
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ]{2,}", t)
    if len(words) < 5:
        return False

    # Skip link-only navigation action button clusters (e.g. [Notifications]... [Fork]... [Star]... [Raw])
    if re.search(r"\[(Notifications|Fork|Star|History|Raw|Edit|Delete|Download)\]", t):
        return False

    # Skip social sharing buttons and actions
    if re.search(r"\[(Share on |Share|Facebook|Twitter|X|LinkedIn|Telegram|Viber|Whatsapp|Messenger)\]", t, re.I):
        return False

    # Skip blog/newsletter/marketing boilerplate (e.g. Substack home for great culture, subscribe)
    if re.search(r"\b(is the home for great culture|utm_campaign|utm_content|subscribe to|newsletter|substack\.com|read in the app|download the app|privacy policy|terms of service|all rights reserved|copyright \d{4})\b", t, re.I):
        return False

    # Skip lines where markdown links dominate (>65% of character length)
    links_len = sum(len(m.group(0)) for m in re.finditer(r"\[.*?\]\(.*?\)", t))
    if links_len > 0.65 * len(t) and not ("|" in t):
        return False

    # Skip citations, references, and bibliographies
    if t.startswith(("↑", "ISBN", "DOI")) or re.match(r"^\[\d+\]", t) or re.search(r"\b(?:ISBN|DOI|Retrieved|Archived from|bibcode|arxiv)\b", t, re.I):
        return False

    # Skip TOC fragments with dotted numbering (e.g. 6.1.3., 3.1.2., Path6.1.3)
    if re.search(r"\d+\.\d+\.\d+|[a-zA-Z]\d+\.\d+", t):
        return False

    # Skip download tables, version changelogs and release notes
    if re.search(r"\b\d+\.\d+[a-zA-Z]+|\bDownloadRelease\b|\bPEP \d+\b|\bend-of-life\b", t, re.I):
        return False

    # Skip metadata, cookies, and cookie notices
    if re.search(r"\b(?:cookie|cookies|javascript|stylesheets|browser settings)\b", t, re.I):
        return False

    return True


# Regex matching a standalone markdownify image line: "![alt](src)"
MD_IMAGE_LINE_REGEX = re.compile(r"^!\[(.*?)\]\((.*?)\)\s*$")

_JUNK_ALT_REGEX = re.compile(
    r"^(image|photo|picture|img|untitled|logo|icon|banner|avatar|spinner|"
    r"placeholder|loading|blank|pixel|spacer|thumbnail|cover|hero)\b|"
    r"\.(png|jpe?g|gif|webp|svg|ico)$",
    re.I,
)


def _sanitize_fig_text(text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", t).strip()


def _is_junk_alt(alt: str) -> bool:
    return not alt or len(alt) < 8 or bool(_JUNK_ALT_REGEX.search(alt))


def prepare_figures(parser: HTMLParser) -> Dict[str, str]:
    """
    Prunes decorative images (empty/junk alt, tracking pixels) so that
    markdownify emits `![alt](src)` blocks only for descriptive figures.
    A <figure> survives if it has a figcaption even when the alt is junk;
    the caption node is decomposed and returned as {src: caption} so it can
    be merged into the figure block instead of becoming an orphan paragraph.
    Must be called before markdownify conversion.
    """
    captions: Dict[str, str] = {}
    for fig in parser.css("figure"):
        img = fig.css_first("img")
        cap = fig.css_first("figcaption")
        alt = _sanitize_fig_text(img.attributes.get("alt", "")) if img else ""
        caption = _sanitize_fig_text(cap.text(deep=True, separator=" ")) if cap else ""
        src = ""
        if img:
            src = img.attributes.get("src") or img.attributes.get("data-src") or ""
        if caption and src:
            captions[src] = caption
            cap.decompose()
        if _is_junk_alt(alt) and not caption:
            fig.decompose()

    for img in parser.css("img"):
        alt = _sanitize_fig_text(img.attributes.get("alt", ""))
        if _is_junk_alt(alt):
            img.decompose()

    return captions


def extract_figure_blocks(
    lines: List[str],
    header: str,
    start_index: int,
    captions: Optional[Dict[str, str]] = None
) -> List[Dict[str, any]]:
    """
    Converts a raw Markdown block containing `![alt](src)` image lines into
    figure blocks: image description (figcaption preferred, adjacent text
    lines or alt as fallback) plus the source URL for provenance.
    """
    captions = captions or {}
    caption = _sanitize_fig_text(" ".join(l for l in lines if not l.startswith("![")))
    out = []
    for l in lines:
        m = MD_IMAGE_LINE_REGEX.match(l)
        if not m:
            continue
        alt = _sanitize_fig_text(m.group(1))
        src = m.group(2).strip()
        desc = captions.get(src) or caption or alt
        if not desc:
            continue
        out.append({
            "index": start_index + len(out),
            "text": f"[Изображение] {desc}" + (f" (источник: {src})" if src else ""),
            "header": header,
            "figure": True
        })
    return out


def parse_markdown_table_blocks(lines: List[str], max_rows: int = 12) -> List[str]:
    """
    Parses table lines into cohesive, valid Markdown tables with header and separator.
    If table has <= max_rows, returns full table intact so comparison data is never severed.
    If table > max_rows, chunks with repeated header to preserve column semantics.
    """
    table_lines = [l.strip() for l in lines if l.strip()]
    if not table_lines:
        return []

    header = table_lines[0]
    data_start = 1
    if len(table_lines) > 1 and re.match(r"^\|(\s*:?-+:?\s*\|)+$", table_lines[1]):
        separator = table_lines[1]
        data_start = 2
    else:
        cols = max(1, header.count("|") - 1)
        separator = "|" + " --- |" * cols

    data_rows = table_lines[data_start:]
    if not data_rows:
        return ["\n".join([header, separator])]

    chunks = []
    for i in range(0, len(data_rows), max_rows):
        chunk_rows = data_rows[i : i + max_rows]
        table_str = "\n".join([header, separator] + chunk_rows)
        chunks.append(table_str)

    return chunks


def extract_dom_blocks(html: str) -> List[Dict[str, any]]:
    """
    Parses HTML, decomposes noise tags, converts content to ATX Markdown via markdownify,
    preserves tables and tracks H1/H2 breadcrumbs, splitting text into valid sentences.
    """
    parser = HTMLParser(html)
    # Decompose all noise elements, comments/feedback, and navigation containers
    for tag in parser.css(
        "script, style, nav, footer, header, aside, form, svg, noscript, "
        ".toc, #toc, .sidebar, .reflist, .references, .navbox, .catlinks, "
        ".toctree-wrapper, .mw-editsection, .infobox, .table-of-contents, "
        ".menu, .sublinks, .comments, #comments, .comment-respond, "
        ".comment-list, .comment-form, .feedback, #feedback, .discussion, #discussion, "
        ".file-navigation, .pagehead, .breadcrumb, .js-repo-nav, .blob-header, .react-directory-row"
    ):
        tag.decompose()

    # Prune decorative images; descriptive figures survive into Markdown
    # as `![alt](src)` blocks and become scoreable, citable context.
    fig_captions = prepare_figures(parser)

    body = parser.body
    if not body:
        return []

    clean_html = body.html if body else html
    md_text = md(clean_html, heading_style="ATX", strip=["audio", "video"])

    cur_h1, cur_h2 = "", ""
    blocks: List[Dict[str, any]] = []
    sentence_idx = 0

    raw_blocks = re.split(r"\n\s*\n", md_text)
    for rb in raw_blocks:
        rb = rb.strip()
        if not rb:
            continue

        lines = [l.strip() for l in rb.splitlines() if l.strip()]
        if not lines:
            continue

        first_line = lines[0]
        h_match = re.match(r"^(#{1,6})\s+(.+)$", first_line)
        if h_match and len(lines) == 1:
            level = len(h_match.group(1))
            h_text = clean_header_text(h_match.group(2))
            if level == 1:
                cur_h1 = h_text
                cur_h2 = ""
            else:
                cur_h2 = h_text
            continue

        sec_path = " > ".join(filter(None, [cur_h1, cur_h2]))
        if is_blacklisted_section(sec_path):
            continue

        # Figure block: markdownify emitted `![alt](src)` line(s), possibly
        # with a figcaption text line — becomes an atomic figure unit
        if first_line.startswith("!["):
            fig_blocks = extract_figure_blocks(lines, sec_path, sentence_idx, fig_captions)
            blocks.extend(fig_blocks)
            sentence_idx += len(fig_blocks)
            continue

        # Fenced code block (```...```): keep atomic, never sentence-split
        if first_line.startswith("```") or "```" in rb:
            code_text = "\n".join(lines)
            if len(code_text.strip() ) >= 25:
                blocks.append({
                    "index": sentence_idx,
                    "text": code_text,
                    "header": sec_path
                })
                sentence_idx += 1
            continue

        # Check for Markdown table (keep cohesive table block intact with header and separator)
        if any(l.startswith("|") and l.endswith("|") for l in lines):
            t_lines = [l for l in lines if l.startswith("|") and l.endswith("|")]
            t_chunks = parse_markdown_table_blocks(t_lines, max_rows=12)
            for tbl in t_chunks:
                if is_valid_sentence(tbl):
                    blocks.append({
                        "index": sentence_idx,
                        "text": tbl,
                        "header": sec_path
                    })
                    sentence_idx += 1
            continue

        full_text = " ".join(lines)
        if full_text.startswith("#"):
            h_match = re.match(r"^(#{1,6})\s+([^\n]+)(.*)$", full_text)
            if h_match:
                level = len(h_match.group(1))
                h_text = clean_header_text(h_match.group(2))
                if level == 1:
                    cur_h1 = h_text
                    cur_h2 = ""
                else:
                    cur_h2 = h_text
                full_text = h_match.group(3).strip()
                sec_path = " > ".join(filter(None, [cur_h1, cur_h2]))
                if is_blacklisted_section(sec_path):
                    continue

        if not full_text:
            continue

        clean_para = re.sub(r"^[-*+]\s+", "", full_text)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", clean_para) if is_valid_sentence(s)]
        for s in sentences:
            blocks.append({
                "index": sentence_idx,
                "text": s,
                "header": sec_path
            })
            sentence_idx += 1

    return blocks


async def fetch_url_html(client: httpx.AsyncClient, url: str, timeout: float = 3.5) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        r = await client.get(url, timeout=timeout, headers=headers, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return ""


async def fetch_and_parse_all(
    urls: List[str],
    timeout: float = 3.5,
    on_url: Optional[Callable[[str, bool, int], None]] = None
) -> List[Tuple[str, List[Dict[str, any]]]]:
    """
    Parallel async fetch of selected URLs and parsing into DOM blocks.
    `on_url(url, ok, n_blocks)` fires as each page finishes (for live progress).
    Returns: List of (url, doc_blocks) tuples.
    """
    async with httpx.AsyncClient(verify=False) as client:
        async def _fetch_parse(url: str) -> Tuple[str, List[Dict[str, any]]]:
            html = await fetch_url_html(client, url, timeout=timeout)
            blocks = extract_dom_blocks(html) if html else []
            if on_url:
                try:
                    on_url(url, bool(html), len(blocks))
                except Exception:
                    pass
            return url, blocks

        return await asyncio.gather(*[_fetch_parse(url) for url in urls])


STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves", "vs", "versus", "com", "org", "net", "http", "https",
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то", "все",
    "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за", "бы", "по",
    "только", "ее", "мне", "было", "вот", "от", "меня", "еще", "нет", "о", "из",
    "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли", "если", "уже", "или",
    "ни", "быть", "был", "него", "до", "вас", "нибудь", "опять", "уж", "вам",
    "сказал", "ведь", "там", "потом", "себя", "ничего", "ей", "может", "они", "тут",
    "где", "есть", "надо", "ней", "для", "мы", "тебя", "их", "чем", "была", "сам",
    "чтоб", "без", "будто", "чего", "раз", "тоже", "себе", "под", "будет", "ж",
    "тогда", "кто", "этот", "того", "потому", "этого", "какой", "совсем", "ним",
    "здесь", "этом", "один", "почти", "мой", "тем", "чтобы", "нее", "сейчас", "были",
    "куда", "зачем", "всех", "никогда", "можно", "при", "наконец", "два", "об",
    "другой", "хоть", "после", "над", "больше", "тот", "через", "эти", "нас", "про",
    "всего", "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем", "хорошо",
    "свою", "этой", "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им",
    "более", "всегда", "конечно", "всю", "между"
}


def extract_prf_expansion_terms(query: str, snippets: List[Dict[str, str]], top_k: int = 6) -> List[str]:
    """
    Fast Pseudo-Relevance Feedback (PRF) / Fast HyDE without LLM (~0.1-0.2 ms on CPU).
    Extracts high-frequency domain terms from search snippets, excluding query terms and stopwords.
    """
    if not snippets:
        return []

    q_words = set(re.findall(r"\w+", query.lower()))
    q_stems = set(stem_token(w) for w in q_words)
    counter = Counter()

    for s in snippets:
        title_words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}", s.get("title", "").lower())
        desc_words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}", s.get("snippet", "").lower())

        # Title terms receive double weight
        for w in title_words:
            if w not in q_words and stem_token(w) not in q_stems and w not in STOPWORDS and not w.isdigit():
                counter[w] += 2

        for w in desc_words:
            if w not in q_words and stem_token(w) not in q_stems and w not in STOPWORDS and not w.isdigit():
                counter[w] += 1

    return [word for word, _ in counter.most_common(top_k)]


# ---------------------------------------------------------------------------
# 5. Sentence Relevance Scoring
# ---------------------------------------------------------------------------

try:
    from nltk.stem.snowball import SnowballStemmer
    _stemmer_ru = SnowballStemmer("russian")
    _stemmer_en = SnowballStemmer("english")
    def stem_token(token: str) -> str:
        t = token.lower()
        if re.search(r"[а-яё]", t):
            return _stemmer_ru.stem(t)
        return _stemmer_en.stem(t)
except Exception:
    def stem_token(token: str) -> str:
        t = token.lower()
        return t[:5] if len(t) > 4 else t


def score_sentences(
    sentences: List[Dict[str, any]],
    query: str,
    threshold: float = 0.3,
    alpha: float = 0.65,
    theta_anchor: float = 0.45,
    use_two_phase: bool = True,
    prf_terms: Optional[List[str]] = None,
    gamma_prf: float = 0.25,
    min_query_terms: Optional[int] = None,
    min_overlap: Optional[float] = None,
    max_candidates: Optional[int] = None,
    return_details: bool = False
):
    """
    v4 Relevance scoring featuring:
    1. Blacklist meta-section exclusion (R2)
    2. Contextual Header Diffusion (Breadcrumbs Scoring) (R1):
       Score_diffused(s_i) = alpha * Score(s_i) + (1 - alpha) * Score(B(s_i))
    3. Two-phase candidate selection with semantic anchors & +-1 expansion (R3)
    4. Snippet-based Pseudo-Relevance Feedback (PRF / Fast HyDE without LLM)
    5. IDF-weighted term overlap: query terms are weighted by corpus IDF, so a
       single ubiquitous term (e.g. the topic keyword repeated on every chunk
       of a topical page) can no longer push a chunk over threshold on its own.
       Approval requires either >= min_query_terms distinct matched terms or a
       weighted overlap >= min_overlap — header diffusion still boosts scores
       but no longer substitutes for chunk-level evidence.

    `min_query_terms` / `min_overlap` / `max_candidates` default to
    `config.json -> pipeline` keys of the same name when not passed.
    """
    if not sentences:
        return []

    _pipe_cfg = CONFIG.get("pipeline", {})
    if min_query_terms is None:
        min_query_terms = int(_pipe_cfg.get("min_query_terms", 2))
    if min_overlap is None:
        min_overlap = float(_pipe_cfg.get("min_overlap", 0.15))
    if max_candidates is None:
        max_candidates = _pipe_cfg.get("max_candidates") or None

    q_words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    if not q_words:
        q_words = re.findall(r"\w+", query.lower())
    q_set = set(q_words)
    q_stems = set(stem_token(w) for w in q_words)

    if prf_terms:
        prf_set = set(w.lower() for w in prf_terms)
        prf_stems = set(stem_token(w) for w in prf_set)
    else:
        prf_set, prf_stems = set(), set()

    texts = [s.get("text", "") for s in sentences]
    headers = [s.get("header", "") for s in sentences]
    unique_headers = list(dict.fromkeys(h for h in headers if h and not is_blacklisted_section(h)))

    def tokenize_stemmed(text: str):
        words = re.findall(r"\w+", text.lower())
        return [stem_token(w) for w in words if len(w) > 1]

    all_corpus = [query] + texts + unique_headers
    vectorizer = TfidfVectorizer(max_features=2000, analyzer=tokenize_stemmed)
    try:
        tfidf = vectorizer.fit_transform(all_corpus).toarray()
        q_vec = tfidf[0]
        sent_vecs = tfidf[1 : 1 + len(texts)]
        header_vecs = {h: tfidf[1 + len(texts) + i] for i, h in enumerate(unique_headers)}
        q_norm = np.linalg.norm(q_vec)
        sent_norms = np.linalg.norm(sent_vecs, axis=1)
        sent_norms[sent_norms == 0] = 1e-9
        sent_sims = np.dot(sent_vecs, q_vec) / (sent_norms * q_norm) if q_norm > 0 else np.zeros(len(texts))
    except ValueError:
        sent_sims = np.zeros(len(texts))
        header_vecs = {}
        q_norm = 0.0

    # IDF weights of the query terms from the fitted corpus vocabulary. Terms
    # absent from the corpus get the max possible idf (df = 0): they can never
    # match but still count toward the achievable overlap mass.
    feat_idf = getattr(vectorizer, "idf_", None)
    vocab = getattr(vectorizer, "vocabulary_", {})
    n_docs = len(all_corpus)
    idf_stem_w: Dict[str, float] = {}
    if feat_idf is not None and len(q_stems):
        for st in q_stems:
            idf_stem_w[st] = (
                float(feat_idf[vocab[st]])
                if st in vocab
                else float(np.log((1.0 + n_docs) / 1.0) + 1.0)
            )
    idf_stem_total = sum(idf_stem_w.values()) or 1.0
    # A raw query word inherits the weight of its stem.
    idf_word_w = {w: idf_stem_w.get(stem_token(w), 0.0) for w in q_set}
    idf_word_total = sum(idf_word_w.values()) or 1.0
    eff_min_terms = max(1, min(min_query_terms, len(q_set))) if q_set else 1

    # Precalculate relevance scores for unique valid headers B(s_i)
    header_scores: Dict[str, float] = {}
    for h in unique_headers:
        h_words = set(re.findall(r"\w+", h.lower()))
        h_stems = set(stem_token(w) for w in h_words)
        h_overlap = max(len(q_set & h_words), len(q_stems & h_stems)) / max(1, len(q_set))
        if h in header_vecs and q_norm > 0:
            h_v = header_vecs[h]
            h_norm = np.linalg.norm(h_v)
            h_sim = np.dot(h_v, q_vec) / (h_norm * q_norm) if h_norm > 0 else 0.0
        else:
            h_sim = 0.0
        header_scores[h] = 0.5 * h_overlap + 0.5 * float(h_sim)

    # Phase 1: Diffused Scoring & Candidate / Anchor identification
    candidate_dict: Dict[int, float] = {}
    diffused_scores: Dict[int, float] = {}
    anchors: List[int] = []

    for i, s in enumerate(sentences):
        # R2: Guarantee exclusion of blacklisted sections
        hdr = s.get("header", "")
        if is_blacklisted_section(hdr):
            continue

        s_words = set(re.findall(r"\w+", s.get("text", "").lower()))
        s_stems = set(stem_token(w) for w in s_words)
        if idf_stem_w:
            matched_words = q_set & s_words
            matched_stems = q_stems & s_stems
            overlap_sent = max(
                sum(idf_word_w[w] for w in matched_words) / idf_word_total,
                sum(idf_stem_w[t] for t in matched_stems) / idf_stem_total
            )
            n_matched = max(len(matched_words), len(matched_stems))
        else:
            overlap_sent = max(len(q_set & s_words), len(q_stems & s_stems)) / max(1, len(q_set))
            n_matched = max(len(q_set & s_words), len(q_stems & s_stems))

        # Snippet-based PRF expansion overlap boost
        if prf_set:
            overlap_prf = max(len(prf_set & s_words), len(prf_stems & s_stems)) / max(1, len(prf_set))
            effective_overlap = (1.0 - gamma_prf) * overlap_sent + gamma_prf * overlap_prf
        else:
            overlap_prf = 0.0
            effective_overlap = overlap_sent

        score_sent = 0.5 * effective_overlap + 0.5 * float(sent_sims[i])

        # Chunk-level evidence guard: a topical header boosts the score via
        # diffusion but no longer counts as relevance signal on its own —
        # the chunk needs >= min_query_terms distinct matched terms or a
        # weighted overlap >= min_overlap (relaxed fallback keeps the PRF path).
        own_signal = (n_matched >= eff_min_terms) or (overlap_sent >= min_overlap)

        # R1: Breadcrumbs contextual diffusion formula
        if hdr and hdr in header_scores:
            score_hdr = header_scores[hdr]
            score_diffused = max(score_sent, alpha * score_sent + (1.0 - alpha) * score_hdr)
        else:
            score_hdr = 0.0
            score_diffused = score_sent
        has_query_signal = own_signal or (overlap_prf > 0 and threshold <= 0.20)

        # Structured Tabular Boost: Comparison tables with query entities receive relevance boost
        is_table = "|" in s.get("text", "") and ("\n|" in s.get("text", "") or s.get("text", "").startswith("|"))
        if is_table and (overlap_sent > 0 or score_hdr > 0):
            score_diffused = min(1.0, score_diffused + 0.06)
            has_query_signal = True

        diffused_scores[i] = score_diffused
        s_idx = s.get("index", i)

        if score_diffused >= threshold and has_query_signal:
            candidate_dict[s_idx] = round(score_diffused, 3)
            if score_diffused >= theta_anchor:
                anchors.append(i)

    # Phase 2: Local Window Expansion around Semantic Anchors (R3)
    if use_two_phase and anchors:
        for a_idx in anchors:
            for neighbor_pos in (a_idx - 1, a_idx + 1):
                if 0 <= neighbor_pos < len(sentences):
                    neighbor_sent = sentences[neighbor_pos]
                    if is_blacklisted_section(neighbor_sent.get("header", "")):
                        continue
                    n_orig_idx = neighbor_sent.get("index", neighbor_pos)
                    if n_orig_idx not in candidate_dict:
                        candidate_dict[n_orig_idx] = round(max(threshold, diffused_scores.get(neighbor_pos, threshold)), 3)

    # Optional per-document candidate budget (top-K by diffused score),
    # applied after anchor expansion like decide_chunks_fitness does.
    if max_candidates and len(candidate_dict) > max_candidates:
        top_idx = sorted(candidate_dict, key=lambda k: -candidate_dict[k])[:max_candidates]
        candidate_dict = {k: candidate_dict[k] for k in top_idx}

    fragments = [Fragment(index=idx, score=candidate_dict[idx]) for idx in sorted(candidate_dict.keys())]
    if return_details:
        # diffused_scores maps list position -> score for every non-blacklisted
        # sentence (pre-threshold), enabling ranking metrics against gold labels.
        return fragments, diffused_scores
    return fragments


# ---------------------------------------------------------------------------
# 6. End-to-End Pipeline Execution with Detailed Trace Report & Fallback Mode
# ---------------------------------------------------------------------------

def run_pipeline(
    query: str,
    tau_gap: int = 1,
    delta: int = 1,
    theta: float = 0.3,
    top_urls: int = 4,
    search_endpoint: str = "http://localhost/web",
    max_context_tokens: Optional[int] = 4000,
    on_event: Optional[Callable[[Dict[str, any]], None]] = None
) -> Dict[str, any]:
    """
    Executes the full pipeline:
    Query -> 4get -> MinHash -> MMR -> Fetch/DOM Parse (Markdown) ->
    Snippet PRF -> Scoring -> Window Stitching -> Soft Degradation Fallback -> Metrics.

    `on_event` (optional) receives live trace events for UI streaming:
    stage_start / stage_end (with per-stage data) and fetch_progress per URL.
    """
    def emit(event_type: str, **payload):
        if on_event:
            try:
                on_event({"type": event_type, **payload})
            except Exception:
                pass

    t_start = time.perf_counter()
    timings: Dict[str, float] = {}

    # Stage 1: 4get metasearch
    emit("stage_start", stage=1, title="Все найденные ссылки (4get Metasearch)")
    t0 = time.perf_counter()
    raw_snippets = search_4get(query, endpoint=search_endpoint)
    timings["1_search_4get_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    emit("stage_end", stage=1, ms=timings["1_search_4get_ms"],
         data={"links": raw_snippets})

    # Stage 2: MinHash LSH deduplication + MMR diversification & Snippet PRF
    emit("stage_start", stage=2, title="Фильтрация и выбор источников (MinHash LSH + MMR)")
    t0 = time.perf_counter()
    dedup_snippets = deduplicate_snippets(raw_snippets, threshold=0.6)
    timings["2_minhash_dedup_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    diverse_snippets = diversify_mmr(dedup_snippets, query, top_k=top_urls)
    selected_urls = [s["url"] for s in diverse_snippets]
    prf_terms = extract_prf_expansion_terms(query, diverse_snippets if diverse_snippets else dedup_snippets, top_k=6)
    timings["3_mmr_diversify_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    emit("stage_end", stage=2, ms=timings["2_minhash_dedup_ms"] + timings["3_mmr_diversify_ms"],
         data={
             "total": len(raw_snippets),
             "unique_count": len(dedup_snippets),
             "unique_links": dedup_snippets,
             "selected_sources": diverse_snippets,
             "prf_terms": prf_terms
         })

    # Stage 3: Async Fetch & DOM Parsing (HTML -> Markdown)
    emit("stage_start", stage=3, title="Чтение страниц и извлечение структуры DOM")
    t0 = time.perf_counter()
    parsed_docs = asyncio.run(fetch_and_parse_all(
        selected_urls, timeout=3.5,
        on_url=lambda u, ok, n: emit("fetch_progress", url=u, ok=ok, blocks=n)
    ))
    timings["4_scrape_and_dom_ms"] = round((time.perf_counter() - t0) * 1000, 2)

    read_pages_report = []
    for url, doc_blocks in parsed_docs:
        sections = list(dict.fromkeys(b["header"] for b in doc_blocks if b["header"]))
        read_pages_report.append({
            "url": url,
            "status": "OK" if doc_blocks else "EMPTY/FAILED",
            "total_sentences": len(doc_blocks),
            "figures": sum(1 for b in doc_blocks if b.get("figure")),
            "sections": sections[:6]
        })
    emit("stage_end", stage=3, ms=timings["4_scrape_and_dom_ms"],
         data={"pages": read_pages_report})

    # Stage 4 & 5: Sentence Scoring and Window Stitching across documents
    emit("stage_start", stage=4, title="Поиск и скоринг релевантных предложений")
    t0 = time.perf_counter()
    all_passages: List[StitchedPassage] = []
    candidates_report = []

    for url, doc_blocks in parsed_docs:
        if not doc_blocks:
            continue

        doc_sentences = [b["text"] for b in doc_blocks]
        breadcrumbs = {b["index"]: b["header"] for b in doc_blocks}

        candidates = score_sentences(doc_blocks, query, threshold=theta, prf_terms=prf_terms)
        if candidates:
            candidates_report.append({
                "url": url,
                "candidate_count": len(candidates),
                "top_candidates": [
                    {
                        "score": round(c.score, 3),
                        "index": c.index,
                        "text": doc_blocks[c.index]["text"],
                        "header": doc_blocks[c.index]["header"]
                    }
                    for c in candidates[:5]
                ]
            })

            passages = window_stitching(
                candidates=candidates,
                document_sentences=doc_sentences,
                breadcrumbs=breadcrumbs,
                tau_gap=tau_gap,
                delta=delta,
                url=url
            )
            all_passages.extend(passages)

    emit("stage_end", stage=4,
         ms=round((time.perf_counter() - t0) * 1000, 2),
         data={
             "prf_terms": prf_terms,
             "total_candidates": sum(sc["candidate_count"] for sc in candidates_report),
             "sources": candidates_report
         })

    # -----------------------------------------------------------------------
    # Soft Degradation / Fallback Cascade (when standard candidates = 0)
    # -----------------------------------------------------------------------
    emit("stage_start", stage=5, title="Финальная выдача (Window Stitching + DOM-инъекция)")
    fallback_mode: Optional[str] = None
    diagnostic: Dict[str, any] = {}

    if not all_passages:
        # Diagnostic analysis of query terms vs scraped corpus
        q_words_diag = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2] or re.findall(r"\w+", query.lower())
        all_doc_words = set()
        for _, dblocks in parsed_docs:
            for b in dblocks:
                all_doc_words.update(re.findall(r"\w+", b["text"].lower()))
        all_doc_stems = set(stem_token(w) for w in all_doc_words)
        found_terms = [w for w in q_words_diag if w in all_doc_words or stem_token(w) in all_doc_stems]
        missing_terms = [w for w in q_words_diag if w not in found_terms]

        diagnostic = {
            "query_terms": q_words_diag,
            "found_terms": found_terms,
            "missing_terms": missing_terms,
            "prf_terms": prf_terms
        }

        # Level 1 Fallback: Relaxed Threshold (0.15) with PRF expansion boost
        fallback_passages: List[StitchedPassage] = []
        for url, doc_blocks in parsed_docs:
            if not doc_blocks:
                continue
            cands_fb = score_sentences(doc_blocks, query, threshold=0.15, prf_terms=prf_terms, gamma_prf=0.35)
            if cands_fb:
                doc_sentences = [b["text"] for b in doc_blocks]
                breadcrumbs = {b["index"]: b["header"] for b in doc_blocks}
                fb_pass = window_stitching(
                    candidates=cands_fb,
                    document_sentences=doc_sentences,
                    breadcrumbs=breadcrumbs,
                    tau_gap=tau_gap,
                    delta=delta,
                    url=url
                )
                for p in fb_pass:
                    p.header = f"[FALLBACK / Частичное совпадение] {p.header}" if p.header else "[FALLBACK / Частичное совпадение]"
                fallback_passages.extend(fb_pass)

        if fallback_passages:
            all_passages = fallback_passages
            fallback_mode = "RELAXED_THRESHOLD"
        elif diverse_snippets or dedup_snippets:
            # Level 2 Fallback: Metasearch Snippet Synthesis
            snips = diverse_snippets if diverse_snippets else dedup_snippets
            for s in snips[:4]:
                snippet_text = s.get("snippet", "").strip()
                if not snippet_text:
                    continue
                title = s.get("title", "Источник")
                url = s.get("url", "")
                p = StitchedPassage(
                    start_index=0,
                    end_index=0,
                    text=f"[FALLBACK / Сниппет метапоиска | {title} | {url}]\n{snippet_text}",
                    header=f"[FALLBACK: Сниппет] {title}",
                    recovered_sentences=0,
                    url=url
                )
                all_passages.append(p)
            if all_passages:
                fallback_mode = "SNIPPET_FALLBACK"

    # Global passage ranking: windows sorted by peak candidate score (desc),
    # then trimmed to the consumer's context token budget (~4 chars/token).
    all_passages.sort(key=lambda p: -p.score)
    if max_context_tokens is not None:
        est_tokens = 0
        budgeted: List[StitchedPassage] = []
        for p in all_passages:
            p_tokens = max(1, len(p.text) // 4)
            if budgeted and est_tokens + p_tokens > max_context_tokens:
                continue
            est_tokens += p_tokens
            budgeted.append(p)
        all_passages = budgeted

    timings["5_stitching_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    timings["total_latency_ms"] = round((time.perf_counter() - t_start) * 1000, 2)

    # Stage 7: Coherence Metrics Evaluation
    passage_texts = [p.text for p in all_passages]
    passage_headers = [p.header for p in all_passages]
    coherence_eval = evaluate_coherence(passage_texts, headers=passage_headers)

    emit("stage_end", stage=5, ms=timings["total_latency_ms"],
         data={
             "fallback_mode": fallback_mode,
             "diagnostic": diagnostic,
             "passage_count": len(all_passages),
             "coherence": coherence_eval
         })

    # Detailed Step-by-Step Report for Manual Audit
    detailed_report = {
        "all_links": raw_snippets,
        "unique_links": dedup_snippets,
        "selected_sources": diverse_snippets,
        "prf_terms": prf_terms,
        "read_pages": read_pages_report,
        "search_candidates": candidates_report,
        "final_passages": all_passages,
        "fallback_mode": fallback_mode,
        "diagnostic": diagnostic
    }

    return {
        "query": query,
        "timings_ms": timings,
        "sla_pass": timings["total_latency_ms"] < 5000,
        "fallback_mode": fallback_mode,
        "diagnostic": diagnostic,
        "prf_terms": prf_terms,
        "stats": {
            "snippets_found": len(raw_snippets),
            "snippets_after_dedup": len(dedup_snippets),
            "urls_selected": len(selected_urls),
            "passages_extracted": len(all_passages),
            "total_recovered_sentences": sum(p.recovered_sentences for p in all_passages),
            "figures_extracted": sum(1 for _, dblocks in parsed_docs for b in dblocks if b.get("figure")),
            "raw_char_count": sum(len(b["text"]) for _, dblocks in parsed_docs for b in dblocks)
        },
        "report": detailed_report,
        "passages": all_passages,
        "parsed_docs": parsed_docs,
        "coherence": coherence_eval
    }
