"""Following an identifier to the published thing it names, and nothing else."""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

__all__ = [
    "Registry",
    "REGISTRIES",
    "OffTheList",
    "NotFound",
    "Found",
    "refuse_unlisted",
    "look_up",
    "search",
    "resolve",
]

#: Sent so the registries can see who is asking, which is their own request.
USER_AGENT = "OFAG/0.1 (geophysics case validation; identifier resolution only)"

#: How long to wait before giving up on one lookup.
TIMEOUT_SECONDS = 25.0


@dataclass(frozen=True)
class Registry:
    """One place that answers about published work, and what it answers."""

    host: str
    what: str
    #: How a lookup URL is built.
    lookup: str = ""
    #: How a bibliographic search is built, where the registry offers one.
    query: str = ""
    #: Sent with the request where the registry needs it to return metadata rather than
    #: a page.
    accept: str = "application/json"


REGISTRIES: tuple[Registry, ...] = (
    Registry(
        host="api.crossref.org",
        what="journal articles, conference proceedings and books, by DOI or title",
        lookup="https://api.crossref.org/works/{id}",
        query="https://api.crossref.org/works?rows=5&query.bibliographic={id}",
    ),
    Registry(
        host="api.datacite.org",
        what="datasets and data releases, by DOI",
        lookup="https://api.datacite.org/dois/{id}",
        query="https://api.datacite.org/dois?page[size]=5&query={id}",
    ),
    Registry(
        host="doi.org",
        what="any registered DOI, as the record itself rather than a publisher's page",
        lookup="https://doi.org/{id}",
        accept="application/vnd.citationstyles.csl+json",
    ),
    Registry(
        host="www.sciencebase.gov",
        what="USGS items: releases, reports and the products behind them",
        lookup="https://www.sciencebase.gov/catalog/item/{id}?format=json",
    ),
    Registry(
        host="api.openalex.org",
        what="a broad scholarly index, including preprints and conference papers",
        lookup="https://api.openalex.org/works/doi:{id}",
        query="https://api.openalex.org/works?per-page=5&search={id}",
    ),
)

#: The hosts, derived from the registries so the two cannot disagree.
LISTED: frozenset[str] = frozenset(item.host for item in REGISTRIES)


class OffTheList(RuntimeError):
    """A URL outside the registries this is allowed to reach."""


class NotFound(RuntimeError):
    """An identifier that no listed registry answered for."""


@dataclass(frozen=True)
class Found:
    """What came back, in the words a source table wants."""

    identifier: str
    #: The title as the registry states it.
    title: str
    authors: tuple[str, ...]
    year: int | None
    kind: str
    publisher: str
    #: Which registry answered, so a reader can go and look at the same place.
    registry: str

    def as_resolved_to(self) -> str:
        """One line for the source table."""
        people = ", ".join(self.authors[:3]) + (" and others" if len(self.authors) > 3 else "")
        parts = [self.title]
        if people:
            parts.append(people)
        if self.year:
            parts.append(str(self.year))
        if self.publisher:
            parts.append(self.publisher)
        return "; ".join(parts)


