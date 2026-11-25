#!/usr/bin/env python3
"""Builds Maisy's link-in-bio pages from her public ShopMy shop.

  python3 tools/bio/build.py [out_dir]        (default: preview/bio)

Reads ShopMy (sections -> collections -> items), keeps a copy in tools/bio/shopmy.json, and writes
index.html plus one page per video or room. If ShopMy can't be read, it builds from the kept copy and
says so; it never writes an empty page. Names, codes and order live in tools/bio/bio.json.

Links: an item ShopMy earns on goes through ShopMy's own short link (go.shopmy.us/p-<id>), because its
commission link is made fresh for each tap. Items with Maisy's own programme link use that link as is.
Needs Python 3 and Pillow.
"""
import html, json, os, re, subprocess, sys, urllib.parse
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else 'preview/bio')
IMG = os.path.join(OUT, 'img')
CFG = json.load(open(os.path.join(HERE, 'bio.json')))
SNAP = os.path.join(HERE, 'shopmy.json')
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'
PHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
API = 'https://apiv3.shopmy.us/api'
e = html.escape
problems = []


def curl(url, out=None, ua=UA, origin=True):
    cmd = ['curl', '-s', '-L', '--max-time', '40', '-A', ua]
    if origin:
        cmd += ['-H', 'Origin: https://shopmy.us']
    if out:
        cmd += ['-o', out]
    r = subprocess.run(cmd + [url], capture_output=True)
    return r.stdout


def read_shop():
    """Every public collection with its items, or None if ShopMy can't be read."""
    try:
        cols = {}
        for sec in CFG['sections']:
            d = json.loads(curl(f"{API}/Shop/Collections?Curator_username={CFG['curator']}&Section_id={sec}&limit=100"))
            for c in d['collections']:
                if not c.get('private') and not c.get('isArchived') and c.get('total_num_pins'):
                    cols[str(c['id'])] = None
        for cid in cols:
            d = json.loads(curl(f'{API}/Collections/{cid}'))
            c = d.get('collection', d)
            c['pins'] = [p for p in c.get('pins') or [] if not p.get('isHidden')]
            cols[cid] = {k: c.get(k) for k in ('id', 'name', 'description', 'Section_id', 'image', 'custom_image', 'social_image', 'social_links')}
            cols[cid]['pins'] = [slim(p) for p in c['pins']]
        if len(cols) < 3 or sum(len(c['pins']) for c in cols.values()) < 10:
            raise ValueError('ShopMy answered with almost nothing')
        json.dump(cols, open(SNAP, 'w'), indent=1, ensure_ascii=False)
        return cols
    except Exception as ex:  # noqa: BLE001 - any failure means: use the kept copy
        problems.append(f'ShopMy could not be read ({ex}); built from the copy kept in tools/bio/shopmy.json.')
        return json.load(open(SNAP)) if os.path.exists(SNAP) else None


def slim(p):
    """What we keep of an item. ShopMy's own commission links change on every read, so only 'earns' is kept of them."""
    aff = p.get('affiliate_link') or ''
    earns = bool(p.get('click_token')) or '<custom_id>' in aff or 'shopmy.us' in aff
    out = {k: p.get(k) for k in ('id', 'title', 'image', 'link', 'domain')}
    out['earns'] = earns
    out['affiliate_link'] = None if earns else aff
    return out


def cdn(u):
    u = u or ''
    if u.startswith('//'):
        u = 'https:' + u
    return u.replace('production-shopmyshelf-uploads.s3.us-east-2.amazonaws.com/', 'static.shopmy.us/uploads/') \
        .replace('production-shopmyshelf-uploads.s3-us-east-2.amazonaws.com/', 'static.shopmy.us/uploads/') \
        .replace('production-shopmyshelf-pins.s3.us-east-2.amazonaws.com/', 'static.shopmy.us/pins/')


def trim(im, least=.04):
    """Cut plain white bands some photos carry at the edges. A product on a white backdrop is left alone."""
    if is_cutout(im):
        return im
    g = im.convert('L').point(lambda v: 0 if v > 244 else 255)
    box = g.getbbox()
    if not box:
        return im
    w, h = im.size
    l, t, r, b = box
    if (r - l) < w * .5 or (b - t) < h * .5:  # a small cut-out on white: keep the white, it is the backdrop
        return im
    return im.crop(box) if (l > w * least or t > h * least or r < w * (1 - least) or b < h * (1 - least)) else im


