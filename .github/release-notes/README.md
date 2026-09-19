# Release notes

One file per release, named `v<X.Y.Z>.md`, holding the reviewed **Overview** and
**Highlights** for that version.

`release.yaml`'s `create-release` job passes the matching file to
`softprops/action-gh-release` as `body_path`, which **pre-pends** it to GitHub's
auto-generated notes. So the file contains the human summary only — do **not**
add a "Generated changelog" section, the action appends the PR list itself.

A missing file is not an error: the release then publishes with generated notes
alone, exactly as it did before this was wired up. Preparing notes is therefore
optional, but it is the only way to get an overview onto the release without
editing it by hand afterwards.

These live outside `docs/` on purpose. VitePress builds every `.md` under `docs/`
into a deployed page, and these are not site content.

## Format

```markdown
## Overview

One or two paragraphs describing the release as a coherent change.

## Highlights

**Area**

- Grouped by user-visible outcome or operational impact.
```

Write the file in the PR that prepares the release, so the notes get reviewed
along with the code, then tag.
