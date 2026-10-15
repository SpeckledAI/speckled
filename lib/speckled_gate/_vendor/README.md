# Bundled third-party code

The plugin has no install step, so the one library it needs is bundled here.

## PyYAML 6.0.3

- **Source:** https://pypi.org/project/PyYAML/6.0.3/
- **sdist:** `pyyaml-6.0.3.tar.gz`, SHA-256 `d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f`
- **Licence:** MIT, see `yaml/LICENSE` (also credited in the repository's `NOTICE`)
- **What's here:** every file from the sdist's `lib/yaml/`, **unmodified**, except `cyaml.py`. That file is the optional C binding and the only one with an absolute import (`yaml._yaml`). Without it, PyYAML's own `__init__.py` falls back to pure Python.
- **How it's used:** only through `speckled_gate.yamlio`, which loads files safely (no Python objects are built from YAML) and reads `yes`/`no`/`on`/`off` and dates as text.

`MANIFEST.sha256` lists the SHA-256 of every bundled file. `tests/gate/test_yamlio.py` checks it, so any change to these files fails the tests.

## Updating

1. Download the new sdist into an empty scratch folder and check its SHA-256 against PyPI.
2. Replace `yaml/*.py` with the sdist's `lib/yaml/*.py`, leaving out `cyaml.py`, and replace `yaml/LICENSE`.
3. Regenerate the manifest from this folder:
   `find . -type f ! -name MANIFEST.sha256 ! -name README.md ! -path '*/__pycache__/*' | sort | xargs shasum -a 256 > MANIFEST.sha256`
4. Update the version and hash in this file, then run `python3 -m unittest discover tests` on Python 3.9 and the latest Python 3.
