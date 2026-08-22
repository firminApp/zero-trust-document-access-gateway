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

Hors conteneur, le pack `fra` peut manquer : le moteur le signale bruyamment et
se replie sur `eng` plutôt que de renvoyer une erreur. Pour l'installer sur la
machine de développement, déposer `fra.traineddata` dans le répertoire
`tessdata` de Tesseract (`brew --prefix`/share/tessdata sur macOS).

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

**Tolérance au texte océrisé** — `rules.detecter(texte, ocr=True)` active trois
comportements que le texte propre n'a aucune raison de subir :

1. les jetons disloqués par l'OCR sont réparés dans une variante du texte, avec
   report exact des offsets
   ([`reparation_ocr.py`](ai-engine/app/detection/reparation_ocr.py)) ;
2. les candidats dont une **somme de contrôle** échoue (mod-97, Luhn) sont
   conservés, non validés, plutôt qu'écartés — une somme de contrôle est
   détruite par un seul caractère mal lu, alors que le motif reconnaît toujours
   la donnée. Un contrôle de *plausibilité* (une date au 32 du mois) reste au
   contraire une bonne raison d'écarter le candidat ;
3. certains motifs ont une **variante tolérante** (`motif_ocr`) là où la
   confusion de caractères empêche le motif strict de correspondre : chiffres de
   clé IBAN lus comme des lettres, extension de domaine rognée, caractère
   parasite dans un domaine.

Aucun des trois ne s'applique au texte propre. Ces tolérances font passer le
rappel `critique` de bout en bout de 0,556 à 0,962 (spaCy) et 0,981
(CamemBERT) ; le détail des défauts qu'elles corrigent est en §Résultats.

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
laissent passer aucun IBAN, numéro de carte ni numéro de pièce — **sur du texte
propre**. Cette réserve est essentielle : la campagne de bout en bout ci-dessous
montre que la même propriété tombe à 0,556 sur un scan flou, et que ce sont
précisément ces validateurs qui en sont la cause. Le tableau ci-dessus mesure la
détection, pas la chaîne complète.

#### OCR — CER par condition de dégradation

20 documents rendus puis dégradés, Tesseract `fra`, correspondance caractère à
caractère contre la vérité terrain du corpus.

| Condition | CER moyen | CER médian | CER p90 |
|---|---|---|---|
| référence | **0,066** | 0,036 | 0,259 |
| flou (gaussien 5×5) | **0,060** | 0,036 | 0,229 |
| rotation 3° | **0,041** | 0,011 | 0,210 |
| JPEG q=40 | **0,048** | 0,022 | 0,198 |
| bruit gaussien σ=18 | 0,150 | 0,128 | 0,283 |

Quatre conditions sur cinq passent la cible de 0,10. **Le bruit gaussien reste
au-dessus**, et c'est un résultat, pas un réglage à trouver : la médiane vaut
0,128, donc la dégradation est uniforme et non tirée par quelques pages. La
cause est l'ordre imposé du prétraitement — la binarisation précède le filtre
médian, si bien que le grain est d'abord amplifié en points isolés, puis
seulement lissé. Débruiter avant de binariser corrigerait ce cas, au prix
d'une modification de la chaîne spécifiée en §M3.

Deux enseignements méthodologiques sont venus de cette campagne, tous deux
consignés dans le code :

**Le rendu du corpus doit utiliser une vraie police TrueType.** Avec la police
vectorielle d'OpenCV (`FONT_HERSHEY_SIMPLEX`), le point du « i » n'est pas
tracé : Tesseract lit « DOMACILE », « soussgné », « Bneta Ndaye », et le CER
mesuré passe de 0,025 à 0,133 sur la même page. La mesure décrivait alors le
générateur d'images, pas la chaîne OCR.

**Le redressement doit refuser d'agir quand sa mesure n'est pas fiable.** Sur
une page bruitée, Hough détecte 70 à 110 « lignes » qui ne sont que du grain ;
pivoter de leur angle médian arbitraire étalait le grain en amas lus comme du
texte — 1135 caractères restitués pour 174 attendus, soit un CER de 5,9. Ce qui
distingue une inclinaison réelle du bruit n'est pas le nombre de lignes mais
leur accord : écart absolu médian de 0,06–0,13° pour une inclinaison de 3°,
contre 1,10–1,84° pour du bruit. `ocr.py` exige désormais cet accord, et
s'abstient sinon. Un redressement qui se trompe coûte bien plus cher qu'un
redressement omis.

#### Bout en bout : rappel par condition de dégradation

C'est la mesure qui **compose** les deux précédentes, et la seule qui dise ce
que le système protège réellement sur un document scanné. `make eval-e2e`.

Elle ne se déduit pas des deux autres. L'appariement se fait **par valeur** et
non par position : les offsets de la vérité terrain vivent dans le texte
d'origine, ceux des prédictions dans le texte océrisé, et l'OCR insère et
supprime des caractères. Tolérance de 25 % des caractères, avec la casse, les
accents et la ponctuation neutralisés — mais **sans** replier les confusions
propres à l'OCR (O/0, I/1, S/5), ce qui gonflerait le rappel en faisant passer
pour trouvée une donnée que le système n'a pas su lire.

