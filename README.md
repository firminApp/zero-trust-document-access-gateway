# Zero-Trust Document Access Gateway

Passerelle d'accès aux documents pour une plateforme de services numériques.
Elle devient **l'unique point de lecture** du patrimoine documentaire : elle
authentifie l'appelant, vérifie ses droits, journalise l'accès, et masque à la
volée les données personnelles détectées par IA selon le rôle du demandeur.

> Projet de fin d'année · Master 1 Intelligence Artificielle · Dakar Institute
> of Technology · Kpapou Banigante · 2025–2026

---

## Le problème

Une plateforme VTC / livraison / e-commerce collecte des documents personnels —
pièces d'identité, permis, cartes grises, contrats, RIB — dispersés dans des
buckets S3, des dossiers Google Drive et des disques locaux, consultés depuis
plusieurs back-offices. Deux voies d'accès existent, aucune n'est contrôlée :

1. **accès direct au stockage** — quiconque détient les identifiants voit tout ;
2. **accès par back-office** — non journalisé, sans filtrage par rôle.

Le système ferme les deux en interposant un portail obligatoire.

### Règle qui gouverne tout le code

**Refus par défaut.** Toute branche qui n'a pas explicitement établi qu'un accès
est autorisé retourne un refus, et ce refus est journalisé. Une case absente de
la matrice de politique vaut « refus », pas « on verra ».

### Limite assumée

Le contrôle est **applicatif** : le stockage n'est pas chiffré, les lectures
sont redirigées. La parade est de ne distribuer les identifiants de stockage
qu'au compte de service du portail (`docker-compose.yml` : seuls `passerelle` et
`orchestrateur` reçoivent `S3_*` et `GDRIVE_*`). Le chiffrement au repos est un
durcissement optionnel (`ai-engine/app/protection/crypt.py`).

---

## Architecture

```
   Back-office / app mobile / app web        Tableau de bord React
                    │                                 │
                    ▼                                 ▼
   ╔══════════════════════════════════════════════════════════╗
   ║   PORTAIL D'ACCÈS — NestJS  (PEP, NIST SP 800-207)        ║
   ║   auth JWT · RBAC · audit chaîné · restitution            ║
   ╚═══════╤══════════════════════════════════╤═══════════════╝
           │                                  │
   ┌───────▼─────────┐            ┌───────────▼──────────┐    ┌────────────┐
   │ Moteur IA       │            │ Orchestrateur        │───▶│ PostgreSQL │
   │ FastAPI         │            │ node-cron + BullMQ   │    │ catalogue  │
   │ (réseau interne)│            └───────────┬──────────┘    │ politiques │
   └───────┬─────────┘                        │               │ audit      │
           └──────────────┬───────────────────┘               └────────────┘
                          ▼
              S3  ·  Google Drive  ·  disque local
```

| Runtime | Rôle | Répertoire |
|---|---|---|
| Node.js 20 / NestJS | Portail (PEP), RBAC, audit, connecteurs, orchestrateur | [`gateway/`](gateway/) |
| Python 3.11 / FastAPI | Extraction, OCR, détection, classification, protection | [`ai-engine/`](ai-engine/) |
| React 18 / Vite | Tableau de bord de supervision | [`dashboard/`](dashboard/) |

### Invariants d'architecture

Vérifiables en revue de code, et chacun couvert par un test :

| Invariant | Où il est appliqué |
|---|---|
| Seul `gateway/` détient des identifiants de stockage | [`docker-compose.yml`](docker-compose.yml) — le service `moteur-ia` ne reçoit ni `S3_*` ni `GDRIVE_*` |
| `ai-engine/` n'est pas exposé hors du réseau Docker | `moteur-ia` déclare `expose`, jamais `ports` |
| `journal_audit` n'accepte que des `INSERT` | [`db/migrations/001_init.sql`](db/migrations/001_init.sql) — règles `DO INSTEAD NOTHING` |
| Aucune valeur d'entité en clair en base | [`catalog.service.ts`](gateway/src/catalog/catalog.service.ts) — `empreinteValeur()` est le seul point de passage |

#### Portée exacte de l'append-only

Les règles SQL neutralisent `UPDATE` et `DELETE`, y compris pour le compte
applicatif — T-04 le vérifie. Elles ne couvrent pas `TRUNCATE`, qui ne
déclenche aucune règle, ni `ALTER TABLE ... DISABLE RULE` : ce sont des
opérations de **propriétaire de table**. La parade est de déploiement — le
compte applicatif ne doit pas posséder `journal_audit` — et
[`003_audit_privileges.sql`](db/migrations/003_audit_privileges.sql) pose les
droits correspondants.

