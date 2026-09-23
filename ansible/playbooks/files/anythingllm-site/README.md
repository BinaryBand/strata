# Site rules

This folder is published as a website on the tailnet. Every file here is served as-is, so anything you write here is public to every device on the tailnet. Follow these rules whenever you create or change a page.

## Layout

The site root holds only this `README.md` and `index.html`, the list of publications. Never write anything else at the root.

Every publication lives in its own folder, named in lowercase with dashes, such as `news/` for the daily paper or `trip-report/` for a one-off page. When you add a publication, add a link to its folder to the root `index.html`, copying the markup of the existing entries.

A publication folder contains:

| Path | Contents |
| --- | --- |
| `template.html` | The one page template every page of the publication is filled from |
| `style.css` | The one stylesheet every page of the publication links to |
| `components.html` | Optional: a reference page showing each building block of a page body and its exact markup |
| `index.html` | The publication's front page |
| `archive/index.html` | Optional: a list of every past edition, newest first, each linking to its page |
| `archive/YYYY-MM-DD.html` | Optional: one page per edition |
| `previous/` | Earlier versions of `template.html` and `style.css`, kept before each redesign |

## Building pages

- Build every page by filling its publication's `template.html`. Never write a page from scratch.
- If the publication has no `template.html` or `style.css` yet, create them first, following the rules below, and then build the page.
- If `components.html` exists, build page bodies only from the components it shows, in the order it shows them, copying their markup.
- Before changing `template.html` or `style.css`, copy the current version into the publication's `previous/`.
- Link the stylesheet with a relative path, such as `style.css` from the publication's front page or `../style.css` from its archive, so the site works under any address.
- Use only files in this folder, plus Google Fonts (`fonts.googleapis.com` and `fonts.gstatic.com`). Do not load images or anything else from other sites.
- When you publish a new edition, write its page in `archive/`, then update the publication's `index.html` to show it, then add it at the top of `archive/index.html`.

## Security line

The first element inside `<head>` of every `template.html`, and so of every page, must be exactly:

```html
<meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'; base-uri 'none'">
```

It stops the browser from running any script on the page, including one hidden in a headline or summary copied from a feed. Never remove it, move it, or add a `<script>` element. The site needs no JavaScript.

## Look

- A publication uses its own name and masthead. Never use the name, logo or masthead lettering of a real newspaper.
- Headlines and summaries come from the feeds as plain text. Put them in the page as text, never as HTML.
