"""Create a hash-bound CMMC Level 2 catalog package from the official guide PDF."""
import argparse
import hashlib
import json
import re
from pathlib import Path

SOURCE_URL = "https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL2v2.pdf"
DOMAIN_NAMES = {
    "AC": "Access Control", "AT": "Awareness and Training", "AU": "Audit and Accountability",
    "CA": "Security Assessment", "CM": "Configuration Management", "IA": "Identification and Authentication",
    "IR": "Incident Response", "MA": "Maintenance", "MP": "Media Protection", "PE": "Physical Protection",
    "PS": "Personnel Security", "RA": "Risk Assessment", "SC": "System and Communications Protection",
    "SI": "System and Information Integrity",
}
HEADING = re.compile(r"(?m)^([A-Z]{2}\.L2-3\.\d+\.\d+) \u2013 ([A-Z][A-Z0-9 &,-]*?)(?: \[[A-Z ]+\])?\s*$")
OBJECTIVE = re.compile(r"(?ms)^\[([a-z])\]\s*(.*?)(?=^\[[a-z]\]|\Z)")


class GuideCatalogError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    value = value.replace("\x0c", " ").replace("\\f", " ")
    value = re.sub(r"CMMC Assessment Guide.*?Version 2\.13\s+\d+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def parse_guide(path: Path) -> dict:
    from pypdf import PdfReader
    reader = PdfReader(path)
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    headings = list(HEADING.finditer(text))
    if len(headings) != 110:
        raise GuideCatalogError(f"Expected 110 uppercase Level 2 headings; found {len(headings)}.")
    practices = []
    for index, heading in enumerate(headings):
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[heading.end():section_end]
        if "ASSESSMENT OBJECTIVES" not in section or "POTENTIAL ASSESSMENT METHODS" not in section:
            raise GuideCatalogError(f"Could not locate assessment section for {heading.group(1)}.")
        statement_block, assessment_block = section.split("ASSESSMENT OBJECTIVES", 1)
        if "Determine if:" not in assessment_block:
            raise GuideCatalogError(f"Could not locate determination statements for {heading.group(1)}.")
        assessment_block = assessment_block.split("Determine if:", 1)[1].split("POTENTIAL ASSESSMENT METHODS", 1)[0]
        objectives = []
        for letter, content in OBJECTIVE.findall(assessment_block):
            statement = normalize(content)
            if not statement:
                raise GuideCatalogError(f"Empty objective {heading.group(1)}[{letter}].")
            objectives.append({"identifier": f"{heading.group(1)}[{letter}]", "statement": statement})
        if not objectives:
            raise GuideCatalogError(f"No objectives found for {heading.group(1)}.")
        identifier = heading.group(1)
        practices.append({"domain": identifier.split(".", 1)[0], "identifier": identifier, "title": normalize(heading.group(2)), "statement": normalize(statement_block), "objectives": objectives})
    total_objectives = sum(len(item["objectives"]) for item in practices)
    if total_objectives != 320:
        raise GuideCatalogError(f"Expected 320 assessment objectives; found {total_objectives}.")
    return {"manifest": {"framework": "CMMC", "level": 2, "version": "2.13", "source_url": SOURCE_URL, "source_sha256": sha256_file(path), "source_filename": path.name}, "domains": [{"code": code, "name": name} for code, name in DOMAIN_NAMES.items()], "practices": practices}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a CMMC Level 2 catalog package from the official v2.13 guide.")
    parser.add_argument("guide", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package = parse_guide(args.guide)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(f"Created {args.out} with {len(package['practices'])} practices and {sum(len(item['objectives']) for item in package['practices'])} objectives")


if __name__ == "__main__":
    main()
