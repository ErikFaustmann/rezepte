"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const app = $("#app");
let config = { nutzer: "", datenordner: "" };
const liste = { suche: "", sortierung: "geaendert" };

// ---------------------------------------------------------------- Hilfsfunktionen

// Baut DOM-Elemente; Texte werden nie als HTML interpretiert.
function h(tag, attrs = {}, ...kinder) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kinder.flat()) {
    if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  }
  return el;
}

async function api(methode, pfad, body) {
  const opt = { method: methode, headers: { "X-Rezepte": "1" } };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  const antwort = await fetch(pfad, opt);
  const daten = await antwort.json().catch(() => ({}));
  if (!antwort.ok) {
    const fehler = new Error(daten.fehler || `Fehler ${antwort.status}`);
    fehler.status = antwort.status;
    throw fehler;
  }
  return daten;
}

let meldungTimer;
function meldung(text, art = "fehler") {
  const el = $("#meldung");
  el.textContent = text;
  el.className = `meldung ${art}`;
  el.hidden = false;
  clearTimeout(meldungTimer);
  meldungTimer = setTimeout(() => (el.hidden = true), art === "fehler" ? 8000 : 4000);
}

function datum(iso) {
  return iso ? new Date(iso).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" }) : "–";
}

function dauer(min) {
  if (!min) return null;
  return min >= 60 ? `${Math.floor(min / 60)} h ${min % 60 ? (min % 60) + " min" : ""}`.trim() : `${min} min`;
}

function schnitt(bewertungen) {
  const werte = Object.values(bewertungen || {});
  return werte.length ? werte.reduce((a, b) => a + b, 0) / werte.length : 0;
}

function sterne(wert, beiWahl) {
  const box = h("span", { class: "sterne" + (beiWahl ? " waehlbar" : "") });
  for (let i = 1; i <= 5; i++) {
    const an = i <= Math.round(wert);
    box.append(beiWahl
      ? h("button", { type: "button", class: an ? "an" : "aus", title: `${i} von 5`, onclick: () => beiWahl(i === wert ? 0 : i) }, "★")
      : h("span", { class: an ? "an" : "aus" }, "★"));
  }
  return box;
}

function istWebLink(url) {
  try { return ["http:", "https:"].includes(new URL(url).protocol); } catch { return false; }
}

