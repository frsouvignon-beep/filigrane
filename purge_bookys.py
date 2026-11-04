#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import sys
import glob
from typing import List, Optional, Tuple

try:
    import fitz  # bibliothèque PyMuPDF
except ImportError:
    print("[ERREUR] La bibliothèque 'PyMuPDF' est introuvable.")
    sys.exit(1)

DOSSIER_RACINE = "/Users/francoissouvignon/Desktop/generateur_bbcode"
DOSSIER_MAGAZINES = os.path.join(DOSSIER_RACINE, "magazines")
DOSSIER_SORTIE = os.path.expanduser("~/Downloads")

if not os.path.isdir(DOSSIER_MAGAZINES):
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _alt = os.path.join(_script_dir, "magazines")
    if os.path.isdir(_alt):
        DOSSIER_RACINE = _script_dir
        DOSSIER_MAGAZINES = _alt

MOTIFS_TEXTE = ["Bookys", "bookys", "BOOKYS", "Bookys-gratuit", "bookys-gratuit", "Bookys gratuit", "bookys-ebooks", "bookys-ebooks.com", "ebooks.com", "-ebooks.com"]
MOTIFS_URL = ["bookys.me", "www.bookys.me", "bookys.net", "www.bookys.net", "bookys.org", "bookys.co", "bookys.io", "http://bookys", "https://bookys", "ww3.bookys", "ww2.bookys"]
TOUS_MOTIFS = MOTIFS_TEXTE + MOTIFS_URL
_JETON_RE = rb"(?<![A-Za-z0-9_.+-])re(?![A-Za-z0-9_.+-])"
_NUM = rb"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?"
_OPS_SANS_OPERANDES = {b"n", b"v", b"y", b"h", b"G", b"g", b"RG", b"rg", b"K", b"k", b"gs", b"ri", b"i", b"j", b"J", b"w"}

def _get_area(r: fitz.Rect) -> float:
    """Calcul universel et robuste de la surface d'un fitz.Rect."""
    if r is None or not hasattr(r, "x0"): return 0.0
    w = r.x1 - r.x0
    h = r.y1 - r.y0
    return float(w * h) if (w > 0 and h > 0) else 0.0

def _parse_bbox(chaine: bytes) -> Optional[fitz.Rect]:
    vals = [float(v) for v in re.findall(_NUM, chaine)]
    if len(vals) >= 4:
        return fitz.Rect(min(vals[0], vals[2]), min(vals[1], vals[3]), max(vals[0], vals[2]), max(vals[1], vals[3]))
    return None

def _resoudre_xobjects(doc, xref: int) -> dict:
    resultat = {}
    try: val = doc.xref_get_key(xref, "Resources/XObject")
    except Exception: return resultat
    if val[0] != "dict": return resultat
    for nom, cible in re.findall(rb"/([A-Za-z0-9_.+-]+)\s+(\d+)\s+\d+\s+R", val[1].encode()):
        try: sub = doc.xref_get_key(int(cible), "Subtype")[1]
        except Exception: sub = ""
        resultat[nom.decode()] = (int(cible), sub)
    return resultat

def _transform_pts(matrice, coins):
    a, b, c, d, e, f = matrice
    return [(a * x + c * y + e, b * x + d * y + f) for (x, y) in coins]

def _rect_from_pts(pts):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))

