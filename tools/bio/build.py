#!/usr/bin/env python3
"""Builds Maisy's link-in-bio pages from her public ShopMy shop.

  python3 tools/bio/build.py [out_dir]        (default: links, served at maisyleigh.com/links/)

Reads ShopMy (sections -> collections -> items), keeps a copy in tools/bio/shopmy.json, and writes
index.html plus one page per video or room. If ShopMy can't be read, it builds from the kept copy and
says so; it never writes an empty page. Names, codes and order live in tools/bio/bio.json.

Links: an item ShopMy earns on goes through ShopMy's own short link (go.shopmy.us/p-<id>), because its
commission link is made fresh for each tap. Items with Maisy's own programme link use that link as is.
Needs Python 3 and Pillow.
"""
import html, json, os, re, subprocess, sys, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else 'links')
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


def whiten(im):
    """Make a product photo's plain backdrop white, so on the page's sand card it blends away (multiply).
    Only when the four corners agree (a plain backdrop); a photo of a room is left as it is."""
    w, h = im.size
    corners = [im.getpixel(xy) for xy in ((3, 3), (w - 4, 3), (3, h - 4), (w - 4, h - 4))]
    if max(max(c[i] for c in corners) - min(c[i] for c in corners) for i in range(3)) > 60:
        return im
    bg = [sorted(c[i] for c in corners)[2] for i in range(3)]
    return Image.merge('RGB', [ch.point(lambda v, b=b: min(255, int(v * 255 / max(b, 1)))) for ch, b in zip(im.split(), bg)])


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
                im = whiten(trim(im))
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
            whiten(Image.open(src).convert('RGB')).save(dst, quality=84)
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


def pill(code):
    """The code in the photo's top corner, so every row keeps the same height (Maisy, Nov 25 2026). Read out as "Code …"."""
    return f'<i aria-label="Code {e(code)}">{e(code)}</i>' if code else ''


def name_of(pin):
    """(label, brand, code, studio, own photo key) for an item."""
    title = pin.get('title') or ''
    low = title.lower()
    for r in CFG['names']:
        if r['match'] in low:
            code = r.get('code') if r.get('code_until', '9999') >= today_ny() else None  # a dated code leaves after its day
            return r['label'], r['brand'], code, bool(r.get('studio')), r.get('photo')
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
        q += [('utm_source', 'maisyleigh.com'), ('utm_medium', 'bio'), ('utm_campaign', slug), ('utm_content', slug)]
        return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), u.fragment))
    if pin.get('earns') or pin.get('click_token') or '<custom_id>' in aff or 'shopmy.us' in aff:
        return f"https://go.shopmy.us/p-{pin['id']}"  # ShopMy earns on it: let ShopMy make the tap's link
    return aff or link


DATES = os.path.join(HERE, 'dates.json')
B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'



def live_codes():
    """Codes still running today (New York). A code with "until" (YYYY-MM-DD) leaves the page on the nightly
    rebuild after that day, so a sale never stays up after it ends."""
    return [c for c in CFG['codes'] if not c.get('until') or c['until'] >= today_ny()]


def offer_of(c):
    """A standing code can carry a dated sale line ("sale" until "sale_until"); after that day its usual offer shows."""
    return c['sale'] if c.get('sale') and c.get('sale_until', '0000') >= today_ny() else c['offer']


def code_row(c):
    """A code copies on tap; a sale with no code (Black Friday, Nov 26 2026) opens the shop through Maisy's own link."""
    text = f'<span><b>{e(c["name"])}</b><small>{e(offer_of(c))}</small></span>'
    if c.get('code'):
        return f'<button class="code" type="button" data-code="{e(c["code"])}">{text}<em>{e(c["code"])}</em></button>'
    return f'<a class="code" href="{e(c["link"])}" rel="noopener">{text}<em>Shop</em></a>'


def today_ny():
    """Today in New York, or BIO_TODAY=YYYY-MM-DD to check what a given day's build would show."""
    return os.environ.get('BIO_TODAY') or datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d')


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
    hide = CFG.get('hide_links', [])
    for p in pins:
        if any(h in (p.get('link') or '') + (p.get('affiliate_link') or '') for h in hide):
            continue  # a dead, out-of-stock or wrong-country link (bio.json hide_links)
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
        out.append((studio, f'<a class="t{" cut" if cut else ""}" href="{e(link_of(p, slug))}" rel="noopener"><span class="ph"><img src="{src}" width="700" height="700" alt="{e(label)}: {e(brand)}" loading="lazy">{pill(code)}</span>'
                            f'<b>{e(label)}</b><span>{e(brand)}</span></a>'))
    return out


