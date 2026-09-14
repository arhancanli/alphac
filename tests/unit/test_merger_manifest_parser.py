import pytest
from audit_merger_manifests import primary_link

ACC = "0000000001-10-000001"


def page(href):
    return (
        '<table summary="Document Format Files"><tr><td>1</td><td>Description</td>'
        f'<td><a href="{href}">main.htm</a></td><td>DEFM14A</td><td>100</td></tr></table>'
    )


def test_exact_form_sequence_and_accession():
    p = page("/Archives/edgar/data/1/000000000110000001/main.htm")
    assert primary_link(p, accession=ACC, form="DEFM14A")["filename"] == "main.htm"
    with pytest.raises(ValueError):
        primary_link(p, accession=ACC, form="SC 14D9")
    with pytest.raises(ValueError):
        primary_link(p + p, accession=ACC, form="DEFM14A")


def test_external_or_wrong_accession_link_rejected():
    for url in ["https://example.com/main.htm", "/Archives/edgar/data/1/wrong/main.htm"]:
        with pytest.raises(ValueError):
            primary_link(page(url), accession=ACC, form="DEFM14A")
