#!/usr/bin/env python3
"""HomoloBase Update-Check.

Fragt frei zugängliche amtliche Quellen ab und schreibt data/updates.json:
  - eCFR (49 CFR 571): Datum der letzten Änderung je FMVSS
  - Federal Register: NHTSA-Regeln und Regelentwürfe zu FMVSS
  - EU-Amtsblatt (CELLAR SPARQL): veröffentlichte UN-Regelungen und EU-Typgenehmigungsrecht
Nur Python-Standardbibliothek. Die Datei wird nur neu geschrieben, wenn sich Einträge ändern.
"""
import json, os, re, sys, datetime, urllib.request, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "updates.json")
UA = {"User-Agent": "HomoloBase-UpdateCheck/1.0 (+https://homologation.henneberger-projects.de)"}
TODAY = datetime.date.today()
SINCE = TODAY - datetime.timedelta(days=730)

# UN-Regelung -> Modul
UN = {"0":"modul1","6":"licht","7":"licht","10":"hv","12":"passiv","13":"bremse","13-H":"bremse","14":"rueckhalte","16":"rueckhalte",
 "17":"rueckhalte","19":"licht","23":"licht","28":"fanfare","30":"reifen","38":"licht","39":"tacho","44":"rueckhalte","46":"sicht",
 "48":"licht","51":"geraeusch","54":"reifen","64":"notrad","79":"adas","87":"licht","89":"begrenzer","94":"passiv","95":"passiv",
 "98":"licht","100":"hv","108":"reifen","109":"reifen","112":"licht","113":"licht","117":"reifen","121":"anzeige","122":"heizung",
 "123":"licht","125":"sicht","127":"passiv","128":"licht","129":"rueckhalte","130":"adas","131":"adas","135":"passiv","137":"passiv",
 "138":"geraeusch","139":"bremse","140":"bremse","141":"tpms","142":"reifen","144":"ecall","145":"rueckhalte","148":"licht",
 "149":"licht","150":"licht","151":"sicht","152":"adas","153":"passiv","155":"cyber","156":"cyber","157":"adas","158":"sicht",
 "159":"sicht","160":"adas","166":"sicht","171":"adas"}
# FMVSS -> Modul
FM = {"101":"anzeige","102":"getriebe","103":"entfrostung","104":"wischer","105":"bremse","108":"licht","109":"reifen","110":"reifen",
 "111":"sicht","114":"getriebe","119":"reifen","126":"bremse","127":"adas","135":"bremse","138":"tpms","139":"reifen","141":"geraeusch",
 "201":"passiv","207":"rueckhalte","208":"passiv","209":"rueckhalte","210":"rueckhalte","213":"rueckhalte","213a":"rueckhalte",
 "214":"passiv","216":"passiv","225":"rueckhalte","226":"passiv","301":"passiv","305":"hv","305a":"hv"}
NAMES = {"101":"Controls and displays","102":"Transmission shift sequence","103":"Windshield defrosting","104":"Windshield wiping and washing",
 "105":"Hydraulic and electric brake systems","108":"Lamps and reflective devices","109":"New pneumatic tires","110":"Tire selection and rims",
 "111":"Rear visibility","114":"Theft protection and rollaway prevention","126":"Electronic stability control","127":"Automatic emergency braking",
 "135":"Light vehicle brake systems","138":"Tire pressure monitoring systems","139":"New pneumatic radial tires","141":"Minimum sound requirements",
 "207":"Seating systems","208":"Occupant crash protection","209":"Seat belt assemblies","210":"Seat belt assembly anchorages",
 "213":"Child restraint systems","214":"Side impact protection","225":"Child restraint anchorage systems","301":"Fuel system integrity",
 "305":"Electric-powered vehicles: electrolyte spillage and electrical shock protection"}

def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def modules_from_text(t):
    mods = set()
    for m in re.finditer(r"(?:UN[- ]?Regelung|UN[- ]?Regulation|Regelung|Regulation)\s*(?:Nr\.?|No\.?)\s*(\d+)(-H)?", t, re.I):
        k = m.group(1) + ("-H" if m.group(2) else "")
        if k in UN: mods.add(UN[k])
        elif m.group(1) in UN: mods.add(UN[m.group(1)])
    for m in re.finditer(r"(?:FMVSS|Standard)\s*(?:No\.?|Nos\.?)?\s*(\d{3}a?)", t, re.I):
        if m.group(1) in FM: mods.add(FM[m.group(1)])
    return sorted(mods)

def src_ecfr(items):
    n = 0
    for sec in FM:
        if sec in ("213a","305a","119","201","216","226"): continue
        try:
            v = get("https://www.ecfr.gov/api/versioner/v1/versions/title-49.json?part=571&section=571.%s" % sec)
        except Exception:
            continue
        cv = [c for c in v.get("content_versions", []) if not c.get("removed")]
        if not cv: continue
        last = max(cv, key=lambda c: c.get("amendment_date") or c.get("date"))
        subst = [c for c in cv if c.get("substantive")]
        lsub = max(subst, key=lambda c: c.get("amendment_date") or c.get("date")) if subst else None
        d = (lsub or last).get("amendment_date") or (lsub or last).get("date")
        items.append({"id": "ecfr-571.%s-%s" % (sec, d), "source": "eCFR", "kind": "Rechtsstand",
            "date": d, "title": "FMVSS %s – %s: letzte %sÄnderung im eCFR" % (sec, NAMES.get(sec, ""), "inhaltliche " if lsub else ""),
            "url": "https://www.ecfr.gov/current/title-49/subtitle-B/chapter-V/part-571/section-571.%s" % sec,
            "modules": [FM[sec]], "market": "USA"})
        n += 1
    return n