def is_cutout(im):
    """True when the picture is a product on a white backdrop (so it sits on a paper card)."""
    s = im.convert('RGB').resize((40, 40))
    edge = [s.getpixel((x, y)) for x in range(40) for y in (0, 1, 38, 39)] + [s.getpixel((x, y)) for y in range(40) for x in (0, 1, 38, 39)]
    return sum(1 for r, g, b in edge if min(r, g, b) > 238) / len(edge) > .85


def picture(url, name, size=700, square=False, ua=UA, cover=False):
    """Download once, save a small jpg. Returns (file name, is cut-out) or (None, False)."""
    dst = os.path.join(IMG, name + '.jpg')
    if not (os.path.exists(dst) and os.path.getsize(dst) > 1500):
        raw = dst + '.raw'
        curl(url, raw, ua=ua, origin=False)
        try:
            im = Image.open(raw)
            im = im.convert('RGBA')
            bg = Image.new('RGBA', im.size, 'white')
            im = Image.alpha_composite(bg, im).convert('RGB')
            box = CFG.get('crops', {}).get(name)
            if box:  # a badge or band a brand's own photo carries
                im = im.crop((int(box[0] * im.width), int(box[1] * im.height), int(box[2] * im.width), int(box[3] * im.height)))
            if square:
                im = trim(im)
            if cover:
                im = trim(im, .004)
            im.thumbnail((size, size * 2))
            im.save(dst, quality=82)
        except Exception:  # noqa: BLE001
            problems.append(f'A picture could not be read: {name} ({url[:70]})')
            return None, False
        finally:
            if os.path.exists(raw):
                os.remove(raw)
    return f'img/{name}.jpg', (is_cutout(Image.open(dst)) if square else False)


def own_photo(key):
    src = os.path.join(HERE, 'photos', key + '.jpg')
    dst = os.path.join(IMG, 'own-' + key + '.jpg')
    if os.path.exists(src):
        if not os.path.exists(dst):
            Image.open(src).convert('RGB').save(dst, quality=84)
        return f'img/own-{key}.jpg'
    return None


DOMAINS = {'amazon.com': 'Amazon', 'ikea.com': 'IKEA', 'lumens.com': 'Lumens', 'the-qi.com': 'The Qi', 'crateandbarrel.com': 'Crate & Barrel',
           'fromourplace.com': 'Our Place', 'fromourplace.ca': 'Our Place', 'selfridges.com': 'Our Place', 'littleking.online': 'Hasami Porcelain',
           'kansodesigns.co': 'Kanso', 'stickietech.com': 'StickieTech', 'moft.com': 'MOFT', 'orbitkey.com': 'Orbitkey', 'kbdfans.com': 'KBDfans',
           'soltech.com': 'Soltech', 'sundays-company.com': 'Sundays', 'philips-hue.com': 'Philips Hue', 'makerworld.com': 'MakerWorld',
           'cozyleigh.studio': 'Cozyleigh', 'gantri.sjv.io': 'Gantri', 'bestbuycreators.7tiv.net': 'Best Buy', 'howl.link': '', 'awin1.com': '', 'tidd.ly': ''}


def short(text, n=24):
    text = re.sub(r'\s+', ' ', text).strip(' -|,')
    if len(text) <= n:
        return text
    cut = text[:n + 1].rsplit(' ', 1)[0]
    return cut.rstrip(' ,-&(')


def name_of(pin):
    """(label, brand, code, studio, own photo key) for an item."""
    title = pin.get('title') or ''
    low = title.lower()
    for r in CFG['names']:
        if r['match'] in low:
            return r['label'], r['brand'], r.get('code'), bool(r.get('studio')), r.get('photo')
    brand = DOMAINS.get((pin.get('domain') or '').replace('www.', ''), '')
    if '\n' in title:  # IKEA style: "NAME\nWhat it is, details"
        first, rest = title.split('\n', 1)
        return short(rest.split(',')[0].capitalize()), 'IKEA ' + first.title() if brand == 'IKEA' else first.title(), None, False, None
    if '|' in title:
        b, rest = title.split('|', 1)
        return short(rest), b.strip().title(), None, False, None
    if ' - ' in title[:22]:
        b, rest = title.split(' - ', 1)
        return short(rest), b.strip().title(), None, False, None
    return short(re.sub(r'\(.*?\)', '', title)), brand, None, pin.get('domain') == 'cozyleigh.studio', None


