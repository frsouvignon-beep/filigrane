#!/bin/zsh
# ============================================================================
# Nettoyer_Bookys.command
# ----------------------------------------------------------------------------
# Lanceur macOS (double-clic depuis le Bureau) pour la purge des filigranes
# "Bookys" et "FCK HMS" dans les PDF du dossier :
#   /Users/francoissouvignon/Desktop/generateur_bbcode/magazines/
# ============================================================================

# Positionnement dans le dossier de l'application
cd /Users/francoissouvignon/Desktop/generateur_bbcode/

echo "============================================================"
echo " NETTOYAGE GLOBAL — Purge des filigranes PDF"
echo "============================================================"
echo ""

# 1) Vérification de la présence de python3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERREUR] 'python3' est introuvable sur ce Mac."
    read "?Appuyez sur Entrée pour quitter..."
    exit 1
fi

# 2) Vérification de la bibliothèque PyMuPDF
if ! python3 -c "import fitz" >/dev/null 2>&1; then
    echo "[INFO] Bibliothèque 'pymupdf' absente — installation..."
    pip3 install pymupdf
    if [ $? -ne 0 ]; then
        echo "[ERREUR] Échec de l'installation de pymupdf."
        read "?Appuyez sur Entrée pour quitter..."
        exit 1
    fi
fi

# 3) Exécution du script de purge unifié
python3 purge_bookys.py
CODE=$?

echo ""

# 4) Notification visuelle et sonore de fin de traitement
afplay /System/Library/Sounds/Glass.aiff &
osascript -e 'display notification "Purge des filigranes terminée !" with title "Nettoyer_Bookys" sound name "Glass"'

if [ $CODE -eq 0 ]; then
    echo ">>> Traitement terminé avec succès !"
    echo ">>> Les PDF propres sont disponibles dans votre dossier : Téléchargements"
else
    echo ">>> Traitement terminé avec des erreurs (code ${CODE})."
fi

read "?Appuyez sur Entrée pour fermer la fenêtre..."
exit $CODE
