# Hub Veille Marché Isograd

Hub central d'agrégation de la veille marché Isograd : 5 volets (Education, Organismes de formation, RNCP, Corporate/DRH, Appels d'offres) + une vue agrégée "Top signaux 7 derniers jours".

**Live dashboard :** https://veille-hub-isograd.vercel.app
**Repo :** https://github.com/chg637/veille-hub

Principe : on ne garde que les **signaux d'achat actionnables** (un compte identifié, un déclencheur précis, un produit Isograd à pitcher). Le bruit éditorial (tribunes, analyses, séminaires) est écarté dès l'entrée.

---

## État actuel (README recalé le 5 octobre 2026)

- ✅ 5 volets live, front connecté aux JSON de `data/` : Education, OF, RNCP, Corporate, AO
- ✅ 17 scrapers actifs lancés par `scrapers/run_all.py` (liste ci-dessous)
- ✅ Workflow GitHub Actions quotidien (cron 6h UTC) qui committe `data/` dans `main`
- ✅ Filtre "signal d'achat" strict, scoring par type de signal, tiers 1/2/3
- ✅ Triage persistant Traité / Ignoré (`data/triage.json`) + triage en masse par volet
- ✅ Mail drafté + contacts cibles (liens Sales Nav préremplis) sur chaque signal
- ✅ Santé des sources affichée dans le hub (muette / en erreur) via `data/_meta.json`
- ✅ Deux boucles manuelles par CSV : Radar Hebdo Tosa (Education) et AO curated
- ⏳ `accounts.json` (comptes prioritaires + boost ICP) : vides pour Education, OF et Corporate, à alimenter

Dernier run enregistré : 5 octobre 2026, 64 signaux (AO 30, RNCP 14, Education 10, Corporate 9, OF 1).

Voir aussi : [`sources.md`](sources.md) (référentiel des sources par vertical) et [`docs/lessons-learned-ao.md`](docs/lessons-learned-ao.md) (leçons des AO traités, à relire avant de toucher au filtre AO).

---

## Comment ça tourne

Chaque jour, `scrapers/run_all.py` :

1. **Remet à zéro** les `data/<volet>/signals.json` (on ne garde que ce que produisent les scrapers actifs du run, un scraper désactivé ne laisse donc rien derrière lui).
2. **Lance chaque scraper** de la liste `SCRAPERS`, dans l'ordre. Un scraper qui plante n'arrête pas les autres.
3. **Filtre** chaque signal avec `is_purchase_signal` (3 critères cumulatifs, voir plus bas), puis fusionne et déduplique par fingerprint (titre + compte + jour).
4. **Maintient le triage** : `data/triage.json` n'est jamais reset ; `last_seen` est posé sur les signaux encore présents, les entrées disparues depuis plus de 14 jours sont purgées.
5. **Écrit `data/_meta.json`** : date du run, total, et nombre de signaux par scraper (`0` = muet, `-1` = erreur).

Le workflow committe ensuite `data/` (utilisateur `veille-bot`) avec retry de rebase, pour absorber d'éventuels commits humains arrivés entre-temps. Il peut aussi être lancé à la main (`workflow_dispatch`).

### Les critères "signal d'achat"

Un signal n'est retenu que s'il remplit les trois :

1. son `signal_type` est dans la liste blanche `PURCHASE_SIGNAL_TYPES` ;
2. son `compte` est identifiable (pas vide, pas dans `BLACKLIST_COMPTES`) ;
3. un produit Isograd est matché (`produit_match` non vide).

### Scoring et tiers

- **Hors AO** : score de base selon le type de signal (ex. `plan_recrutement` 88, `nomination_chro` 85, `accreditation` 85, `levee_fonds` 85), plus un bonus selon le tier de la source (+10 / +5 / 0). Boost ICP optionnel via `accounts.json` (+10 si ICP ≥ 80, -15 si < 40), pas encore alimenté.
- **AO** (`score_ao`, v5.4) : base par type d'avis (publié 55, pré-info 45, modificatif 40, attribué 25) + fit métier (cappé à 30) + acheteur whitelist ICP (+8) + fenêtre de réponse (+5 entre J-7 et J-45, -10 sous J-7, -25 si échu). Plafond 98.
- **Tiers** : score ≥ 80 = tier 1 (action sous 7 jours), ≥ 60 = tier 2 (30 jours), sinon tier 3 (surveillance). Chaque signal reçoit une action recommandée et une deadline selon son tier (`scrapers/lib/actions.py`).
- **Produit matché** : Corporate = ITS (+ Tosa Corporate sur les signaux stratégiques RH/IA) ; Education = Pack Education Tosa (+ ITS ou Cert IA selon le signal) ; OF, RNCP et AO = ITS.

---

## Scrapers actifs par volet

