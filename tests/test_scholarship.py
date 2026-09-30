"""Following an identifier, and the two rules that bound it."""

import os
from datetime import date

import pytest

from ofag.agent.dispatch import GRANTED_BY_DEFAULT, Dispatcher, ToolError
from ofag.agent.identifiers import Resolution, Source, UnresolvedIdentifier, refuse_unresolved
from ofag.agent.scholarship import (
    LISTED,
    REGISTRIES,
    Found,
    NotFound,
    OffTheList,
    _from_crossref,
    _from_datacite,
    refuse_unlisted,
    resolve,
)
from ofag.agent.tools import Tier, tool_manifest

live = pytest.mark.skipif(
    os.environ.get("OFAG_LIVE_LOOKUP") != "1",
    reason="set OFAG_LIVE_LOOKUP=1 to check the registries have not changed shape",
)


class TestWhereItMayReach:
    def test_the_scope_is_a_host_list_and_not_a_judgement(self) -> None:
        """A6 is why. An index for "is this scholarly" would have to be measured against the
        thing it filters for before it gated anything, and there is nothing here to
        calibrate one on."""
        assert LISTED == {
            "api.crossref.org",
            "api.datacite.org",
            "doi.org",
            "www.sciencebase.gov",
            "api.openalex.org",
        }

    def test_the_hosts_are_derived_from_the_registries(self) -> None:
        """So the two cannot disagree, which is how an allowlist rots."""
        assert LISTED == {item.host for item in REGISTRIES}

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/paper.pdf",
            "https://scholar.google.com/citations",
            "https://api.crossref.org.evil.test/works/x",
        ],
    )
    def test_anything_off_the_list_is_refused(self, url: str) -> None:
        with pytest.raises(OffTheList):
            refuse_unlisted(url)

    def test_the_refusal_says_what_is_on_the_list(self) -> None:
        with pytest.raises(OffTheList, match="api.crossref.org"):
            refuse_unlisted("https://example.com/x")

    def test_plain_http_is_refused_even_on_a_listed_host(self) -> None:
        with pytest.raises(OffTheList, match="not https"):
            refuse_unlisted("http://api.crossref.org/works/x")

    def test_every_registry_is_reachable_by_its_own_rule(self) -> None:
        """The URLs this builds have to pass the check this enforces, or the list and the
        templates have drifted apart."""
        for item in REGISTRIES:
            for template in (item.lookup, item.query):
                if template:
                    assert refuse_unlisted(template.format(id="10.0/x"))


class TestWhatItMakesOfAnAnswer:
    def test_a_crossref_body_becomes_a_line_for_a_source_table(self) -> None:
        found = _from_crossref(
            {
                "message": {
                    "title": ["A modified pseudosection for resistivity and IP"],
                    "author": [{"family": "Edwards", "given": "L. S."}],
                    "issued": {"date-parts": [[1977]]},
                    "type": "journal-article",
                    "publisher": "Society of Exploration Geophysicists",
                }
            },
            "10.1190/1.1440762",
        )

        assert found.year == 1977
        assert "Edwards, L. S." in found.as_resolved_to()
        assert found.as_resolved_to().startswith("A modified pseudosection")

    def test_a_datacite_body_keeps_the_creators_in_order(self) -> None:
        found = _from_datacite(
            {
                "data": {
                    "attributes": {
                        "titles": [{"title": "Utah FORGE: 3D Gravity Data"}],
                        "creators": [
                            {"name": "Hardwick, Christian"},
                            {"name": "Witter, Jeff"},
                        ],
                        "publicationYear": 2019,
                        "types": {"resourceTypeGeneral": "Dataset"},
                        "publisher": "DOE Geothermal Data Repository",
                    }
                }
            },
            "10.15121/1542061",
        )

        assert found.authors == ("Hardwick, Christian", "Witter, Jeff")
        assert found.kind == "Dataset"

    def test_more_than_three_authors_is_said_rather_than_listed(self) -> None:
        found = Found(
            identifier="x",
            title="a paper",
            authors=("A", "B", "C", "D"),
            year=2020,
            kind="",
            publisher="",
            registry="api.crossref.org",
        )

        assert "and others" in found.as_resolved_to()

    def test_a_missing_year_is_left_out_rather_than_guessed(self) -> None:
        found = Found("x", "a report", (), None, "", "USGS", "www.sciencebase.gov")

        assert "None" not in found.as_resolved_to()


