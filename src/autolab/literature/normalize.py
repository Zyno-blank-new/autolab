"""Conservative publication identity and metadata normalization."""
import re
import unicodedata
from urllib.parse import urlsplit, unquote


def whitespace(text: str) -> str:
    return " ".join(text.split())


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = unquote(value.strip()).casefold()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value)
    return value if re.fullmatch(r"10\.\d{4,9}/\S+", value) else None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^arxiv:\s*", "", value.strip(), flags=re.I)
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.hostname not in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
            return None
        value = re.sub(r"^/(?:abs|pdf)/", "", parsed.path)
    value = re.sub(r"\.pdf$", "", value)
    value = re.sub(r"v\d+$", "", value)
    return value if re.fullmatch(r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})", value) else None


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return whitespace("".join(c if c.isalnum() else " " for c in value))


def safe_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        return None
    # Bibliographic links never need credential-bearing queries.
    if any(token in parsed.query.casefold() for token in ("api_key=", "token=", "key=")):
        return None
    return value


def reconstruct_abstract(index) -> str | None:
    if not isinstance(index, dict) or not index:
        return None
    tokens = {}
    for word, positions in index.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            raise ValueError("Malformed abstract index")
        for position in positions:
            if type(position) is not int or position < 0 or position > 20000 or position in tokens:
                raise ValueError("Malformed abstract position")
            tokens[position] = word
    if sorted(tokens) != list(range(len(tokens))):
        raise ValueError("Incomplete abstract index")
    return " ".join(tokens[n] for n in range(len(tokens))) or None
