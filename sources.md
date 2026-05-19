# Référentiel des sources — Hub Veille Marché Isograd

Source-by-source breakdown pour les 3 verticaux. Chaque entrée précise URL, type d'accès, auth requise, tier de signal généré, cadence de scan, et état d'avancement.

Légende :
- **Type** : `RSS` (flux RSS standard), `HTML` (scraping de page), `API` (API publique/privée), `Apify` (acteur Apify)
- **Auth** : `non` (public), `oui` (login/API key requis)
- **Tier** : qualité du signal (1 = forte, 3 = faible)
- **Cadence** : fréquence de scan
- **État** : `S2`/`S3`/`S4` = sprint de branchement, `Manuel` = pas auto

---

## 🎓 Education — Sup, grandes écoles, universités, CFA

### Tier 1 — sources institutionnelles haute qualité

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| AEF Info — Enseignement sup | https://www.aefinfo.fr/automne (RSS thèmes Sup) | RSS | oui (compte Isograd) | Daily | S2 |
| MESR (Ministère ESR) — communiqués | https://www.enseignementsup-recherche.gouv.fr/fr/presse | HTML | non | Daily | S2 |
| Conférence des Grandes Écoles | https://www.cge.asso.fr/actualites/ | RSS | non | Daily | S2 |
| France Universités (ex-CPU) | https://franceuniversites.fr/actualites/ | RSS | non | Daily | S2 |
| HCERES — accréditations | https://www.hceres.fr/fr/actualites | HTML | non | Weekly | S2 |
| TED (eTendering) Education | https://ted.europa.eu/ — filtres CPV éducation | API | non | Daily | S2 (réutiliser code Radar AO) |
| EducPros (groupe AEF) | https://www.letudiant.fr/educpros | RSS | oui | Daily | S2 |

### Tier 2 — presse spécialisée

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| L'Étudiant | https://www.letudiant.fr | RSS | non | Daily | S2 |
| Studyrama | https://www.studyrama.com/actualites | RSS | non | Daily | S2 |
| Campus Matin | https://www.campusmatin.com | RSS | non | Daily | S2 |
| Newstank Higher Education | https://education.newstank.fr | HTML | oui (payant) | Weekly | S3 (si licence) |

### Tier 3 — sites officiels écoles top 30

Liste des établissements à monitorer individuellement (alertes Google + scraping page presse) :

**Top business schools :** HEC Paris, ESSEC, ESCP, EM Lyon, EDHEC, NEOMA, KEDGE, SKEMA, GEM, Audencia, TBS Education
**Top écoles d'ingé :** Polytechnique, CentraleSupélec, Mines ParisTech, Ponts ParisTech, Télécom Paris, ESPCI, AgroParisTech, ENSAE, ENSAI
**Universités/IAE :** Sciences Po Paris, Dauphine, Paris 1, Paris-Saclay, PSL, Sorbonne Université, ENS Ulm, IAE Aix, IAE Bordeaux, IAE Lyon, IAE Paris
**INSA :** Lyon, Toulouse, Rouen, Rennes, Strasbourg

Méthode S2 : page "actualités" / "presse" de chaque école → scraping HTML simple. Si pas de page presse, fallback Google News query `site:[domain] (nouveau OR lance OR annonce OR partenariat)`.

### Référentiels et bases tierces

| Source | URL | Type | Auth | Usage |
|---|---|---|---|---|
| France Compétences RNCP | https://www.francecompetences.fr/recherche-rncp-rs/ | API publique | non | Surveillance nouvelles fiches RNCP avec mention IA / data / digital |
| Campus France | https://www.campusfrance.org | HTML | non | Recrutement international (signal volume) |

---

## 🏫 Organismes de formation — OF, CFA privés, EdTech

### Tier 1 — sources institutionnelles & écosystème

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| France Compétences — RNCP/RS | https://www.francecompetences.fr/recherche-rncp-rs/ | API | non | Daily | S2 |
| Liste organismes Qualiopi | https://travail-emploi.gouv.fr/formation-professionnelle/qualiopi | HTML | non | Monthly | S2 |
| Maddyness — section EdTech | https://www.maddyness.com/tag/edtech/ | RSS | non | Daily | S2 |
| Frenchweb — EdTech | https://www.frenchweb.fr | RSS / HTML | non | Daily | S2 |
| Les Échos Startup — EdTech | https://www.lesechos.fr/start-up | RSS | non | Daily | S2 |

