"""Rezepte – lokale Web-App für eine gemeinsame Rezeptsammlung in einem OneDrive-Ordner.

Start:   py app.py                 (öffnet http://127.0.0.1:8642 im Browser)
Optionen: --ordner PFAD           anderen Datenordner verwenden (z. B. zum Testen)
          --no-browser            Browser nicht automatisch öffnen

Jedes Rezept ist eine JSON-Datei im Datenordner, Fotos liegen im Unterordner "fotos".
Nur die Python-Standardbibliothek wird benötigt.
"""
import base64
import getpass
import html
import json
import os
import re
import secrets
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
CONFIG_FILE = APP_DIR / "config.json"
HOST, PORT = "127.0.0.1", 8642

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
FOTO_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,100}\.(jpg|png|webp)$")
MAX_BODY = 25 * 1024 * 1024
MAX_FOTO = 15 * 1024 * 1024
MAX_SEITE = 8 * 1024 * 1024
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
}
FOTO_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


class ApiError(Exception):
    def __init__(self, status, text):
        super().__init__(text)
        self.status = status
        self.text = text


def jetzt():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------- Konfiguration

def standard_datenordner():
    onedrive = os.environ.get("OneDriveConsumer") or os.environ.get("OneDrive")
    return str((Path(onedrive) if onedrive else Path.home()) / "Rezepte")


def lade_config():
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    cfg.setdefault("datenordner", standard_datenordner())
    cfg.setdefault("nutzer", getpass.getuser())
    speichere_config(cfg)
    return cfg


def speichere_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- Rezeptdaten

def text(v, max_len=20000):
    return str(v if v is not None else "").strip()[:max_len]


def textliste(v, max_len=2000):
    if not isinstance(v, list):
        return []
    return [t for t in (text(x, max_len) for x in v) if t]


def bereinige(d):
    """Übernimmt nur bekannte Felder mit passenden Typen."""
    try:
        zeit = int(d.get("zeit_minuten")) if d.get("zeit_minuten") not in (None, "") else None
    except (TypeError, ValueError):
        zeit = None
    return {
        "titel": text(d.get("titel"), 200) or "Unbenanntes Rezept",
        "quelle": text(d.get("quelle"), 2000),
        "beschreibung": text(d.get("beschreibung"), 5000),
        "portionen": text(d.get("portionen"), 50),
        "zeit_minuten": zeit if zeit and zeit > 0 else None,
        "zutaten": textliste(d.get("zutaten")),
        "schritte": textliste(d.get("schritte"), 5000),
        "tags": textliste(d.get("tags"), 50),
        "notizen": text(d.get("notizen")),
    }


def slug(titel):
    s = titel.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50].strip("-")
    return s or "rezept"


