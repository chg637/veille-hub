"""
Scraper HCERES — Haut Conseil de l'évaluation de la recherche et de l'enseignement supérieur.

Source Tier 1 institutionnelle pour le vertical Education. Capture les publications de
rapports d'évaluation (accréditations universités/écoles), nominations de comités, et
changements de gouvernance.

Signaux à fort impact pour Tosa : un rapport d'évaluation HCERES publié = fenêtre de
révision de la maquette pédagogique de l'établissement concerné.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402
from scrapers.lib.rss_helpers import matches_any  # noqa: E402

logger = logging.getLogger(__name__)

PAGE_URL = "https://www.hceres.fr/fr/actualites"
BASE_URL = "https://www.hceres.fr"
SOURCE_NAME = "HCERES"
SOURCE_TIER = 1
VERTICAL = "education"

USER_AGENT = "Mozilla/5.0 (compatible; IsogradVeilleBot/1.0; +contact@isograd.com)"

KW_EVALUATION = ["évaluation", "rapport d'évaluation", "publication du rapport"]
KW_COMITE = ["composition du comité", "comité d'évaluation", "membres du comité"]
KW_ACCREDIT = ["accréditation", "label", "habilitation", "reconnaissance"]
KW_NOMINATION = ["nomination", "nomme", "nouveau président", "nouvelle présidente"]


def _classify(title: str, description: str) -> tuple[str, str]:
    text = f"{title} {description}".lower()
    if matches_any(text, KW_ACCREDIT) or matches_any(text, KW_EVALUATION):
        return ("accreditation", "Université / Établissement supérieur")
    if matches_any(text, KW_COMITE):
        return ("accreditation", "Comité d'évaluation HCERES")
    if matches_any(text, KW_NOMINATION):
        return ("nomination_dg", "Gouvernance enseignement supérieur")
    return ("autre", "Actualité HCERES")


def _extract_compte(title: str) -> str:
    """
    Extrait le nom de l'établissement évalué depuis le titre.
    Pattern fréquent : "Publication du rapport d'évaluation de <Établissement>"
                    ou "Composition du comité d'évaluation de <Établissement>"
    """
    # Pattern "de l'<X>" ou "du <X>" ou "de <X>"
    m = re.search(r"(?:rapport d'évaluation|comité d'évaluation|évaluation)\s+(?:de\s+l['']|de\s+la\s+|du\s+|de\s+)([A-ZÀ-Ÿ][\w\s\-&'']+?)(?:\s*$|\s+est\s|\s+publié|\s+a\s+)", title, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:80]
    # Fallback: cherche un nom propre au milieu du titre
    m = re.search(r"\b(Institut|Université|École|Ecole|Centre|Conservatoire|CNRS|Inserm|Inria|Pasteur)\s+[\w\s\-&'']+", title)
    if m:
        return m.group(0).strip()[:80]
    return "Établissement non identifié"


def scrape(limit: int = 20) -> list[Signal]:
    logger.info("Fetching HCERES: %s", PAGE_URL)
    r = requests.get(PAGE_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Stratégie : chaque actualité est probablement dans un <article> ou un h3 avec lien
    items = []
    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(strip=True)
        if not title or len(title) < 20 or len(title) > 250:
            continue
        # Find associated link
        a = h.find("a") or (h.parent.find("a") if h.parent else None)
        if not a or not a.get("href"):
            continue
        href = a.get("href")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        # Description : chercher un texte suivant le h
        desc = ""
        nxt = h.find_next_sibling()
        if nxt:
            desc = nxt.get_text(strip=True)[:300]
        items.append({"title": title, "url": url, "description": desc})

    # Dédup
    seen = set()
    dedup = []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        dedup.append(it)
    items = dedup[:limit]

    logger.info("Found %d HCERES actualities", len(items))

    today = datetime.utcnow().date().isoformat()
    signals = []
    for it in items:
        signal_type, sous_segment = _classify(it["title"], it["description"])
        compte = _extract_compte(it["title"])
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)
        sig = Signal(
            id=fingerprint(it["title"], compte, today),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=compte,
            titre=it["title"][:200],
            description=it["description"],
            source=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            url=it["url"],
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner=None,
            action_reco=generate_action(signal_type, VERTICAL, compte=compte)["action"],
            deadline_action=generate_action(signal_type, VERTICAL, compte=compte)["deadline_action"],
            status="new",
            date_publication=None,
        )
        signals.append(sig)
        logger.info("[%s] [%s/%s] [%d] %s", SOURCE_NAME, VERTICAL, signal_type, score, it["title"][:70])
    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "data" / VERTICAL / "signals.json"
    new = scrape()
    existing = load_signals(path)
    merged = merge_signals(existing, new)
    save_signals(merged, path)
    logger.info("Saved %d signals total (+%d new) to %s", len(merged), len(new), path.relative_to(repo_root))


if __name__ == "__main__":
    main()
