"""One static page per church, monastery and cathedral, from the Biserici app's data.

Open data only: name, kind, hram, locality, monument status, the Commons photo with its credit,
the map position and the sources. No phone, e-mail, website, service times or people: those stay in
the app, and an address taken from an eparchy site is left out (`field_sources` in the pipeline CSV).

    python tools/build_pages.py <places.db> <Hramuri.kt> [<pipeline.csv>]

Writes b/<id>/index.html for every main place and sitemap.xml. Re-run after each new places.db.
"""
import csv
import html
import json
import re
import shutil
import sqlite3
import sys
import unicodedata
import urllib.parse
from pathlib import Path

SITE = "https://barbuta.github.io/biserici"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "b"
PLAY = "https://play.google.com/store/apps/details?id=ro.infoortodox.app&referrer=utm_source%3Dweb_page"

KIND = {"church": "Biserică", "chapel": "Capelă", "monastery": "Mănăstire", "skete": "Schit", "cathedral": "Catedrală"}
MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]
# Movable hramuri, as days after Pascha (calendar/Hramuri.kt).
MOVABLE = {-7: "Duminica Floriilor", 0: "Duminica Paștilor", 5: "vinerea din Săptămâna Luminată",
           39: "joia Înălțării, la 40 de zile după Paști", 49: "Duminica Rusaliilor",
           50: "lunea Rusaliilor", 56: "Duminica Tuturor Sfinților", 63: "Duminica Sfinților Români"}


def fold(t):
    t = t.lower().replace("ş", "s").replace("ţ", "t")
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def load_hramuri(kotlin):
    """The app's own patterns, so the page names the same hram as the app."""
    src = Path(kotlin).read_text(encoding="utf-8")
    out = []
    for pattern, label, date in re.findall(r'^\s*"(.+?)" to Hram\("(.+?)", (.+?)\),?\s*$', src, re.M):
        m = re.match(r"fixed\((\d+), (\d+)\)", date)
        when = f"{int(m[2])} {MONTHS[int(m[1]) - 1]}" if m else MOVABLE.get(int(re.search(r"-?\d+", date)[0]), "dată mobilă")
        out.append((re.compile(pattern.replace("\\\\", "\\")), label, when))
    return out


def detect(patterns, *texts):
    for t in texts:
        if not t:
            continue
        f, found = fold(t), []
        for rx, label, when in patterns:
            if rx.search(f) and all(w != when for _, w in found):
                found.append((label, when))
            if len(found) == 2:
                break
        if found:
            return found
    return []


def eparchy_addresses(path):
    """Ids whose street came from an eparchy site: their address is not shown."""
    if not path:
        return set()
    out = set()
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        try:
            if json.loads(r.get("field_sources") or "{}").get("street", "").startswith("eparhie"):
                out.add(r["id"])
        except ValueError:
            pass
    return out


def slug(place_id):
    return re.sub(r"[^A-Za-z0-9_-]", "-", place_id)