| Volet | Scraper | Source | Notes |
|---|---|---|---|
| Education | `radar_hebdo_tosa` | CSV curated `data/curated/radar_hebdo_tosa.csv` | Signal le plus qualifié du hub, fenêtre 90 jours côté hub |
| Education | `presse_sup` | RSS Educpros, MGE, PGE, Business Cool | |
| Education | `cge` | Conférence des Grandes Écoles | Seules les labellisations passent le filtre |
| OF | `levees_edtech` | Maddyness + Sifted filtrés EdTech | |
| OF | `presse_of` | RSS Centre Inffo, Digiformag | Levées/rachats d'OF, offres certif/bureautique/IA, Qualiopi |
| RNCP | `france_competences` | data.gouv.fr (fiches RNCP/RS) | Fenêtre 30 jours, 50 signaux max par run |
| Corporate | `levees_rss` | Maddyness FR + Sifted EU | Levées Série B+ |
| Corporate | `signaux_marche_rh` | myRHline + Parlons RH | Pivots concurrents, nominations |
| Corporate | `google_news_rh` | Google News RSS | Nominations DRH/CHRO, plans de recrutement (≥ 50 postes), plans de formation IA |
| AO | `ao_curated` | CSV curated `data/curated/ao_curated.csv` | AO repérés à la main (centraledesmarches, LinkedIn, collègues) |
| AO | `boamp_direct` | API officielle DILA (BOAMP) | Fenêtre 60 jours, capte large puis filtre fin |
| AO | `ted_europe` | TED (UE) | Fenêtre 60 jours, gros tickets au-dessus des seuils communautaires |
| AO | `seed_from_radar` | Radar AO (TED + BOAMP) | Marchés publics formation/certification |
| AO | `france_marches` | France Marchés via Apify | Skip propre si `APIFY_TOKEN` absent |
| AO | `maximilien_idf` | Profil acheteur Île-de-France via Apify | Skip propre si `APIFY_TOKEN` absent |
| AO | `profils_place.esr_global` | Profils acheteurs PLACE, catégorie ESR | Un seul scraper pour tout l'ESR |
| AO | `profils_place.fph_sante` | Profils acheteurs PLACE, catégorie santé publique | AP-HP, CHU, EHPAD publics |

Les articles RSS plus vieux que 14 jours sont écartés par défaut (`DEFAULT_MAX_AGE_DAYS`).

### Désactivés (gardés en commentaire dans `run_all.py` pour réactivation rapide)

Sources de contenu éditorial sans signal d'achat direct : `of.maddyness`, `of.maddyness_edtech` (flux abandonné par Maddyness), `education.hec_paris`, `education.escp`, `education.hceres`, `corporate.myrhline`, `corporate.parlonsrh`.

### À brancher

- LinkedIn nominations CHRO via Apify (Corporate)
- AEF Info section RH (Corporate, nécessite les identifiants `AEF_USERNAME` / `AEF_PASSWORD`)
- Alimenter les `accounts.json` pour activer le boost ICP

---

## Boucles manuelles (CSV)

**Radar Hebdo Tosa (Education).** Chaque mercredi, l'export CSV du Radar est collé dans `data/curated/radar_hebdo_tosa.csv`, puis commit. Le scraper le transforme en signaux au prochain cron. Seules les lignes des 90 derniers jours sont prises en compte (l'historique complet vit dans le Radar).

**AO curated.** Quand un AO est repéré hors radar automatique, on ajoute une ligne à `data/curated/ao_curated.csv` (colonnes : Acheteur, Reference, Titre, Description, CPV, Deadline, Date_Publication, URL_DCE, Segment, Type_Marche, Notes). Le champ `Notes` sert aussi à tracer le statut (déposé, retrait, etc.).

---

## Triage des signaux (Traité / Ignoré)

Chaque carte du hub a des boutons **✓ Traité** / **✕ Ignoré** (et **↩ Rétablir**), avec un triage en masse par volet. Les statuts sont stockés dans `data/triage.json`, committé dans le repo :

- **Lecture** : le front fusionne `data/triage.json` (repo) et `localStorage` (le plus récent gagne, selon `at`).
- **Écriture** : localStorage immédiat, puis push différé de 2,5 s vers le repo via l'API GitHub. Le token fine-grained se colle via « ⚙ sync GitHub » dans le footer (permission *Contents: Read & Write* sur ce repo uniquement), il reste dans le navigateur et n'est jamais commité.
- **Maintenance** : `run_all.py` ne reset jamais ce fichier (voir plus haut pour `last_seen` et la purge à 14 jours).
- **Rétablir** écrit un tombstone `status: "actif"` (un simple delete serait ressuscité au merge multi-device).

Les signaux triés sont masqués par défaut (les compteurs affichent les signaux actifs). Un lien « Afficher les n signaux traités/ignorés » permet de les revoir.

## Santé des sources

Le footer du hub affiche `x/y sources actives` à partir de `data/_meta.json`. Un scraper muet un jour donné est normal ; un scraper en erreur (`-1`) passe l'indicateur en rouge. Survoler le badge donne le détail scraper par scraper.