HEAD = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%s · Maisy Leigh</title><meta name="description" content="%s">
<link rel="canonical" href="https://maisyleigh.com/links/"><meta property="og:type" content="profile"><meta property="og:url" content="https://maisyleigh.com/links/">
<meta property="og:title" content="Maisy Leigh: links"><meta property="og:description" content="My desk, my codes and sales, my videos.">
<meta property="og:image" content="https://maisyleigh.com/links/img/cover-maisy-desk.jpg"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="../img/icon.png"><link rel="apple-touch-icon" href="../img/icon.png"><link rel="stylesheet" href="https://use.typekit.net/ikz6twe.css"><link rel="stylesheet" href="bio.css"></head><body>%s<main>'''
BAR = '''<header class="hd"><div class="wrap hd-in"><a class="wm" href="index.html">Maisy Leigh</a><a class="more" href="https://cozyleigh.studio/?utm_source=maisyleigh.com&amp;utm_medium=bio&amp;utm_campaign=header&amp;utm_content=header">Shop Cozyleigh</a></div></header>'''
SOCIALS = '''<li><a href="https://www.youtube.com/@maisyleigh" aria-label="YouTube"><svg viewBox="0 0 24 24"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2 31 31 0 0 0 0 12a31 31 0 0 0 .5 5.8 3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1A31 31 0 0 0 24 12a31 31 0 0 0-.5-5.8zM9.6 15.6V8.4l6.3 3.6-6.3 3.6z"/></svg></a></li><li><a href="https://www.instagram.com/maisyleigh/" aria-label="Instagram"><svg viewBox="0 0 24 24"><path d="M12 2.2c3.2 0 3.6 0 4.8.1 3.3.1 4.8 1.7 4.9 4.9.1 1.3.1 1.6.1 4.8s0 3.6-.1 4.8c-.1 3.2-1.7 4.8-4.9 4.9-1.3.1-1.6.1-4.8.1s-3.6 0-4.8-.1c-3.3-.1-4.8-1.7-4.9-4.9C2.2 15.6 2.2 15.2 2.2 12s0-3.6.1-4.8C2.4 3.9 3.9 2.4 7.2 2.3 8.4 2.2 8.8 2.2 12 2.2zM12 0C8.7 0 8.3 0 7.1.1 2.7.3.3 2.7.1 7.1 0 8.3 0 8.7 0 12s0 3.7.1 4.9c.2 4.4 2.6 6.8 7 7 1.2.1 1.6.1 4.9.1s3.7 0 4.9-.1c4.4-.2 6.8-2.6 7-7 .1-1.2.1-1.6.1-4.9s0-3.7-.1-4.9c-.2-4.4-2.6-6.8-7-7C15.7 0 15.3 0 12 0zm0 5.8a6.2 6.2 0 1 0 0 12.4 6.2 6.2 0 0 0 0-12.4zM12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm6.4-11.8a1.4 1.4 0 1 0 0 2.9 1.4 1.4 0 0 0 0-2.9z"/></svg></a></li><li><a href="https://www.tiktok.com/@maisyleighs" aria-label="TikTok"><svg viewBox="0 0 24 24"><path d="M19.6 6.7a4.8 4.8 0 0 1-3.8-4.2V2h-3.4v13.7a2.9 2.9 0 1 1-2-2.8V9.4a6.3 6.3 0 1 0 5.4 6.3V8.7a8.2 8.2 0 0 0 4.8 1.5V6.8l-1-.1z"/></svg></a></li><li><a href="https://x.com/maisyleigh_" aria-label="X"><svg viewBox="0 0 24 24"><path d="M18.2 2.3h3.4l-7.4 8.4 8.7 11.5h-6.8l-5.3-7-6.1 7H1.3l7.9-9L.9 2.3h7l4.8 6.4 5.5-6.4zm-1.2 17.9h1.9L7 4.2H5z"/></svg></a></li>'''
# The bio page (maisyleigh.com/links/, Nov 26 2026) opens like the old link page (links.html), but as @maisyleigh is positioned (Nov 24 2026): Maisy the designer,
# at her own desk, in her own words. Family and studio stories belong to @cozyleigh.studios, so no studio group photo here.
PROFILE = '''<header class="profile"><div class="wrap">
<div class="cover"><img src="img/cover-maisy-desk.jpg" width="1400" height="788" alt="Maisy at her desk in the morning light"></div>
<img class="avatar" src="img/profile-maisy.jpg" width="400" height="400" alt="Maisy Leigh">
<h1 class="name">Maisy Leigh</h1>
<p class="line">making life warm again, one design at a time</p>
<p class="role">designer &amp; founder of <a href="https://www.instagram.com/cozyleigh.studios/">@cozyleigh.studios</a></p>
<div class="actions"><ul class="soc">'''+SOCIALS+'''</ul>
<a class="shop" href="https://cozyleigh.studio/?utm_source=maisyleigh.com&amp;utm_medium=bio&amp;utm_campaign=profile&amp;utm_content=profile">Shop Cozyleigh</a></div>%STUDIO_NOW%
</div></header>'''
FOOT = '''</main><footer class="ft"><div class="wrap"><p>Some links earn me a small commission, at no cost to you.</p><small>&copy; 2026 Maisy Leigh</small></div></footer>%s</body></html>'''
COPY_JS = '''<script>document.querySelectorAll('button.code').forEach(function(b){b.addEventListener('click',function(){var c=b.dataset.code,t=b.querySelector('em');
function done(){t.textContent='Copied';setTimeout(function(){t.textContent=c},1600)}
if(navigator.clipboard){navigator.clipboard.writeText(c).then(done,function(){})}})});</script>'''
# Counts what people open and tap (Maisy, Nov 26 2026), sent to the studio server through the shop's app proxy.
# One request per open and per tap; no cookies, no storage, no ids. A failed count never blocks a tap.
TAP_JS = '''<script>(function(){var U='https://cozyleigh.studio/apps/engagement/bio-tap?';
function send(k,s,n){try{var q=new URLSearchParams({k:k});if(s)q.set('s',s);if(n)q.set('n',String(n).trim().slice(0,60));var u=U+q;
if(window.fetch){fetch(u,{mode:'no-cors',keepalive:true,credentials:'omit'}).catch(function(){})}else{new Image().src=u}}catch(e){}}
function txt(el,sel){var b=el.querySelector(sel);return b?b.textContent:''}
send('view');
document.addEventListener('click',function(ev){try{var el=ev.target.closest('a,button');if(!el)return;var sec=el.closest('section');var sid=sec&&sec.id;
if(el.matches('.soc a'))return send('social','profile',(el.getAttribute('aria-label')||'').split(',')[0]);
if(el.matches('.shop'))return send('shop','profile');
if(el.matches('button.code'))return send('code','codes',el.dataset.code);
if(el.matches('.yt'))return send('video','watch');
if(el.matches('.post'))return send('letter','watch');
if(el.closest('.studio-now'))return send('thing','profile',txt(el,'b'));
if(el.matches('a.code'))return send('thing',sid||'codes',txt(el,'b'));
if(el.matches('.t'))return send('thing',sid,txt(el,'b'));}catch(e){}},true);})();</script>'''
# A DM's counted link lands here as ?utm_medium=dm&utm_campaign=<post code> (Maisy, Nov 26 2026: keep each post's sales
# on the post). Its post code then becomes utm_campaign on every cozyleigh.studio link; utm_content keeps the section.
# Affiliate links are left alone.
DM_JS = '''<script>(function(){try{var p=new URLSearchParams(location.search),c=p.get('utm_campaign');
if(p.get('utm_medium')!=='dm'||!c)return;c=c.slice(0,80);
document.querySelectorAll('a[href*="cozyleigh.studio"]').forEach(function(a){try{var u=new URL(a.href);
if(!/(^|\\.)cozyleigh\\.studio$/.test(u.hostname))return;u.searchParams.set('utm_campaign',c);a.href=u.toString()}catch(e){}})}catch(e){}})();</script>'''
DISCLOSE = 'Some links earn me a small commission, at no cost to you.'


