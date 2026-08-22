# =============================================================================
# Zero-Trust Document Access Gateway
#
# Démonstration complète :   make up && make seed && make corpus
# =============================================================================

SHELL := /bin/bash
COMPOSE := docker compose
VENV := ai-engine/.venv
PY := $(VENV)/bin/python

.DEFAULT_GOAL := aide
.PHONY: aide up down logs seed corpus test test-ia test-portail test-securite \
        eval eval-ocr lint format install scan verifier-audit reset

aide:
	@echo "Zero-Trust Document Access Gateway"
	@echo ""
	@echo "  make up          construit et démarre la pile complète"
	@echo "  make down        arrête la pile"
	@echo "  make logs        suit les journaux"
	@echo "  make seed        migrations + rôles + politiques + comptes de démo"
	@echo "  make corpus      génère le corpus synthétique et les scans dégradés"
	@echo "  make scan        déclenche un scan manuel de toutes les sources"
	@echo "  make test        pytest + jest + tests de sécurité T-01..T-05"
	@echo "  make eval        campagne d'évaluation -> CSV + tableaux Markdown"
	@echo "  make lint        ruff + eslint + tsc"
	@echo "  make reset       arrête tout et supprime les volumes (destructif)"

# --- Cycle de vie ------------------------------------------------------------

up:
	@test -f .env || (cp .env.example .env && echo "-> .env créé depuis .env.example")
	$(COMPOSE) up --build -d
	@echo ""
	@echo "Portail          http://localhost:3000"
	@echo "Tableau de bord  http://localhost:5173"
	@echo "MinIO console    http://localhost:9001"
	@echo ""
	@echo "Le moteur IA n'expose aucun port : c'est voulu (invariant §2)."

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

reset:
	$(COMPOSE) down -v
	rm -rf corpus/data/synthetic corpus/data/scans ai-engine/evaluation/resultats

# --- Amorçage ----------------------------------------------------------------

# Conteneur jetable plutôt que `exec` : les migrations doivent pouvoir
# s'appliquer avant que la passerelle n'ait réussi à démarrer.
seed:
	$(COMPOSE) run --rm --no-deps -T passerelle node dist/db/migrate.js
	@echo ""
	@echo "Comptes de démonstration (mot de passe : demo1234) :"
	@echo "  support1 support2 operations conformite partenaire admin"

corpus: install
	$(PY) corpus/generate.py --nombre 200 --sortie corpus/data/synthetic
	$(PY) corpus/degrade.py --entree corpus/data/synthetic --sortie corpus/data/scans --limite 40
	@echo ""
	@echo "Corpus prêt. Relancer 'make up' pour le remonter dans MinIO."

scan:
	@bash scripts/scan-toutes-sources.sh

# --- Tests -------------------------------------------------------------------

test: test-ia test-portail

test-ia: install
	cd ai-engine && .venv/bin/python -m pytest -q

test-portail:
	cd gateway && npm test

# Tests T-01..T-05 : nécessitent la pile démarrée (make up && make seed).
test-securite:
	cd gateway && npm run test:e2e

# --- Évaluation --------------------------------------------------------------

eval: install
	@mkdir -p ai-engine/evaluation/resultats
	cd ai-engine && PYTHONPATH=. .venv/bin/python -m evaluation.run_detection_eval \
	  --annotations ../corpus/data/annotations.jsonl \
	  --partition test \
	  --configurations regles,ner,fusion \
	  --sortie evaluation/resultats

eval-ocr: install
	cd ai-engine && PYTHONPATH=. .venv/bin/python -m evaluation.run_ocr_eval \
	  --index ../corpus/data/scans/index.jsonl \
	  --sortie evaluation/resultats

# --- Qualité -----------------------------------------------------------------

lint: install
	cd ai-engine && .venv/bin/ruff check app evaluation ../corpus
	cd gateway && npm run lint
	cd dashboard && npm run lint

format: install
	cd ai-engine && .venv/bin/black app evaluation ../corpus && .venv/bin/ruff check --fix app evaluation
	cd gateway && npm run format

# --- Dépendances locales -----------------------------------------------------

install: $(VENV)/bin/python
	@test -d gateway/node_modules || (cd gateway && npm install --no-audit --no-fund)
	@test -d dashboard/node_modules || (cd dashboard && npm install --no-audit --no-fund)

$(VENV)/bin/python:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --quiet --upgrade pip
	$(VENV)/bin/pip install --quiet -r ai-engine/requirements-dev.txt
	$(VENV)/bin/python -m spacy download fr_core_news_sm
