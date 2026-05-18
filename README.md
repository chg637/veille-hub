# Hub Veille Marché Isograd

Hub central d'agrégation de la veille marché Isograd — 3 verticaux (Education, Organismes de formation, Corporate/DRH) + vue agrégée.

**Live dashboard :** _à compléter après déploiement Vercel — ex. https://veille-hub-isograd.vercel.app_

---

## État actuel — v0.1 prototype

- ✅ Maquette HTML standalone validée (4 onglets, scoring, signaux mock + vrais)
- ⏳ Sources Education : Radar Hebdo Tosa + Radar AO (à brancher en S2)
- ⏳ Sources OF : à étoffer (France Compétences, Qualiopi, EdTech) — S2
- ⏳ Sources Corporate/DRH : ICP à finaliser puis sources à brancher — S3
- ⏳ Digest hebdo Outlook lundi 8h — S4

Voir le plan stratégique complet : `../plan-hub-veille-isograd.md`

---

## Stack

- **v0.1 (aujourd'hui)** : HTML/CSS/JS standalone, déployé en statique sur Vercel
- **v0.2 (S2)** : migration Next.js + API routes + données JSON depuis le repo
- **v0.3 (S3-S4)** : scrapers Python via GitHub Actions (daily 6h UTC) → JSON commit → Vercel rebuild

---

## Déployer sur Vercel (premier push)

### 1. Initialiser le repo Git local

```bash
cd veille-hub
git init
git branch -M main
git add .
git commit -m "init: hub veille isograd v0.1 prototype"
```

### 2. Créer le repo sur GitHub (via CLI ou interface)

Via GitHub CLI (recommandé) :

```bash
gh repo create isograd/veille-hub --public --source=. --push --description "Hub veille marché Isograd"
```

Ou manuel : créer le repo sur github.com puis :

```bash
git remote add origin git@github.com:isograd/veille-hub.git
git push -u origin main
```

### 3. Connecter Vercel

1. Aller sur https://vercel.com/new
2. Importer le repo `isograd/veille-hub`
3. Framework preset : **Other** (static site)
4. Build command : (laisser vide)
5. Output directory : `.`
6. Deploy

Vercel détecte automatiquement `vercel.json` et déploie en statique. Premier déploiement en ~30 secondes. URL générée : `veille-hub-{hash}.vercel.app` — tu peux ajouter un domaine custom dans les settings (ex. `veille.isograd.com`).

---

## Mises à jour futures

Chaque `git push` sur `main` redéploie automatiquement Vercel. Pour modifier le hub :

```bash
# édite index.html
git add index.html
git commit -m "feat: nouveau signal Corporate Mistral"
git push
```

---

## Ouverture en local (sans déploiement)

Tu peux aussi simplement ouvrir `index.html` dans Firefox ou Chrome — clic droit sur le fichier → "Ouvrir avec" → Firefox. Aucun serveur nécessaire, tout est inline.

---

## Architecture cible (S2-S4)

Voir le plan stratégique pour les détails (`../plan-hub-veille-isograd.md` section 3).

```
GitHub Actions (daily 6h UTC)
  └─ scrapers Python (Education / OF / Corporate)
      └─ commit JSON dans le repo
          └─ Vercel rebuild auto
              └─ Hub affiche données fraîches
```

---

**Charles GOSSET — Isograd / Tosa**
v0.1 — 18 mai 2026