FEED_URL = 'https://cozyleigh.studio/apps/engagement/bio-reels'


def read_feed():
    """@maisyleigh's profile reels, newest first, from the studio server (it syncs Instagram hourly; trial reels and
    archived posts left out). A copy is kept in feed.json; if the server can't be read, the copy is used and the run
    says so. Reels in bio.json "hide_reels" are left out."""
    path = os.path.join(HERE, 'feed.json')
    kept = json.load(open(path)) if os.path.exists(path) else {'posts': []}
    try:
        d = json.loads(curl(FEED_URL, origin=False))
        posts = [{'code': r['code'], 'date': r['date'], 'type': 'reel', 'caption': r.get('caption', '')} for r in d['reels'] if r.get('code')]
        if not posts:
            raise ValueError('the feed came back empty')
        kept = {'_about': 'Your Instagram profile reels, newest first, from the studio server (' + FEED_URL + ').', 'read': d.get('read', ''), 'posts': posts}
        json.dump(kept, open(path, 'w'), indent=1, ensure_ascii=False)
    except Exception as ex:  # noqa: BLE001 - keep the last good copy
        problems.append(f'The studio server\'s reel feed could not be read ({ex}); the reel row uses the copy from {kept.get("read") or "before"}.')
    hide = set(CFG.get('hide_reels', []))
    return [p for p in kept['posts'] if p.get('type', 'reel') == 'reel' and p.get('code') and p['code'] not in hide]


