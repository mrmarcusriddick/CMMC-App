from app.guide_catalog import normalize


def test_normalize_removes_extraction_page_artifacts():
    assert normalize("Example \\f CMMC Assessment Guide - Level 2 | Version 2.13 14 text") == "Example text"
