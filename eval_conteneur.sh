#!/usr/bin/env bash
# Campagnes d'évaluation exécutées dans l'environnement de déploiement.
#
# Pourquoi ce script : les campagnes qui mobilisent CamemBERT ne peuvent tourner
# que dans le conteneur (torch et transformers n'y sont installés que là), alors
# que les autres tournaient sur le poste de développement. Deux versions de
# Tesseract et deux compilations d'OpenCV donnent deux taux d'erreur différents
# sur les mêmes images — mesuré : 0,151 contre 0,428 sous bruit. Les chiffres ne
# sont donc comparables entre eux que si toutes les campagnes partagent le même
# environnement, et c'est celui du déploiement qui compte.
#
# Le script s'ancre sur sa propre position : il est indifférent au répertoire
# courant. Placez-le dans `sources/` et lancez-le de n'importe où.
#
#   chmod +x sources/eval_conteneur.sh
#   ./sources/eval_conteneur.sh
#
# Les sorties vont dans des sous-dossiers distincts plutôt que d'écraser les
# fichiers existants ou d'être renommées après coup : la provenance de chaque
# chiffre reste lisible.
#
#     evaluation/resultats/conteneur/            spaCy + campagne OCR
#     evaluation/resultats/conteneur-camembert/  configuration retenue

set -euo pipefail

S="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORPUS="$S/corpus/data"
RESULTATS="$S/ai-engine/evaluation/resultats"

for chemin in "$CORPUS/annotations.jsonl" "$CORPUS/scans/index.jsonl"; do
  [ -f "$chemin" ] || { echo "Absent : $chemin" >&2; exit 1; }
done
mkdir -p "$RESULTATS"

echo "Corpus    : $CORPUS"
echo "Résultats : $RESULTATS"
echo

executer() {
  local titre="$1"; shift
  echo "══════ $titre"
  docker compose -f "$S/docker-compose.yml" --project-directory "$S" run --rm --no-deps \
    -v "$CORPUS:/data:ro" \
    -v "$RESULTATS:/srv/evaluation/resultats" \
    "$@"
  echo
}

docker compose -f "$S/docker-compose.yml" --project-directory "$S" build moteur-ia

# 1. OCR seul. Aucun modèle chargé : c'est l'instrument de mesure du CER,
#    désormais exécuté là où le système tournera.
executer "OCR — CER par condition" \
  moteur-ia python -m evaluation.run_ocr_eval \
    --index /data/scans/index.jsonl \
    --sortie evaluation/resultats/conteneur

# 2. Les trois configurations de référence. `--backend spacy` est explicite :
#    le service a CamemBERT par défaut, ce qui fausserait la ligne « NER seule ».
executer "Détection — règles, NER, fusion (spaCy)" \
  moteur-ia python -m evaluation.run_detection_eval \
    --annotations /data/annotations.jsonl --partition test \
    --backend spacy --configurations regles,ner,fusion \
    --sortie evaluation/resultats/conteneur

# 3. La configuration retenue.
executer "Détection — fusion + CamemBERT" \
  moteur-ia python -m evaluation.run_detection_eval \
    --annotations /data/annotations.jsonl --partition test \
    --backend camembert --configurations fusion \
    --sortie evaluation/resultats/conteneur-camembert

# 4. Bout en bout, configuration retenue. Aucune limite d'échantillon : la
#    première campagne avait conclu sur dix-huit observations.
executer "Bout en bout — fusion + CamemBERT" \
  moteur-ia python -m evaluation.run_e2e_eval \
    --index /data/scans/index.jsonl \
    --annotations /data/annotations.jsonl \
    --sortie evaluation/resultats/conteneur-camembert

echo "Terminé. Sorties :"
ls -1 "$RESULTATS/conteneur" "$RESULTATS/conteneur-camembert"