def link_of(pin, slug):
    link, aff = pin.get('link') or '', pin.get('affiliate_link') or ''
    if 'cozyleigh.studio' in link:
        u = urllib.parse.urlsplit(link)
        q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not k.startswith('utm_')]
        q += [('utm_source', 'maisyleigh.com'), ('utm_medium', 'bio'), ('utm_campaign', slug)]
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), u.fragment))
    if pin.get('earns') or pin.get('click_token') or '<custom_id>' in aff or 'shopmy.us' in aff:
        return f"https://go.shopmy.us/p-{pin['id']}"  # ShopMy earns on it: let ShopMy make the tap's link
    return aff or link


DATES = os.path.join(HERE, 'dates.json')
B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def posted(kind, code, dates):
    """The day a video went up, 'YYYY-MM-DD', or '' if it can't be told. Kept in dates.json once known."""
    if code in dates:
        return dates[code]
    day = ''
    try:
        if kind == 'reel':  # an Instagram post's code holds the moment it was posted
            n = 0
            for ch in code:
                n = n * 64 + B64.index(ch)
            import datetime
            day = datetime.datetime.fromtimestamp(((n >> 23) + 1314220021721) / 1000, datetime.timezone.utc).strftime('%Y-%m-%d')
        else:
            page = curl('https://www.youtube.com/watch?v=' + code, origin=False).decode('utf8', 'ignore')
            m = re.search(r'"(?:publishDate|datePublished|uploadDate)"(?: content)?[:=]\s*"(\d{4}-\d\d-\d\d)', page) or re.search(r'itemprop="datePublished" content="(\d{4}-\d\d-\d\d)', page)
            day = m.group(1) if m else ''
    except Exception:  # noqa: BLE001
        day = ''
    if day:
        dates[code] = day
    else:
        problems.append(f'The post date of {code} could not be read; it is shown last until it can.')
    return day


def slugify(t):
    return re.sub(r'[^a-z0-9]+', '-', t.lower().replace('é', 'e').replace('&', 'and')).strip('-')


def tiles(pins, slug, seen=None):
    """Tile html for a list of items, one tile per different thing."""
    seen = set() if seen is None else seen
    out = []
    for p in pins:
        label, brand, code, studio, photo = name_of(p)
        key = (label, brand)
        if key in seen:
            continue
        seen.add(key)
        src = own_photo(photo) if photo else None
        cut = False
        if not src:
            src, cut = picture(cdn(p.get('image')), f"p{p['id']}", square=True)
        if not src:
            continue
        out.append((studio, f'<a class="t{" cut" if cut else ""}" href="{e(link_of(p, slug))}" rel="noopener"><span class="ph"><img src="{src}" width="700" height="700" alt="{e(label)}: {e(brand)}" loading="lazy"></span>'
                            f'<b>{e(label)}</b><span>{e(brand)}</span>{f"<i>Code {e(code)}</i>" if code else ""}</a>'))
    return out


