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

# Configuration de l'architecture source (Mac de François)
DOSSIER_RACINE = "/Users/francoissouvignon/Desktop/generateur_bbcode"
DOSSIER_MAGAZINES = os.path.join(DOSSIER_RACINE, "magazines")

# DOSSIER DE DESTINATION MODIFIÉ : Répertoire Téléchargements de l'utilisateur
DOSSIER_SORTIE = os.path.expanduser("~/Downloads")

if not os.path.isdir(DOSSIER_MAGAZINES):
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _alt = os.path.join(_script_dir, "magazines")
    if os.path.isdir(_alt):
        DOSSIER_RACINE = _script_dir
        DOSSIER_MAGAZINES = _alt

# Configuration motifs Bookys
MOTIFS_TEXTE = ["Bookys", "bookys", "BOOKYS", "Bookys-gratuit", "bookys-gratuit", "Bookys gratuit", "bookys-ebooks", "bookys-ebooks.com", "ebooks.com", "-ebooks.com"]
MOTIFS_URL = ["bookys.me", "www.bookys.me", "bookys.net", "www.bookys.net", "bookys.org", "bookys.co", "bookys.io", "http://bookys", "https://bookys", "ww3.bookys", "ww2.bookys"]
TOUS_MOTIFS = MOTIFS_TEXTE + MOTIFS_URL
_JETON_RE = rb"(?<![A-Za-z0-9_.+-])re(?![A-Za-z0-9_.+-])"

# Marqueurs connus du filigrane "FCK HMS" (Kiosk/Fifi). Le nom de la balise de
# marked-content a évolué au fil des versions : on reconnait toute variante
# /KioskFifi* (ex. ancien "/KioskFifiMark Do" ou nouveau "/KioskFifiLogo BMC ... EMC").
_FIFI_TAG_RE = rb"Kiosk[Ff]ifi\w*"

def _balance_q(s: bytes) -> bool:
    """Vérifie l'équilibre des opérateurs q/Q (sauvegarde/restauration d'état)."""
    profondeur = 0
    for m in re.finditer(rb"(?<![A-Za-z0-9_./])(q|Q)(?![A-Za-z0-9_./])", s):
        profondeur += 1 if m.group(1) == b"q" else -1
        if profondeur < 0:
            return False
    return profondeur == 0

def purger_kioskfifi_mark(doc) -> int:
    """Module de neutralisation chirurgicale du filigrane KioskFifi (FCK HMS).

    Nouvelle architecture (2026) : le filigrane est un bloc de marked-content
        /KioskFifiLogo BMC  q  <cm>  /Xnn Do  Q  EMC
    présent deux fois par page (coins opposés). On supprime le bloc complet
    (BMC...EMC, opérateurs q/Q inclus) — le contenu originel (texte/images)
    n'est pas touché. La compatibilité avec l'ancien format
    "/KioskFifiMark Do" est conservée.
    """
    bloc_re = re.compile(rb"/(" + _FIFI_TAG_RE + rb")\s+BMC\b.*?\bEMC", re.S)
    do_re = re.compile(rb"/(" + _FIFI_TAG_RE + rb")\s+Do")
    nb_blocs = 0
    pages_touchees = set()

    # Balayage de tous les flux (streams) du document : content streams des
    # pages ET XObjects éventuels — bien plus robuste que le codage en dur
    # d'un xref (l'ancien « update_stream(4458) » ne correspond plus à rien).
    for x in range(1, doc.xref_length()):
        if not doc.xref_is_stream(x):
            continue
        try:
            stream = doc.xref_stream(x)
        except Exception:
            continue
        if b"Fifi" not in stream:
            continue
        nouveau, n_blocs = bloc_re.subn(b"", stream)
        nouveau, n_do = do_re.subn(b"", nouveau)
        n = n_blocs + n_do
        if n and nouveau != stream:
            # Garde-fou : ne jamais écrire un flux dont l'équilibre q/Q serait
            # rompu (le bloc BMC...EMC contient son propre q...Q, mais on
            # vérifie au cas où le schéma changerait encore).
            if not _balance_q(nouveau) and _balance_q(stream):
                continue
            try:
                doc.update_stream(x, nouveau)
                nb_blocs += n
            except Exception:
                continue

    if nb_blocs:
        for page_num in range(len(doc)):
            page = doc[page_num]
            for content_xref in page.get_contents():
                try:
                    if b"Fifi" in doc.xref_stream_raw(content_xref):
                        pages_touchees.add(page_num)
                except Exception:
                    continue
    return len(pages_touchees) if pages_touchees else (len(doc) if nb_blocs else 0)