CHANNELS = os.path.join(HERE, 'channels.json')
YT_CHANNEL = 'UC_h-Jl4Zxb7p-sSBTxprs4Q'


def count_of(text):
    """'773K' / '1.2M' / '577300' -> a whole number, or None."""
    m = re.fullmatch(r'([\d.,]+)\s*([KM]?)', (text or '').strip(), re.I)
    if not m:
        return None
    n = float(m.group(1).replace(',', '')) * {'': 1, 'K': 1e3, 'M': 1e6}[m.group(2).upper()]
    return int(n) if n > 0 else None


def short_count(n):
    """577300 -> '577K', 1234000 -> '1.2M', the way the apps show it."""
    if n >= 1_000_000:
        return f'{n / 1e6:.1f}'.rstrip('0').rstrip('.') + 'M'
    if n >= 1000:
        return f'{n // 1000}K'
    return str(n)


def read_channels():
    """Follower counts under the channel icons and the newest long YouTube video (Maisy, Nov 26 2026). Read fresh each
    night: YouTube and TikTok from their public pages, Instagram from the studio server's feed (Instagram refuses GitHub).
    The last good copy is kept in channels.json; a failed read keeps the last number and says so, and a count is never 0."""
    kept = json.load(open(CHANNELS)) if os.path.exists(CHANNELS) else {}
    counts = dict(kept.get('counts', {}))
    yt = curl('https://www.youtube.com/@maisyleigh', origin=False).decode('utf8', 'ignore')
    m = re.search(r'"([\d.,]+[KM]?) subscribers"', yt) or re.search(r'([\d.,]+[KM]?) subscribers', yt)
    tt = curl('https://www.tiktok.com/@maisyleighs', origin=False).decode('utf8', 'ignore')
    t = re.search(r'"followerCount":(\d+)', tt)
    try:
        feed = json.loads(curl(FEED_URL, origin=False))
    except Exception:  # noqa: BLE001
        feed = {}
    fresh = {'youtube': count_of(m.group(1)) if m else None, 'tiktok': int(t.group(1)) if t and int(t.group(1)) > 0 else None,
             'instagram': ((feed or {}).get('followers') or {}).get('instagram') or None}
    for k, v in fresh.items():
        if v:
            counts[k] = int(v)
        else:
            problems.append(f'The {k} follower count could not be read; the page keeps {short_count(counts[k]) if counts.get(k) else "no number"}.')
    video = newest_long_video() or kept.get('video')
    letter = newest_letter()
    if letter is None:
        letter = kept.get('letter')
        problems.append('The blog feed could not be read; Watch & read keeps the letter it had.')
    if not video:
        problems.append('No long YouTube video could be found, so Watch & read shows only its links.')
    kept = {'_about': 'Follower counts under the channel icons and the newest long YouTube video on the bio page, kept from the last good read.',
            'read': today_ny(), 'counts': counts, 'video': video, 'letter': letter}
    json.dump(kept, open(CHANNELS, 'w'), indent=1, ensure_ascii=False)
    return counts, video, letter


BLOG_FEED = 'https://cozyleigh.studio/blogs/the-monthly-batch.atom'
GUIDE = re.compile(r'^(how to|what is|which|why does)\b|\bguide\b|\bcare for\b', re.I)


