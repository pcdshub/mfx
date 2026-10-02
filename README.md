# mfx

Repository for MFX specific code.

# MFX Docs Guide

The documentation is available on [github pages](https://pcdshub.github.io/mfx/) and a mirror is served from [S3DF pages](https://s3df.slac.stanford.edu/data/lcls/mfx/).

For those with access to the MFX repo, you are welcome to contribute to the documentation and the main steps are outlined below.

> **Note:** This repo's GitHub Pages site is built exclusively by the `MkDocs Build`
> workflow (`.github/workflows/build_versioned_mkdocs.yml`), which runs
> `mkdocs gh-deploy` on every push to the `documentation` branch. GitHub Pages
> **must** be configured under repo *Settings → Pages → Build and deployment →
> Source* to **"GitHub Actions"**, not "Deploy from a branch". If Pages source is
> set to a branch instead, GitHub's legacy `pages-build-deployment` Jekyll workflow
> auto-triggers on the same push and races the MkDocs deploy, intermittently
> clobbering the Material theme site with a raw Jekyll-rendered `README.md`. A
> `.nojekyll` file is kept at the repo root as a safety net to disable Jekyll
> processing even if the Pages source setting is accidentally left on "branch".

### Installing MkDocs
Install [MkDocs](https://www.mkdocs.org/) on your local machine. This is not strictly necessary, however MkDocs has a built-in html server means you can update and debug the documentation fast and easy locally. Then when everything looks good you can push your changes to the repo.

You will need to install:
- [MkDocs](https://www.mkdocs.org/)
- [MkDocs-material](https://squidfunk.github.io/mkdocs-material/getting-started/) which is the theme used by the MFX documentation page.
- [mkdocstrings](https://mkdocstrings.github.io/)), which converts python docstrings to nice documentation.
```BASH
pip install mkdocs
pip install mkdocs-material
pip install mkdocstrings
pip install mkdocstrings[python]
```
### Clone the MFX Repo
Clone the `documentation` branch of the [MFX repo](https://github.com/pcdshub/mfx/tree/documentation)
- Note: This branch was created from run23 originally. For future versions, the docs can be based off of another branch (or branches), as needed.
```BASH
git clone -b documentation https://github.com/pcdshub/mfx.git
```
### MkDocs Basics
 Here we will review the basics to get started but check out the [Getting Started with MkDocs](https://www.mkdocs.org/getting-started/) guide for their quick intro on creating a project from scratch and the [User Guide](https://www.mkdocs.org/user-guide/) for more details. MkDocs uses [markdown](https://www.markdownguide.org/) which is a simple markup language. See the [cheat sheet here](https://www.markdownguide.org/cheat-sheet/) .
#### Configuration
MkDocs requires a single YAML configuration file `mkdocs.yml` and a directory `docs` containing the markdown files.

The configuration file contains information like site name, favicon usages, navigation structure and plugin/theme configuration. Navigation and other large blocks for configuration follow the syntax of markdown lists.

Two generator scripts in `scripts/` automate most of this instead of hand-editing:
- `scripts/generate_mkdocs.py` — scans all `.py` files, creates/removes the per-module
  `.md` stub files in `docs/` (each just containing `::: module.path` for
  `mkdocstrings`), and regenerates the `nav:` tree + full `mkdocs.yml` config.
- `scripts/generate_code_summary.py` — parses all `.py` files with `ast` and
  writes `docs/code_summary.md` plus a styled `docs/user_cheat_sheet.pdf`
  (requires `pip install markdown weasyprint`).

#### Editting Documentation
There are two types of documentation: (1) documentation automatically created by `mkdocstrings` from the source code and (2) written docs.
- For source code documentation, a markdown file is needed in the `docs` directory that points to the location of the source code in the repo. This is used by `mkdocstrings` to generate the documentation. For example, `docs/attenuator_scan.md` contains `::: mfx.attenuator_scan` which points to `attenuator_scan.py` module in the `mfx` directory.
- For written docs, simply place the markdown files in the documentation directory.

Be sure to update the navigation tree in `mkdocs.yml` when you create/add any new documentation (or just re-run `scripts/generate_mkdocs.py`, which rebuilds the nav automatically).

To view the documentation, to start the html server run the serve command from MFX repo root directory (where `mkdocs.yml` is located).
``` BASH
mkdocs serve
```
Open  http://127.0.0.1:8000/ in your browser and you should see the MFX docs homepage. As you edit `mkdocs.yml` or files in the `docs` directory, the server should automatically load and build the changes in your browser.

Once your satisfied with the documents, you can push the changes to the MFX `documentation` branch. The build process is trigger when changes are pushed to the `documentation branch` so you should be able to see them after a few minutes.

### Typical workflow

```BASH
git checkout documentation
python scripts/generate_mkdocs.py          # regen stub .md files + mkdocs.yml nav
python scripts/generate_code_summary.py    # regen code_summary.md + PDF cheat sheet
mkdocs serve                               # preview at http://127.0.0.1:8000/
# review, then:
git add -A
git commit -m "..."
git push origin documentation               # triggers CI -> gh-deploy -> GitHub Pages
```
</content>
