"""Build a planning repo for CI's `action-smoke` job [T-F08-13].

    python3 tests/chain/action_fixture.py DIR --fault|--fixed

Builds the clean fixture project (`fixtures.clean_project`) at `DIR/plans`, with real
git history, and prints that path. `DIR` must be inside the system's temporary folder
(set `TMPDIR` to put it elsewhere) and must not already contain `plans`.

    --fault   `roles.frd` lists only `bob`, so the FRD's approval by `alice` is one
              `approver-not-listed` error.
    --fixed   the same project with `alice` listed, so there are no errors.

Both have one `warn-event` warning, from the log's `warn` line.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import GATES, PlanRepo, clean_project  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build a planning repo for the action-smoke job.")
    parser.add_argument("dir", help="folder to build in; the repo is DIR/plans")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fault", action="store_true", help="one approval by a name not under roles.frd")
    mode.add_argument("--fixed", action="store_true", help="the same project with no errors")
    args = parser.parse_args(argv)

    roles = {gate: ["alice"] for gate in GATES}
    if args.fault:
        roles["frd"] = ["bob"]
    repo = clean_project(PlanRepo(args.dir, roles=roles))
    print(repo.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
