"""Every .feature file is either bound to step definitions or marked @wip.

The Gherkin files under features/ are the user-story map for the `strata`
CLI, and they are written well ahead of their step definitions on purpose --
the suite is built one gated slice at a time. That is fine; what is not fine
is that an unbound feature is indistinguishable from a bound one. It sits in
the same directory, is listed in the same README journey spine, and is
collected by the same `testpaths`, so it reads as covered while executing
nothing.

features/README.md already declares the convention that says otherwise --
`@wip` for "no step def yet" -- it just had no teeth and no file used it.
This gate gives it teeth: a feature is either bound by a `scenarios(...)`
call or it carries `@wip`, and the moment step definitions land the `@wip`
tag has to come off (an unbound-but-tagged file that *is* bound is reported
as a stale tag, the same way KNOWN_GAPS entries are).
"""

from __future__ import annotations

import re
from pathlib import Path

FEATURES_DIR = Path(__file__).resolve().parents[1] / "features"

_SCENARIOS_RE = re.compile(r'scenarios\(\s*"([^"]+\.feature)"')
_WIP_TAG = "@wip"


def _bound_feature_names() -> set[str]:
    """Feature filenames named by a scenarios(...) call in features/test_*.py."""
    return {
        match.group(1)
        for module in FEATURES_DIR.glob("test_*.py")
        for match in _SCENARIOS_RE.finditer(module.read_text())
    }


def _is_wip(feature: Path) -> bool:
    """Report whether the feature carries a file-level @wip tag.

    Gherkin puts a feature's tags on the lines immediately above `Feature:`,
    so only the preamble counts -- a @wip on a single Scenario says something
    narrower and must not exempt the whole file.
    """
    for line in feature.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("Feature:"):
            return False
        if _WIP_TAG in stripped.split():
            return True
    return False


def test_every_feature_is_bound_or_marked_wip() -> None:
    bound = _bound_feature_names()
    unmarked = sorted(
        feature.name
        for feature in FEATURES_DIR.glob("*.feature")
        if feature.name not in bound and not _is_wip(feature)
    )
    assert not unmarked, (
        f"These .feature files have no scenarios(...) binding and no @wip tag, "
        f"so they read as coverage while executing nothing: {unmarked}. Either "
        f'write features/test_<name>.py with scenarios("<name>.feature"), or '
        f"add {_WIP_TAG} above the Feature: line to declare it pending."
    )


def test_no_bound_feature_is_still_marked_wip() -> None:
    bound = _bound_feature_names()
    stale = sorted(
        feature.name
        for feature in FEATURES_DIR.glob("*.feature")
        if feature.name in bound and _is_wip(feature)
    )
    assert not stale, (
        f"These .feature files have step definitions but are still tagged "
        f"{_WIP_TAG}: {stale}. Remove the tag -- it now understates the coverage."
    )


def test_every_scenarios_call_names_a_feature_that_exists() -> None:
    """A typo'd filename makes pytest-bdd bind nothing, silently."""
    present = {feature.name for feature in FEATURES_DIR.glob("*.feature")}
    missing = sorted(_bound_feature_names() - present)
    assert not missing, f"scenarios(...) names .feature files that do not exist: {missing}"