Ce que le chaînage garantit en tout état de cause : une altération ou une
troncature est **détectable**. On ne prétend pas empêcher un administrateur de
base de détruire la table ; on garantit qu'il ne peut pas le faire
discrètement.

---

## Démarrage

```bash
make up      # construit et démarre la pile
make seed    # migrations + rôles + politiques + comptes de démonstration
make corpus  # génère le corpus synthétique annoté + les scans dégradés
```

- Portail : <http://localhost:3000>
- Tableau de bord : <http://localhost:5173>
- Console MinIO : <http://localhost:9001>
- Moteur IA : **aucun port publié** — c'est voulu.

Comptes de démonstration, mot de passe `demo1234` : `support1`, `support2`,
`operations`, `conformite`, `partenaire`, `admin`.

### Démarrage léger

L'image du moteur IA embarque CamemBERT (~2 Go avec torch). Pour une pile
légère, au prix d'un rappel moindre sur les patronymes :

```bash
AVEC_CAMEMBERT=false NER_BACKEND=spacy make up
```

---

## Matrice de politique

Rôle × niveau de sensibilité → action. Elle est chargée depuis la table
`politique_acces` ; **toute case absente vaut « refus »**.

| Rôle | faible | moyen | eleve | critique |
|---|---|---|---|---|
| `support_n1` | complet | masque | refus | refus |
| `support_n2` | complet | complet | masque | refus |
| `operations` | complet | complet | pseudonymise | refus |
| `conformite` | complet | complet | complet | complet |
| `service_partenaire` | complet | masque | refus | refus |
| `admin_systeme` | refus | refus | refus | refus |

`admin_systeme` administre le portail — déclarer une source, lancer un scan —
mais ne lit **aucun** document. Celui qui exploite le système n'est pas celui
qui consulte les données.

Les 24 cases sont couvertes par un test paramétré
([`policy.service.spec.ts`](gateway/src/policy/policy.service.spec.ts)) et
rejouées de bout en bout par T-02.

---

## API du portail

```
POST /api/v1/auth/token                     { utilisateur, motDePasse }
GET  /api/v1/documents/:id/contenu          ?format=original|texte
GET  /api/v1/documents/:id/metadonnees      types et niveaux, jamais de valeurs
GET  /api/v1/documents                      ?source=&statut=&niveau=&page=
GET  /api/v1/audit                          ?document=&utilisateur=&depuis=
GET  /api/v1/audit/verification             { intact, premiereRupture }
GET  /api/v1/statistiques
POST /api/v1/sources                        rôle admin_systeme
POST /api/v1/sources/:id/scan               rôle admin_systeme
```

`GET /documents/:id/contenu` répond avec les en-têtes `X-Politique-Appliquee`,
`X-Niveau-Max-Detecte`, `X-Document-Id` et `X-Audit-Id`.

### Le code 423

Un document découvert mais **pas encore analysé** renvoie `423 Locked`, jamais
son contenu. Le système ignore ce qu'il contient : la politique est
inapplicable, donc le refus par défaut s'applique. Le servir « en attendant »
recréerait exactement la faille que le projet supprime.

### Séquence de restitution

1. JWT validé — sinon 401, journalisé.
2. Chargement du document — absent : 404, journalisé.
3. `statut != 'analyse'` → 423, journalisé.
4. Décision du PDP (`PolicyService.decide`).
5. `refus` → 403, journalisé, **la source n'est même pas lue**.
6. Lecture des octets via le connecteur.
7. `masque` / `pseudonymise` → appel du moteur IA.
8. **Écriture au journal — avant** la réponse.
9. Réponse et en-têtes de politique.

L'ordre de l'étape 8 n'est pas cosmétique : journaliser après aurait pour effet
qu'une coupure réseau produise un accès non tracé.

---

## Modules

### M3 — Connecteurs, extraction, OCR

`lister()` est un **générateur asynchrone** : un bucket de 500 000 objets se
parcourt sans jamais tenir l'inventaire en mémoire.

| Format | Outil | Note |
|---|---|---|
| PDF | PyMuPDF, repli pdfplumber | bascule OCR si < 100 caractères/page |
| DOCX | python-docx | paragraphes **+ tableaux + en-têtes** |
| TXT / CSV | lecture directe | encodage deviné (latin-1 fréquent) |
| JPEG / PNG | Tesseract `fra` | prétraitement obligatoire |

Prétraitement OCR, dans cet ordre : niveaux de gris → binarisation adaptative
(fenêtre 31) → redressement par angle dominant (Hough) → filtre médian. Il pèse
davantage sur le résultat que le choix du moteur.

