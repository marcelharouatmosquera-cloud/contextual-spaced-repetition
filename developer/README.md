# Development

Users install the `.ankiaddon` from GitHub Releases. These scripts are for working on the source checkout.

- `build_addon.bat`: run tests, the review smoke test, and packaging from Windows.
- `sync_to_anki.bat`: developer installation helper; inspect its paths before use. It is not part of normal installation or updates.
- `capture_examples.py`: run with Anki's Python environment to render actual settings widgets against a temporary example collection. It also writes `dist/docs-preview/review.html` using the production review renderer. Serve that directory locally and capture the question and revealed answer in a browser. Example progress is illustrative. Never capture personal decks or other add-ons for the README.

From the repository root:

```sh
python -m unittest discover -s tests
python scripts/smoke_review_loop.py
python scripts/package_addon.py
```

See [the release checklist](../docs/RELEASE_CHECKLIST.md). Restart Anki after changing Python modules; automated tests do not replace a live Anki smoke test. Keep published tags immutable and use a new patch version for fixes.