def strip_tags(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


e = html.escape


def page(p, hramuri, inside, show_address):
    name = p["name"] or f"{KIND[p['type']]} – {p['town'] or p['city'] or ''}".strip(" –")
    where = ", ".join(x for x in (p["town"] or p["city"], p["county"] and f"județul {p['county']}" if p["country_iso"] == "RO" else p["county"]) if x)
    rows = []
    for label, when in hramuri:
        rows.append(("Hram", f"{e(label)} <span class=muted>· {e(when)}</span>"))
    if show_address and p["address"]:
        rows.append(("Adresă", e(p["address"])))
    elif where:
        rows.append(("Localitate", e(where)))
    if p["heritage"]:
        rows.append(("Patrimoniu", "Monument UNESCO" if p["heritage"] == 2 else "Monument istoric"))
    if inside:
        rows.append(("În incintă", "<br>".join(e(n) for n in inside)))
    facts = "\n".join(f"<div class=row><div class=label>{k}</div><div>{v}</div></div>" for k, v in rows)

    lat, lon = p["lat"], p["lon"]
    osm = f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=17/{lat:.6f}/{lon:.6f}"
    photo = ""
    if p["photo"]:
        file = urllib.parse.quote(p["photo"].replace(" ", "_"))
        credit = ", ".join(x for x in (strip_tags(p["photo_author"]), p["photo_license"]) if x)
        photo = (f'<figure><img src="https://commons.wikimedia.org/wiki/Special:FilePath/{file}?width=800" '
                 f'alt="{e(name)}" loading="lazy" width="800">'
                 f'<figcaption><a href="https://commons.wikimedia.org/wiki/File:{file}">Foto: {e(credit or "Wikimedia Commons")} · Wikimedia Commons</a></figcaption></figure>')
    source = {"osm": "OpenStreetMap", "wd": "Wikidata"}.get(p["id"].split(":")[0], "Biserici")
    desc = f"{KIND[p['type']]} ortodoxă" + (f" din {p['town'] or p['city']}" if (p["town"] or p["city"]) else "") + \
        (f", cu hramul {hramuri[0][0]} ({hramuri[0][1]})" if hramuri else "") + "."
    ld = {"@context": "https://schema.org", "@type": "Church", "name": name, "description": desc,
          "geo": {"@type": "GeoCoordinates", "latitude": round(lat, 6), "longitude": round(lon, 6)}}
    if where:
        ld["address"] = {"@type": "PostalAddress", "addressLocality": p["town"] or p["city"], "addressRegion": p["county"], "addressCountry": p["country_iso"]}
    url = f"{SITE}/b/{slug(p['id'])}/"
    app = "intent://loc/" + urllib.parse.quote(p["id"], safe="") + "#Intent;scheme=biserici;package=ro.infoortodox.app;S.browser_fallback_url=" + urllib.parse.quote(PLAY, safe="") + ";end"
    return f"""<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(name)} · Biserici</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{e(name)}">
<meta property="og:description" content="{e(desc)}">
<link rel="stylesheet" href="../../assets/place.css">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>
</head>
<body>
<main>
<article class="card">
<div class="kicker">{KIND[p['type']]}</div>
<h1>{e(name)}</h1>
{f'<p class="local">{e(p["name_local"])}</p>' if p["name_local"] and p["name_local"] != name else ''}
{photo}
<div class="facts">
{facts}
</div>
<a class="button primary" id="open" href="{PLAY}" data-intent="{e(app)}">Deschide în aplicația Biserici</a>
<a class="button secondary" href="{osm}">Vezi pe hartă (OpenStreetMap)</a>
<p class="note">În aplicație: drumul până aici, telefonul parohiei, programul slujbelor, calendarul și jurnalul tău de pelerin.</p>
</article>
<footer>
<p>Date: {source}. Hărți și date © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> (ODbL); Wikidata (CC0); Lista Monumentelor Istorice. Ai găsit o greșeală? Propune o corectură din aplicație, pe fișa lăcașului.</p>
<p><a href="../../">Biserici</a> · <a href="../../privacy/">Confidențialitate</a></p>
</footer>
</main>
<script src="../../assets/place.js"></script>
</body>
</html>
"""


def main():
    db, kotlin = sys.argv[1], sys.argv[2]
    hidden_address = eparchy_addresses(sys.argv[3] if len(sys.argv) > 3 else None)
    patterns = load_hramuri(kotlin)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    places = con.execute("select * from places").fetchall()
    inside = {}
    for p in places:
        if p["parent_id"]:
            inside.setdefault(p["parent_id"], []).append(p["name"] or KIND[p["type"]])
    if OUT.exists():
        shutil.rmtree(OUT)
    urls = []
    for p in places:
        if p["parent_id"]:
            continue
        d = OUT / slug(p["id"])
        d.mkdir(parents=True)
        hr = detect(patterns, p["dedication"], p["name"])
        (d / "index.html").write_text(page(p, hr, sorted(inside.get(p["id"], [])), p["id"] not in hidden_address), encoding="utf-8")
        urls.append(f"{SITE}/b/{slug(p['id'])}/")
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' +
        "".join(f"<url><loc>{u}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    print(f"{len(urls)} pages, {len(hidden_address)} eparchy addresses left out")


if __name__ == "__main__":
    main()
