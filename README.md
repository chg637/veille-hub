# Hub Veille Marché Isograd

Hub central d'agrégation de la veille marché Isograd — 3 verticaux (Education, Organismes de formation, Corporate/DRH) + vue agrégée.

**Live dashboard :** https://veille-hub-isograd.vercel.app

---

## État actuel — v0.2 (S2 en cours, 19 mai 2026)

- ✅ Maquette HTML standalone (4 onglets, scoring, signaux mock + réels)
- ✅ Déploiement Vercel statique
- ✅ Pipeline Python : schema commun + scoring + scraper Maddyness (1ʳᵉ source live)
- ✅ Workflow GitHub Actions daily (cron 6h UTC)
- ⏳ Autres scrapers Education / OF / Corporate : à brancher au fil de S2-S3
- ⏳ Connexion frontend ↔ JSON : à brancher fin S2

Voir le plan stratégique complet : `../plan-hub-veille-isograd.md` (hors repo, dans outputs).
Voir le cadrage ICP Corporate : `../cadrage-icp-corporate-segment-B.md`.
Voir le référentiel sources : [`sources.md`](sources.md).

## Triage des signaux (Traité / Ignoré)

Chaque carte du hub a des boutons **✓ Traité** / **✕ Ignoré** (et **↩ Rétablir**).
Les statuts sont stockés dans `data/triage.json`, committé dans le repo :

- **Lecture** : le front merge `data/triage.json` (repo) + `localStorage` (latest-wins sur `at`).
- **Écriture** : localStorage immédiat + push debounce 2,5 s vers le repo via l'API GitHub
  (token fine-grained à coller via « ⚙ sync GitHub » dans le footer — permission
  *Contents: Read & Write* sur ce repo uniquement, stocké en localStorage, jamais commité).
- **Maintenance** : `run_all.py` ne reset jamais ce fichier ; il pose `last_seen` sur les
  entrées dont le signal existe encore et purge celles disparues depuis plus de 14 jours.
- « Rétablir » écrit un tombstone `status: "actif"` (un simple delete serait ressuscité
  au merge multi-device).

Les signaux triés sont masqués par défaut (compteurs = signaux actifs) ; un lien
« Afficher les n signaux traités/ignorés » permet de les revoir.

---

## Structure du repo

```
veille-hub/
├── .github/
│   └── workflows/
│       └── scrape-daily.yml      # cron daily 6h UTC, lance les scrapers, commit JSON
├── data/
│   ├── education/
│   │   ├── accounts.json         # comptes prioritaires Education + leur ICP fit
│   │   ├── signals.json          # signaux capturés par les scrapers
│   │   └── sources.yml           # config sources Education
│   ├── of/
│   │   └── ...
│   └── corporate/
│       └── ...
├── scrapers/
│   ├── lib/
│   │   ├── schema.py             # dataclass Signal + fingerprint dédup
│   │   └── scoring.py            # scoring base + boost ICP
│   ├── education/
│   │   └── (à venir : cge.py, france_universites.py, ted_edu.py, ...)
│   ├── of/
│   │   └── maddyness.py          # ✅ 1er scraper opérationnel
│   └── corporate/
│       └── (à venir : maddyness_levees.py, linkedin_nominations.py, aef_rh.py)
├── index.html                    # le hub HTML statique servi par Vercel
├── sources.md                    # référentiel exhaustif sources par vertical
├── requirements.txt              # deps Python pour les scrapers
├── vercel.json                   # config déploiement statique
├── .gitignore
└── README.md
```

---

## Roadmap de branchement des sources

### S2 (sprint actuel — 19-30 mai)
- ✅ Maddyness RSS (Corporate + OF)
- 🔄 France Compétences RNCP (Education + OF)
- 🔄 Conférence Grandes Écoles RSS (Education)
- 🔄 France Universités RSS (Education)
- 🔄 Centre Inffo RSS (OF)
- 🔄 Focus RH / MyRHline RSS (Transverse)
- 🔄 Top 5 écoles (HEC, ESSEC, Polytechnique, Sciences Po, PSL) — HTML
- 🔄 Concurrents OF (OpenClassrooms, Cegos) — HTML

### S3 (2-6 juin)
- LinkedIn nominations via Apify (Corporate)
- Maddyness levées de fonds (Corporate, focus levée Série B+)
- Les Échos Tech & Startup (Corporate)
- AEF Info section RH (Corporate, si auth fournie)
- Welcome to the Jungle magazine (Corporate)

### S4 (9-13 juin)
- Workflow GitHub Actions consolidé
- Template digest HTML Outlook
- Job d'envoi Outlook lundi 8h via outlook-campaign-runner
- Premier digest envoyé cercle réduit (Charles + Juliette)

---

## Lancer les scrapers en local

```bash
# Installer les dépendances
pip install -r requirements.txt

# Lancer un scraper individuel
python scrapers/of/maddyness.py

# Vérifier les signaux capturés
cat data/corporate/signals.json | python -m json.tool | head -50
```

---

## Modèle de données — un signal

```json
{
  "id": "sig-2026-05-19-a1b2c3d4e5f6",
  "date_capture": "2026-05-19",
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
  "produit_match": [],
  "owner": null,
  "action_reco": null,
  "deadline_action": null,
  "status": "new"
}
```

La taxonomie est unifiée à travers les 3 verticaux — un signal est toujours scoré, tagué par type, et fingerprinté pour la déduplication cross-source.

---

## Mises à jour manuelles

Tu peux toujours pousser manuellement :

```bash
# Modifier index.html, ajouter un signal en dur, etc.
git add .
git commit -m "feat: ajout signal Mistral"
git push  # si remote configuré

# Ou déployer direct sur Vercel sans Git remote
npx vercel --prod
```

---

## Premier déploiement Vercel (déjà fait)

Le repo est déjà déployé sur Vercel (compte `charlegosset-7661's projects`, projet `veille-hub-isograd`).

Pour redéployer après changement local :

```bash
npx vercel --prod
```

À configurer plus tard (quand `gh auth` sera résolu) : connexion repo GitHub `isograd/veille-hub` ↔ Vercel pour redéploiement automatique sur push.

---

**Charles GOSSET — Isograd / Tosa**
v0.2 — 19 mai 2026
