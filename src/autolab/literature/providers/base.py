"""Official API transport, with bounded responses and no implicit retries."""
from typing import Protocol
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from autolab.literature.models import LiteratureResult


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    pass


class LiteratureProvider(Protocol):
    name: str
    warnings: list[str]
    def search(self, query: str, limit: int, filters: dict | None = None) -> list[LiteratureResult]: ...


def fetch(url: str, *, headers: dict, timeout: float = 25) -> bytes:
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ProviderError("Provider response exceeds 8 MB limit.")
            return body
    except HTTPError as error:
        # Never echo URLs, response bodies, request headers, or credentials.
        raise ProviderError(f"Provider HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise ProviderError("Provider network failure or timeout") from None


def user_agent(contact: str | None = None) -> str:
    return "AutoLab/0.1 (computational research; https://github.com/omnigent-ai/omnigent)" + (f" mailto:{contact}" if contact else "")
