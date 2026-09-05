"""Validate and import a source-traceable CMMC catalog package.

The importer intentionally does not scrape or invent assessment wording. A package is
prepared from an approved source and accompanied by the exact guide PDF it represents.
"""
import argparse
import hashlib
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, SessionLocal, engine
from .models import FrameworkAssessmentObjective, FrameworkPractice, FrameworkRelease

EXPECTED_DOMAIN_CODES = {"AC", "AT", "AU", "CA", "CM", "IA", "IR", "MA", "MP", "PE", "PS", "RA", "SC", "SI"}


class CatalogValidationError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_package(package: dict, guide_path: Path) -> None:
    manifest = package.get("manifest", {})
    domains = package.get("domains", [])
    practices = package.get("practices", [])
    if manifest.get("framework") != "CMMC" or manifest.get("level") != 2 or not manifest.get("version"):
        raise CatalogValidationError("Manifest must identify a versioned CMMC Level 2 framework.")
    if not manifest.get("source_url") or not manifest.get("source_sha256"):
        raise CatalogValidationError("Manifest must include an official source URL and SHA-256.")
    if not guide_path.is_file() or sha256_file(guide_path).lower() != manifest["source_sha256"].lower():
        raise CatalogValidationError("The supplied guide PDF does not match manifest.source_sha256.")
    domain_codes = {item.get("code") for item in domains}
    if domain_codes != EXPECTED_DOMAIN_CODES or len(domains) != 14:
        raise CatalogValidationError("Catalog must include exactly the 14 CMMC Level 2 domains.")
    identifiers = [item.get("identifier") for item in practices]
    if len(practices) != 110 or len(set(identifiers)) != 110 or any(not item for item in identifiers):
        raise CatalogValidationError("Catalog must include exactly 110 uniquely identified practices.")
    objectives = [objective for practice in practices for objective in practice.get("objectives", [])]
    objective_ids = [item.get("identifier") for item in objectives]
    if len(objectives) != 320 or len(set(objective_ids)) != 320 or any(not item for item in objective_ids):
        raise CatalogValidationError("Catalog must include exactly 320 uniquely identified assessment objectives.")
    for practice in practices:
        if practice.get("domain") not in domain_codes or not practice.get("statement", "").strip():
            raise CatalogValidationError(f"Practice {practice.get('identifier')} has invalid domain or statement.")
        for objective in practice.get("objectives", []):
            if not objective.get("statement", "").strip() or not objective["identifier"].startswith(f"{practice['identifier']}["):
                raise CatalogValidationError(f"Objective {objective.get('identifier')} is not linked to its parent practice.")


def import_package(session: Session, package: dict, imported_by: str) -> FrameworkRelease:
    manifest = package["manifest"]
    existing = session.scalar(select(FrameworkRelease).where(FrameworkRelease.framework == "CMMC", FrameworkRelease.level == 2, FrameworkRelease.version == manifest["version"]))
    if existing:
        raise CatalogValidationError(f"CMMC Level 2 v{manifest['version']} is already registered.")
    release = FrameworkRelease(framework="CMMC", level=2, version=manifest["version"], source_url=manifest["source_url"], source_sha256=manifest["source_sha256"].lower(), status="SOURCE_VALIDATED", imported_by=imported_by)
    session.add(release)
    for item in package["practices"]:
        practice = FrameworkPractice(release=release, domain_code=item["domain"], identifier=item["identifier"], title=item.get("title") or item["statement"], statement=item["statement"])
        session.add(practice)
        for ordinal, objective in enumerate(item["objectives"], start=1):
            session.add(FrameworkAssessmentObjective(practice=practice, identifier=objective["identifier"], ordinal=ordinal, statement=objective["statement"]))
    session.commit()
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a verified CMMC Level 2 catalog package.")
    parser.add_argument("catalog", type=Path, help="JSON catalog package created from the approved guide")
    parser.add_argument("--guide", type=Path, required=True, help="Exact official PDF represented by manifest.source_sha256")
    parser.add_argument("--imported-by", required=True, help="Named reviewer accountable for this baseline")
    args = parser.parse_args()
    package = json.loads(args.catalog.read_text(encoding="utf-8"))
    validate_package(package, args.guide)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        release = import_package(session, package, args.imported_by)
        result = (release.framework, release.level, release.version, release.id)
    print(f"Imported verified {result[0]} Level {result[1]} v{result[2]}: {result[3]}")


if __name__ == "__main__":
    main()
