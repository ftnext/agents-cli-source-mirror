# agents-cli source mirror (unofficial)

This is an **unofficial** source mirror of [`google-agents-cli`](https://pypi.org/project/google-agents-cli/) maintained by an individual. It is **not affiliated with, endorsed by, or sponsored by Google**.

## Purpose

The official PyPI distribution ships only as a pre-built wheel, and the [google/agents-cli](https://github.com/google/agents-cli) repository does not contain the CLI implementation source. As discussed in [google/agents-cli#10](https://github.com/google/agents-cli/issues/10), this makes auditing and reviewing dependency / source changes across releases inconvenient.

This repository is an interim workaround: the contents of each released wheel are extracted and committed as-is, one git tag per upstream release, so that diffs between versions can be inspected with standard git tooling. It will be archived once an official source distribution becomes available.

## How it is built

For each upstream release:

1. Download the wheel from PyPI.
2. Verify the SHA256 against the digest published on PyPI.
3. Extract the wheel.
4. Commit the contents to this repository, overwriting the previous version.
5. Tag the commit `vX.Y.Z`.

Steps 1–3 and the file replacement portion of step 4 are automated by `scripts/import-wheel.sh`:

```sh
./scripts/import-wheel.sh X.Y.Z
```

The script then prints the suggested `git commit` (with provenance) and `git tag vX.Y.Z` commands to run.

Layout in this repository:

- `google/` — the Python package as shipped in the wheel.
- `LICENSE`, `METADATA`, `RECORD`, `WHEEL`, `entry_points.txt` — metadata files extracted from `google_agents_cli-X.Y.Z.dist-info/`, flattened to the repo root so they overwrite cleanly between versions.

The provenance (source URL and SHA256) of each release is recorded in the corresponding commit message.

## No modifications

Files are committed verbatim from the wheel:

- Per-file Apache 2.0 license headers are preserved.
- The `LICENSE` file from the wheel is preserved.
- No source code edits, formatting changes, or additions are made to the imported files.

## License

The mirrored contents are distributed under the Apache License 2.0; see [`LICENSE`](./LICENSE). The original copyright belongs to Google LLC.

## Please do **not** file issues or pull requests here

If you have feedback, bug reports, or contributions for `google-agents-cli` itself, please direct them to the upstream project:

- **Upstream repository**: https://github.com/google/agents-cli
- **PyPI**: https://pypi.org/project/google-agents-cli/

This mirror exists solely to make the released source readable. No development or support happens here.