### Tier 2 — presse RH/formation

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| Focus RH | https://www.focusrh.com | RSS | non | Daily | S2 |
| MyRHline | https://www.myrhline.com | RSS | non | Daily | S2 |
| Parlons RH | https://www.parlonsrh.com | RSS | non | Weekly | S2 |
| Centre Inffo (formation pro) | https://www.centre-inffo.fr | RSS | non | Daily | S2 |
| Le Quotidien de la Formation | https://www.lequotidiendelaformation.fr | HTML | partiel | Daily | S2 |

### Tier 3 — veille concurrence directe

Pages "actualités" et blogs des concurrents :

| Concurrent | URL | Type | Note |
|---|---|---|---|
| OpenClassrooms | https://blog.openclassrooms.com | RSS | Concurrent direct B2B |
| Cegos | https://www.cegos.fr/actualites | HTML | Leader marché entreprise FR |
| CrossKnowledge | https://www.crossknowledge.com/fr/blog | RSS | Plateforme LXP grand groupe |
| Demos | https://www.demos.fr/actualites | HTML | Leader historique |
| M2I Formation | https://www.m2iformation.fr | HTML | Très présent sur tech/data |
| 360Learning | https://360learning.com/fr/blog | RSS | LXP scale-up |
| ENI Service / ENI Editions | https://www.eni-service.fr | HTML | Spécialiste tech |
| Coorpacademy (CrossKnowledge) | https://www.coorpacademy.com/fr | HTML | Pilule pour mobile |

Méthode S2 : agrégation des RSS / scraping mensuel pour les pages news. Tags clés : "certification", "compétences IA", "data", "Power BI", "Excel" → signaux d'attaque.

### OPCO & financements

| Source | URL | Note |
|---|---|---|
| OPCO Atlas | https://www.opco-atlas.fr | Banque, assurance, conseil — appels d'offres formation |
| Akto | https://www.akto.fr | Services à forte intensité de main d'œuvre |
| Constructys | https://www.constructys.fr | BTP |
| Afdas | https://www.afdas.com | Culture, médias |
| Opco EP | https://www.opcoep.fr | Entreprises de proximité |
| Opco Mobilités | https://www.opcomobilites.fr | Transport, services automobile |
| Ocapiat | https://www.ocapiat.fr | Agri |
| Opco Santé | https://www.opco-sante.fr | Santé |
| Uniformation | https://www.uniformation.fr | Cohésion sociale |
| Opcommerce | https://www.lopcommerce.com | Commerce |

À scanner pour les **AO formation OPCO** (Tier 1 = AO publié, Tier 2 = note de cadrage stratégie).

---

## 🏢 Corporate / DRH — Entreprises & recrutement

### Tier 1 — signaux d'achat forts

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| LinkedIn Sales Navigator — alertes par compte | https://www.linkedin.com/sales/ | Apify ou manuel | oui (compte Sales Nav Isograd) | Daily | S3 |
| AEF Info — section RH | https://www.aefinfo.fr (section RH) | RSS | oui | Daily | S3 |
| Maddyness — levées de fonds | https://www.maddyness.com/levees-de-fonds/ | RSS | non | Daily | S3 |
| Frenchweb — entreprises | https://www.frenchweb.fr | RSS | non | Daily | S3 |
| Les Échos — Tech & Startup | https://www.lesechos.fr/tech-medias | RSS | partiel | Daily | S3 |
| Tracxn — fundraising France | https://tracxn.com | API | oui (payant) | Daily | S4 si licence |

### Tier 2 — presse RH & écosystème

