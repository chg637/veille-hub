"""
Scraper Corporate — signaux d'achat ITS via levées de fonds (Maddyness + Sifted).

Logique : une levée Series B+ (>= 10M€) dans une scale-up = pattern de recrutement
intensif sur les 6-12 mois suivants = fenêtre d'opportunité ITS pour
standardiser l'évaluation des candidats.

Sources :
- Maddyness (FR) : RSS principal
- Sifted (EU) : RSS principal

Filtre :
- Item doit matcher un pattern de levée (€ ou $)
- Montant minimum : 10M€ (équivalent : 11M$)
- Exclure éditoriaux (mapping, leaderboard, Tribune, agrégats hebdo)
- Exclure secteurs hors scope ITS (quantique pure, défense pure)
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, extract_compte, is_editorial_noise  # noqa: E402
from scrapers.lib.outreach import email_draft_levee, get_contacts_cibles  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "corporate"

# Blacklist : noms d'investisseurs / fonds / accélérateurs qui ne doivent JAMAIS
# être extraits comme "compte" cible commerciale. Ils annoncent souvent leurs
# investissements ("X backs Y", "X-backed Z raises"), mais c'est Y/Z notre cible.
INVESTOR_BLACKLIST = {
    "KKR", "EQT", "Balderton", "Balderton-backed", "Sequoia", "Earlybird",
    "Index", "Insight", "Insight Partners", "Tiger", "Tiger Global",
    "Accel", "a16z", "Andreessen", "Andreessen Horowitz",
    "Blackstone", "Carlyle", "Apollo", "Bain", "Bain Capital",
    "Lightspeed", "General Catalyst", "Greylock", "Kleiner Perkins",
    "GV", "Google Ventures", "Atomico", "Northzone", "Notion Capital",
    "Partech", "Idinvest", "Eurazeo", "Bpifrance", "BPI",
    "Y Combinator", "Techstars", "Founders Fund",
    "AVP", "Antoine Vibert", "Iris Capital", "Serena", "Serena Capital",
    "DST", "Coatue", "Headline", "Headline.com",
    "Heartcore", "EQT Ventures", "Hoxton", "Highland",
}

# Patterns EN spécifiques aux annonces de levée — extraire le nom de la boîte
# avant le verbe "raises/raised/closed/secures"
EN_LEVEE_PATTERNS = [
    # "Balderton-backed payments startup Primer raises $100m"
    # → Primer (juste avant "raises")
    re.compile(r"(?:[A-Z][\w-]+-backed\s+)?(?:\w+\s+)*?([A-Z][\w&\.-]+(?:\s+[A-Z][\w&\.-]+){0,2})\s+(?:raises|raised|closes|closed|secures|secured|nets)\b"),
    # "Startup Primer secures $100m"
    re.compile(r"(?:^|\s)([A-Z][\w&\.-]+(?:\s+[A-Z][\w&\.-]+){0,2})\s+(?:announces|announced)\s+\$"),
    # "in $80m round led by KKR" — pas extractible directement
    # → Si on a juste "X backs Y in $Zm round", X est le VC = à blacklister
]

SOURCES = [
    {
        "name": "Maddyness",
        "url": "https://www.maddyness.com/feed/",
        "lang": "fr",
        "tier": 1,
    },
    {
        "name": "Sifted",
        "url": "https://sifted.eu/feed",
        "lang": "en",
        "tier": 1,
    },
]

# Patterns regex pour détecter une levée + extraire le montant
# Retourne (montant_unité, devise) — l'unité est en millions par défaut
MONTANT_PATTERNS = [
    # FR : "X millions d'euros" / "X M€"
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:millions?|m)\s*(?:d['']?euros?|€|euros?)\b", re.I), "M", "EUR"),
    (re.compile(r"€\s*(\d+(?:[.,]\d+)?)\s*(?:m|million)?", re.I), "M", "EUR"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*M\s*€", re.I), "M", "EUR"),
    # FR : "X millions de dollars" / "X M$"
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:millions?|m)\s*(?:de\s+dollars?|\$|dollars?)\b", re.I), "M", "USD"),
    (re.compile(r"\$\s*(\d+(?:[.,]\d+)?)\s*(?:m|million)?", re.I), "M", "USD"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*M\s*\$", re.I), "M", "USD"),
    # EN : "$80m round" / "raises $80m"
    (re.compile(r"\$\s*(\d+(?:[.,]\d+)?)\s*m\b", re.I), "M", "USD"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s+round", re.I), "M", "USD"),
    # EN : "€500m fund"
    (re.compile(r"€\s*(\d+(?:[.,]\d+)?)\s*m\b", re.I), "M", "EUR"),
]

# Mots-clés indiquant une levée (au moins un doit matcher)
LEVEE_KEYWORDS = [
    "lève", "lèvent", "levée", "boucle", "bouclent",
    "raises", "raised", "raising", "funding", "funded",
    "Series A", "Series B", "Series C", "Series D",
    "round", "tour de table", "tour de financement",
]

# Secteurs / patterns à exclure (peu de fit ITS)
EXCLUSION_PATTERNS = [
    re.compile(r"\bquantum\b|quantique", re.I),
    re.compile(r"\bdefence\b|\bdefense\b|défense\b", re.I),
    re.compile(r"\bbiotech\b", re.I),  # pharma R&D = peu de recrutement softskills
    re.compile(r"\bspace\b|spatial", re.I),  # tech aérospatiale = peu de RH classique
    re.compile(r"acquires?\b|rachète|rachat\b", re.I),  # M&A ≠ levée (autre signal)
    # Fund qui lève (≠ entreprise qui lève)
    re.compile(r"raising.*fund\b|fund.*raising", re.I),
    re.compile(r"\bVC\s+(?:fund|raises)|venture fund", re.I),
    # Récap / agrégats hebdomadaires
    re.compile(r"ont levé.*cette semaine", re.I),
    re.compile(r"^Les\s+\w+\s+ont levé", re.I),
    # Politique macro / réglementation
    re.compile(r"\bAI Act\b|RGPD|GDPR", re.I),
    re.compile(r"Macron annonce|gouvernement annonce", re.I),
    # Listicles / analyses
    re.compile(r"^\d+\+?\s+(companies|startups|investors)", re.I),
    re.compile(r"mapped\b|leaderboard|top investors", re.I),
]


def _extract_compte_levee(title: str, lang: str) -> str:
    """
    Extraction du nom de la boîte qui lève, spécifique aux annonces de levée.

    Stratégie pour EN : pattern "<COMPANY> raises|closes|secures" (avant le verbe).
    Stratégie pour FR : utilise extract_compte standard (verbes "lève|boucle").
    Filtre : si extrait → si dans INVESTOR_BLACKLIST → fallback / retour "Inconnu".
    """
    candidate = None

    if lang == "en":
        for pattern in EN_LEVEE_PATTERNS:
            m = pattern.search(title)
            if m:
                cand = m.group(1).strip()
                # Strip noisy prefixes
                parts = cand.split()
                while parts and parts[0].lower() in {"the", "a", "an", "uk", "us", "european", "german", "french", "british", "italian", "spanish"}:
                    parts.pop(0)
                if parts:
                    candidate = " ".join(parts)
                    break

    if not candidate:
        candidate = extract_compte(title)

    # Filtre investor blacklist
    candidate_norm = candidate.replace("-backed", "").strip()
    if candidate_norm in INVESTOR_BLACKLIST or candidate in INVESTOR_BLACKLIST:
        # Fallback : essayer de trouver un autre nom de boîte dans le titre
        if lang == "en":
            for pattern in EN_LEVEE_PATTERNS:
                m = pattern.search(title)
                if m:
                    alt = m.group(1).strip()
                    alt_parts = alt.split()
                    while alt_parts and alt_parts[0].lower() in {"the", "a", "an", "uk", "us", "european"}:
                        alt_parts.pop(0)
                    if alt_parts:
                        alt = " ".join(alt_parts)
                        if alt not in INVESTOR_BLACKLIST and alt.replace("-backed", "").strip() not in INVESTOR_BLACKLIST:
                            return alt
        return "Inconnu"

    return candidate


def _extract_montant_meur(text: str) -> tuple[float, str] | None:
    """
    Extrait le montant en M€ équivalent depuis le titre + description.
    Retourne (montant_meur, raw_match) ou None.
    """
    for pattern, unit, currency in MONTANT_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        val_str = m.group(1).replace(",", ".")
        try:
            val = float(val_str)
        except ValueError:
            continue
        # Conversion en M€ (USD * 0.92 = EUR approx)
        meur = val * 0.92 if currency == "USD" else val
        raw = f"{val:.1f}M {currency} (~{meur:.1f}M€)"
        return meur, raw
    return None


def _is_levee(title: str, description: str) -> bool:
    """Détermine si l'item est une levée (au moins 1 keyword)."""
    blob = f"{title} {description}".lower()
    return any(kw.lower() in blob for kw in LEVEE_KEYWORDS)


