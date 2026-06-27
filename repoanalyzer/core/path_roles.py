from __future__ import annotations

from pathlib import PurePosixPath

VENDOR_SEGMENTS = {"vendor", "vendors", "third_party", "third-party", "external", "extern", "deps", "dependencies"}
GENERATED_SEGMENTS = {"generated", "gen", "autogen", "auto_generated", "build", "out"}
TEST_SEGMENTS = {"test", "tests", "unittest", "unit_test", "gtest", "spec", "specs"}


def path_role(path: str) -> str:
    """Classify a repo-relative path for large-repo diagnostics.

    This is intentionally heuristic and non-authoritative. It is used for
    diagnostics and warnings only; ingest inclusion/exclusion remains governed by
    explicit exclude_patterns.
    """
    parts = {part.lower() for part in PurePosixPath(path).parts}
    if parts & VENDOR_SEGMENTS:
        return "vendor"
    if parts & GENERATED_SEGMENTS:
        return "generated"
    if parts & TEST_SEGMENTS:
        return "test"
    return "project"