def _contenu_reel_form(doc, xref: int, matrice, profondeur: int = 0):
    if profondeur > 8: return None, None
    try: flux = doc.xref_stream(xref)
    except Exception: return None, None
    flux = re.sub(rb"(?<=[a-zA-Z])(?=/)", b" ", flux)
    xo = _resoudre_xobjects(doc, xref)
    try: bb = _parse_bbox(doc.xref_get_key(xref, "BBox")[1].encode())
    except Exception: bb = None
    if bb is None or bb.is_empty: bb = fitz.Rect(0, 0, 1, 1)

    reels = []
    union = fitz.Rect()
    pile = []
    ct = list(matrice)
    attente = []
    fenetre_locale = fitz.Rect(bb)
    tokens = re.findall(rb"(?:" + _NUM + rb")|[A-Za-z][A-Za-z0-9'\"]*|/[^\s/\[\]<>()]+", flux)
    for tok in tokens:
        if re.fullmatch(_NUM, tok):
            attente.append(float(tok))
            continue
        if tok == b"q": pile.append(list(ct))
        elif tok == b"Q" and pile: ct = pile.pop()
        elif tok == b"cm" and len(attente) >= 6:
            m = attente[-6:]
            a, b_, c_, d_, e_, f_ = ct
            ct = [m[0]*a + m[1]*c_, m[0]*b_ + m[1]*d_, m[2]*a + m[3]*c_, m[2]*b_ + m[3]*d_, m[4]*a + m[5]*c_ + e_, m[4]*b_ + m[5]*d_ + f_]
        elif tok in (b"re", b"m", b"c", b"v", b"l", b"S", b"f", b"F", b"B"): reels.append("vecteur")
        elif tok.startswith(b"/"):
            nom = tok[1:].decode(errors="ignore")
            if nom in xo:
                cxref, subtype = xo[nom]
                if subtype == "/Image":
                    try:
                        w = float(doc.xref_get_key(cxref, "Width")[1])
                        h = float(doc.xref_get_key(cxref, "Height")[1])
                    except Exception: w = h = 1.0
                    pts = _transform_pts(ct, [(0, 0), (w, 0), (w, h), (0, h)])
                    union |= _rect_from_pts(pts)
                    reels.append("image")
                elif subtype == "/Form":
                    try: mv = doc.xref_get_key(cxref, "Matrix")[1]
                    except Exception: mv = ""
                    mm = [float(v) for v in re.findall(_NUM, mv.encode())]
                    if len(mm) != 6: mm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                    a, b_, c_, d_, e_, f_ = ct
                    lm = [mm[0]*a + mm[1]*c_, mm[0]*b_ + mm[1]*d_, mm[2]*a + mm[3]*c_, mm[2]*b_ + mm[3]*d_, mm[4]*a + mm[5]*c_ + e_, mm[4]*b_ + mm[5]*d_ + f_]
                    sous_type, sous_eff = _contenu_reel_form(doc, cxref, lm, profondeur + 1)
                    if sous_type is not None:
                        reels.append(sous_type)
                        if sous_eff is not None: union |= sous_eff
                    else:
                        pts = _transform_pts(lm, [(0, 0), (1, 0), (1, 1), (0, 1)])
                        union |= _rect_from_pts(pts)
                        reels.append("vecteur")
        elif tok == b"W" and len(attente) >= 4 and ct[:4] == [1.0, 0.0, 0.0, 1.0]:
            x0, y0, w0, h0 = attente[-4:]
            r = fitz.Rect(min(x0, x0 + w0), min(y0, y0 + h0), max(x0, x0 + w0), max(y0, y0 + h0))
            inter = r & fenetre_locale
            if not inter.is_empty: fenetre_locale = inter
        
        if tok not in _OPS_SANS_OPERANDES and tok not in (b"re", b"W", b"W*", b"cm"):
            attente = []

    if not reels: return None, None
    eff = None
    if not union.is_empty:
        restreint = union & fenetre_locale
        if restreint is not None:
            coins = [(restreint.x0 - bb.x0, restreint.y0 - bb.y0), (restreint.x1 - bb.x0, restreint.y0 - bb.y0), (restreint.x1 - bb.x0, restreint.y1 - bb.y0), (restreint.x0 - bb.x0, restreint.y1 - bb.y0)]
            eff = _rect_from_pts(_transform_pts(matrice, coins))
        else: eff = fitz.Rect()
    return ("image" if "image" in reels else "vecteur"), (eff if (eff is not None and not eff.is_empty) else None)

def _bbox_visibilite_parent(doc, page) -> fitz.Rect:
    media = page.rect
    try: crop = fitz.Rect(page.cropbox)
    except Exception: crop = media
    r = media & crop
    return r if not r.is_empty else media