def motif_interdit(url: str) -> bool:
    if not url: return False
    u = url.lower()
    return any(m.lower() in u for m in MOTIFS_URL) or "bookys" in u

def _dessin_dangereux(dessin: dict) -> bool:
    try:
        rect = dessin.get("rect")
        if rect is None: return False
        couleur_contour = None
        couleur_fill = None
        try: couleur_contour = dessin.get("color")
        except Exception: couleur_contour = None
        try: couleur_fill = dessin.get("fill")
        except Exception: couleur_fill = None

        def _est_noire(coul: Optional[Tuple[float, ...]]) -> bool:
            if coul is None: return False
            try: return all(float(v) < 0.15 for v in coul[:3])
            except (TypeError, ValueError, IndexError): return False

        if not (_est_noire(couleur_contour) or _est_noire(couleur_fill)): return False
        largeur, hauteur = float(rect.width), float(rect.height)
        fin = float(dessin.get("width") or 0.0) <= 1.5
        return (largeur > 300 and hauteur > 30) or (fin and (largeur > 200 or hauteur > 200))
    except Exception: return False

def _decouper_groupements(brut: bytes) -> List[bytes]:
    tokens: List[bytes] = []
    positions: List[int] = []
    precedent = 0
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

    blocs: List[bytes] = []
    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        if t == b"q":
            debut_tok = i
            profondeur = 0
            j = i
            fin_tok = None
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
    resultats: List[Tuple[float, float, float, float]] = []
    for m in re.finditer(_JETON_RE, bloc):
        prefixe = bloc[:m.start()]
        try:
            champs = prefixe.split()
            if len(champs) < 4: continue
            vals = [float(c) for c in champs[-4:]]
            resultats.append((vals[0], vals[1], vals[2], vals[3]))
        except ValueError: continue
    return resultats

def nettoyer_page_bookys(page) -> int:
    nb_suppr = 0
    for motif in TOUS_MOTIFS:
        try: rect_list = page.search_for(motif)
        except Exception: rect_list = []
        for rect in rect_list:
            zone = fitz.Rect(rect.x0 - 2, rect.y0 - 2, rect.x1 + 2, rect.y1 + 2)
            page.add_redact_annot(zone)
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
            xref_data = ""
            if annot.type == 2: xref_data = str(page.parent.xref_get_key(annot.xref, "A"))
            if "bookys" in contenu or motif_interdit(xref_data):
                page.delete_annot(annot)
                nb_suppr += 1
        except Exception: pass
        annot = suivant

    vecteurs_dangereux = []
    if nb_suppr > 0 or "bookys" in page.get_text("text").lower():
        try: dessins = page.get_drawings()
        except Exception: dessins = []
        for dessin in dessins:
            try:
                if _dessin_dangereux(dessin): vecteurs_dangereux.append(dessin)
            except Exception: continue

    if vecteurs_dangereux:
        try:
            xrefs = list(page.get_contents())
            if xrefs:
                brut = page.read_contents()
                if brut:
                    blocs = _decouper_groupements(brut)
                    zones_coupees = []
                    ph = page.rect.height
                    for d in vecteurs_dangereux:
                        r = d.get("rect")
                        if r is not None: zones_coupees.append(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1))
                    nouveau = []
                    modifie = False
                    for bloc in blocs:
                        couper = False
                        if b" re" in bloc or b"\nre" in bloc:
                            for x, y, w, h in _operateurs_re(bloc):
                                rect_pdf = fitz.Rect(x, ph - (y + h), x + w, ph - y)
                                if any(z.intersects(rect_pdf) for z in zones_coupees): couper = True; break
                        if couper: modifie = True; nb_suppr += 1
                        else: nouveau.append(bloc)
                    if modifie:
                        page.set_contents(xrefs[0], b"".join(nouveau))
                        for xref_surplus in xrefs[1:]:
                            try: page.set_contents(xref_surplus, b" ")
                            except Exception: pass
        except Exception: pass
    return nb_suppr

