#!/usr/bin/env bash
# Déclenche un scan manuel de toutes les sources actives.
# Nécessite la pile démarrée et amorcée (make up && make seed).
set -euo pipefail

PORTAIL="${URL_PORTAIL:-http://localhost:3000}"
MOT_DE_PASSE="${SEED_PASSWORD:-demo1234}"

jeton=$(curl -fsS -X POST "$PORTAIL/api/v1/auth/token" \
  -H 'Content-Type: application/json' \
  -d "{\"utilisateur\":\"admin\",\"motDePasse\":\"$MOT_DE_PASSE\"}" \
  | sed -n 's/.*"accessToken":"\([^"]*\)".*/\1/p')

if [ -z "$jeton" ]; then
  echo "Authentification impossible — la pile est-elle démarrée et amorcée ?" >&2
  exit 1
fi

# `admin_systeme` peut déclencher un scan mais ne peut lire aucun document :
# c'est exactement la séparation des pouvoirs recherchée.
curl -fsS "$PORTAIL/api/v1/sources" -H "Authorization: Bearer $jeton" \
  | tr ',' '\n' | sed -n 's/.*"id":"\([0-9a-f-]\{36\}\)".*/\1/p' \
  | while read -r source; do
      echo "-> scan de la source $source"
      curl -fsS -X POST "$PORTAIL/api/v1/sources/$source/scan" \
        -H "Authorization: Bearer $jeton" && echo
    done