Rappel par niveau de sensibilité, 60 documents par condition (support 366),
fusion + **CamemBERT** — la configuration par défaut :

| Niveau | référence | bruit | flou | rotation | jpeg40 |
|---|---|---|---|---|---|
| faible | 0,886 | 0,867 | 0,895 | 0,914 | 0,905 |
| moyen | 0,847 | 0,810 | 0,883 | 0,942 | 0,920 |
| eleve | 0,944 | 0,859 | 0,873 | 0,958 | 0,986 |
| **critique** | **0,981** | **1,000** | **0,981** | **0,981** | **0,981** |

| Indicateur | Mesuré | Cible | Statut |
|---|---|---|---|
| Rappel `critique`, pire condition | **0,981** | 0,95 | atteinte |
| Rappel global, pire condition | 0,863 | 0,90 | non atteinte |
| Rappel global, hors condition `bruit` | 0,896 – 0,943 | 0,90 | atteinte sur 3 conditions / 4 |
| F2, pire condition | 0,832 | 0,90 | non atteinte |

**Le rappel `critique` tient sur la condition la plus défavorable, pas en
moyenne** : c'est la garantie qui engage le système, puisque c'est le niveau que
le portail confronte au rôle. Le rappel global reste en dessous de la cible sur
`bruit`, la condition où le CER atteint 0,428 — l'ordre imposé du prétraitement
binarise avant de filtrer, ce qui amplifie le grain (voir §OCR).

Le même protocole avec spaCy donne un rappel `critique` minimal de 0,962 et un
rappel global de 0,738 – 0,779 : l'écart entre les deux backends se concentre sur
les types que la NER porte seule, et **ne touche pas** le niveau `critique`, dont
les types passent tous par une règle et un validateur.

Le type restant nettement en retrait est `EMAIL` (0,615 – 0,846). Les autres
sont à 0,80 ou au-delà, et les quatre types `critique` à 0,957 – 1,000.

##### Ce qu'il a fallu corriger pour y arriver

La première mesure donnait un rappel `critique` de **0,556**. Le protocole a
donc d'abord servi à révéler cinq défauts, tous dans la détection et non dans
l'OCR — la décomposition des pertes le disait sans ambiguïté : sur 41 entités
perdues, 36 étaient encore lisibles dans le texte océrisé.

**1. L'OCR remplace le point du domaine par un espace.** `binetandiaye@mail.bj`
ressort en `binetandiaye @mall bJ`. Le point n'est pas déplacé, il a disparu :
aucun recollage de ponctuation ne pouvait le retrouver.
[`reparation_ocr.py`](ai-engine/app/detection/reparation_ocr.py) le restitue,
mais seulement après un `@` et devant ce qui a la forme d'une extension de
domaine — hors de ce contexte, transformer un espace en point fabriquerait des
jetons de toutes pièces.

**2. Un chiffre de la clé IBAN est lu comme une lettre.** `SN68…` ressort en
`SNG8…`, `SNS8…`. Le motif exige `[A-Z]{2}\d{2}` et ne correspond alors **plus
du tout** : il n'y avait même pas de candidat à soumettre au mod-97, et aucune
tolérance sur le validateur ne pouvait rattraper cela. La correction est au
niveau du motif (`MOTIF_IBAN_OCR`), pas du validateur.

**3. Le score attribué aux candidats non validés était trop bas.** Fixé d'abord
à 0,45, il faisait perdre l'IBAN à la fusion face au `LOCALITE`/`ORGANISATION`
rendu par spaCy — dont le score de 0,85 est une **constante arbitraire** et non
une probabilité. L'IBAN n'était pas seulement manqué : il était *remplacé*, donc
reclassé de `critique` à `faible`. Un sous-classement, la faille même que M5
interdit. Une chaîne de 28 caractères au format IBAN dans un document océrisé
est bien plus probablement un IBAN qu'une étiquette NER générique : l'échec du
mod-97 est *expliqué* par le bruit de lecture, il n'est pas un indice contre la
nature de la donnée. Le score est donc à 0,90.

**4. Un numéro national satisfait parfois le contrôle de Luhn par coïncidence.**
`CARTE_BANCAIRE`, validé, l'emportait sur `NUM_PIECE_IDENTITE`. Les deux types
étant `critique`, **la donnée restait protégée à l'identique et aucune fuite n'en
résultait** — seule la métrique par type y voyait un manque. Une seule
amélioration était fondée : quand le document **étiquette** le numéro
(« N° CNI : »), ce contexte vaut plus qu'une coïncidence de format. Sans
étiquette, l'ambiguïté est réelle et n'est pas tranchée artificiellement.

