import hashlib
import pytest
from app.catalog_import import CatalogValidationError, validate_package


def test_rejects_a_catalog_without_authoritative_cardinality():
    guide = __file__
    with open(guide, "rb") as stream:
        source_hash = hashlib.sha256(stream.read()).hexdigest()
    package = {"manifest": {"framework": "CMMC", "level": 2, "version": "2.13", "source_url": "https://example.invalid/guide.pdf", "source_sha256": source_hash}, "domains": [], "practices": []}
    with pytest.raises(CatalogValidationError, match="14 CMMC"):
        validate_package(package, __import__("pathlib").Path(guide))