def newest_letter():
    """Maisy's newest letter from the studio (Maisy, Nov 26 2026: "include my blog posts"). Only her own letters:
    Ash's and Tristan's belong to @cozyleigh.studios, and how-to guides aren't letters. bio.json "skip_letters" leaves
    out a letter by its link's last part. Returns {} when the feed has none of hers, None when it can't be read."""
    try:
        feed = curl(BLOG_FEED, origin=False).decode('utf8', 'ignore')
        entries = re.findall(r'<entry>(.*?)</entry>', feed, re.S)
        if not entries:
            raise ValueError('no entries')
    except Exception:  # noqa: BLE001
        return None
    skip = set(CFG.get('skip_letters', []))
    best = {}
    for ent in entries:
        author = re.search(r'<author>\s*<name>(.*?)</name>', ent, re.S)
        title = html.unescape(re.search(r'<title>(.*?)</title>', ent, re.S).group(1).strip())
        link = re.search(r'<link[^>]*rel="alternate"[^>]*href="([^"]+)"', ent) or re.search(r'<link[^>]*href="([^"]+)"', ent)
        day = re.search(r'<published>(\d{4}-\d\d-\d\d)', ent)
        if not (author and link and day) or not author.group(1).strip().lower().startswith('maisy'):
            continue
        if GUIDE.search(title) or link.group(1).rstrip('/').rsplit('/', 1)[-1] in skip:
            continue
        if not best or day.group(1) > best['date']:
            summary = re.search(r'<summary[^>]*>(.*?)</summary>', ent, re.S)
            content = re.search(r'<content[^>]*>(.*?)</content>', ent, re.S)
            raw = lambda m: html.unescape(m.group(1).replace('<![CDATA[', '').replace(']]>', '')) if m else ''
            text = lambda m: re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', raw(m))).strip()
            body = raw(content)
            first_img = re.search(r'<img[^>]*src="([^"]+)"', body)
            best = {'title': title, 'link': link.group(1), 'date': day.group(1),
                    'summary': re.sub(r'\s*More$', '', text(summary)), 'words': len(text(content).split()),
                    'image': first_img.group(1) if first_img else ''}
    if best:  # the letter's own featured photo, the one its page shares
        page = curl(best['link'], origin=False).decode('utf8', 'ignore')
        og = re.search(r'property="og:image" content="([^"]+)"', page)
        if og:
            best['image'] = html.unescape(og.group(1))
    return best