def src_fedreg(items):
    n = 0
    q = {"conditions[agencies][]": "national-highway-traffic-safety-administration",
         "conditions[term]": '"Motor Vehicle Safety Standard"',
         "conditions[type][]": ["RULE", "PRORULE"],
         "conditions[publication_date][gte]": SINCE.isoformat(),
         "order": "newest", "per_page": "100",
         "fields[]": ["title", "publication_date", "html_url", "type", "document_number", "abstract", "effective_on"]}
    url = "https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q, doseq=True)
    for _ in range(3):
        data = get(url)
        for d in data.get("results", []):
            text = (d.get("title") or "") + " " + (d.get("abstract") or "")
            if re.search(r"exemption|petition for (temporary )?exemption|inconsequential noncompliance", d.get("title",""), re.I):
                continue
            kind = "Regelentwurf (NPRM)" if d.get("type") == "Proposed Rule" else "Regel (Final Rule)"
            items.append({"id": "fr-" + d["document_number"], "source": "Federal Register", "kind": kind,
                "date": d["publication_date"], "title": d["title"], "url": d["html_url"],
                "summary": (d.get("abstract") or "")[:400], "effective": d.get("effective_on"),
                "modules": modules_from_text(text), "market": "USA"})
            n += 1
        url = data.get("next_page_url")
        if not url: break
    return n

SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
def sparql(q):
    return get(SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "application/sparql-results+json"}), timeout=120)["results"]["bindings"]

def src_eu(items):
    n = 0
    base = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title WHERE {
 ?work cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date .
 FILTER(%s && ?date >= "%s"^^xsd:date)
 ?exp cdm:expression_belongs_to_work ?work ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/DEU> ; cdm:expression_title ?title .
 %s
} ORDER BY DESC(?date) LIMIT 150"""
    q1 = base % ('STRSTARTS(STR(?celex),"42")', SINCE.isoformat(), 'FILTER(REGEX(STR(?title),"Regelung Nr|Regelung der Wirtschaftskommission","i"))')
    q2 = base % ('(STRSTARTS(STR(?celex),"32") || STRSTARTS(STR(?celex),"52"))', SINCE.isoformat(),
                 'FILTER(REGEX(STR(?title),"Typgenehmigung|Kraftfahrzeug|2018/858|2019/2144|UN-Regelung","i"))')
    seen = set()
    for q, kind in ((q1, "UN-Regelung im EU-Amtsblatt"), (q2, "EU-Rechtsakt")):
        for b in sparql(q):
            celex = b["celex"]["value"]
            if celex in seen: continue
            seen.add(celex)
            title = re.sub(r"\s+", " ", b["title"]["value"]).strip()
            if kind == "EU-Rechtsakt" and celex.startswith("52") and not re.search(r"Typgenehmigung|Kraftfahrzeug", title): continue
            if kind == "UN-Regelung im EU-Amtsblatt" and re.search(r"Vertreter der Regierungen|Entschließung", title): continue
            items.append({"id": "eu-" + celex, "source": "EU-Amtsblatt", "kind": kind if not celex.startswith("52") else "EU-Vorschlag / Mitteilung",
                "date": b["date"]["value"][:10], "title": title[:300],
                "url": "https://eur-lex.europa.eu/legal-content/DE/TXT/?uri=CELEX:" + celex,
                "modules": modules_from_text(title), "market": "EU"})
            n += 1
    return n

def main():
    old = {}
    try:
        with open(OUT, encoding="utf-8") as f: prev = json.load(f)
        old = {i["id"]: i for i in prev.get("items", [])}
    except Exception:
        prev = {}
    items, status = [], {}
    for name, fn in (("eCFR", src_ecfr), ("Federal Register", src_fedreg), ("EU-Amtsblatt", src_eu)):
        try:
            status[name] = {"ok": True, "count": fn(items)}
        except Exception as e:
            status[name] = {"ok": False, "error": str(e)[:200]}
            # Quelle ausgefallen: alte Einträge dieser Quelle behalten
            items += [i for i in old.values() if i.get("source") == name]
    uniq = {}
    for i in items:
        i["firstSeen"] = old.get(i["id"], {}).get("firstSeen") or (i["date"] if not old else TODAY.isoformat())
        uniq[i["id"]] = i
    items = sorted(uniq.values(), key=lambda i: (i["date"], i["id"]), reverse=True)
    changed = [ (i["id"], i["date"], i["title"]) for i in items ] != [ (i["id"], i["date"], i["title"]) for i in prev.get("items", []) ] \
              or {k: v.get("ok") for k, v in status.items()} != {k: v.get("ok") for k, v in prev.get("sources", {}).items()}
    if not changed and "--force" not in sys.argv:
        print("keine Änderungen"); return
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "since": SINCE.isoformat(), "sources": status, "items": items}, f, ensure_ascii=False, indent=1)
    print("geschrieben:", len(items), "Einträge", status)

if __name__ == "__main__":
    main()