HEAD = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>%s · Maisy Leigh</title><meta name="description" content="%s">
<link rel="icon" href="../../img/icon.png"><link rel="stylesheet" href="https://use.typekit.net/ikz6twe.css"><link rel="stylesheet" href="bio.css"></head><body>%s<main>'''
BAR = '''<header class="hd"><div class="wrap hd-in"><a class="wm" href="index.html">Maisy Leigh</a><a class="more" href="https://cozyleigh.studio/?utm_source=maisyleigh.com&amp;utm_medium=bio&amp;utm_campaign=header">Shop Cozyleigh</a></div></header>'''
SOCIALS = '''<li><a href="https://www.youtube.com/@maisyleigh" aria-label="YouTube"><svg viewBox="0 0 24 24"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8zM9.6 15.6V8.4l6.3 3.6-6.3 3.6z"/></svg></a></li><li><a href="https://www.instagram.com/maisyleigh/" aria-label="Instagram"><svg viewBox="0 0 24 24"><path d="M12 2.2c3.2 0 3.6 0 4.8.1 3.3.1 4.8 1.7 4.9 4.9.1 1.3.1 1.6.1 4.8s0 3.6-.1 4.8c-.1 3.2-1.7 4.8-4.9 4.9-1.3.1-1.6.1-4.8.1s-3.6 0-4.8-.1c-3.3-.1-4.8-1.7-4.9-4.9C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.8C2.4 3.9 3.9 2.4 7.2 2.3 8.4 2.2 8.8 2.2 12 2.2zM12 0C8.7 0 8.3 0 7.1.1 2.7.3.3 2.7.1 7.1 0 8.3 0 8.7 0 12s0 3.7.1 4.9c.2 4.4 2.6 6.8 7 7 1.2.1 1.6.1 4.9.1s3.7 0 4.9-.1c4.4-.2 6.8-2.6 7-7 .1-1.2.1-1.6.1-4.9s0-3.7-.1-4.9c-.2-4.4-2.6-6.8-7-7C15.7 0 15.3 0 12 0zm0 5.8a6.2 6.2 0 1 0 0 12.4 6.2 6.2 0 0 0 0-12.4zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.4-11.8a1.4 1.4 0 1 0 0 2.9 1.4 1.4 0 0 0 0-2.9z"/></svg></a></li><li><a href="https://www.tiktok.com/@maisyleighs" aria-label="TikTok"><svg viewBox="0 0 24 24"><path d="M19.6 6.7a4.8 4.8 0 0 1-3.8-4.2V2h-3.4v13.7a2.9 2.9 0 1 1-2-2.8V9.4a6.3 6.3 0 1 0 5.4 6.3V8.7a8.2 8.2 0 0 0 4.8 1.5V6.8l-1-.1z"/></svg></a></li><li><a href="https://x.com/maisyleigh_" aria-label="X"><svg viewBox="0 0 24 24"><path d="M18.2 2.3h3.4l-7.4 8.4 8.7 11.5h-6.8l-5.3-7-6.1 7H1.3l7.9-9L.9 2.3h7l4.8 6.4 5.5-6.4zm-1.2 17.9h1.9L7 4.2H5z"/></svg></a></li>'''
# The bio page opens like the old link page (links.html), but as @maisyleigh is positioned (Nov 24 2026): Maisy the designer,
# at her own desk, in her own words. Family and studio stories belong to @cozyleigh.studios, so no studio group photo here.
PROFILE = '''<div class="cover"><img src="img/cover-maisy-desk.jpg" width="1400" height="788" alt="Maisy at her desk in the morning light"></div>
<section class="band b-top profile"><div class="wrap"><img class="avatar" src="img/profile-maisy.jpg" width="400" height="400" alt="Maisy Leigh">
<h1 class="name">Maisy Leigh</h1><p class="line">making life warm again, one design at a time</p><p class="role">designer &amp; founder of <a href="https://www.instagram.com/cozyleigh.studios/">@cozyleigh.studios</a></p>
<ul class="soc">'''+SOCIALS+'''</ul>
<a class="btn shop" href="https://cozyleigh.studio/?utm_source=maisyleigh.com&amp;utm_medium=bio&amp;utm_campaign=profile">Shop Cozyleigh Studios</a>
<p class="note">Tap a video to see what&rsquo;s in it. Some links earn me a small commission.</p></div></section>'''
FOOT = '''</main><footer class="ft"><div class="wrap"><small>&copy; 2026 Maisy Leigh</small></div></footer>%s</body></html>'''
COPY_JS = '''<script>document.querySelectorAll('.code').forEach(function(b){b.addEventListener('click',function(){var c=b.dataset.code,t=b.querySelector('em');
function done(){t.textContent='Copied';setTimeout(function(){t.textContent=c},1600)}
if(navigator.clipboard){navigator.clipboard.writeText(c).then(done,function(){})}})});</script>'''
DISCLOSE = 'Some links earn me a small commission, at no cost to you.'


def reel_tile(v):
    rel = '' if v['list'] else ' rel="noopener"'
    return f'<a href="{e(v["href"])}"{rel}><img src="{v["cover"]}" alt="Reel: {e(v["title"][:80])}"></a>'


def band(cls, title, body):
    h = f'<h2 class="sub">{e(title)}</h2>' if title else ''
    return f'<section class="band {cls}"><div class="wrap">{h}{body}</div></section>'


def grid(items, cls='g3'):
    return f'<div class="{cls}">' + ''.join(items) + '</div>'


