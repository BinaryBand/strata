# Site rules

This folder is published as a website on the tailnet. Every file here is served as-is, so anything you write here is public to every device on the tailnet. Follow these rules whenever you create or change a page.

## Layout

| Path | Contents |
| --- | --- |
| `template.html` | The one page template every page is filled from |
| `style.css` | The one stylesheet every page links to |
| `components.html` | Optional: a reference page showing each building block of a page body and its exact markup |
| `index.html` | The front page: the latest digest |
| `archive/index.html` | A list of every past digest, newest first, each linking to its day page |
| `archive/YYYY-MM-DD.html` | One page per day |
| `previous/` | Earlier versions of `template.html` and `style.css`, kept before each redesign |

## Building pages

- Build every page by filling `template.html`. Never write a page from scratch.
- If `template.html` or `style.css` does not exist yet, create them first, following the rules below, and then build the page.
- If `components.html` exists, build page bodies only from the components it shows, in the order it shows them, copying their markup.
- Before changing `template.html` or `style.css`, copy the current version into `previous/`.
- Link the stylesheet with a relative path, such as `style.css` from the front page or `../style.css` from the archive, so the site works under any address.
- Use only files in this folder, plus Google Fonts (`fonts.googleapis.com` and `fonts.gstatic.com`). Do not load images or anything else from other sites.
- When you publish a new day, write its day page, then update `index.html` to show it, then add it at the top of `archive/index.html`.

## Security line

The first element inside `<head>` of `template.html`, and so of every page, must be exactly:

```html
<meta http-equiv="Content-Security-Policy" content="script-src 'none'; object-src 'none'; base-uri 'none'">
```

It stops the browser from running any script on the page, including one hidden in a headline or summary copied from a feed. Never remove it, move it, or add a `<script>` element. The site needs no JavaScript.

## Look

- The site uses the paper's own name and masthead. Never use the name, logo or masthead lettering of a real newspaper.
- Headlines and summaries come from the feeds as plain text. Put them in the page as text, never as HTML.