// Fotos vor dem Hochladen verkleinern, damit OneDrive nicht vollläuft.
async function fotoVorbereiten(datei, max = 1600) {
  const bild = await createImageBitmap(datei);
  const faktor = Math.min(1, max / Math.max(bild.width, bild.height));
  const canvas = h("canvas", { width: Math.round(bild.width * faktor), height: Math.round(bild.height * faktor) });
  canvas.getContext("2d").drawImage(bild, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", 0.85));
  return new Promise((ok, fehler) => {
    const leser = new FileReader();
    leser.onload = () => ok(leser.result.split(",")[1]);
    leser.onerror = fehler;
    leser.readAsDataURL(blob);
  });
}

// ---------------------------------------------------------------- Ansichten

async function zeigeListe() {
  const { rezepte, konflikte } = await api("GET", "/api/rezepte");
  const raster = h("div", { class: "raster" });

  const zeichne = () => {
    const q = liste.suche.toLowerCase().trim();
    const treffer = rezepte
      .filter((r) => !q || [r.titel, ...r.tags, ...r.zutaten].join(" ").toLowerCase().includes(q))
      .sort({
        geaendert: (a, b) => b.geaendert.localeCompare(a.geaendert),
        erstellt: (a, b) => b.erstellt.localeCompare(a.erstellt),
        bewertung: (a, b) => schnitt(b.bewertungen) - schnitt(a.bewertungen),
        titel: (a, b) => a.titel.localeCompare(b.titel, "de"),
      }[liste.sortierung]);

    raster.replaceChildren(...treffer.map((r) => {
      const anzahl = Object.keys(r.bewertungen).length;
      return h("a", { class: "karte", href: `#/rezept/${r.id}` },
        r.foto
          ? h("img", { src: `/fotos/${r.foto}`, alt: "", loading: "lazy" })
          : h("div", { class: "platzhalter" }, "🍽️"),
        h("div", { class: "karte-text" },
          h("h3", {}, r.titel),
          h("div", { class: "karte-meta" },
            sterne(schnitt(r.bewertungen)),
            anzahl ? h("span", { class: "leise" }, `(${anzahl})`) : null,
            r.zeit_minuten ? h("span", { class: "leise" }, "⏱ " + dauer(r.zeit_minuten)) : null),
          r.tags.length ? h("div", { class: "tags" }, r.tags.map((t) => h("span", { class: "tag" }, t))) : null));
    }));
    if (!treffer.length) {
      raster.append(h("p", { class: "leer" }, rezepte.length
        ? "Keine Rezepte gefunden."
        : "Noch keine Rezepte. Füge oben eine Rezept-URL ein oder lege eins mit „+ Neu“ an."));
    }
  };

  app.replaceChildren(
    konflikte.length ? h("div", { class: "hinweis" },
      h("strong", {}, "OneDrive-Konfliktkopien gefunden: "),
      konflikte.join(", "),
      h("br"),
      "Bitte im Datenordner prüfen, welche Version richtig ist, und die andere löschen.") : "",
    h("div", { class: "werkzeuge" },
      h("input", {
        type: "search", placeholder: "Suchen nach Titel, Zutat, Tag …", value: liste.suche,
        oninput: (e) => { liste.suche = e.target.value; zeichne(); },
      }),
      h("select", { onchange: (e) => { liste.sortierung = e.target.value; zeichne(); } },
        [["geaendert", "Zuletzt geändert"], ["erstellt", "Neueste zuerst"], ["bewertung", "Beste Bewertung"], ["titel", "Titel A–Z"]]
          .map(([v, t]) => h("option", { value: v, selected: v === liste.sortierung }, t))),
      h("span", { class: "leise" }, `${rezepte.length} Rezepte`)),
    raster);
  zeichne();
}

async function zeigeRezept(id) {
  const r = await api("GET", `/api/rezepte/${id}`);
  const eigene = r.bewertungen?.[config.nutzer] || 0;
  const andere = Object.entries(r.bewertungen || {}).filter(([n]) => n !== config.nutzer);

  const bewerten = async (wert) => {
    try {
      await api("PUT", `/api/rezepte/${id}/bewertung`, { sterne: wert });
      zeigeRezept(id);
    } catch (e) { meldung(e.message); }
  };

  const fotoInput = h("input", {
    type: "file", accept: "image/*", multiple: true, hidden: true,
    onchange: async (e) => {
      for (const datei of e.target.files) {
        try {
          await api("POST", `/api/rezepte/${id}/fotos`, { daten: await fotoVorbereiten(datei) });
        } catch (err) {
          meldung(`${datei.name}: ${err.status ? err.message : "Bild konnte nicht gelesen werden"}`);
        }
      }
      zeigeRezept(id);
    },
  });

  const loeschen = async () => {
    if (!confirm(`„${r.titel}“ wirklich löschen?\nEs wird in den Ordner _papierkorb verschoben.`)) return;
    try {
      await api("DELETE", `/api/rezepte/${id}`);
      meldung("Rezept in den Papierkorb verschoben.", "ok");
      location.hash = "#/";
    } catch (e) { meldung(e.message); }
  };

  const fotoLoeschen = async (name) => {
    if (!confirm("Foto entfernen?")) return;
    try {
      await api("DELETE", `/api/rezepte/${id}/fotos/${name}`);
      zeigeRezept(id);
    } catch (e) { meldung(e.message); }
  };

  app.replaceChildren(h("article", { class: "rezept" },
    h("div", { class: "rezept-kopf" },
      h("div", {},
        h("a", { href: "#/", class: "zurueck" }, "← Alle Rezepte"),
        h("h1", {}, r.titel),
        h("div", { class: "meta" },
          r.portionen ? h("span", {}, "🍴 " + r.portionen) : null,
          r.zeit_minuten ? h("span", {}, "⏱ " + dauer(r.zeit_minuten)) : null,
          istWebLink(r.quelle) ? h("a", { href: r.quelle, target: "_blank", rel: "noopener noreferrer" }, "🔗 Originalrezept") : null),
        r.tags?.length ? h("div", { class: "tags" }, r.tags.map((t) => h("span", { class: "tag" }, t))) : null),
      h("div", { class: "aktionen" },
        h("a", { href: `#/rezept/${id}/bearbeiten`, class: "knopf" }, "Bearbeiten"),
        h("button", { class: "gefahr", onclick: loeschen }, "Löschen"))),

    h("section", { class: "bewertung" },
      h("div", {}, h("span", { class: "label" }, `Deine Bewertung (${config.nutzer}): `), sterne(eigene, bewerten)),
      andere.map(([name, wert]) => h("div", {}, h("span", { class: "label" }, `${name}: `), sterne(wert)))),

    h("section", { class: "fotos" },
      (r.fotos || []).map((f) => h("figure", {},
        h("a", { href: `/fotos/${f}`, target: "_blank" }, h("img", { src: `/fotos/${f}`, alt: "" })),
        h("button", { class: "foto-weg", title: "Foto entfernen", onclick: () => fotoLoeschen(f) }, "×"))),
      h("button", { class: "foto-neu", onclick: () => fotoInput.click() }, "+ Foto"),
      fotoInput),

    r.beschreibung ? h("p", { class: "beschreibung" }, r.beschreibung) : null,

    h("div", { class: "spalten" },
      h("section", {}, h("h2", {}, "Zutaten"),
        r.zutaten?.length ? h("ul", { class: "zutaten" }, r.zutaten.map((z) => h("li", {}, z))) : h("p", { class: "leise" }, "Keine Zutaten eingetragen.")),
      h("section", {}, h("h2", {}, "Zubereitung"),
        r.schritte?.length ? h("ol", { class: "schritte" }, r.schritte.map((s) => h("li", {}, s))) : h("p", { class: "leise" }, "Keine Schritte eingetragen."))),

    r.notizen ? h("section", { class: "notizen" }, h("h2", {}, "Notizen"), h("p", {}, r.notizen)) : null,

    h("p", { class: "leise klein" },
      `Angelegt von ${r.erstellt_von || "?"} am ${datum(r.erstellt)} · zuletzt geändert von ${r.geaendert_von || "?"} am ${datum(r.geaendert)}`)));
}

async function zeigeBearbeiten(id) {
  const r = id ? await api("GET", `/api/rezepte/${id}`) : {};
  const feld = (name, label, wert, attrs = {}) => h("label", {}, label, h("input", { name, value: wert ?? "", ...attrs }));
  const bereich = (name, label, wert, hilfe, zeilen) => h("label", {}, label,
    hilfe ? h("span", { class: "leise klein" }, hilfe) : null,
    h("textarea", { name, rows: zeilen, value: wert ?? "" }));

  const formular = h("form", { class: "formular" },
    feld("titel", "Titel", r.titel, { required: true }),
    h("div", { class: "reihe" },
      feld("portionen", "Portionen", r.portionen, { placeholder: "z. B. 4 Portionen" }),
      feld("zeit_minuten", "Gesamtzeit (Minuten)", r.zeit_minuten, { type: "number", min: 0 }),
      feld("tags", "Tags", (r.tags || []).join(", "), { placeholder: "kommagetrennt, z. B. vegetarisch, schnell" })),
    feld("quelle", "Quelle (URL)", r.quelle, { type: "url" }),
    bereich("beschreibung", "Beschreibung", r.beschreibung, null, 2),
    bereich("zutaten", "Zutaten", (r.zutaten || []).join("\n"), "eine Zutat pro Zeile", 10),
    bereich("schritte", "Zubereitung", (r.schritte || []).join("\n"), "ein Schritt pro Zeile", 12),
    bereich("notizen", "Notizen", r.notizen, "z. B. eigene Anpassungen, Tipps", 4),
    h("div", { class: "aktionen" },
      h("button", { type: "submit" }, "Speichern"),
      h("a", { href: id ? `#/rezept/${id}` : "#/", class: "knopf zweitrangig" }, "Abbrechen")));

  const zeilen = (s) => s.split("\n").map((z) => z.trim()).filter(Boolean);
  const daten = () => {
    const f = new FormData(formular);
    return {
      titel: f.get("titel"), portionen: f.get("portionen"), zeit_minuten: f.get("zeit_minuten"),
      quelle: f.get("quelle"), beschreibung: f.get("beschreibung"), notizen: f.get("notizen"),
      tags: f.get("tags").split(",").map((t) => t.trim()).filter(Boolean),
      zutaten: zeilen(f.get("zutaten")), schritte: zeilen(f.get("schritte")),
    };
  };

  const speichern = async (basis) => {
    try {
      const ergebnis = id
        ? await api("PUT", `/api/rezepte/${id}`, { rezept: daten(), basis })
        : await api("POST", "/api/rezepte", daten());
      meldung("Gespeichert.", "ok");
      location.hash = `#/rezept/${ergebnis.id}`;
    } catch (e) {
      if (e.status === 409 && confirm(`${e.message}\n\nOK = deine Version trotzdem speichern (die andere Änderung geht verloren)\nAbbrechen = weiter bearbeiten`)) {
        return speichern(null);
      }
      meldung(e.message);
    }
  };
  formular.addEventListener("submit", (e) => { e.preventDefault(); speichern(r.geaendert); });

  app.replaceChildren(h("article", { class: "rezept" }, h("h1", {}, id ? "Rezept bearbeiten" : "Neues Rezept"), formular));
}

// ---------------------------------------------------------------- Start

async function route() {
  const m = location.hash.match(/^#\/rezept\/([a-z0-9-]+)(\/bearbeiten)?$/);
  try {
    if (location.hash === "#/neu") await zeigeBearbeiten(null);
    else if (m) await (m[2] ? zeigeBearbeiten(m[1]) : zeigeRezept(m[1]));
    else await zeigeListe();
    window.scrollTo(0, 0);
  } catch (e) {
    meldung(e.message);
    if (e.status === 404) location.hash = "#/";
  }
}

function zeigeNutzer() {
  $("#nutzer-btn").textContent = "👤 " + config.nutzer;
  $("#fuss").textContent = "Datenordner: " + config.datenordner;
}

$("#nutzer-btn").addEventListener("click", async () => {
  const name = prompt("Unter welchem Namen bewertest und bearbeitest du Rezepte?", config.nutzer);
  if (!name || !name.trim()) return;
  try {
    config = await api("PUT", "/api/config", { nutzer: name.trim() });
    zeigeNutzer();
    route();
  } catch (e) { meldung(e.message); }
});

$("#import-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const knopf = $("button", e.target);
  knopf.disabled = true;
  knopf.textContent = "Importiere …";
  try {
    const r = await api("POST", "/api/import", { url: $("#import-url").value });
    $("#import-url").value = "";
    meldung(`„${r.titel}“ importiert.`, "ok");
    location.hash = `#/rezept/${r.id}`;
  } catch (err) {
    meldung(err.message);
  } finally {
    knopf.disabled = false;
    knopf.textContent = "Importieren";
  }
});

window.addEventListener("hashchange", route);
api("GET", "/api/config").then((c) => { config = c; zeigeNutzer(); route(); }, (e) => meldung(e.message));