class _StayOnTheList(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to another listed host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        refuse_unlisted(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def refuse_unlisted(url: str) -> str:
    """Raise unless this is https and its host is one of the registries."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        raise OffTheList(f"{url} is not https")
    if parts.hostname not in LISTED:
        raise OffTheList(
            f"{parts.hostname} is not one of the registries this may reach: "
            + ", ".join(sorted(LISTED))
            + ". The scope is published work -- literature, reports, datasets, conference "
            "papers -- and it is a host list rather than a judgement about content."
        )
    return url


def _get(url: str, accept: str) -> Any:
    """One GET, no body, on a listed host."""
    refuse_unlisted(url)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": accept}, method="GET"
    )
    opener = urllib.request.build_opener(_StayOnTheList())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _from_crossref(body: dict[str, Any], identifier: str) -> Found:
    work = body.get("message", body)
    return Found(
        identifier=identifier,
        title=" ".join(work.get("title") or []) or "",
        authors=tuple(
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
            for a in work.get("author") or []
        ),
        year=_year(((work.get("issued") or {}).get("date-parts") or [[None]])[0][0]),
        kind=str(work.get("type") or ""),
        publisher=str(work.get("publisher") or ""),
        registry="api.crossref.org",
    )


def _from_datacite(body: dict[str, Any], identifier: str) -> Found:
    at = (body.get("data") or {}).get("attributes") or {}
    titles = at.get("titles") or []
    return Found(
        identifier=identifier,
        title=str(titles[0].get("title")) if titles else "",
        authors=tuple(str(c.get("name") or "") for c in at.get("creators") or []),
        year=_year(at.get("publicationYear")),
        kind=str((at.get("types") or {}).get("resourceTypeGeneral") or ""),
        publisher=str(at.get("publisher") or ""),
        registry="api.datacite.org",
    )


def _from_csl(body: dict[str, Any], identifier: str) -> Found:
    return Found(
        identifier=identifier,
        title=str(body.get("title") or ""),
        authors=tuple(
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
            for a in body.get("author") or []
        ),
        year=_year(((body.get("issued") or {}).get("date-parts") or [[None]])[0][0]),
        kind=str(body.get("type") or ""),
        publisher=str(body.get("publisher") or ""),
        registry="doi.org",
    )


def _from_sciencebase(body: dict[str, Any], identifier: str) -> Found:
    return Found(
        identifier=identifier,
        title=str(body.get("title") or ""),
        authors=tuple(
            str(c.get("name") or "") for c in body.get("contacts") or [] if c.get("name")
        ),
        year=None,
        kind=str(body.get("browseCategories", [""])[0] if body.get("browseCategories") else ""),
        publisher="U.S. Geological Survey",
        registry="www.sciencebase.gov",
    )


def _year(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def look_up(identifier: str) -> Found:
    """Follow one identifier, and say what came back."""
    wanted = identifier.strip()
    if not wanted:
        raise NotFound("no identifier given")
    quoted = urllib.parse.quote(wanted, safe="")
    readers = {
        "api.crossref.org": _from_crossref,
        "api.datacite.org": _from_datacite,
        "doi.org": _from_csl,
        "www.sciencebase.gov": _from_sciencebase,
    }
    tried: list[str] = []
    for registry in REGISTRIES:
        if not registry.lookup or registry.host not in readers:
            continue
        try:
            body = _get(registry.lookup.format(id=quoted), registry.accept)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as missed:
            tried.append(f"{registry.host} ({type(missed).__name__})")
            continue
        found = readers[registry.host](body, wanted)
        if found.title:
            return found
        tried.append(f"{registry.host} (answered with no title)")
    raise NotFound(f"{wanted} was not found at " + ", ".join(tried))


def search(bibliographic: str) -> tuple[Found, ...]:
    """Find candidates for a reference written out in prose."""
    quoted = urllib.parse.quote(bibliographic.strip(), safe="")
    registry = next(item for item in REGISTRIES if item.host == "api.crossref.org")
    body = _get(registry.query.format(id=quoted), registry.accept)
    items = (body.get("message") or {}).get("items") or []
    return tuple(_from_crossref({"message": item}, str(item.get("DOI") or "")) for item in items)


def resolve(source: Any, *, on: date | None = None) -> Any:
    """Follow a `identifiers.Source` and return it with its resolution filled."""
    from ofag.agent.identifiers import Resolution, Source

    if not isinstance(source, Source):  # pragma: no cover - defensive
        raise TypeError(f"expected an identifiers.Source, got {type(source).__name__}")
    when = on or datetime.now(UTC).date()
    try:
        found = look_up(source.identifier)
    except NotFound:
        return source.model_copy(
            update={
                "resolution": Resolution.DEAD,
                "resolved_to": "",
                "checked_on": when,
            }
        )
    return source.model_copy(
        update={
            "resolution": Resolution.CONFIRMED,
            "resolved_to": found.as_resolved_to(),
            "checked_on": when,
        }
    )
