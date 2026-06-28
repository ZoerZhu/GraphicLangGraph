from __future__ import annotations

import html as html_lib
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from .. import engine
from ..common import compact_value, positive_int


def web_search(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or args.get("q") or "").strip()
    if not query:
        raise RuntimeError("web_search 需要 query 参数。")
    mode = str(args.get("mode") or args.get("search_mode") or "serp").strip().lower()
    if mode not in {"auto", "instant", "serp"}:
        mode = "serp"
    serp_fallback = args.get("serp_fallback", args.get("fallback", True)) is not False
    max_results = min(positive_int(args.get("max_results", args.get("limit", 5)), 5), 12)

    data: dict[str, Any] = {}
    related_topics: list[dict[str, str]] = []
    if mode != "serp":
        assert_network_allowed("https://api.duckduckgo.com/", runtime, extra_allowed_hosts={"api.duckduckgo.com"})
        params = {
            "q": query,
            "format": "json",
            "no_redirect": "1",
            "no_html": "1",
            "skip_disambig": "1",
        }
        url = "https://api.duckduckgo.com/?" + urlencode(params)
        response = httpx.get(url, timeout=12, follow_redirects=True, headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()
        related_topics = duckduckgo_related_topics(data.get("RelatedTopics"), max_results)

    has_instant_answer = duckduckgo_has_instant_answer(data, related_topics)
    should_run_serp = mode == "serp" or (mode == "auto" and serp_fallback and not has_instant_answer)
    serp_results = duckduckgo_serp_results(query, max_results, runtime) if should_run_serp else []
    source = "duckduckgo_serp" if mode == "serp" else "duckduckgo_serp_fallback" if serp_results and not has_instant_answer else "duckduckgo_instant_answer"
    return {
        "query": query,
        "source": source,
        "searchMode": mode,
        "serpFallbackUsed": bool(serp_results and mode != "serp" and not has_instant_answer),
        "answer": data.get("Answer") or "",
        "abstract": data.get("AbstractText") or data.get("Abstract") or "",
        "abstractUrl": data.get("AbstractURL") or "",
        "definition": data.get("Definition") or "",
        "relatedTopics": related_topics,
        "serpResults": serp_results,
        "rawLimited": compact_value(data),
    }


def duckduckgo_has_instant_answer(data: dict[str, Any], related_topics: list[dict[str, str]]) -> bool:
    return bool(
        str(data.get("Answer") or "").strip()
        or str(data.get("AbstractText") or data.get("Abstract") or "").strip()
        or str(data.get("Definition") or "").strip()
        or related_topics
    )


def duckduckgo_serp_results(query: str, limit: int, runtime: dict[str, Any]) -> list[dict[str, str]]:
    assert_network_allowed(
        "https://html.duckduckgo.com/html/",
        runtime,
        extra_allowed_hosts={"duckduckgo.com", "html.duckduckgo.com"},
    )
    params = {"q": query}
    response = httpx.get(
        "https://html.duckduckgo.com/html/?" + urlencode(params),
        timeout=15,
        follow_redirects=True,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "GraphicLangGraph/0.1 (+https://local)",
        },
    )
    response.raise_for_status()
    parser = DuckDuckGoHtmlResultsParser(limit)
    parser.feed(response.text)
    parser.close()
    return parser.results[:limit]


class DuckDuckGoHtmlResultsParser(HTMLParser):
    def __init__(self, limit: int) -> None:
        super().__init__(convert_charrefs=True)
        self.limit = limit
        self.results: list[dict[str, str]] = []
        self._active_title: dict[str, Any] | None = None
        self._active_snippet_index: int | None = None
        self._snippet_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.results) >= self.limit:
            return
        attr = {key: value or "" for key, value in attrs}
        class_name = attr.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._active_title = {"href": attr.get("href", ""), "parts": []}
            return
        if tag in {"a", "div"} and "result__snippet" in class_name and self.results:
            self._active_snippet_index = len(self.results) - 1
            self._snippet_depth = 1
            return
        if self._active_snippet_index is not None:
            self._snippet_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._active_title is not None:
            title = clean_search_text(" ".join(self._active_title["parts"]))
            url = duckduckgo_result_url(str(self._active_title.get("href") or ""))
            if title and url and not any(item["url"] == url for item in self.results):
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._active_title = None
            return
        if self._active_snippet_index is not None:
            self._snippet_depth -= 1
            if self._snippet_depth <= 0:
                self._active_snippet_index = None

    def handle_data(self, data: str) -> None:
        if self._active_title is not None:
            self._active_title["parts"].append(data)
            return
        if self._active_snippet_index is not None and 0 <= self._active_snippet_index < len(self.results):
            current = self.results[self._active_snippet_index].get("snippet", "")
            self.results[self._active_snippet_index]["snippet"] = clean_search_text(f"{current} {data}")


def duckduckgo_result_url(raw_url: str) -> str:
    url = html_lib.unescape(raw_url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    if url.startswith("/"):
        url = f"https://duckduckgo.com{url}"
    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target.strip()
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return url
    return ""


def clean_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def duckduckgo_related_topics(value: Any, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    def visit(items: Any) -> None:
        if len(results) >= limit or not isinstance(items, list):
            return
        for item in items:
            if len(results) >= limit:
                break
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("Topics"), list):
                visit(item["Topics"])
                continue
            text = str(item.get("Text") or "").strip()
            url = str(item.get("FirstURL") or "").strip()
            if text or url:
                results.append({"title": text[:180], "url": url, "snippet": text})

    visit(value)
    return results


def fetch_url(args: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    if not url:
        raise RuntimeError("fetch_url 需要 url 参数。")
    assert_network_allowed(url, runtime)
    max_bytes = engine._runtime_max_http_bytes(runtime)
    response = httpx.get(url, timeout=15, follow_redirects=True)
    response.raise_for_status()
    body = response.content[: max_bytes + 1]
    truncated = len(body) > max_bytes
    if truncated:
        body = body[:max_bytes]
    encoding = response.encoding or "utf-8"
    text = body.decode(encoding, errors="replace")
    max_chars = positive_int(args.get("max_chars"), len(text))
    if max_chars < len(text):
        text = text[:max_chars]
        truncated = True
    return {
        "url": str(response.url),
        "statusCode": response.status_code,
        "contentType": response.headers.get("content-type", ""),
        "truncated": truncated,
        "text": text,
    }


def assert_network_allowed(url: str, runtime: dict[str, Any], extra_allowed_hosts: set[str] | None = None) -> None:
    return engine._assert_network_allowed(url, runtime, extra_allowed_hosts)


def host_allowed(host: str, allowed_hosts: set[str]) -> bool:
    return engine._host_allowed(host, allowed_hosts)