def _analyse_invocations(page, nom: str) -> List[Tuple[Optional[fitz.Rect], list]]:
    resultat = []
    try: brut = page.read_contents()
    except Exception: return resultat
    motif = re.compile(rb"/" + re.escape(nom.encode()) + rb"\s+Do")
    jetons_re = rb"(?:" + _NUM + rb")|[A-Za-z][A-Za-z0-9'\"]*|/[^\s/\[\]<>()]+"
    for m in motif.finditer(brut):
        j = brut.rfind(b"q ", 0, m.start())
        if j == -1: j = brut.rfind(b"\nq", 0, m.start())
        k = brut.find(b"Q", m.end())
        if j == -1 or k == -1: continue
        tokens = re.findall(jetons_re, brut[j:m.end()])
        ct = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        pile, clips, attente = [], [], []
        for tok in tokens:
            if re.fullmatch(_NUM, tok):
                attente.append(float(tok))
                continue
            if tok == b"q": pile.append(list(ct))
            elif tok == b"Q" and pile: ct = pile.pop()
            elif tok == b"cm" and len(attente) >= 6:
                mm = attente[-6:]
                a, b_, c_, d_, e_, f_ = ct
                ct = [mm[0]*a + mm[1]*c_, mm[0]*b_ + mm[1]*d_, mm[2]*a + mm[3]*c_, mm[2]*b_ + mm[3]*d_, mm[4]*a + mm[5]*c_ + e_, mm[4]*b_ + mm[5]*d_ + f_]
            elif tok in (b"W", b"W*") and len(attente) >= 4:
                x0, y0, w0, h0 = attente[-4:]
                pts = _transform_pts(ct, [(x0, y0), (x0 + w0, y0), (x0 + w0, y0 + h0), (x0, y0 + h0)])
                clips.append(_rect_from_pts(pts))
            
            if tok not in _OPS_SANS_OPERANDES and tok not in (b"re", b"W", b"W*", b"cm"):
                attente = []
        clip_eff = None
        for r in clips: clip_eff = r if clip_eff is None else (clip_eff & r)
        resultat.append((clip_eff, ct))
    return resultat

def detecter_forms_fantomes(doc) -> set:
    fantomes, invoques = set(), {}
    for page in doc:
        try: xos = page.get_xobjects()
        except Exception: continue
        for entree in xos:
            try: xref, nom = entree[0], entree[1]
            except Exception: continue
            invoques.setdefault(xref, []).append((page, nom))

    infos = {}
    for x in list(invoques):
        try:
            if doc.xref_get_key(x, "Subtype")[1] != "/Form": continue
        except Exception: continue
        try: bb = _parse_bbox(doc.xref_get_key(x, "BBox")[1].encode())
        except Exception: bb = None
        if bb is None or bb.is_empty: continue
        type_contenu, eff_local = _contenu_reel_form(doc, x, [1.0, 0.0, 0.0, 1.0, 0.0, 0.0])
        if type_contenu is None: continue
        infos[x] = (type_contenu, eff_local, bb)
        if type_contenu != "image": continue
        if eff_local is None:
            fantomes.add(x)
            continue
        inter = eff_local & bb
        if inter.is_empty or (_get_area(inter) / max(_get_area(bb), 1e-9)) < 0.01: fantomes.add(x)

    seuil_ratio_page = 0.01
    for xref, occ in invoques.items():
        if xref in fantomes or xref not in infos: continue
        type_contenu, eff_local, bb = infos[xref]
        if type_contenu != "image" or eff_local is None: continue
        if _get_area(eff_local & bb) / max(_get_area(bb), 1e-9) >= 0.90: continue
        tous_infimes = True
        for page, nom in occ:
            aire_page = max(_get_area(page.rect), 1e-9)
            union_visible = None
            invs = _analyse_invocations(page, nom)
            if not invs:
                tous_infimes = False
                break
            for clip_eff, ct in invs:
                pts = _transform_pts(ct, [(eff_local.x0, eff_local.y0), (eff_local.x1, eff_local.y0), (eff_local.x1, eff_local.y1), (eff_local.x0, eff_local.y1)])
                zone = _rect_from_pts(pts)
                if clip_eff is not None: zone &= clip_eff
                zone &= page.rect
                if zone.is_valid and _get_area(zone) > 0: union_visible = zone if union_visible is None else (union_visible | zone)
            if (_get_area(union_visible) if union_visible is not None else 0.0) / aire_page >= seuil_ratio_page:
                tous_infimes = False
                break
        if tous_infimes: fantomes.add(xref)
    return fantomes

