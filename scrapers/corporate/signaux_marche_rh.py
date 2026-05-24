"""
Scraper Corporate Sprint A2 — Signaux marché RH (myRHline + Parlons RH).

Détecte 2 types de signaux d'achat ITS dans les flux RH FR :

1. **Concurrent_news** : un concurrent direct (Central Test, AssessFirst, Talogy,
   Pix, 365Talents, HackerRank, Workday, etc.) est mentionné dans le TITRE.
   → action : reach-out aux ex-clients du concurrent
   → ex: "Central Test devient Key Predict" = pivot de marque = clients perturbés

2. **Nomination_chro** : pattern de nomination (nommé, rejoint, intègre, prend la
   direction) dans le titre, sur poste senior RH (CHRO, DRH, Head of TA, CDO).
   → action : InMail/email sous 30j (fenêtre nouvelle prise de poste)
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

logger = logging.getLogger(__name__)

VERTICAL = "corporate"

SOURCES = [
    {"name": "myRHline", "url": "https://www.myrhline.com/feed/", "tier": 1},
    {"name": "Parlons RH", "url": "https://www.parlonsrh.com/feed/", "tier": 1},
]

# ─────────────────────────────────────────────────────────────────────────────
# Concurrents directs ITS / Tosa à monitorer
# Si l'un d'eux apparaît dans le TITRE → signal "concurrent_news"
# ─────────────────────────────────────────────────────────────────────────────
CONCURRENTS = [
    # Concurrents directs ITS (test/évaluation/assessment)
    "Central Test", "Key Predict",
    "AssessFirst", "Talogy", "eDarwin",
    "Pix", " PIX ",  # PIX en majuscule (concurrent État pour DigComp)
    "OpenClassrooms",
    "365Talents", "MyCareerPath",
    "HireRoad", "Skillup",
    "Codingame", "CodinGame", "HackerRank",
    "Workday", "SAP SuccessFactors", "Cornerstone",
    "Mercer Mettl", "Mettl",
    "Mercer", "BrightHire",
    "TestGorilla", "Maki People",
    "AssessTeam", "iMocha",
    # Concurrents Tosa (bureautique / digital skills)
    "MOS Microsoft Office Specialist",
    "ICDL", "PCIE",
    "TOEIC", "Cambridge English", "Cambridge Assessment",
    "ETS Global", "ETS Europe",
    "Bright Language", "Pipplet",
]

# ─────────────────────────────────────────────────────────────────────────────
# Patterns de nomination — combinés à un poste senior pour qualifier
# ─────────────────────────────────────────────────────────────────────────────
NOMINATION_VERB_PATTERNS = [
    re.compile(r"\bnomm[ée]e?\b", re.I),
    re.compile(r"\bnomination\s+(?:de|d['])\s+", re.I),
    re.compile(r"\brejoint\b", re.I),
    re.compile(r"\bintègre\b", re.I),
    re.compile(r"\bprend la (?:direction|tête)\b", re.I),
    re.compile(r"\bdevient (?:le |la |directeur|directrice|head|chief|président)", re.I),
    re.compile(r"\best nommé", re.I),
    re.compile(r"\barrive (?:à la|chez|au poste)", re.I),
]

# Postes seniors RH/digital pertinents pour ITS
POSTES_PERTINENTS = [
    "DRH", "Directeur des Ressources Humaines", "Directrice des Ressources Humaines",
    "CHRO", "Chief Human Resources Officer", "Chief People Officer", "CPO",
    "Head of Talent Acquisition", "Head of TA", "Talent Acquisition Director",
    "Head of L&D", "Head of Learning", "Directeur Formation", "Directrice Formation",
    "Head of People", "People Director",
    "CDO", "Chief Digital Officer", "Chief Data Officer",
    "Head of Digital", "Directeur Digital",
    "Head of HR Tech", "HR Tech Director", "HRIS Director",
    "Directeur Recrutement", "Directrice Recrutement",
    "VP People", "VP HR", "VP Talent",
]

# Patterns exclusion : tribunes, revues, podcasts (déjà couvert par is_editorial_noise
# mais certains slipent à travers — on ajoute des patterns spécifiques RH)
EXCLUSION_PATTERNS_RH = [
    re.compile(r"^\d+\s+bonnes?\s+pratiques?", re.I),
    re.compile(r"^Revue du web", re.I),
    re.compile(r"En voiture les RH", re.I),
    re.compile(r"^Livres? blancs?", re.I),
    re.compile(r"^infographie", re.I),
    re.compile(r"^podcast\s", re.I),
    re.compile(r"^webinaire", re.I),
    re.compile(r"être conforme", re.I),
    re.compile(r"#24heuresRH", re.I),  # event recap
]


def _detect_concurrent(title: str) -> str | None:
    """Si le titre mentionne un concurrent, retourne son nom. Sinon None."""
    for c in CONCURRENTS:
        if c.lower().strip() in title.lower():
            return c.strip()
    return None


def _detect_nomination(title: str) -> bool:
    """Vrai si le titre matche un pattern de nomination + un poste senior pertinent."""
    has_verb = any(pat.search(title) for pat in NOMINATION_VERB_PATTERNS)
    if not has_verb:
        return False
    has_poste = any(p.lower() in title.lower() for p in POSTES_PERTINENTS)
    return has_poste


def _is_excluded_rh(title: str) -> bool:
    """Vrai si le titre matche un pattern à exclure côté RH."""
    return any(pat.search(title) for pat in EXCLUSION_PATTERNS_RH)


def _generate_action_concurrent(concurrent: str, source_url: str, titre: str) -> str:
    """Action commerciale pour un signal de pivot/news concurrent."""
    action = (
        f"📋 **Source** : {source_url}\n"
        f"📰 **Titre** : « {titre} »\n"
        f"🎯 **Action immédiate** : sur LinkedIn Sales Navigator, filtrer les "
        f"profils Head of TA / DRH / Chief People Officer dans des entreprises "
        f">500 salariés qui mentionnent **{concurrent}** dans leur expérience.\n"
        f"💡 **Angle ITS** : « Vous utilisiez {concurrent}. Avec leur récent "
        f"{'pivot' if 'devient' in titre.lower() else 'changement'}, beaucoup "
        f"de RH cherchent une alternative stable. Discussion 20min sur ITS ? »\n"
        f"📅 **Fenêtre** : 60j post-annonce (pic d'incertitude clientèle)\n"
        f"🥊 **Positionnement** : ITS = solution mature, stable, multi-tenant, "
        f"déjà déployée chez {concurrent} comme partenaire ou concurrent."
    )
    return action


def _generate_action_nomination(personne: str, poste: str, entreprise: str, source_url: str) -> str:
    """Action commerciale pour une nomination senior RH."""
    action = (
        f"📋 **Source** : {source_url}\n"
        f"👤 **Personne** : {personne} — {poste} chez {entreprise}\n"
        f"🎯 **Action** : InMail LinkedIn sous 30j (fenêtre de bonne disposition "
        f"post-prise de poste).\n"
        f"💡 **Angle ITS** : « Félicitations pour votre nouveau poste. Beaucoup "
        f"de DRH récemment nommés veulent rapidement industrialiser leur "
        f"processus d'évaluation. ITS permet de standardiser sans gros chantier "
        f"IT. RDV 30min ? »\n"
        f"📅 **Fenêtre** : 30-90j post-nomination (avant qu'ils s'organisent avec l'existant)\n"
        f"🥊 **Bénéfice clé à pitcher** : ITS plug-and-play, ROI mesurable en 6 semaines."
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

            # Filtre éditorial global
            if is_editorial_noise(title):
                continue
            if _is_excluded_rh(title):
                continue

            # Tentative 1 — Concurrent dans le titre
            concurrent = _detect_concurrent(title)
            if concurrent:
                score = 70
                tier = 2
                signal_type = "concurrent_news"
                compte = concurrent
                sous_segment = f"Signal concurrent — {concurrent}"
                action = _generate_action_concurrent(concurrent, link, title)

                sig = Signal(
                    id=fingerprint(title, concurrent, date_iso),
                    date_capture=today,
                    vertical=VERTICAL,
                    sous_segment=sous_segment,
                    compte=compte,
                    titre=title[:200],
                    description=description[:400],
                    source=src["name"],
                    source_tier=src["tier"],
                    url=link,
                    signal_type=signal_type,
                    tier=tier,
                    score=score,
                    produit_match=produit_match_for(signal_type, VERTICAL),
                    owner="Charles",
                    action_reco=action,
                    deadline_action=None,
                    status="new",
                    date_publication=date_iso,
                )
                signals.append(sig)
                logger.info(
                    "[Corp/%s] [concurrent_news/%d] %s — %s",
                    src["name"], score, concurrent, title[:60],
                )
                continue  # un seul signal par item

            # Tentative 2 — Nomination senior RH
            if _detect_nomination(title):
                # Extraction approximative personne/poste/entreprise
                compte_brut = extract_compte(title)
                if not compte_brut or compte_brut == "Inconnu":
                    logger.info("[Corp/%s] NOMINATION détectée mais compte inconnu : %s", src["name"], title[:70])
                    continue

                # On essaie d'identifier le poste
                poste_match = next((p for p in POSTES_PERTINENTS if p.lower() in title.lower()), "poste senior RH")

                score = 80
                tier = 1
                signal_type = "nomination_chro"
                sous_segment = f"Nomination — {poste_match}"
                action = _generate_action_nomination(
                    personne="(voir source pour le nom complet)",
                    poste=poste_match,
                    entreprise=compte_brut,
                    source_url=link,
                )

                sig = Signal(
                    id=fingerprint(title, compte_brut, date_iso),
                    date_capture=today,
                    vertical=VERTICAL,
                    sous_segment=sous_segment,
                    compte=compte_brut,
                    titre=title[:200],
                    description=description[:400],
                    source=src["name"],
                    source_tier=src["tier"],
                    url=link,
                    signal_type=signal_type,
                    tier=tier,
                    score=score,
                    produit_match=produit_match_for(signal_type, VERTICAL),
                    owner="Charles",
                    action_reco=action,
                    deadline_action=None,
                    status="new",
                    date_publication=date_iso,
                )
                signals.append(sig)
                logger.info(
                    "[Corp/%s] [nomination_chro/%d] %s — %s",
                    src["name"], score, compte_brut, title[:60],
                )

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux Corporate (Sprint A2) captés ===", len(sigs))
    for s in sigs:
        logger.info("  [%d/T%d] [%s] %s — %s", s.score, s.tier, s.signal_type, s.compte, s.titre[:80])


if __name__ == "__main__":
    main()