def newest_long_video():
    """The newest upload that isn't a Short. The channel's feed mixes Shorts in; YouTube answers youtube.com/shorts/<id>
    with 200 only for a Short (a long video redirects to /watch)."""
    rss = curl(f'https://www.youtube.com/feeds/videos.xml?channel_id={YT_CHANNEL}', origin=False).decode('utf8', 'ignore')
    for vid, title in re.findall(r'<yt:videoId>([\w-]{11})</yt:videoId>\s*<yt:channelId>[^<]*</yt:channelId>\s*<title>([^<]*)</title>', rss):
        code = subprocess.run(['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '20', '-A', UA, f'https://www.youtube.com/shorts/{vid}'], capture_output=True).stdout.decode()
        if code == '200':
            continue
        if code not in ('301', '302', '303'):
            problems.append(f'Could not tell whether video {vid} is a Short (YouTube said {code or "nothing"}).')
            return None
        page = curl('https://www.youtube.com/watch?v=' + vid, origin=False).decode('utf8', 'ignore')
        secs = re.search(r'"lengthSeconds":"(\d+)"', page)
        views = re.search(r'"viewCount":"(\d+)"', page)
        day = re.search(r'"(?:publishDate|uploadDate)":"(\d{4}-\d\d-\d\d)', page)
        return {'id': vid, 'title': html.unescape(title), 'seconds': int(secs.group(1)) if secs else None,
                'views': int(views.group(1)) if views else None, 'date': day.group(1) if day else None}
    return None


def short_day(day):
    """'2026-11-26' -> 'Nov 26'."""
    d = datetime.strptime(day, '%Y-%m-%d')
    return f"{d.strftime('%b')} {d.day}"


def soc_counts(counts):
    """The channel icons with each one's follower count under it; X stays an icon."""
    soc = SOCIALS
    for label, key in (('YouTube', 'youtube'), ('Instagram', 'instagram'), ('TikTok', 'tiktok')):
        if counts.get(key):
            n = short_count(counts[key])
            start = soc.index(f'aria-label="{label}">')
            end = soc.index('</svg></a>', start) + len('</svg>')
            link = soc[start:end].replace(f'aria-label="{label}">', f'aria-label="{label}, {n} followers">')
            soc = soc[:start] + link + f'<span>{n}</span>' + soc[end:]
    return soc


def ago(day):
    """'2026-08-18' -> '3 months ago', the way YouTube says it."""
    days = (datetime.strptime(today_ny(), '%Y-%m-%d') - datetime.strptime(day, '%Y-%m-%d')).days
    for size, unit in ((365, 'year'), (30, 'month'), (7, 'week'), (1, 'day')):
        if days >= size:
            n = days // size
            return f'{n} {unit}{"s" if n > 1 else ""} ago'
    return 'today'


def clock(secs):
    """1222 -> '20:22', 3725 -> '1:02:05'."""
    h, m, sec = secs // 3600, secs % 3600 // 60, secs % 60
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def views_of(n):
    return (short_count(n) if n >= 1000 else str(n)) + (' view' if n == 1 else ' views')


def watch_section(video, letter=None):
    """Watch & read (Maisy, Nov 26 2026: "i want blog post to look more like a blog post. and i want yt video to look more
    like a yt video"): the newest long video laid out like YouTube (thumbnail, length, avatar, title, views, age), the newest
    letter like a blog post (photo, label, title, opening lines, byline, Keep reading), then all videos and interviews."""
    card = ''
    if video:
        pic, _ = picture(f'https://i.ytimg.com/vi/{video["id"]}/maxresdefault.jpg', 'yt-' + video['id'], size=1280)
        if not pic:
            pic, _ = picture(f'https://i.ytimg.com/vi/{video["id"]}/hqdefault.jpg', 'yt-' + video['id'], size=1280)
        if pic:
            title = re.sub(r'\s+', ' ', re.sub(r'\s*[^\w\s,.:;!?\'"&()\-–—|/]+\s*', ': ', video['title'])).strip(' :')
            meta = ' &middot; '.join(['Maisy Leigh'] + ([views_of(video['views'])] if video.get('views') else []) + ([ago(video['date'])] if video.get('date') else []))
            length = f'<i>{clock(video["seconds"])}</i>' if video.get('seconds') else ''
            card += (f'<a class="yt" href="https://www.youtube.com/watch?v={e(video["id"])}" rel="noopener"><span class="th"><img src="{pic}" width="1280" height="720" '
                     f'alt="Video: {e(title)}" loading="lazy">{length}</span><span class="yt-row"><img class="yt-av" src="img/profile-maisy.jpg" alt="">'
                     f'<span><b>{e(title)}</b><small>{meta}</small></span></span></a>')
    if letter and letter.get('image'):
        pic, _ = picture(letter['image'], 'letter-' + slugify(letter['title'])[:40], size=1000)
        if pic:
            tagged = letter['link'] + ('&' if '?' in letter['link'] else '?') + 'utm_source=maisyleigh.com&utm_medium=bio&utm_campaign=letter&utm_content=letter'
            read = f' &middot; {max(1, round(letter["words"] / 200))} min read' if letter.get('words') else ''
            opening = f'<p>{e(letter["summary"])}</p>' if letter.get('summary') else ''
            card += (f'<a class="post" href="{e(tagged)}" rel="noopener"><img src="{pic}" alt="{e(letter["title"])}" loading="lazy"><span class="kind">Letter from the studio</span>'
                     f'<b>{e(letter["title"])}</b>{opening}<span class="by"><img src="img/profile-maisy.jpg" alt="">Maisy Leigh &middot; {short_day(letter["date"])}{read}</span>'
                     f'<span class="more">Keep reading &rarr;</span></a>')
    rows = [{'name': 'All my videos', 'line': 'Slow living, the studio and how we make things', 'link': 'https://www.youtube.com/@maisyleigh/videos', 'pill': 'YouTube'}] + CFG.get('reads', [])
    items = ''.join(f'<li><a class="code" href="{e(r["link"])}" rel="noopener"><span><b>{e(r["name"])}</b><small>{e(r["line"])}</small></span><em>{e(r.get("pill", "Read"))}</em></a></li>' for r in rows)
    return (f'<section class="sec sand" id="watch"><div class="wrap"><div class="sec-hd"><h2>Watch &amp; read</h2><span>More of me</span></div>'
            f'{card}<ul class="codes{" reads" if card else ""}">{items}</ul></div></section>')
LOGO_URL = 'https://cozyleigh.studio/cdn/shop/files/Cozyleigh_Logo_Colored_300x.png'


def shop_button(profile):
    """The profile's Shop button with the Cozyleigh logo in it (Maisy, Nov 26 2026). The logo is kept in img/ as the
    shop's own PNG (transparent, so it sits on the pill's paper); if it can't be fetched the button keeps its words."""
    dst = os.path.join(IMG, 'cozyleigh-logo.png')
    if not (os.path.exists(dst) and os.path.getsize(dst) > 1000):
        curl(LOGO_URL, dst, origin=False)
        try:
            Image.open(dst).verify()
        except Exception:  # noqa: BLE001
            if os.path.exists(dst):
                os.remove(dst)
            problems.append('The Cozyleigh logo could not be read, so the Shop button says "Shop Cozyleigh" in words.')
            return profile
    return profile.replace('<a class="shop" href=', '<a class="shop shop--logo" aria-label="Shop Cozyleigh" href=').replace(
        '>Shop Cozyleigh</a>', '>Shop <img src="img/cozyleigh-logo.png" width="300" height="90" alt=""></a>')


def studio_now():
    """One dated studio row under the profile (Maisy, Nov 26 2026): the first bio.json "studio_now" entry live today in
    New York ("from"/"until", YYYY-MM-DD, both days included), in the codes' row style; nothing when none is live.
    An optional "image" (with "focus" as a CSS object-position and "alt") puts a photo on top, the whole card one link."""
    today = today_ny()
    for r in CFG.get('studio_now', []):
        if r.get('from', '0000') <= today <= r.get('until', '9999'):
            slug = r.get('key') or slugify(r['name'])
            u = urllib.parse.urlparse(r['link'])
            q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query) if not k.startswith('utm_')]
            q += [('utm_source', 'maisyleigh.com'), ('utm_medium', 'bio'), ('utm_campaign', 'profile'), ('utm_content', slug)]
            link = urllib.parse.urlunparse(u._replace(query=urllib.parse.urlencode(q)))
            pic = None
            if r.get('image'):  # a photo card on top of the row, like the Watch & read video (Maisy: "use the hero img")
                pic, _ = picture(r['image'], 'now-' + slug, size=1200)
            img = (f'<img src="{pic}" width="1200" height="675" alt="{e(r.get("alt", r["name"]))}" loading="lazy"'
                   + (f' style="object-position:{e(r["focus"])}"' if r.get('focus') else '') + '>') if pic else ''
            return (f'<ul class="codes studio-now{" has-pic" if pic else ""}"><li><a class="code" href="{e(link)}" rel="noopener">{img}<span><b>{e(r["name"])}</b>'
                    f'<small>{e(r["line"])}</small></span><em>Shop</em></a></li></ul>')
    return ''


