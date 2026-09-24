# Site content format

This folder is the source of the website. You never write HTML: you write small data files, and a builder turns them into pages within a few seconds of each save. After saving, read `BUILD.md` in this folder: it says whether the build published and lists every file it skipped, with the reason. Fix a skipped file and save it again.

## The Daily Seek

One folder per edition, `news/editions/YYYY-MM-DD/`. Write the stories first and `edition.toml` last: an edition is built only once `edition.toml` exists, so readers never see half of one. To redo an edition that already exists, first move its folder into `news/previous/` (for example as `news/previous/2026-09-25-first-try/`), then write the new one: mixing old and new story files would leave two leads.

### Stories: `news/editions/YYYY-MM-DD/NN-slug.toml`

`NN` is two digits and `slug` is lowercase letters, digits and dashes, for example `01-america.toml`. Write one file per region, each holding that region's stories as `[[story]]` tables; a file of up to 16 KB holds about fifteen stories:

```toml
[[story]]
headline = "Trump gives Xi a rare airport welcome as a state visit begins"
region = "America"
lead = true
rank = 1
summary = "One sentence, based only on the feed text."
sources = [
  { name = "NPR", url = "https://www.npr.org/..." },
  { name = "BBC", url = "https://www.bbc.co.uk/..." },
]

[[story]]
headline = "The next story in the same region"
region = "America"
lead = false
rank = 4
summary = "One sentence."
sources = [{ name = "AP", url = "https://apnews.com/..." }]
```

One invalid story skips its whole file, and `BUILD.md` names the story by its position in the file.

| Field | Rule |
| --- | --- |
| `headline` | Plain text, up to 300 characters, in English |
| `region` | Exactly one of `America`, `Europe & Sweden`, `World` |
| `lead` | `true` for exactly one story per edition, `false` for the rest |
| `rank` | 1 for the most significant; the order within each region follows it |
| `summary` | Plain text, up to 1000 characters |
| `sources` | 1 to 10 sources, each an outlet `name` and an `http(s)` `url`; the headline links to the first |

### The edition: `news/editions/YYYY-MM-DD/edition.toml`

```toml
date = "2026-09-25"
feeds_total = 11
feed_errors = []
briefs = ["One short line per item considered but not chosen."]
```

`date` must equal the folder's name. `feed_errors` lists each failed feed as the news tool reported it, such as `"svt.se (timed out)"`. `briefs` is optional.

Text is plain text everywhere: write `<` and `&` as they are, never as HTML. The builder escapes everything, and there is no way to add markup.

### Look

`news/style.css` is the paper's stylesheet. Before changing it, copy the current version into `news/previous/`. Every page uses the same class names, so a change applies site-wide.

## Other publications

A publication is a folder of its own, such as `trip-report/`, holding:

- `publication.toml` with `title = "..."` and an optional `description = "..."`;
- one page per file, `slug.md`, starting with a header and followed by Markdown:

```markdown
+++
title = "Day one"
description = "Optional, one line."
+++
Plain Markdown: *emphasis*, lists, headings and [links](https://example.com).
```

Pages may not contain raw HTML, `{{`, `{%` or `{#`, and links and images may only use `http`, `https` or `mailto` (or a relative path). The site's list of publications is built automatically. The names `news`, `archive` and `previous` are reserved.
