import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel


DOCUMENT_ID = re.compile(r"^\*\*Document ID:\*\*\s+(\S+)", re.MULTILINE)
SECTION = re.compile(r"^#{2,3} +(\d+(?:\.\d+)*)\.? +(.+)$", re.MULTILINE)
WORD = re.compile(r"[a-z]+|\d+")
STOP_WORDS = frozenset(
    "a an and are after be can do does for how i in is it make my of on the "
    "to use what when will with you your".split()
)
ALIASES = {
    "charges": "charge",
    "data": "internet",
    "days": "day",
    "disputes": "dispute",
    "extra": "additional",
    "overage": "additional",
    "part": "partial",
    "pay": "payment",
    "payments": "payment",
    "restrict": "restriction",
    "restricted": "restriction",
    "restrictions": "restriction",
}


class Passage(BaseModel):
    section: str
    heading: str
    excerpt: str


class SearchResult(BaseModel):
    document_id: str
    passages: list[Passage]


def _terms(text: str) -> set[str]:
    return {
        ALIASES.get(word, word)
        for word in WORD.findall(text.casefold())
        if word not in STOP_WORDS
    }


@dataclass(frozen=True)
class BillingGuideIndex:
    document_id: str
    passages: tuple[Passage, ...]
    postings: dict[str, dict[int, int]]

    @classmethod
    def load(cls, path: Path) -> "BillingGuideIndex":
        markdown = path.read_text(encoding="utf-8-sig")
        document = DOCUMENT_ID.search(markdown)
        if document is None:
            raise ValueError("Billing guide is missing its document ID")

        headings = list(SECTION.finditer(markdown))
        passages = []
        postings: dict[str, dict[int, int]] = {}
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
            excerpt = markdown[heading.end() : end].strip()
            section, title = heading.groups()
            # Section 9 describes how to build the assignment's tool.
            if not excerpt or section == "9":
                continue

            passage_index = len(passages)
            passages.append(Passage(section=section, heading=title, excerpt=excerpt))
            title_terms = _terms(title)
            for term in title_terms | _terms(excerpt):
                postings.setdefault(term, {})[passage_index] = 4 if term in title_terms else 1

        if not passages:
            raise ValueError("Billing guide contains no policy passages")
        return cls(document[1], tuple(passages), postings)

    def search(self, query: str) -> SearchResult:
        terms = _terms(query)
        scores: Counter[int] = Counter()
        matched_terms: Counter[int] = Counter()
        for term in terms:
            postings = self.postings.get(term, {})
            scores.update(postings)
            matched_terms.update(postings.keys())

        minimum_matches = min(2, len(terms))
        candidates = (
            index for index, count in matched_terms.items() if count >= minimum_matches
        )
        selected = sorted(candidates, key=lambda index: (-scores[index], index))[:3]
        return SearchResult(
            document_id=self.document_id,
            passages=[self.passages[index] for index in selected],
        )
