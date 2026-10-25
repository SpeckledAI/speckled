# lint-chain GitHub Action

Runs `lint-chain` on a Speckled planning repo in CI. It checks the repo's documents, approvals and history, fails the job if there are errors, and writes the report to the job summary.

It's a composite action: no Docker image, so it runs on Linux and macOS runners using the runner's own `python3` (3.9 or later). It needs no token and makes no API calls.

## Usage

In the planning repo, add `.github/workflows/lint-chain.yml`:

```yaml
name: lint-chain

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  lint-chain:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # history checks need the full history
      - uses: SpeckledAI/speckled/actions/lint-chain@v0.4.0
        with:
          path: .                 # the planning repo's folder (default .)
          strict: "false"         # "true" to fail on warnings too
```

### Full history: `fetch-depth: 0`

`actions/checkout` fetches a single commit by default. `lint-chain` reads the repo's history to check that approvals are only ever added, that approvers were listed when they approved, and that approved documents aren't changed without a new review. One commit isn't enough history for those checks, and a clean result from it would be misleading. So, in a shallow clone, `lint-chain` reports a `history-unavailable` **error** and the job fails. Set `fetch-depth: 0`.

The action never fetches more history itself, because `lint-chain` doesn't change the repository.

### Permissions

The action only reads the checked-out files. Give the workflow `permissions: contents: read` and nothing more. It needs no `GITHUB_TOKEN` and no secrets.

### Pinning

Pin the action to a release tag, such as `@v0.4.0`. Releases are tagged `vX.Y.Z` from 0.4.0 on. There's no moving major-version tag, so update the tag when you want a newer release. To pin exactly, use the tag's commit SHA.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `path` | `.` | The planning repo's folder (the one with `speckled.yaml`), relative to the workspace. |
| `strict` | `"false"` | `"true"` counts warnings as errors, so any finding fails the job. |

## Outputs

| Output | Meaning |
|---|---|
| `errors` | Number of errors. |
| `warnings` | Number of warnings. |
| `report` | Path to the JSON report, in `$RUNNER_TEMP`. Upload it with `actions/upload-artifact` to keep it. |

If `lint-chain` couldn't run (exit code `2`), there's no report and the outputs are empty. The reason is in the job summary.

## Exit codes

The step exits with `lint-chain`'s exit code:

| Code | Meaning |
|---|---|
| `0` | No errors. Warnings don't fail the job unless `strict` is `"true"`. |
| `1` | At least one error, or with `strict`, any finding. |
| `2` | Couldn't run: no `speckled.yaml`, an unreadable configuration, or a git failure. |

Run `lint-chain --explain <rule>` locally to see what a rule means and how to fix it.
