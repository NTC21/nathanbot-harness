# Wiki Schema

Contract for how wiki pages are written. Keeps pages consistent so agents and humans can
both navigate the graph.

## Page frontmatter
Every page in `pages/` starts with:

```yaml
---
title: <human title>
type: entity | project | strategy | person | reference | decision
status: active | dormant | archived
updated: YYYY-MM-DD
---
```

## Body structure
1. **One-line definition** — what this is, in a sentence.
2. **Current state** — what's true right now (the part that goes stale; keep it honest).
3. **Detail** — background, decisions, history.
4. **Links** — `[[other-page]]` wikilinks to related pages. Link generously; the graph is the value.

## Naming
- Filenames: `kebab-case.md`, no dates in the name.
- One concept per page. If a page covers two things, split it.
- `owner.md` is the central self page — most pages should link back to it or to `index`.

## Rules
- **Every page must link to at least one other page.** Orphan pages don't show up in the graph
  and get forgotten.
- Update `status:` and `updated:` when reality changes. A page claiming `active` for something
  dead is worse than no page.
- Facts live in exactly one page; others link to it rather than restating.
- Add each new page to `index.md` and log it in `log.md`.
