"""Supabase identifies migrations by version, not by their descriptive names.
Reject collisions in either edition before the CLI can skip a required change.
"""

from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DIRS = [
    path for path in (
        ROOT / "infra/supabase/migrations",
        ROOT / "oss/overrides/infra/supabase/migrations",
    ) if path.is_dir()
]


@pytest.mark.parametrize("directory", MIGRATION_DIRS, ids=lambda path: str(path.relative_to(ROOT)))
def test_migration_versions_are_unique(directory):
    versions = defaultdict(list)
    for path in directory.glob("*.sql"):
        versions[path.name.split("_", 1)[0]].append(path.name)
    duplicates = {version: names for version, names in versions.items() if len(names) > 1}
    assert not duplicates, f"Supabase migration versions collide: {duplicates}"