def nettoyer_pdf(chemin: str, dossier_sortie: Optional[str] = None) -> bool:
    nom = os.path.basename(chemin)
    if dossier_sortie is None:
        dossier_sortie = DOSSIER_SORTIE
        # Si le PDF à traiter se trouve déjà dans le dossier de sortie, on écrit
        # à côté avec le suffixe « _purge » pour éviter d'écraser l'original.
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
    if purgé_fifi > 0:
        print(f"    - Module KioskFifiMark : Filigrane effacé sur {purgé_fifi} page(s).")

    total_bookys = 0
    for page in doc:
        try: total_bookys += nettoyer_page_bookys(page)
        except Exception: continue

    if total_bookys > 0:
        print(f"    - Module Bookys : {total_bookys} élément(s) d'arrière-plan purgé(s).")
    if purgé_fifi == 0 and total_bookys == 0:
        print(f"  [OK]     '{nom}' : aucun filigrane connu détecté (copie propre).")

    try: doc.save(sortie, garbage=4, deflate=True, clean=True)
    except Exception: doc.save(sortie, garbage=1, deflate=True)
    doc.close()
    print(f"  [SAUVEGARDE] -> {sortie}")
    return True

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    # Mode « fichiers explicites » : python3 purge_bookys.py fichier1.pdf [dossier_sortie]
    if args and (args[0].lower().endswith(".pdf") or os.path.isdir(args[0])):
        fichiers = [a for a in args if os.path.isfile(a) and a.lower().endswith(".pdf")]
        dossier_out = next((a for a in args if os.path.isdir(a)), None) or DOSSIER_SORTIE
        if not fichiers:
            print("[ERREUR] Aucun fichier PDF valide passé en argument.")
            sys.exit(1)
        os.makedirs(dossier_out, exist_ok=True)
        print(f"{len(fichiers)} fichier(s) PDF à traiter -> {dossier_out}\n")
        succes = 0
        for idx, chemin in enumerate(fichiers, start=1):
            print(f"[{idx}/{len(fichiers)}] Nettoyage de : {os.path.basename(chemin)}")
            if _nettoyer_pdf(chemin, os.path.join(dossier_out, os.path.basename(chemin))):
                succes += 1
        print("-" * 60)
        print(f"TERMINÉ : {succes} PDF traité(s) avec succès.")
        sys.exit(0 if succes == len(fichiers) else 2)

    # Mode historique : traitement du dossier « magazines »
    print("=" * 60)
    print(" PURGE UNIFIÉE DES FILIGRANES MULTI-SOURCES — macOS")
    print("=" * 60)
    print(f"Dossier source   : {DOSSIER_MAGAZINES}")
    print(f"Dossier de sortie: {DOSSIER_SORTIE}")
    print()

    if not os.path.isdir(DOSSIER_MAGAZINES):
        print(f"[ERREUR] Le dossier 'magazines' est introuvable.")
        sys.exit(1)

    os.makedirs(DOSSIER_SORTIE, exist_ok=True)
    motifs_glob = [glob.glob(os.path.join(DOSSIER_MAGAZINES, "*.pdf")), glob.glob(os.path.join(DOSSIER_MAGAZINES, "*.PDF"))]
    fichiers = sorted({f for grp in motifs_glob for f in grp if os.path.isfile(f)})

    if not fichiers:
        print(f"\n[AUCUN FICHIER] Aucun PDF dans : {DOSSIER_MAGAZINES}")
        sys.exit(0)

    print(f"{len(fichiers)} fichier(s) PDF détecté(s) :\n")
    succes = 0
    for idx, chemin in enumerate(fichiers, start=1):
        nom = os.path.basename(chemin)
        print(f"[{idx}/{len(fichiers)}] Nettoyage de : {nom}")
        if nettoyer_pdf(chemin): succes += 1

    print("-" * 60)
    print(f"TERMINÉ : {succes} PDF traité(s) avec succès.")
    print("-" * 60)

if __name__ == "__main__":
    main()
