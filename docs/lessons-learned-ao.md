# Leçons apprises — sourcing et qualification AO

Ce document capitalise sur les AO sur lesquels Charles a investi du temps de réponse, pour affiner en continu le filtre `seed_from_radar.py` et la stratégie de recherche d'AO.

## Inventaire des AO traités

| AO | Date | Issue | Apprentissage clé |
|----|------|-------|-------------------|
| **Paris-Saclay 2026-A009** (CAP PAC 2030) | 8 juin 2026 | ✅ **DÉPOSÉ** (réponse conjointe Isograd + Mimbus) | Le partenariat sur volet RV était la bonne voie. Modèle à reproduire pour AO avec composante immersive. |
| **Neoma 2026-TIC-NBS-0008** (évaluation collaborative) | 8 juin 2026 | ❌ **RETRAIT** | « Évaluation collaborative » = peer assessment = hors-cible ITS. Concurrent montpelliérain spécialisé bien mieux placé. À flagger en amont. |

---

## Leçon 1 — Partenariat ouvre des AO « complexes »

**Contexte.** Paris-Saclay demandait un outil de positionnement avec 15 % de mises en situation immersives (VR). Sans partenaire VR, l'AO était hors d'atteinte.

**Action prise.** Partenariat technique avec Mimbus (Lyon) en sous-traitance. Architecture LTI bidirectionnelle ITS ↔ Mimbus (cf. CR technique du call CTO du 27 mai). Isograd mandataire, Mimbus sous-traitant.

**À reproduire.** Pour tout AO qui mentionne :
- réalité virtuelle, mises en situation immersives, simulation 3D
- évaluation comportementale en environnement reconstitué
- escape game pédagogique, serious games

…ne pas écarter d'office. Vérifier la part technique « tordable » par notre partenariat existant (Mimbus, et à terme d'autres acteurs RV/serious game).

**Pas codé dans le filtre.** C'est une politique de qualification commerciale, pas un filtre auto. Le RV reste un signal positif tant qu'il est minoritaire dans l'AO (< 25 %).

---

## Leçon 2 — Peer assessment = hors-cible ITS structurel

**Contexte.** Neoma demandait une « solution logicielle d'évaluation collaborative ». À l'analyse fine du CCTP : peer assessment (les apprenants évaluent les copies des autres apprenants selon une rubrique, calcul de note composite, anonymisation, affectation algorithmique).

**Pourquoi on s'est retiré.** Tordre ITS pour faire ça aurait demandé :
- rôle hybride candidat ↔ correcteur sur la même session
- algorithme d'affectation aléatoire des copies entre pairs
- calcul de note composite multi-évaluateurs avec pondération
- anonymisation côté UI correcteur

Soit 15-30 jours de dev sur la plateforme, avec un risque produit (rôle hybride = casse les hypothèses du moteur d'autorisation). Et un concurrent montpelliérain spécialisé peer assessment était structurellement mieux placé.

**Codé dans le filtre.** `KW_PEER_ASSESSMENT` dans `scrapers/ao/seed_from_radar.py` détecte 17 variantes (« évaluation collaborative », « peer assessment », « évaluation par les pairs », « co-évaluation », etc.). Quand détecté :
- pénalité de −8 pts sur le score → l'AO descend dans le hub
- drapeau 🚩 en tête de l'action commerciale, avec rappel de la leçon Neoma
- l'AO reste visible dans le hub (on n'écarte pas, on flagge) pour traçabilité

**Pourquoi flagger plutôt qu'écarter.** Certains AO pourraient être à 80 % ITS standard et 20 % peer assessment marginal — auquel cas Charles veut quand même les voir et juger.

---

## Leçon 3 — La présence d'un concurrent spécialisé est un signal

L'AO Neoma précédent (évaluation des enseignements, 2024) avait été gagné par **Explorance** (Canada/Montréal). L'AO Neoma 2026 sur peer assessment va probablement être gagné par le concurrent montpelliérain. Ces concurrents sont :

- soit déjà fournisseurs historiques de l'acheteur
- soit hyper-spécialisés sur un cas d'usage où ITS doit tordre la plateforme

**Action à prendre.** Constituer une liste de concurrents spécialisés à monitorer dans `KW_CONCURRENTS` du filtre :
- Explorance (peer assessment + éval enseignements)
- Acteur peer assessment basé à Montpellier (à identifier précisément — TODO Charles)
- EvaluationKIT, Bluepulse, Watermark (eval enseignements)
- ExamSoft, Pearson VUE, Caveon (proctoring + exam delivery)
- Aurion (ERP scolarité)

Quand un AO mentionne un de ces concurrents dans le DCE ou les pré-études, c'est un signal d'attribution probable — à pondérer dans la qualification.

---

## TODO sourcing & filtre

- [ ] Identifier précisément l'acteur montpelliérain peer assessment et l'ajouter à `KW_CONCURRENTS`
- [ ] Élargir la liste `KW_PEER_ASSESSMENT` au fur et à mesure des AO observés
- [ ] Constituer un tracker des AO en pipeline (déposés / retraits) côté hub pour mesurer le hit rate
- [ ] Ajouter une colonne « statut » au curated CSV (déposé / retiré / gagné / perdu / en cours) pour mémoriser l'historique
- [ ] Brancher une note de notification quand un AO peer-flag passe le seuil (alerte amont sans qu'il pourrisse le hub)