def _retirer_dessin_xobject(doc, page, nom: str) -> int:
    cxrefs = list(page.get_contents())
    if not cxrefs: return 0
    brut = page.read_contents()
    motif = re.compile(rb"/(" + re.escape(nom.encode()) + rb")\s+Do")
    occ = 0
    while True:
        m = motif.search(brut)
        if not m: break
        j = brut.rfind(b"q", 0, m.start())
        k = brut.find(b"Q", m.end())
        if j == -1 or k == -1: break
        segment = brut[j:k + 1]
        if len(re.findall(rb"/[A-Za-z0-9_.+-]+\s+Do", segment)) != 1: break
        brut = brut[:j] + b" " + brut[k + 1:]
        occ += 1
    if occ:
        try:
            doc.update_stream(cxrefs[0], brut)
            for surplus in cxrefs[1:]: doc.update_stream(surplus, b" ")
        except Exception: return 0
        try:
            if doc.xref_get_key(page.xref, "Resources/XObject/" + nom)[0] != "null":
                doc.xref_set_key(page.xref, "Resources/XObject/" + nom, "null")
        except Exception: pass
    return occ

def purger_form_fantome(doc) -> int:
    fantomes = detecter_forms_fantomes(doc)
    if not fantomes: return 0
    total = 0
    for page in doc:
        try: xos = page.get_xobjects()
        except Exception: continue
        noms_a_retirer = []
        for entree in xos:
            try: xref, nom = entree[0], entree[1]
            except Exception: continue
            if xref in fantomes: noms_a_retirer.append(nom)
        for nom in noms_a_retirer: total += _retirer_dessin_xobject(doc, page, nom)
    return total

def purger_traces_kiosk(doc) -> int:
    nb = 0
    cat = doc.pdf_catalog()
    try:
        clefs = [k for k in doc.xref_get_keys(cat) if re.search(r"(?i)kiosk|fifi|fck|hms", k)]
        if clefs:
            garde = []
            for k in doc.xref_get_keys(cat):
                if k in clefs: continue
                t, v = doc.xref_get_key(cat, k)
                garde.append("/%s %s" % (k, v))
            doc.update_object(cat, "<< " + " ".join(garde) + " >>")
            nb += len(clefs)
    except Exception: pass
    try:
        meta = dict(doc.metadata or {})
        modif = False
        for champ in ("producer", "creator", "author"):
            val = str(meta.get(champ) or "")
            if re.search(r"(?i)fck|hms|kiosk|fifi", val):
                meta[champ] = ""
                modif = True
        if modif:
            doc.set_metadata(meta)
            nb += 1
    except Exception: pass
    return nb

def _balance_q(s: bytes) -> bool:
    profondeur = 0
    for m in re.finditer(rb"(?<![A-Za-z0-9_./])(q|Q)(?![A-Za-z0-9_./])", s):
        profondeur += 1 if m.group(1) == b"q" else -1
        if profondeur < 0: return False
    return profondeur == 0

def purger_kioskfifi_mark(doc) -> int:
    bloc_re = re.compile(rb"/(Kiosk[Ff]ifi\w*)\s+BMC\b.*?\bEMC", re.S)
    do_re = re.compile(rb"/(Kiosk[Ff]ifi\w*)\s+Do")
    nb_blocs = 0
    for x in range(1, doc.xref_length()):
        if not doc.xref_is_stream(x): continue
        try: stream = doc.xref_stream(x)
        except Exception: continue
        if b"Fifi" not in stream: continue
        nouveau, n_blocs = bloc_re.subn(b"", stream)
        nouveau, n_do = do_re.subn(b"", nouveau)
        n = n_blocs + n_do
        if n and nouveau != stream:
            if not _balance_q(nouveau) and _balance_q(stream): continue
            try:
                doc.update_stream(x, nouveau)
                nb_blocs += n
            except Exception: continue
    return nb_blocs

def motif_interdit(url: str) -> bool:
    if not url: return False
    u = url.lower()
    return any(m.lower() in u for m in MOTIFS_URL) or "bookys" in u

def _dessin_dangereux(dessin: dict) -> bool:
    try:
        rect = dessin.get("rect")
        if rect is None: return False
        couleur_contour, couleur_fill = dessin.get("color"), dessin.get("fill")
        def _est_noire(coul) -> bool:
            if coul is None: return False
            try: return all(float(v) < 0.15 for v in coul[:3])
            except Exception: return False
        if not (_est_noire(couleur_contour) or _est_noire(couleur_fill)): return False
        largeur, hauteur = float(rect.width), float(rect.height)
        fin = float(dessin.get("width") or 0.0) <= 1.5
        return (largeur > 300 and hauteur > 30) or (fin and (largeur > 200 or hauteur > 200))
    except Exception: return False