**Correspondance des offsets** ([`normalize.py`](ai-engine/app/extraction/normalize.py)) :
la détection travaille sur du texte normalisé, la protection écrit dans le
document source. Sans table de correspondance, le masquage s'applique à côté et
la donnée reste lisible. C'est le premier test du projet
([`test_normalize.py`](ai-engine/tests/test_normalize.py)).

### M4 — Détection

Deux familles **complémentaires**, jamais substituables : aucune regex ne trouve
un patronyme, aucun modèle NER ne valide une clé IBAN.

**Règles** — chaque motif est assorti d'un validateur quand c'est possible, ce
qui transforme un motif peu spécifique en détecteur très précis : IBAN mod-97,
Luhn, plages de dates, longueurs nationales (+221, +229, +228, +225, +233).

**NER** — deux backends interchangeables par `NER_BACKEND`, sans changement de
code appelant : `spacy` (léger) et `camembert` (meilleur sur les patronymes et
toponymes ouest-africains). `presidio` est disponible comme référence externe de
comparaison, jamais requis au runtime.

**Fusion** — arbitrage des chevauchements, dans cet ordre strict : détection
validée > empan le plus large > score le plus élevé > **on conserve**. La
dernière règle traduit la priorité au rappel : quand le système ne sait pas
trancher, il protège davantage.

### M5 — Classification

`faible` → `moyen` → `eleve` → `critique`. Un `NOM_PERSONNE` entouré d'une date
de naissance et d'un numéro de pièce dans une fenêtre de 200 caractères passe de
`moyen` à `eleve` : c'est une identité, pas une mention en passant.

Le sur-classement est acceptable, le **sous-classement est une faille** — il
ouvrirait l'accès à un rôle qui ne devrait pas l'avoir.

### M6 — Protection

| Format | Méthode |
|---|---|
| texte / CSV | substitution par offsets, en partant de la fin |
| PDF natif | `add_redact_annot` **+ `apply_redactions`** |
| DOCX | substitution au niveau du run |
| image | rectangle opaque aux boîtes OCR, image réencodée |

Sur PDF, dessiner un rectangle noir sans `apply_redactions()` laisse le texte
extractible dessous. C'est une fausse protection, et c'est exactement ce que
vérifie `test_pdf_le_texte_est_reellement_supprime`.

La pseudonymisation est déterministe (même valeur → même jeton, sinon on ne peut
plus recouper deux documents) et réversible via la table `pseudonyme`, où la
valeur arrive **déjà chiffrée par le moteur** : la base ne voit jamais de clair.

### M1 — Audit chaîné

```
empreinte(n) = SHA256(empreinte(n-1) ‖ utilisateur ‖ rôle ‖ document ‖
                      action ‖ politique ‖ horodatage_iso8601)
```

`append()` lit la dernière empreinte et insère dans une même transaction
`SERIALIZABLE` : sans cela, deux requêtes concurrentes liraient la même
empreinte précédente et casseraient la chaîne.

### M2 — Orchestrateur

`node-cron` émet une tâche par source ; le worker BullMQ fait le travail. Si
l'empreinte SHA-256 d'une ressource est inchangée, elle est ignorée — c'est ce
qui rend le coût d'un scan proportionnel aux nouveautés. Lots de 200 ; un échec
unitaire n'interrompt jamais le lot ; reprise tant que `tentatives < 3`.

---

## Tests

```bash
make test            # pytest (moteur IA) + jest (portail)
make test-securite   # T-01..T-05, nécessite la pile démarrée et amorcée
```

| Réf | Test | Emplacement |
|---|---|---|
| T-01 | Lecture directe sur le stockage → doit échouer | [`securite.e2e-spec.ts`](gateway/test/securite.e2e-spec.ts) |
| T-02 | Les 24 cases renvoient exactement l'action attendue | idem + `policy.service.spec.ts` |
| T-03 | Entrées d'audit == requêtes émises, refus compris | idem + `documents.service.spec.ts` |
| T-04 | Altération d'une entrée détectée par `verifyChain()` | idem + `audit.service.spec.ts` |
| T-05 | Bout en bout sur les sources déclarées | idem |

---

## Corpus et évaluation

```bash
make corpus     # 200 documents annotés + 5 conditions de dégradation
make eval       # règles / NER / fusion -> CSV + tableaux Markdown
make eval-ocr   # CER par condition
```

L'annotation est **produite en même temps que le document** : la vérité terrain
est exacte, pas estimée. Partition 70/15/15 **au niveau du document** — jamais au
niveau de l'entité, sinon une entité du jeu de test aurait pu être vue à
l'entraînement.

Cinq conditions sur les mêmes documents : référence, bruit gaussien, flou,
rotation 3°, JPEG q=40.

### La métrique de décision est le F2

```
F1 = 2·P·R / (P + R)                F2 = 5·P·R / (4·P + R)
```