def foto_endung(daten):
    if daten[:3] == b"\xff\xd8\xff":
        return "jpg"
    if daten[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if daten[:4] == b"RIFF" and daten[8:12] == b"WEBP":
        return "webp"
    return None


class Store:
    def __init__(self, ordner):
        self.dir = Path(ordner)
        self.fotos = self.dir / "fotos"
        self.papierkorb = self.dir / "_papierkorb"
        self.fotos.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def pfad(self, rid):
        if not ID_RE.match(rid):
            raise ApiError(400, "Ungültige Rezept-ID")
        return self.dir / f"{rid}.json"

    def lies(self, rid):
        p = self.pfad(rid)
        if not p.exists():
            raise ApiError(404, "Rezept nicht gefunden")
        r = json.loads(p.read_text(encoding="utf-8"))
        r["id"] = rid
        return r

    def schreibe(self, rid, r):
        r = {k: v for k, v in r.items() if k != "id"}
        ziel = self.pfad(rid)
        tmp = ziel.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        for versuch in range(5):
            try:
                os.replace(tmp, ziel)
                return
            except PermissionError:
                # OneDrive hält die Datei gelegentlich kurz fest
                if versuch == 4:
                    raise
                time.sleep(0.2)

    def liste(self):
        rezepte, konflikte = [], []
        for p in sorted(self.dir.glob("*.json")):
            if not ID_RE.match(p.stem):
                # z. B. OneDrive-Konfliktkopien wie "lasagne-DESKTOP-AB12.json"
                konflikte.append(p.name)
                continue
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                konflikte.append(p.name)
                continue
            rezepte.append({
                "id": p.stem,
                "titel": r.get("titel", ""),
                "tags": r.get("tags", []),
                "zutaten": r.get("zutaten", []),
                "zeit_minuten": r.get("zeit_minuten"),
                "bewertungen": r.get("bewertungen", {}),
                "foto": (r.get("fotos") or [None])[0],
                "erstellt": r.get("erstellt", ""),
                "geaendert": r.get("geaendert", ""),
            })
        return {"rezepte": rezepte, "konflikte": konflikte}

    def neu(self, daten, nutzer):
        r = bereinige(daten)
        with self.lock:
            while True:
                rid = f"{slug(r['titel'])}-{secrets.token_hex(2)}"
                if not self.pfad(rid).exists():
                    break
            r.update(bewertungen={}, fotos=[], erstellt=jetzt(), erstellt_von=nutzer,
                     geaendert=jetzt(), geaendert_von=nutzer)
            self.schreibe(rid, r)
        r["id"] = rid
        return r

    def speichere(self, rid, daten, basis, nutzer):
        """Speichert Textfelder. Bewertungen und Fotos bleiben wie in der Datei."""
        with self.lock:
            aktuell = self.lies(rid)
            if basis and aktuell.get("geaendert") != basis:
                raise ApiError(409, f"Das Rezept wurde inzwischen von "
                                    f"{aktuell.get('geaendert_von', 'jemand anderem')} geändert.")
            aktuell.update(bereinige(daten), geaendert=jetzt(), geaendert_von=nutzer)
            self.schreibe(rid, aktuell)
            return aktuell

    def bewerte(self, rid, nutzer, sterne):
        with self.lock:
            r = self.lies(rid)
            bew = r.setdefault("bewertungen", {})
            if sterne:
                bew[nutzer] = sterne
            else:
                bew.pop(nutzer, None)
            self.schreibe(rid, r)
            return r

    def in_papierkorb(self, datei):
        self.papierkorb.mkdir(exist_ok=True)
        ziel = self.papierkorb / f"{datetime.now():%Y%m%d-%H%M%S}-{datei.name}"
        shutil.move(str(datei), str(ziel))

    def loesche(self, rid):
        with self.lock:
            r = self.lies(rid)
            for f in r.get("fotos", []):
                if FOTO_RE.match(f) and (self.fotos / f).exists():
                    self.in_papierkorb(self.fotos / f)
            self.in_papierkorb(self.pfad(rid))

    def foto_hinzu(self, rid, daten):
        if len(daten) > MAX_FOTO:
            raise ApiError(413, "Foto ist zu groß (max. 15 MB)")
        endung = foto_endung(daten)
        if not endung:
            raise ApiError(400, "Nur JPG, PNG oder WebP werden unterstützt")
        with self.lock:
            r = self.lies(rid)
            name = f"{rid}-{secrets.token_hex(3)}.{endung}"
            (self.fotos / name).write_bytes(daten)
            r.setdefault("fotos", []).append(name)
            self.schreibe(rid, r)
            return r

    def foto_weg(self, rid, name):
        with self.lock:
            r = self.lies(rid)
            if name not in r.get("fotos", []):
                raise ApiError(404, "Foto nicht gefunden")
            r["fotos"].remove(name)
            if (self.fotos / name).exists():
                self.in_papierkorb(self.fotos / name)
            self.schreibe(rid, r)
            return r

    def foto_pfad(self, name):
        if not FOTO_RE.match(name) or not (self.fotos / name).exists():
            raise ApiError(404, "Foto nicht gefunden")
        return self.fotos / name


# ---------------------------------------------------------------- Import von Webseiten

class LdJsonParser(HTMLParser):
    """Sammelt alle <script type="application/ld+json">-Blöcke und das og:image."""

    def __init__(self):
        super().__init__()
        self.bloecke, self._puffer, self._aktiv = [], [], False
        self.og_bild = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "script" and (a.get("type") or "").strip().lower() == "application/ld+json":
            self._aktiv, self._puffer = True, []
        elif tag == "meta" and a.get("property") == "og:image" and not self.og_bild:
            self.og_bild = a.get("content")

    def handle_data(self, data):
        if self._aktiv:
            self._puffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._aktiv:
            self._aktiv = False
            self.bloecke.append("".join(self._puffer))


def lade_url(url, limit):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as antwort:
            daten = antwort.read(limit + 1)
            charset = antwort.headers.get_content_charset() or "utf-8"
    except urllib.error.HTTPError as e:
        raise ApiError(502, f"Die Webseite antwortet mit Fehler {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(502, f"Webseite nicht erreichbar: {getattr(e, 'reason', e)}")
    if len(daten) > limit:
        raise ApiError(413, "Die Datei ist zu groß")
    return daten, charset


def finde_rezept(knoten):
    if isinstance(knoten, list):
        for x in knoten:
            r = finde_rezept(x)
            if r:
                return r
    elif isinstance(knoten, dict):
        typ = knoten.get("@type")
        if "Recipe" in (typ if isinstance(typ, list) else [typ]):
            return knoten
        for schluessel in ("@graph", "mainEntity", "itemListElement"):
            if schluessel in knoten:
                r = finde_rezept(knoten[schluessel])
                if r:
                    return r
    return None


def html_text(v):
    """Entfernt HTML-Tags und Entities, Zeilenumbrüche bleiben erhalten."""
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", str(v or ""))
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    zeilen = (re.sub(r"[ \t\xa0]+", " ", z).strip() for z in s.splitlines())
    return "\n".join(z for z in zeilen if z)


def schritte_aus(v):
    if isinstance(v, str):
        return html_text(v).splitlines()
    if isinstance(v, dict):
        if "itemListElement" in v:
            titel = html_text(v.get("name"))
            return ([f"— {titel} —"] if titel else []) + schritte_aus(v["itemListElement"])
        t = html_text(v.get("text") or v.get("name"))
        return [t] if t else []
    if isinstance(v, list):
        return [s for x in v for s in schritte_aus(x)]
    return []


def minuten_aus(v):
    m = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", str(v or ""))
    if not m or not any(m.groups()):
        return 0
    tage, std, mins = (int(x or 0) for x in m.groups())
    return tage * 1440 + std * 60 + mins


def erstes(v, index=None):
    """Erster Wert einer Liste; bei Objekten deren URL. Verweise per @id werden aufgelöst."""
    if isinstance(v, list):
        return erstes(v[0], index) if v else None
    if isinstance(v, dict):
        if not (v.get("url") or v.get("contentUrl")) and index and v.get("@id") in index:
            v = index[v["@id"]]
        return v.get("url") or v.get("contentUrl")
    return v


def sammle_ids(knoten, index):
    if isinstance(knoten, list):
        for x in knoten:
            sammle_ids(x, index)
    elif isinstance(knoten, dict):
        if isinstance(knoten.get("@id"), str) and len(knoten) > 1:
            index.setdefault(knoten["@id"], knoten)
        for x in knoten.values():
            sammle_ids(x, index)


def importiere(url):
    if urllib.parse.urlparse(url).scheme not in ("http", "https"):
        raise ApiError(400, "Bitte eine http(s)-Adresse angeben")
    daten, charset = lade_url(url, MAX_SEITE)
    parser = LdJsonParser()
    parser.feed(daten.decode(charset, errors="replace"))

    knoten = []
    for block in parser.bloecke:
        try:
            knoten.append(json.loads(block, strict=False))
        except ValueError:
            continue
    rezept = finde_rezept(knoten)
    if not rezept:
        raise ApiError(422, "Auf dieser Seite wurden keine Rezeptdaten gefunden. "
                            "Lege das Rezept über „+ Neu“ von Hand an.")

    zeit = minuten_aus(rezept.get("totalTime")) or (
        minuten_aus(rezept.get("prepTime")) + minuten_aus(rezept.get("cookTime")))
    tags = []
    for feld in ("recipeCategory", "recipeCuisine"):
        werte = rezept.get(feld)
        for wert in (werte if isinstance(werte, list) else [werte]):
            for t in html_text(wert).split(","):
                t = t.strip()
                if t and t not in tags and len(t) <= 50:
                    tags.append(t)
    index = {}
    sammle_ids(knoten, index)

    return {
        "titel": html_text(rezept.get("name")),
        "quelle": url,
        "beschreibung": html_text(rezept.get("description")),
        "portionen": html_text(erstes(rezept.get("recipeYield"))),
        "zeit_minuten": zeit or None,
        "zutaten": [html_text(z) for z in rezept.get("recipeIngredient") or [] if html_text(z)],
        "schritte": schritte_aus(rezept.get("recipeInstructions")),
        "tags": tags,
    }, [u for u in (erstes(rezept.get("image"), index), parser.og_bild) if u]


def lade_bild(url, basis):
    """Lädt das Rezeptbild herunter; Fehler werden ignoriert."""
    try:
        url = urllib.parse.urljoin(basis, str(url))
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return None
        daten, _ = lade_url(url, MAX_FOTO)
        return daten if foto_endung(daten) else None
    except ApiError:
        return None


# ---------------------------------------------------------------- HTTP-Server

class Handler(BaseHTTPRequestHandler):
    server_version = "Rezepte/0.1"

    @property
    def store(self):
        return self.server.store

    @property
    def nutzer(self):
        return self.server.cfg["nutzer"]

    def log_request(self, code="-", size="-"):
        # Nur fehlgeschlagene Anfragen protokollieren
        if str(code)[:1] in ("4", "5"):
            super().log_request(code, size)

    def do_GET(self):
        self.verarbeite("GET")

    def do_POST(self):
        self.verarbeite("POST")

    def do_PUT(self):
        self.verarbeite("PUT")

    def do_DELETE(self):
        self.verarbeite("DELETE")

    def verarbeite(self, methode):
        pfad = urllib.parse.urlparse(self.path).path
        try:
            # Schutz gegen DNS-Rebinding und Anfragen fremder Webseiten
            if self.headers.get("Host") not in (f"{HOST}:{PORT}", f"localhost:{PORT}"):
                raise ApiError(403, "Ungültiger Host")
            if methode != "GET" and self.headers.get("X-Rezepte") != "1":
                raise ApiError(403, "Fehlender Header")
            for m, muster, funktion in ROUTEN:
                treffer = re.fullmatch(muster, pfad)
                if m == methode and treffer:
                    return funktion(self, *treffer.groups())
            raise ApiError(404, "Nicht gefunden")
        except ApiError as e:
            self.sende_json({"fehler": e.text}, e.status)
        except Exception as e:  # noqa: BLE001 – Fehler als JSON an die Oberfläche melden
            self.log_error("Fehler: %r", e)
            self.sende_json({"fehler": f"Interner Fehler: {e}"}, 500)

    def body(self):
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge > MAX_BODY:
            raise ApiError(413, "Anfrage ist zu groß")
        try:
            return json.loads(self.rfile.read(laenge) or b"{}")
        except ValueError:
            raise ApiError(400, "Ungültiges JSON")

    def sende(self, daten, typ, status=200):
        self.send_response(status)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(daten)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(daten)

    def sende_json(self, obj, status=200):
        self.sende(json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", status)

    # --- Routen

    def statisch(self, name="index.html"):
        if name not in STATIC_FILES:
            raise ApiError(404, "Nicht gefunden")
        self.sende((STATIC_DIR / name).read_bytes(), STATIC_FILES[name])

    def foto(self, name):
        p = self.store.foto_pfad(name)
        self.sende(p.read_bytes(), FOTO_TYPES[p.suffix[1:]])

    def config_lesen(self):
        self.sende_json({"nutzer": self.nutzer, "datenordner": str(self.store.dir)})

    def config_schreiben(self):
        name = text(self.body().get("nutzer"), 50)
        if not name:
            raise ApiError(400, "Name darf nicht leer sein")
        self.server.cfg["nutzer"] = name
        speichere_config(self.server.cfg)
        self.config_lesen()

    def rezepte(self):
        self.sende_json(self.store.liste())

    def rezept_neu(self):
        self.sende_json(self.store.neu(self.body(), self.nutzer), 201)

    def rezept_import(self):
        url = text(self.body().get("url"), 2000)
        daten, bild_urls = importiere(url)
        r = self.store.neu(daten, self.nutzer)
        for bild_url in bild_urls:
            bild = lade_bild(bild_url, url)
            if bild:
                r = self.store.foto_hinzu(r["id"], bild)
                break
        self.sende_json(r, 201)

    def rezept(self, rid):
        self.sende_json(self.store.lies(rid))

    def rezept_speichern(self, rid):
        b = self.body()
        self.sende_json(self.store.speichere(rid, b.get("rezept") or {}, b.get("basis"), self.nutzer))

    def rezept_loeschen(self, rid):
        self.store.loesche(rid)
        self.sende_json({"ok": True})

    def bewertung(self, rid):
        try:
            sterne = int(self.body().get("sterne"))
        except (TypeError, ValueError):
            sterne = -1
        if not 0 <= sterne <= 5:
            raise ApiError(400, "Bewertung muss zwischen 0 und 5 liegen")
        self.sende_json(self.store.bewerte(rid, self.nutzer, sterne))

    def foto_hochladen(self, rid):
        try:
            daten = base64.b64decode(self.body().get("daten") or "", validate=True)
        except ValueError:
            raise ApiError(400, "Ungültige Bilddaten")
        self.sende_json(self.store.foto_hinzu(rid, daten), 201)

    def foto_loeschen(self, rid, name):
        self.sende_json(self.store.foto_weg(rid, name))


RID = r"([a-z0-9][a-z0-9-]*)"
ROUTEN = [
    ("GET", r"/", Handler.statisch),
    ("GET", r"/static/([\w.-]+)", Handler.statisch),
    ("GET", r"/fotos/([\w.-]+)", Handler.foto),
    ("GET", r"/api/config", Handler.config_lesen),
    ("PUT", r"/api/config", Handler.config_schreiben),
    ("GET", r"/api/rezepte", Handler.rezepte),
    ("POST", r"/api/rezepte", Handler.rezept_neu),
    ("POST", r"/api/import", Handler.rezept_import),
    ("GET", rf"/api/rezepte/{RID}", Handler.rezept),
    ("PUT", rf"/api/rezepte/{RID}", Handler.rezept_speichern),
    ("DELETE", rf"/api/rezepte/{RID}", Handler.rezept_loeschen),
    ("PUT", rf"/api/rezepte/{RID}/bewertung", Handler.bewertung),
    ("POST", rf"/api/rezepte/{RID}/fotos", Handler.foto_hochladen),
    ("DELETE", rf"/api/rezepte/{RID}/fotos/([\w.-]+)", Handler.foto_loeschen),
]


def main():
    args = sys.argv[1:]
    if sys.stdout is None or sys.stderr is None:
        # Gestartet mit pythonw (ohne Konsole): Ausgaben und Fehler in eine Logdatei schreiben
        log = open(APP_DIR / "rezepte.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log
        print(f"\n=== Start {jetzt()} ===")
    cfg = lade_config()
    ordner = args[args.index("--ordner") + 1] if "--ordner" in args else cfg["datenordner"]
    url = f"http://{HOST}:{PORT}/"
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        print(f"Port {PORT} ist belegt – läuft die App schon? Öffne {url}")
        if "--no-browser" not in args:
            webbrowser.open(url)
        return
    server.cfg = cfg
    server.store = Store(ordner)
    print(f"Rezepte läuft auf {url}")
    print(f"Datenordner: {server.store.dir}")
    print(f"Angemeldet als: {cfg['nutzer']}")
    print("Beenden mit Strg+C")
    if "--no-browser" not in args:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
