# Verified CMMC catalog package

The development database contains a count-complete seed only. It must not be used as an assessment baseline. A verified baseline is imported as a JSON package accompanied by the exact official PDF from which it was transcribed.

## Source

Use the DoD CIO [CMMC Assessment Guide - Level 2, Version 2.13](https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL2v2.pdf). The guide identifies the objectives as authoritative and associates the 110 Level 2 requirements with 320 objectives. Record the SHA-256 of the exact PDF acquired by your organization in the package manifest.

## Package shape

```json
{
  "manifest": {
    "framework": "CMMC",
    "level": 2,
    "version": "2.13",
    "source_url": "https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL2v2.pdf",
    "source_sha256": "<SHA-256 of the approved local PDF>"
  },
  "domains": [{"code": "AC", "name": "Access Control"}],
  "practices": [{
    "domain": "AC",
    "identifier": "AC.L2-3.1.1",
    "title": "AUTHORIZED ACCESS CONTROL",
    "statement": "<approved requirement statement>",
    "objectives": [{"identifier": "AC.L2-3.1.1[a]", "statement": "<approved objective statement>"}]
  }]
}
```

The importer rejects packages unless they contain exactly 14 domains, 110 unique practices, and 320 unique objectives, and it refuses the import if the supplied source PDF hash differs from the manifest.

## Import

Run from `backend` after a reviewer has prepared and peer-reviewed the package:

```powershell
$env:PYTHONPATH = (Resolve-Path '.').Path
py -3.13 -m app.catalog_import ..\frameworks\cmmc-l2-v2.13.json --guide ..\source\AssessmentGuideL2v2.pdf --imported-by "Name of reviewer"
```

The importer will not overwrite an existing framework version. It stores a new, source-validated baseline alongside historical assessment data, so evidence created against an earlier catalog is never altered. Treat a framework update as a new versioned baseline and preserve the older baseline for assessment traceability.