def main():
    os.makedirs(IMG, exist_ok=True)
    shop = read_shop()
    if not shop:
        sys.exit('ShopMy could not be read and there is no kept copy. Nothing was written.')

    # which collections are videos, and where each page lives
    videos = []
    dates = json.load(open(DATES)) if os.path.exists(DATES) else {}
    for cid in [str(i) for i in CFG['video_order']] + [c for c in shop if int(c) not in CFG['video_order']]:
        c, v = shop.get(cid), CFG['videos'].get(cid, {})
        if not c or v.get('hide') or not c['pins']:
            continue
        url = c.get('social_links') or (f"https://www.instagram.com/reel/{v['reel']}/" if v.get('reel') else '')
        m_reel = re.search(r'instagram\.com/(?:reel|p)/([\w-]+)', url)
        m_yt = re.search(r'(?:v=|youtu\.be/)([\w-]{11})', url)
        if not (m_reel or m_yt):
            continue
        title = v.get('title') or short(re.sub(r'[^\w\s&,\'’-]', '', re.split(r' — | ☁', c['name'])[0]), 30)
        if m_reel:
            cover, _ = picture(f'https://www.instagram.com/p/{m_reel.group(1)}/media/?size=l', 'r_' + m_reel.group(1), size=540, ua=PHONE)
        else:
            cover, _ = picture(f'https://i.ytimg.com/vi/{m_yt.group(1)}/maxresdefault.jpg', 'y_' + m_yt.group(1), size=800, cover=True)
            if not cover:
                cover, _ = picture(f'https://i.ytimg.com/vi/{m_yt.group(1)}/hqdefault.jpg', 'y_' + m_yt.group(1), size=800, cover=True)
        if not cover:
            continue
        videos.append({'cid': cid, 'kind': 'reel' if m_reel else 'yt', 'title': title, 'url': url, 'cover': cover, 'slug': slugify(title), 'note': v.get('note'),
                       'when': posted('reel' if m_reel else 'yt', (m_reel or m_yt).group(1), dates)})
        for code in v.get('more_reels', []):  # another reel of the same things: its own cover, the same page
            extra, _ = picture(f'https://www.instagram.com/p/{code}/media/?size=l', 'r_' + code, size=540, ua=PHONE)
            if extra:
                videos.append({**videos[-1], 'cover': extra, 'twin': True, 'when': posted('reel', code, dates)})
    json.dump(dates, open(DATES, 'w'), indent=1, sort_keys=True)
    videos.sort(key=lambda v: v['when'], reverse=True)  # newest first; python keeps ShopMy's order between equals
    rooms = [{'cid': str(r['collection']), 'title': r['title'], 'slug': slugify(r['title']), 'cover': r.get('cover')} for r in CFG['rooms'] if shop.get(str(r['collection']))]
    video_slug = {v['cid']: v['slug'] for v in videos}
    notes = []

    def whole_rows(items, per, what):
        extra = len(items) % per
        if extra and len(items) > per:
            notes.append(f'{what}: {extra} left off so the last row is full ({len(items)} in all).')
            return items[:len(items) - extra]
        return items

    # one page per video and per room
    pages = {}
    for v in [v for v in videos if not v.get('twin')]:
        ts = tiles(shop[v['cid']]['pins'], v['slug'])
        ordered = [t for s, t in ts if s] + [t for s, t in ts if not s]
        watch = 'Watch the reel' if v['kind'] == 'reel' else 'Watch on YouTube'
        top = (f'<a class="back" href="index.html">All my videos</a><div class="vh {v["kind"]}"><img src="{v["cover"]}" alt="{e(v["title"])}"><div><h1 class="lead">{e(v["title"])}</h1>'
               + (f'<p class="note">{e(v["note"])}</p>' if v.get('note') else '') + f'<a class="more" href="{e(v["url"])}" rel="noopener">{watch}</a></div></div>')
        body = band('b-top', None, top) + band('b-green', 'In this video', grid(ordered) + f'<p class="note">{DISCLOSE}</p><a class="btn" href="index.html">See my whole desk</a>')
        pages[v['slug']] = (v['title'], body)
    for r in rooms:
        if r['cid'] in video_slug:
            r['slug'] = video_slug[r['cid']]
            continue
        ts = tiles(shop[r['cid']]['pins'], r['slug'])
        top = f'<a class="back" href="index.html">My desk and videos</a><h1 class="lead">{e(r["title"])}</h1>'
        body = band('b-top', None, top) + band('b-peach', None, grid([t for _, t in ts]) + f'<p class="note">{DISCLOSE}</p><a class="btn" href="index.html">See my whole desk</a>')
        pages[r['slug']] = (r['title'], body)

    # the bio page
    # The reel row is the profile itself: the latest reels in feed order, so it matches what people just scrolled.
    # A reel opens its "what's in it" page when a ShopMy list belongs to it, otherwise the reel on Instagram.
    feed_path = os.path.join(HERE, 'feed.json')
    feed = [p for p in (json.load(open(feed_path))['posts'] if os.path.exists(feed_path) else []) if p.get('type') == 'reel' and p.get('code')]
    page_of = {v['url'].rstrip('/').rsplit('/', 1)[-1]: v for v in videos if v['kind'] == 'reel'}
    for code, cid in CFG.get('reel_lists', {}).items():
        page_of[code] = next((v for v in videos if v['cid'] == str(cid)), page_of.get(code))
    reels = []
    for p in feed[:CFG.get('reels_shown', 9)]:
        cover, _ = picture(f"https://www.instagram.com/p/{p['code']}/media/?size=l", 'r_' + p['code'], size=540, ua=PHONE)
        if not cover:
            continue
        v = page_of.get(p['code'])
        reels.append({'cover': cover, 'title': v['title'] if v else p.get('caption', ''), 'href': f"{v['slug']}.html" if v else f"https://www.instagram.com/reel/{p['code']}/", 'list': bool(v)})
    if not feed:
        problems.append('tools/bio/feed.json is missing, so the reel row is empty.')
    yts = [v for v in videos if v['kind'] == 'yt']
    reels, yts = whole_rows(reels, 3, 'Reels'), whole_rows(yts, 6, 'YouTube videos')
    every = {str(p['id']): p for c in shop.values() for p in c['pins']}
    desk_pins = shop[str(CFG['desk_collection'])]['pins'] + [every[str(i)] for i in CFG.get('desk_extra', []) if str(i) in every]
    desk = tiles(desk_pins, 'bio')
    studio, rest = [t for s, t in desk if s], [t for s, t in desk if not s]
    studio, rest = whole_rows(studio, 3, 'Studio pieces'), whole_rows(rest, 3, 'Rest of the desk')
    room_tiles = []
    for r in rooms:
        pins = shop[r['cid']]['pins']
        first = next((p for p in pins if p['id'] == r.get('cover')), pins[0])
        src, cut = picture(cdn(first.get('image')), f"p{first['id']}", square=True)
        n = len({name_of(p)[:2] for p in pins})
        room_tiles.append(f'<a class="t{" cut" if cut else ""}" href="{r["slug"]}.html"><span class="ph"><img src="{src}" width="700" height="700" alt="{e(r["title"])}" loading="lazy"></span><b>{e(r["title"])}</b><span>{n} things</span></a>')
    codes = ''.join(f'<button class="code" type="button" data-code="{e(c["code"])}"><span><b>{e(c["name"])}</b><small>{e(c["offer"])}</small></span><em>{e(c["code"])}</em></button>' for c in CFG['codes'])
    body = band('b-paper', 'From my reels', grid([reel_tile(v) for v in reels], 'g3 v'))
    body += band('b-paper tight', 'From YouTube', grid([f'<a class="t" href="{v["slug"]}.html"><img src="{v["cover"]}" alt="Video: {e(v["title"])}" loading="lazy"><b>{e(v["title"])}</b></a>' for v in yts], 'g2'))
    body += band('b-green', 'On my desk, made in our studio', grid(studio))
    body += band('b-peach', 'The rest of my desk', grid(rest) + '<h2 class="sub more-sub">More of my things</h2>' + grid(room_tiles))
    body += band('b-coral', 'My codes', f'<div class="codes">{codes}</div><p class="note">Tap a code to copy it.</p>')
    pages['index'] = ('Links', body)

    for slug, (title, body) in pages.items():
        open(os.path.join(OUT, slug + '.html'), 'w').write(HEAD % (e(title), 'Everything on my desk and in my videos, with links.', PROFILE if slug == 'index' else BAR) + body + FOOT % (COPY_JS if slug == 'index' else ''))
    print(f'Wrote {len(pages)} pages to {OUT}: {len(reels)} reels, {len(yts)} YouTube videos, {len(studio)} studio pieces, {len(rest)} other things, {len(rooms)} rooms.')
    for n in notes:
        print('NOTE:', n)
    for p in problems:
        print('PROBLEM:', p)
    sys.exit(3 if problems else 0)  # 3 = pages written, but something could not be read


if __name__ == '__main__':
    main()
