"""Reading what a release says about its own data."""

from pathlib import Path

import pytest

from ofag.formats.fgdc import read_release_notes

_RECORD = """<?xml version="1.0"?>
<metadata>
  <idinfo><citation><citeinfo><title>A survey of somewhere</title></citeinfo></citation>
    <descript><abstract>{abstract}</abstract></descript>
  </idinfo>
  <dataqual>
    <attracc><attraccr>{attraccr}</attraccr></attracc>
    <logic>{logic}</logic>
    <lineage><procstep><procdesc>{procdesc}</procdesc></procstep></lineage>
  </dataqual>
  <eainfo><detailed>{attributes}</detailed></eainfo>
</metadata>
"""

_ATTRIBUTE = """
    <attr>
      <attrlabl>{label}</attrlabl>
      <attrdef>{definition}</attrdef>
      <attrdomv><rdom><attrunit>{unit}</attrunit></rdom></attrdomv>
    </attr>
"""


def _write(tmp_path: Path, **fields) -> Path:
    attributes = "".join(
        _ATTRIBUTE.format(**attribute) for attribute in fields.pop("attributes", [])
    )
    body = {"abstract": "", "attraccr": "", "logic": "", "procdesc": ""} | fields
    path = tmp_path / "metadata.xml"
    path.write_text(_RECORD.format(attributes=attributes, **body), encoding="utf-8")
    return path


def test_a_concession_is_surfaced_with_the_term_that_found_it(tmp_path) -> None:
    """The sentence that explained a whole case, one paragraph into a field nobody reads
    before inverting."""
    notes = read_release_notes(
        _write(
            tmp_path,
            logic=(
                "Seismic data along some profiles may be subject to erroneous depths "
                "because of the presence of velocity inversions within the aquifer, "
                "which were confirmed by drilling."
            ),
        )
    )

    assert len(notes.admissions) == 1
    found = notes.admissions[0]
    assert found.field == "logic"
    assert found.about == "logical consistency"
    assert found.term == "velocity inversion"
    assert "confirmed by drilling" in found.sentence


def test_a_claim_is_kept_apart_from_a_concession(tmp_path) -> None:
    """"Reciprocal times were checked and were generally acceptable" reads like reassurance
    and is a hypothesis: on this release one pair disagreed by 39 ms where the next worst
    differed by 6.9 (F044)."""
    notes = read_release_notes(
        _write(
            tmp_path,
            logic=(
                "Reciprocal times were checked for all seismic refraction profiles and "
                "were generally acceptable. The data may be subject to erroneous depths."
            ),
        )
    )

    assert [statement.term for statement in notes.claims] == ["were checked"]
    assert [statement.term for statement in notes.admissions] == ["may be subject"]


def test_one_sentence_is_not_both(tmp_path) -> None:
    """A sentence conceding something is not also a claim, whichever terms it happens to
    contain: "high-quality and error free; however, there are some discrepancies" is the
    concession."""
    notes = read_release_notes(
        _write(tmp_path, attraccr="The data are high-quality with some discrepancies noted.")
    )

    assert len(notes.admissions) == 1
    assert not notes.claims


def test_the_declared_unit_of_every_column_is_read(tmp_path) -> None:
    """What column names do not say."""
    notes = read_release_notes(
        _write(
            tmp_path,
            attributes=[
                {"label": "Top_Depth_feet", "unit": "feet", "definition": "top of interval"},
                {"label": "Easting", "unit": "meters", "definition": "position"},
                {"label": "Profile_ID", "unit": "unitless", "definition": "which line"},
            ],
        )
    )

    assert {unit.attribute: unit.unit for unit in notes.units} == {
        "Top_Depth_feet": "feet",
        "Easting": "meters",
        "Profile_ID": "unitless",
    }
    assert [unit.attribute for unit in notes.imperial_units] == ["Top_Depth_feet"]


def test_the_field_a_sentence_came_from_travels_with_it(tmp_path) -> None:
    """Which field it is in is most of what it means: the same words in `abstract` are a
    summary and in `logic` they are a warning."""
    notes = read_release_notes(
        _write(
            tmp_path,
            abstract="Depths are approximate.",
            procdesc="Positions were estimated from a map.",
        )
    )

    assert {(s.field, s.term) for s in notes.admissions} == {
        ("abstract", "approximate"),
        ("procdesc", "estimated"),
    }


def test_the_whole_field_is_kept_beside_the_sentences_pulled_from_it(tmp_path) -> None:
    """A sentence out of context is how F040 happened: one row of a log read without the two
    rows under it."""
    notes = read_release_notes(tmp_path and _write(tmp_path, logic="A. " * 3 + "It is uncertain."))

    assert "logic" in notes.narrative
    assert notes.narrative["logic"][0].endswith("It is uncertain.")


def test_a_record_with_nothing_to_admit_says_so_rather_than_failing(tmp_path) -> None:
    notes = read_release_notes(_write(tmp_path, abstract="A survey."))

    assert notes.admissions == () and notes.claims == () and notes.units == ()
    assert notes.title == "A survey of somewhere"


def test_a_file_that_is_not_xml_is_refused(tmp_path) -> None:
    path = tmp_path / "metadata.xml"
    path.write_text("not xml at all <<<", encoding="utf-8")

    with pytest.raises(ValueError, match="not parsable XML"):
        read_release_notes(path)