def nice_day(day):
    import datetime
    try:
        d = datetime.date.fromisoformat(day)
        return f"{d.strftime('%b')} {d.day}, {d.year}"
    except ValueError:
        return day


def reel_tile(v):
    rel = '' if v['list'] else ' rel="noopener"'
    return f'<a href="{e(v["href"])}"{rel}><img src="{v["cover"]}" alt="Reel: {e(v["title"][:80])}"></a>'


def band(cls, title, body):
    h = f'<h2 class="sub">{e(title)}</h2>' if title else ''
    return f'<section class="band {cls}"><div class="wrap">{h}{body}</div></section>'


def grid(items, cls='g3'):
    return f'<div class="{cls}">' + ''.join(items) + '</div>'


def build_spaces(shop):
    """The page by space (Nov 25 2026): profile top, then 'What's on my desk', 'What's in my kitchen'... each a photo
    of the space and its things (our pieces first), then the codes. One page; nothing to set up per post."""
    import glob
    every_pin = {p['id']: p for col in shop.values() for p in col['pins']}
    sections = []
    for sp in CFG['spaces']:
        pins = [every_pin[i] for i in sp.get('lead', []) if i in every_pin]
        for cid in sp['lists']:
            pins += shop.get(str(cid), {}).get('pins', [])
        if not pins:
            problems.append(f"{sp['title']}: none of its ShopMy lists could be read, so it's left off.")
            continue
        slug = slugify(sp['title'].replace("'", ''))
        ts = tiles(pins, slug)
        lead_n = len([i for i in sp.get('lead', []) if i in every_pin])
        items = [t for _, t in ts[:lead_n]] + [t for s_, t in ts[lead_n:] if s_] + [t for s_, t in ts[lead_n:] if not s_]
        extra = len(items) % 3
        if extra and len(items) > 3:  # three across: never a lonely tile on the last row
            problems_note = f"{sp['title']}: the last {extra} in ShopMy's order left off so the last row is full ({len(items)} in all)."
            print('NOTE:', problems_note)
            items = items[:len(items) - extra]
        photo = own_photo(sp['photo']) if sp.get('photo') else None
        pic = f'<img class="space" src="{photo}" width="1500" height="1000" alt="{e(sp.get("alt", sp["title"]))}" loading="lazy">' if photo else ''
        sections.append(f'<section class="sec" id="{slug}"><div class="wrap"><div class="sec-hd"><h2>{e(sp["title"])}</h2><span>{len(items)} things</span></div>{pic}{grid(items)}</div></section>')
    if not sections:
        sys.exit('No space could be built. Nothing was written.')
    rows = live_codes()
    codes = ''.join(f'<li>{code_row(c)}</li>' for c in rows)
    sales = any(not c.get('code') for c in rows)  # a sale with no code is a link, so the heading says both
    head = '<h2>Codes &amp; sales</h2><span>Tap to copy or shop</span>' if sales else '<h2>My codes</h2><span>Tap to copy</span>'
    counts, video, letter = read_channels()
    body = ''.join(sections) + f'<section class="sec" id="codes"><div class="wrap"><div class="sec-hd">{head}</div><ul class="codes">{codes}</ul></div></section>'
    body += watch_section(video, letter)
    for old in glob.glob(os.path.join(OUT, '*.html')):
        os.remove(old)  # the per-post pages are gone; one page now
    open(os.path.join(OUT, 'index.html'), 'w').write(HEAD % ('Links', 'Everything on my desk and around my home, with links.', shop_button(PROFILE.replace(SOCIALS, soc_counts(counts))).replace('%STUDIO_NOW%', studio_now())) + body + FOOT % (COPY_JS + TAP_JS + DM_JS))
    print(f"Wrote the bio page to {OUT}: {len(sections)} spaces.")
    for p in problems:
        print('PROBLEM:', p)
    sys.exit(3 if problems else 0)