def _is_excluded(title: str, description: str) -> str | None:
    """Si exclu, retourne la raison. Sinon None."""
    blob = f"{title} {description}"
    for pattern in EXCLUSION_PATTERNS:
        if pattern.search(blob):
            return pattern.pattern[:50]
    return None


def _determine_levee_tier(meur: float) -> int:
    """
    Tier basé sur la taille de la levée :
    - >= 50M€ : Tier 1 (HOT — scale-up confirmé, recrutement massif)
    - 20-50M€ : Tier 2 (Series B+ — phase de structuration)
    - 10-20M€ : Tier 3 (Series A late — encore early mais signal)
    """
    if meur >= 50:
        return 1
    if meur >= 20:
        return 2
    return 3


def _generate_corporate_action(compte: str, montant_raw: str, meur: float, source_url: str, date_iso: str) -> str:
    """Action commerciale ITS pour une levée."""
    if meur >= 50:
        contexte = f"💰 Levée {montant_raw} → scale-up confirmé, plan de recrutement massif sur 12 mois"
        urgence = "🔥 PRIORITÉ — fenêtre 30j (avant que les RH s'organisent)"
    elif meur >= 20:
        contexte = f"💰 Levée {montant_raw} → Series B+, structuration des processus RH en cours"
        urgence = "🎯 Fenêtre 60j (timing optimal post-Series B)"
    else:
        contexte = f"💰 Levée {montant_raw} → Series A late, signal mais startup encore early"
        urgence = "📌 À surveiller — relancer dans 3-6 mois quand ils auront recruté 30+"

    action = (
        f"📋 **Source** : {source_url}\n"
        f"🎯 **Décideur cible** : Chief People Officer / Head of Talent Acquisition / Head of Hiring\n"
        f"💡 **Angle de valeur** : industrialiser l'évaluation des candidats à scale, "
        f"standardiser les tests compétences (techniques + soft) sur ITS\n"
        f"{contexte}\n"
        f"{urgence}\n"
        f"🥊 **Concurrents probables** : AssessFirst, Central Test, Codingame, HackerRank, "
        f"BrightHire (selon profil tech vs sales)\n"
        f"📅 Date annonce : {date_iso}"
    )
    return action


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    signals = []

    for src in SOURCES:
        try:
            items = fetch_rss(src["url"], limit=30)
        except Exception as e:
            logger.warning("[Corp/%s] fetch failed: %s", src["name"], e)
            continue
        logger.info("[Corp/%s] %d items fetched", src["name"], len(items))

        for item in items:
            title = item["title"]
            description = item["description"]
            link = item["link"]
            date_iso = item["date_iso"]

            # 1. Filtre éditorial (Tribune, Top 10, etc.)
            if is_editorial_noise(title):
                logger.debug("[Corp/%s] ÉDITORIAL : %s", src["name"], title[:70])
                continue

            # 2. Exclusion par secteur / type
            excl = _is_excluded(title, description)
            if excl:
                logger.debug("[Corp/%s] EXCLU (%s) : %s", src["name"], excl, title[:70])
                continue

            # 3. Est-ce une levée ?
            if not _is_levee(title, description):
                continue

            # 4. Montant suffisant ?
            montant = _extract_montant_meur(f"{title} {description}")
            if not montant:
                logger.info("[Corp/%s] PAS DE MONTANT EXTRACTIBLE : %s", src["name"], title[:70])
                continue
            meur, montant_raw = montant
            if meur < 10:
                logger.info("[Corp/%s] TROP PETIT (%.1fM€) : %s", src["name"], meur, title[:70])
                continue

            # 5. Extraction du compte (avec blacklist investisseurs)
            compte = _extract_compte_levee(title, src.get("lang", "fr"))
            if compte == "Inconnu" or len(compte) < 2:
                logger.info("[Corp/%s] COMPTE NON IDENTIFIÉ (investor ou parsing) : %s", src["name"], title[:70])
                continue

            # 6. Build signal
            tier = _determine_levee_tier(meur)
            score = 80 if meur >= 50 else (65 if meur >= 20 else 50)
            action = _generate_corporate_action(compte, montant_raw, meur, link, date_iso)

            sig = Signal(
                id=fingerprint(title, compte, date_iso),
                date_capture=today,
                vertical=VERTICAL,
                sous_segment=f"Scale-up / Levée Series B+ ({src['name']})",
                compte=compte,
                titre=title[:200],
                description=description[:400],
                source=src["name"],
                source_tier=src["tier"],
                url=link,
                signal_type="levee_fonds",
                tier=tier,
                score=score,
                produit_match=produit_match_for("levee_fonds", VERTICAL),
                owner="Charles",
                action_reco=action,
                deadline_action=None,  # à enrichir manuellement si RDV calé
                status="new",
                date_publication=date_iso,
                email_draft=email_draft_levee(compte, montant_raw, meur, link),
                contacts_cibles=get_contacts_cibles("levee_fonds", compte),
            )
            signals.append(sig)
            logger.info(
                "[Corp/%s] [%s/%d] %s — %s (%.0fM€)",
                src["name"], "levee_fonds", score, compte, title[:60], meur,
            )

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux Corporate captés ===", len(sigs))
    for s in sigs:
        logger.info("  [%d/T%d] %s — %s", s.score, s.tier, s.compte, s.titre[:80])


if __name__ == "__main__":
    main()