def _decouper_groupements(brut: bytes) -> List[bytes]:
    tokens, positions, precedent = [], [], 0
    for m in re.finditer(rb"(?<![A-Za-z0-9_.+-])([qQ])(?![A-Za-z0-9_.+-])", brut):
        if m.start() > precedent:
            tokens.append(brut[precedent:m.start()])
            positions.append(precedent)
        tokens.append(m.group(1))
        positions.append(m.start())
        precedent = m.end()
    if precedent < len(brut):
        tokens.append(brut[precedent:])
        positions.append(precedent)

    blocs, i, n = [], 0, len(tokens)
    while i < n:
        if tokens[i] == b"q":
            debut_tok, profondeur, j, fin_tok = i, 0, i, None
            while j < n:
                if tokens[j] == b"q": profondeur += 1
                elif tokens[j] == b"Q":
                    profondeur -= 1
                    if profondeur == 0:
                        fin_tok = j
                        break
                j += 1
            if fin_tok is not None:
                bout = positions[fin_tok] + len(tokens[fin_tok])
                while bout < len(brut) and brut[bout:bout + 1] in (b" ", b"\n"): bout += 1
                blocs.append(brut[positions[debut_tok]:bout])
                i = fin_tok + 1
                continue
        k = i
        while k < n and tokens[k] != b"q": k += 1
        bornes_fin = positions[k] if k < n else len(brut)
        if bornes_fin > positions[i]: blocs.append(brut[positions[i]:bornes_fin])
        i = k if k > i else i + 1
    return blocs if blocs else [brut]

def _operateurs_re(bloc: bytes) -> List[Tuple[float, float, float, float]]:
    resultats = []
    for m in re.finditer(_JETON_RE, bloc):
        try:
            champs = bloc[:m.start()].split()
            if len(champs) < 4: continue
            vals = [float(c) for c in champs[-4:]]
            resultats.append((vals[0], vals[1], vals[2], vals[3]))
        except Exception: continue
    return resultats

def nettoyer_page_bookys(page) -> int:
    nb_suppr = 0
    for motif in TOUS_MOTIFS:
        try: rect_list = page.search_for(motif)
        except Exception: rect_list = []
        for rect in rect_list:
            page.add_redact_annot(fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2))
            nb_suppr += 1
    if nb_suppr > 0:
        try: page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)
        except Exception: page.apply_redactions()

    for lien in list(page.get_links()):
        if motif_interdit(lien.get("uri", "")):
            try: page.delete_link(lien); nb_suppr += 1
            except Exception: pass

    annot = page.first_annot
    while annot:
        suivant = page.next_annot(annot)
        try:
            info = annot.info or {}
            contenu = (str(info.get("content", "")) + " " + str(info.get("title", ""))).lower()
            xref_data = str(page.parent.xref_get_key(annot.xref, "A")) if annot.type == 2 else ""
            if "bookys" in contenu or motif_interdit(xref_data):
                page.delete_annot(annot)
                nb_suppr += 1
        except Exception: pass
        annot = suivant

    vecteurs_dangereux = []
    if nb_suppr > 0 or "bookys" in page.get_text("text").lower():
        try: dessins = page.get_drawings()
        except Exception: dessins = []
        for d in dessins:
            if _dessin_dangereux(d): vecteurs_dangereux.append(d)

    if vecteurs_dangereux and page.get_contents():
        try:
            xrefs = list(page.get_contents())
            brut = page.read_contents()
            if brut:
                blocs = _decouper_groupements(brut)
                zones_coupees = [fitz.Rect(d["rect"].x0 - 1, d["rect"].y0 - 1, d["rect"].x1 + 1, d["rect"].y1 + 1) for d in vecteurs_dangereux if d.get("rect")]
                nouveau, modifie, ph = [], False, page.rect.height
                for b in blocs:
                    couper = False
                    if b" re" in b or b"\nre" in b:
                        for x, y, w, h in _operateurs_re(b):
                            if any(z.intersects(fitz.Rect(x, ph - (y + h), x + w, ph - y)) for z in zones_coupees): couper = True; break
                    if couper: modifie, nb_suppr = True, nb_suppr + 1
                    else: nouveau.append(b)
                if modifie:
                    page.set_contents(xrefs[0], b"".join(nouveau))
                    for xs in xrefs[1:]: page.set_contents(xs, b" ")
        except Exception: pass
    return nb_suppr