**5. L'OCR abîme le domaine des adresses de plusieurs façons.** Extension rognée
(`poste.ci` → `poste.c`), caractère parasite inséré (`poste` → `pos'e`), accolade
en fin de ligne (`mail.bj` → `mail.b]`). Plutôt que d'énumérer indéfiniment les
confusions rencontrées, le motif OCR admet tout caractère non blanc dans le
domaine : la structure `@…point…extension` reste très sélective dans un
document. Deux régressions ont été trouvées en écrivant les tests de ce
correctif — la réparation ajoutait un point après une adresse *déjà complète*
(`awa.diouf@exemple.sn pour` → `…sn.pour`, le masquage débordait sur le texte
courant), et une mention `@twitter` devient une fausse adresse. La première est
corrigée ; la seconde est assumée : masquer deux mots de trop coûte moins que
laisser une adresse en clair.

Les tolérances ne s'appliquent **qu'au texte issu de l'OCR** : la détection sur
texte propre est inchangée, rappel critique 1,000. C'est un arbitrage local
et assumé — sur un scan, mieux vaut masquer un faux IBAN que laisser passer un
vrai, ce que le F2 accepte par construction. La précision de bout en bout a
d'ailleurs **augmenté** à chaque étape (0,578 → 0,607 avec spaCy, 0,777 avec
CamemBERT) : les entités récupérées sont de vrais positifs, et non du bruit
gagné contre de la précision.

##### Une leçon de méthode

Le premier chiffre publiable était 0,944, à une entité près de la cible sur un
échantillon de 18. Plutôt que d'ajuster des scores pour franchir le seuil,
l'échantillon a été porté à 366 entités par condition : la mesure s'est stabilisée
à 0,962. Un seuil manqué de 0,006 sur 18 observations ne se corrige pas dans le
code, il se mesure mieux.

#### Matrices de confusion

`make eval` produit, pour chaque configuration, deux matrices en plus des
scores : `confusion_<config>_types.csv` et `confusion_<config>_niveaux.csv`,
avec le relevé des sous-classements.

Elles reposent sur un appariement **agnostique au type** : deux empans au même
endroit sont appariés même si leurs étiquettes diffèrent. C'est indispensable,
car précision et rappel confondent deux erreurs de nature très différente —
une donnée **manquée** (elle sort en clair : fuite) et une donnée **trouvée
mais mal étiquetée** (elle est protégée, au mauvais niveau). La colonne
`(manquée)` et la ligne `(superflue)` portent les marges.

Confusion par niveau, fusion + CamemBERT, partition `test` :

| attendu \ prédit | critique | eleve | faible | moyen | (manquée) | total |
|---|---|---|---|---|---|---|
| **critique** | **26** | 0 | 0 | 0 | 0 | 26 |
| **eleve** | 0 | **33** | 0 | 0 | 0 | 33 |
| **faible** | 0 | 1 | **49** | 0 | 2 | 52 |
| **moyen** | 0 | 19 | 0 | **47** | 0 | 66 |
| (superflue) | 0 | 27 | 4 | 8 | — | 39 |

Trois lectures :

**Zéro sous-classement** — la moitié sous la diagonale est vide. Aucune donnée
n'a été classée à un niveau inférieur au sien, donc aucune n'est devenue
lisible par un rôle qui n'y a pas droit. C'est le critère d'acceptation de M5,
et c'est la seule moitié de la matrice qui constitue une faille : le
sur-classement ne fait que masquer trop.

**Les 19 `moyen -> eleve` ne sont pas des erreurs** — c'est l'ajustement
contextuel de M5 qui fonctionne. Un `NOM_PERSONNE` entouré d'une date de
naissance et d'un numéro de pièce passe volontairement de `moyen` à `eleve`. Le
corpus annote le type, pas cet ajustement : d'où la précision de 0,516 sur le
niveau `eleve` dans le tableau par type, qui se lirait à tort comme un défaut.

**Le niveau `critique` est exact à 26/26** — sans confusion ni omission, parce
que ces types passent tous par un validateur structurel (mod-97, Luhn, formats
nationaux). C'est ce que la matrice permet d'affirmer, là où un rappel de 1,000
laissait encore ouverte la question de l'étiquetage.

##### La confusion a une conséquence de sécurité, pas seulement de rappel

Le même tableau produit avec spaCy révèle **3 sous-classements** là où
CamemBERT n'en produit aucun :

| Confusion de type | Effet sur le niveau |
|---|---|
| `PLAQUE_IMMAT` → `ORGANISATION` (×1) | eleve → faible |
| `NOM_PERSONNE` → `LOCALITE` (×1) | moyen → faible |
| `NOM_PERSONNE` → `ORGANISATION` (×1) | moyen → faible |

La faiblesse de spaCy sur les noms propres ouest-africains ne coûte donc pas
seulement du rappel : elle **déclasse** la donnée, et un rôle `support_n1` peut
lire en clair une plaque d'immatriculation ou un patronyme. C'est un argument
de sécurité en faveur de l'ADR n°4, qui s'ajoute à l'argument de rappel — et il
n'apparaît que dans la matrice de confusion, pas dans les scores agrégés.

Le niveau `critique` reste exact avec les deux backends : les types critiques
ne dépendent pas de la NER.

Reproduire : `make eval` (spaCy) et `make eval-ocr` ; pour CamemBERT, depuis le conteneur —
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
