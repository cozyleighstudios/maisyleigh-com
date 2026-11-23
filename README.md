# maisyleigh.com

Maisy Leigh's personal site: the home page (`index.html`) and the link page (`links.html`, served at `/links`).
Plain HTML, hosted on GitHub Pages. Fonts come from Adobe Fonts kit `ikz6twe` (the same kit as cozyleigh.studio);
the domain must be on that kit's list or the pages fall back to Georgia / Futura.

Every number and quote on the page was checked against its source on Nov 14 2026 (YouTube, cozyleigh.studio,
Instagram via the studio server, CanvasRebel). Update the numbers by checking them again, never by guessing.
Never link Grovemade. Never mention Maisy's mom in the copy.

## Link in bio (`preview/bio/`, not live yet)

Maisy's desk and video links, built from her public ShopMy shop by `python3 tools/bio/build.py` (Python 3 + Pillow).
She keeps editing in ShopMy: a collection with a reel or YouTube link becomes a video page. What ShopMy doesn't hold
(short names like "My chair", codes, which reel belongs to a collection, photo fixes) lives in `tools/bio/bio.json`,
and our own photos of studio pieces in `tools/bio/photos/`.

- The ShopMy read is not an official ShopMy feature. Each run keeps a copy in `tools/bio/shopmy.json`; if ShopMy can't
  be read the pages are built from that copy and the script says so and exits 3. It never writes an empty page.
- Items ShopMy earns on link through `go.shopmy.us/p-<item id>`, because ShopMy makes that commission link fresh for
  each tap. Items with Maisy's own programme link use it as is. Cozyleigh links carry `utm_source=maisyleigh.com`,
  `utm_medium=bio`, `utm_campaign=<page>`.
- Colours are the three in the Cozyleigh logo (peach `#FEDBAE`, coral `#EF886E`, green `#AEBE6C`), as grainy gradients.
- `.github/workflows/bio-nightly.yml` runs the script every night at 08:30 UTC (and from the Actions tab, "Run workflow") and commits
  what changed to `main`. A run that couldn't read ShopMy or a picture ends red, so GitHub emails the repo's owners.
  Instagram often refuses GitHub's servers, so a brand-new reel's cover may need one run of the script on a laptop.