def nettoyer_pdf(chemin: str, dossier_sortie: Optional[str] = None) -> bool:
    nom = os.path.basename(chemin)
    if dossier_sortie is None:
        dossier_sortie = DOSSIER_SORTIE
        if os.path.dirname(os.path.abspath(chemin)) == os.path.abspath(dossier_sortie):
            base, ext = os.path.splitext(nom)
            return _nettoyer_pdf(chemin, os.path.join(dossier_sortie, f"{base}_purge{ext}"))
    return _nettoyer_pdf(chemin, os.path.join(dossier_sortie, nom))

def _nettoyer_pdf(chemin: str, sortie: str) -> bool:
    nom = os.path.basename(chemin)
    try: doc = fitz.open(chemin)
    except Exception as e:
        print(f"  [ERREUR] Impossible d'ouvrir '{nom}' : {e}")
        return False
    if doc.needs_pass:
        print(f"  [SKIP]   '{nom}' est protégé par mot de passe, ignoré.")
        doc.close()
        return False

    purgé_fifi = purger_kioskfifi_mark(doc)
    if purgé_fifi > 0: print(f"    - Module KioskFifiMark (historique) : {purgé_fifi} bloc(s) neutralisé(s).")
    fantomes_neutres = purger_form_fantome(doc)
    if fantomes_neutres > 0: print(f"    - Module FormFantôme : {fantomes_neutres} filigrane(s) FCK HMS neutralisé(s).")
    traces_doc = purger_traces_kiosk(doc)
    if traces_doc > 0: print(f"    - Module TracesKiosk : {traces_doc} trace(s) documentaire(s) purgée(s).")

    total_bookys = 0
    for page in doc:
        try: total_bookys += nettoyer_page_bookys(page)
        except Exception: continue
    if total_bookys > 0: print(f"    - Module Bookys : {total_bookys} élément(s) d'arrière-plan purgé(s).")
    if purgé_fifi == 0 and total_bookys == 0 and fantomes_neutres == 0 and traces_doc == 0:
        print(f"  [OK]     '{nom}' : aucun filigrane connu détecté (copie propre).")

    try: doc.save(sortie, garbage=4, deflate=True, clean=True)
    except Exception: doc.save(sortie, garbage=1, deflate=True)
    doc.close()
    print(f"  [SAUVEGARDE] -> {sortie}")
    return True

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and (args[0].lower().endswith(".pdf") or os.path.isdir(args[0])):
        fichiers = [a for a in args if os.path.isfile(a) and a.lower().endswith(".pdf")]
        dossier_out = next((a for a in args if os.path.isdir(a)), None) or DOSSIER_SORTIE
        if not fichiers:
            print("[ERREUR] Aucun fichier PDF valide passé en argument.")
            sys.exit(1)
        os.makedirs(dossier_out, exist_ok=True)
        succes = 0
        for idx, chemin in enumerate(fichiers, start=1):
            if _nettoyer_pdf(chemin, os.path.join(dossier_out, os.path.basename(chemin))): succes += 1
        sys.exit(0 if succes == len(fichiers) else 2)

    print("=" * 60)
    print(" PURGE UNIFIÉE DES FILIGRANES MULTI-SOURCES — macOS")
    print("=" * 60)
    if not os.path.isdir(DOSSIER_MAGAZINES):
        print(f"[ERREUR] Le dossier 'magazines' est introuvable.")
        sys.exit(1)
    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    fichiers = sorted({f for grp in [glob.glob(os.path.join(DOSSIER_MAGAZINES, "*.pdf")), glob.glob(os.path.join(DOSSIER_MAGAZINES, "*.PDF"))] for f in grp if os.path.isfile(f)})
    if not fichiers:
        print(f"\n[AUCUN FICHIER] Aucun PDF dans : {DOSSIER_MAGAZINES}")
        sys.exit(0)
    succes = 0
    for idx, chemin in enumerate(fichiers, start=1):
        if nettoyer_pdf(chemin): succes += 1
    print("-" * 60)
    print(f"TERMINÉ : {succes} PDF traité(s) avec succès.")

if __name__ == "__main__":
    main()