def main():
    os.makedirs(IMG, exist_ok=True)
    shop = read_shop()
    if not shop:
        sys.exit('ShopMy could not be read and there is no kept copy. Nothing was written.')
    if CFG.get('spaces'):
        return build_spaces(shop)

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
    feed = read_feed()
    every_pin = {p['id']: p for col in shop.values() for p in col['pins']}
    rp = CFG.get('reel_pages', {})
    reels = []
    for p in feed[:CFG.get('reels_shown', 9)]:
        cover, _ = picture(FEED_URL + f"/{p['code']}.jpg", 'r_' + p['code'], size=540)
        if not cover:
            continue
        spec = rp.get(p['code'])
        url = f"https://www.instagram.com/reel/{p['code']}/"
        if spec and str(spec.get('list')) in shop:
            title, slug = spec.get('title') or p.get('caption', ''), 'reel-' + p['code'].lower()
            lead = [every_pin[i] for i in spec.get('lead', []) if i in every_pin]
            ts = tiles(lead + shop[str(spec['list'])]['pins'], slug)
            items = [t for _, t in ts[:len(lead)]] + [t for s_, t in ts[len(lead):] if s_] + [t for s_, t in ts[len(lead):] if not s_]
            top = (f'<a class="back" href="index.html">All my videos</a><div class="vh reel"><img src="{cover}" alt="{e(title)}"><div><h1 class="lead">{e(title)}</h1>'
                   f'<p class="note">Posted {e(nice_day(p.get("date", "")))}</p><a class="more" href="{e(url)}" rel="noopener">Watch the reel</a></div></div>')
            pages[slug] = (title, band('b-top', None, top) + band('b-green', 'In this video', grid(items) + f'<p class="note">{DISCLOSE}</p><a class="btn" href="index.html">See my whole desk</a>'))
            reels.append({'cover': cover, 'title': title, 'href': slug + '.html', 'list': True})
        else:
            reels.append({'cover': cover, 'title': p.get('caption', ''), 'href': url, 'list': False})
            notes.append(f"Reel {p['code']} has no list in bio.json reel_pages, so it opens on Instagram.")
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
    codes = ''.join(code_row(c) for c in live_codes())
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