---

## Structure du repo

```
veille-hub/
├── .github/workflows/
│   └── scrape-daily.yml          # cron 6h UTC + lancement manuel, commit de data/
├── data/
│   ├── _meta.json                # date du run + santé par scraper
│   ├── triage.json               # statuts Traité / Ignoré (écrit par le front)
│   ├── curated/
│   │   ├── radar_hebdo_tosa.csv  # boucle manuelle Education (mercredi)
│   │   └── ao_curated.csv        # boucle manuelle AO
│   ├── education/  of/  rncp/  corporate/  ao/
│   │   ├── signals.json          # produit par run_all (reset à chaque run)
│   │   ├── accounts.json         # comptes prioritaires + ICP (à alimenter)
│   │   └── sources.yml           # config sources du volet (sauf rncp)
├── scrapers/
│   ├── run_all.py                # orchestrateur : liste SCRAPERS, filtre, merge, meta
│   ├── lib/
│   │   ├── schema.py             # dataclass Signal, filtre signal d'achat, fingerprint, merge
│   │   ├── scoring.py            # scores par type, score AO, tiers, produit matché, boost ICP
│   │   ├── actions.py            # action recommandée + deadline par (volet, type)
│   │   ├── outreach.py           # mail drafté + contacts cibles (URL Sales Nav)
│   │   ├── triage.py             # maintenance de data/triage.json
│   │   ├── rss_helpers.py        # utilitaires RSS
│   │   ├── place_helpers.py      # utilitaires profils acheteurs PLACE
│   │   └── edtech_filter.py      # filtre EdTech pour les flux de levées
│   ├── education/  of/  corporate/
│   └── ao/                       # dont profils_place/
├── docs/
│   └── lessons-learned-ao.md     # leçons des AO traités (Paris-Saclay, Neoma...)
├── index.html                    # hub statique servi par Vercel (HTML + JS, sans build)
├── sources.md                    # référentiel des sources par vertical
├── requirements.txt              # deps Python des scrapers
├── vercel.json                   # config de déploiement statique + headers
├── .vercelignore                 # exclut scrapers, workflows et .md du déploiement web
└── README.md
```

---

## Lancer les scrapers en local

```bash
# Installer les dépendances
pip install -r requirements.txt

# Tout lancer (réécrit data/*/signals.json et data/_meta.json)
python scrapers/run_all.py

# Vérifier ce qui a été capté
python -m json.tool data/corporate/signals.json | head -50
cat data/_meta.json
```

Variables d'environnement optionnelles : `APIFY_TOKEN` (France Marchés, Maximilien IDF ; sans lui ces scrapers sont simplement ignorés), `AEF_USERNAME` / `AEF_PASSWORD` (réservés au futur scraper AEF). En CI, ce sont des secrets du repo.

Attention : `run_all.py` remet à zéro les `signals.json` avant de scraper. Pour tester un seul scraper, l'importer et appeler `scrape()` plutôt que de relancer tout le runner.

---

## Modèle de données : un signal

```json
{
  "id": "sig-2026-05-19-a1b2c3d4e5f6",
  "date_capture": "2026-05-19",
  "date_publication": "2026-05-18",
  "vertical": "corporate",
  "sous_segment": "ETI tech / IA",
  "compte": "Mistral AI",
  "titre": "Mistral AI boucle une nouvelle acquisition en Autriche",
  "description": "Le champion français de l'IA générative...",
  "source": "Maddyness",
  "source_tier": 2,
  "url": "https://www.maddyness.com/2026/05/19/...",
  "signal_type": "plan_ia",
  "tier": 1,
  "score": 90,
  "produit_match": ["ITS", "Tosa Corporate"],
  "owner": null,
  "action_reco": "...",
  "deadline_action": "2026-05-26",
  "email_draft": { "subject": "...", "body": "..." },
  "contacts_cibles": [
    { "poste": "Head of TA", "priorite": 1, "sales_nav_url": "https://...", "raison": "..." }
  ],
  "status": "new"
}
```

Taxonomie unifiée sur les 5 volets : un signal est toujours scoré, tagué par type, relié à un produit et fingerprinté pour la déduplication. `date_publication` est la date réelle de l'article ou de l'AO ; le front retombe sur `date_capture` si elle est absente.

---

## Déploiement

Le hub est un site statique (aucun build) déployé sur Vercel, projet `veille-hub-isograd`. Le workflow committe dans `main` ; le commentaire du workflow suppose que Vercel redéploie à chaque push. À vérifier côté projet Vercel que le repo GitHub `chg637/veille-hub` y est bien connecté (l'ancienne version de ce README notait que la connexion restait à faire). À défaut, déploiement manuel :

```bash
npx vercel --prod
```

Mises à jour à la main (modifier `index.html`, ajouter une ligne dans un CSV curated) : commit puis push sur `main`.

---

**Charles GOSSET, Isograd / Tosa**
README mis à jour le 5 octobre 2026