En sécurité des données les erreurs sont asymétriques : un faux positif masque
une donnée inutilement — visible, réversible ; un faux négatif laisse un IBAN en
clair — invisible, c'est une fuite. Le F2 pondère le rappel quatre fois plus que
la précision. Le F1 n'est rapporté que pour la comparaison avec la littérature.

Cibles : rappel global ≥ 0,90 · rappel critique ≥ 0,95 · F2 ≥ 0,90 · CER ≤ 0,10 ·
latence p95 ≤ 2 s.

### Résultats mesurés

Corpus synthétique, 200 documents, partition `test` (30 documents, 205 entités),
correspondance **stricte** des frontières.

| Configuration | Rappel global | Rappel critique | F2 global |
|---|---|---|---|
| Règles seules | 0,435 | **1,000** | 0,473 |
| NER seule (spaCy `lg`) | 0,367 | 0,000 | 0,369 |
| Fusion (spaCy `lg`) | 0,791 | **1,000** | 0,748 |
| **Fusion (CamemBERT)** | **0,949** | **1,000** | **0,911** |

Trois lectures, et ce sont les trois décisions du projet :

**ADR n°3 — règles *et* NER.** Prises isolément, les deux familles échouent :
les règles ne trouvent aucun patronyme (rappel 0 sur `NOM_PERSONNE`), la NER ne
valide aucune clé IBAN (rappel 0 sur le niveau critique). Leur union fait plus
que la somme, parce que leurs ensembles d'entités sont disjoints.

**ADR n°4 — CamemBERT plutôt que spaCy.** L'écart se concentre exactement où il
était attendu : `NOM_PERSONNE` passe de 0,567 à 0,900 et `LOCALITE` de 0,576 à
0,939 sur des patronymes et toponymes ouest-africains. C'est ce seul écart qui
fait passer le système au-dessus des cibles.

**Rappel critique de 1,000 dans toutes les configurations comportant les
règles.** Les validateurs structurels (mod-97, Luhn, formats nationaux) ne
laissent passer aucun IBAN, numéro de carte ni numéro de pièce. C'est la
propriété la plus importante du tableau : c'est sur elle que repose la
promesse du système.

Reproduire : `make eval` (spaCy) ; pour CamemBERT, depuis le conteneur —
`docker compose exec -e NER_BACKEND=camembert moteur-ia python -m
evaluation.run_detection_eval --annotations /tmp/annotations.jsonl`.

**Toujours lire la ventilation par type.** Un rappel global de 0,92 peut masquer
un rappel de 0,60 sur `NUM_PIECE_IDENTITE`, précisément la catégorie la plus
critique. `evaluation/report.py` produit systématiquement le détail par type et
par niveau, et
[`test_metrics.py`](ai-engine/tests/test_metrics.py) contient un test qui met ce
piège en évidence.

---

## Configuration

Voir [`.env.example`](.env.example). Deux variables méritent attention :

- `HASH_SALT` — sel du hachage des valeurs d'entités. Le changer **invalide
  toutes les empreintes** déjà stockées dans `entite_detectee`.
- `AES_KEY` — sans elle, la pseudonymisation reste déterministe mais devient
  irréversible : aucune correspondance n'est enregistrée.

---

## Cadre de référence

- **NIST SP 800-207** — le portail est le PEP, `PolicyService` est le PDP.
- **RBAC** (Sandhu et al. 1996 ; ANSI INCITS 359-2004) — les permissions
  s'attachent aux rôles.
- **RGPD** — l'article 25 justifie l'invariant « pas de valeurs en clair en base ».
- **Acte additionnel A/SA.1/01/10 de la CEDEAO (2010)** — motive les formats
  nationaux et les patronymes régionaux du corpus.
- **Campagnes i2b2 (2007, 2014)** — évaluation au niveau de l'entité, priorité au rappel.
- **CamemBERT** (Martin et al., ACL 2020) · **Microsoft Presidio** — comparaison externe.

## Journal des décisions

| # | Décision | Raison |
|---|---|---|
| 1 | Contrôle applicatif | déployable incrémentalement sur un SI en production |
| 2 | RBAC plutôt qu'ABAC | politique auditable en un tableau |
| 3 | Règles **et** NER | ensembles d'entités disjoints |
| 4 | CamemBERT plutôt qu'un modèle multilingue | corpus francophone, patronymes régionaux |
| 5 | F2 comme métrique de décision | asymétrie des erreurs |
| 6 | Empreintes seulement en base | sinon le catalogue devient la base de DCP la plus dense |
| 7 | Audit chaîné append-only | un journal modifiable par celui qu'il surveille ne prouve rien |
| 8 | 423 sur document non analysé | politique inapplicable sans connaissance du contenu |