class TestWritingItBackIntoTheSourceTable:
    """A13's loop, closed. The gate refuses a source nobody followed; this is what follows
    it."""

    def test_a_source_that_resolves_becomes_confirmed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "ofag.agent.scholarship.look_up",
            lambda identifier: Found(
                identifier,
                "Utah FORGE: 3D Gravity Data",
                ("Hardwick, Christian",),
                2019,
                "Dataset",
                "DOE GDR",
                "api.datacite.org",
            ),
        )
        followed = resolve(
            Source(what="the gravity release", identifier="10.15121/1542061"),
            on=date(2026, 9, 23),
        )

        assert followed.resolution is Resolution.CONFIRMED
        assert "Utah FORGE: 3D Gravity Data" in followed.resolved_to
        assert followed.checked_on == date(2026, 9, 23)
        assert refuse_unresolved([followed]) == (followed,)

    def test_a_source_that_does_not_resolve_becomes_dead(self, monkeypatch) -> None:
        def missing(identifier: str) -> Found:
            raise NotFound(f"{identifier} was not found anywhere")

        monkeypatch.setattr("ofag.agent.scholarship.look_up", missing)
        followed = resolve(
            Source(what="the one that was wrong", identifier="10.15121/1559241"),
            on=date(2026, 9, 23),
        )

        assert followed.resolution is Resolution.DEAD
        with pytest.raises(UnresolvedIdentifier, match="1559241"):
            refuse_unresolved([followed])

    def test_mismatch_is_left_to_a_person(self, monkeypatch) -> None:
        """A status code cannot say whether what came back is the thing in hand."""
        monkeypatch.setattr(
            "ofag.agent.scholarship.look_up",
            lambda identifier: Found(
                identifier, "SRTM 1 Arc-Second Global", (), 2017, "Dataset", "USGS", "doi.org"
            ),
        )
        followed = resolve(Source(what="terrain", identifier="10.5066/F7PR7TFT"))

        assert followed.resolution is Resolution.CONFIRMED
        assert "SRTM" in followed.resolved_to, "the reader is who notices this is not 3DEP"


class TestThroughTheToolSurface:
    def test_reaching_outward_is_not_granted_by_default(self) -> None:
        """`may this reach the network` is a question a caller should have to have answered."""
        assert Tier.OUTWARD not in GRANTED_BY_DEFAULT

    def test_it_is_invisible_until_granted(self, tmp_path) -> None:
        ordinary = Dispatcher(artifact_root=tmp_path)

        assert "ofag.resolve_identifier" not in {t.name for t in ordinary.manifest()}

    def test_the_scope_can_be_read_without_reaching_anything(self, tmp_path) -> None:
        ordinary = Dispatcher(artifact_root=tmp_path)

        listed = ordinary.call("ofag.registries", {})

        assert {row["host"] for row in listed} == LISTED
        assert all(row["answers_for"] for row in listed)

    def test_an_identifier_and_a_search_together_are_refused(self, tmp_path) -> None:
        """They are different questions and the second is a guess."""
        granted = Dispatcher(artifact_root=tmp_path, granted=(*GRANTED_BY_DEFAULT, Tier.OUTWARD))

        with pytest.raises(ToolError, match="different questions"):
            granted.call(
                "ofag.resolve_identifier", {"identifier": "10.0/x", "bibliographic": "a title"}
            )

    def test_neither_is_refused_too(self, tmp_path) -> None:
        granted = Dispatcher(artifact_root=tmp_path, granted=(*GRANTED_BY_DEFAULT, Tier.OUTWARD))

        with pytest.raises(ToolError, match="different questions"):
            granted.call("ofag.resolve_identifier", {})

    def test_the_refusals_are_in_the_description_an_agent_reads(self) -> None:
        tool = next(t for t in tool_manifest(None) if t.name == "ofag.resolve_identifier")

        assert "host list" in tool.refuses
        assert "no body" in tool.refuses


@live
class TestTheRegistriesStillAnswer:
    """Opt-in. A registry that changed shape would otherwise be found by a case write-up
    rather than by a test."""

    def test_a_journal_doi_resolves_to_its_own_title(self) -> None:
        from ofag.agent.scholarship import look_up

        found = look_up("10.1016/j.cageo.2015.09.015")

        assert "SimPEG" in found.title

    def test_a_dataset_doi_resolves_where_crossref_cannot_help(self) -> None:
        from ofag.agent.scholarship import look_up

        found = look_up("10.5066/F72Z14G6")

        assert "Llano" in found.title
        assert found.registry == "api.datacite.org"

    def test_the_three_that_were_wrong_are_still_dead(self) -> None:
        """Not a test of the registries so much as of the finding: these were recorded in a
        source table and none of them points anywhere."""
        for identifier in ("10.15121/1559241", "10.15121/1452445", "10.15121/1846183"):
            followed = resolve(Source(what="a case 1 row", identifier=identifier))
            assert followed.resolution is Resolution.DEAD, identifier