| Source | URL | Type | Auth | Cadence | État |
|---|---|---|---|---|---|
| Focus RH | https://www.focusrh.com | RSS | non | Daily | S3 (déjà branché côté OF) |
| MyRHline | https://www.myrhline.com | RSS | non | Daily | S3 |
| Parlons RH | https://www.parlonsrh.com | RSS | non | Weekly | S3 |
| Welcome to the Jungle — magazine | https://www.welcometothejungle.com/fr/articles | RSS | non | Daily | S3 |
| RH Info | https://www.rhinfo.com | HTML | non | Weekly | S3 |
| Liaisons Sociales | https://www.liaisons-sociales.fr | HTML | partiel | Weekly | S3 |

### Tier 3 — labels & événements

| Source | URL | Type | Note |
|---|---|---|---|
| Top Employer Institute — palmarès FR | https://www.top-employers.com | HTML annuel | Liste annuelle (1x/an) |
| Great Place to Work — palmarès FR | https://greatplacetowork.fr | HTML trimestriel | Tier 2 marché RH |
| Choose My Company — HappyIndex | https://choosemycompany.com | HTML | Signal RH culture |
| HR Tech salon (sponsoring/exposants) | https://www.salondesrh.com | HTML annuel | Décideurs présents |
| Universités d'Été du MEDEF | https://www.medef.com | HTML annuel | Comptes top management |

### LinkedIn — par compte (40 look-alikes shortlist)

Pour chaque compte de la shortlist (cadrage-icp-corporate-segment-B.md §7), scraper via Apify Linkedin Company Scraper :
- Volume offres tech ouvertes (signal Tier 3 — embauche)
- Nouveaux titres "Head of L&D", "Head of TA" affichés (signal Tier 1 — nomination)
- Posts récents de l'entreprise (signal Tier 2 — communication)
- Nominations C-level (signal Tier 1)

Acteur Apify candidat : `apify/linkedin-company-scraper` (à valider en S3).

### Welcome to the Jungle — par compte

Pour chaque compte de la shortlist, page entreprise WTTJ → volume offres tech ouvertes + nouvelle équipe créée (signal Tier 3).

---

## Récap stratégique par sprint

### S2 (semaine 26-30 mai) — 12 sources branchées Education + OF

Sources prioritaires à brancher d'abord (max coverage, min friction) :
1. France Compétences API RNCP (Education + OF, no auth, simple JSON) ← **scraper démo S2**
2. TED Education (réutilisation Radar AO)
3. Maddyness RSS (EdTech)
4. Frenchweb RSS (EdTech + Tech)
5. Focus RH RSS (transverse OF + Corpo)
6. MyRHline RSS
7. Centre Inffo RSS
8. CGE RSS (Conférence Grandes Écoles)
9. France Universités RSS
10. Top 5 écoles (HEC, ESSEC, Polytechnique, Sciences Po, PSL) — pages news HTML
11. OpenClassrooms blog RSS (concurrence)
12. Cegos news HTML (concurrence)

Source payante à brancher en parallèle si tu valides : **AEF Info** (déjà ton outil Tier 1 manuel, on le passe en auto si tu donnes accès aux credentials Isograd).

### S3 (semaine 2-6 juin) — sources Corporate

13. Apify LinkedIn Company Scraper (40 comptes shortlist) — signaux nominations + posts
14. Maddyness levées de fonds (RSS dédié)
15. Les Échos Tech & Startup (RSS)
16. AEF Info section RH (si auth fournie)
17. Welcome to the Jungle (magazine + pages entreprises)
18. Top Employer / Great Place to Work palmarès

### S4 (semaine 9-13 juin) — digest & monitoring

19. Workflow GitHub Actions consolidé (1 run daily 6h UTC)
20. Template digest HTML Outlook
21. Job d'envoi Outlook lundi 8h (via outlook-campaign-runner)

---

## Politique anti-doublon & déduplication

Une même actualité peut être reprise par 3 médias différents (Maddyness + Frenchweb + Les Échos). Le pipeline doit dédupliquer :

1. Calcul d'un **fingerprint** par signal : hash SHA256 de `slugify(titre) + entité_principale + date_ISO_jour`
2. Si fingerprint déjà présent dans `data/<vertical>/signals.json` → on garde celui avec la source de meilleur tier
3. Si égalité de tier → on garde le plus récent dans le temps

Le fingerprint évite : (a) le bruit dans le hub, (b) le digest qui renvoie 3 fois le même signal sous des angles différents.
