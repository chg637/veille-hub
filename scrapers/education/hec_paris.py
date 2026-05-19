"""
Scraper HEC Paris — page News Room.

Source institutionnelle Tier 1 — actualités HEC Paris (école, instituts, recherche, programmes).
Capture : nouveaux programmes, partenariats, nominations, accréditations, événements.
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

PAGE_URL = "https://www.hec.edu/fr/news-room"
BASE_URL = "https://www.hec.edu"
SOURCE_NAME = "HEC Paris"
SOURCE_TIER = 1
VERTICAL = "education"

USER_AGENT = "Mozilla/5.0 (compatible; IsogradVeilleBot/1.0; +contact@isograd.com)"

# Mots-clés de classification
KEYWORDS_ACCREDITATION = ["aacsb", "equis", "amba", "accréditation", "labellis"]
KEYWORDS_NOMINATION = ["nomme", "nomination", "nouveau directeur", "nouvelle directrice", "nouveau doyen", "rejoint"]
KEYWORDS_NOUVELLE_FORMATION = [
    "lance", "inaugure", "ouvre", "nouveau programme", "nouvelle formation",
    "nouveau master", "msc", "mba", "bachelor",
]
KEYWORDS_PARTENARIAT = ["partenariat", "convention", "alliance"]
KEYWORDS_IA = ["intelligence artificielle", "ia ", "llm", " ai ", "machine learning"]


def _classify(title: str, description: str) -> tuple[str, str]:
    text = f"{title} {description}".lower()

    if matches_any(text, KEYWORDS_ACCREDITATION):
        return ("accreditation", "grande-ecole")
    if matches_any(text, KEYWORDS_NOMINATION):
        return ("nomination_dg", "grande-ecole")
    if matches_any(text, KEYWORDS_NOUVELLE_FORMATION):
        return ("nouvelle_formation", "grande-ecole")
    if matches_any(text, KEYWORDS_IA):
        return ("autre", "grande-ecole / IA")
    return ("autre", "grande-ecole")


def scrape(limit: int = 30) -> list[Signal]:
    logger.info("Fetching HEC Paris news room: %s", PAGE_URL)
    r = requests.get(PAGE_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Trouver les cartes d'article principales (class="article-item" sans sous-class)
    cards = soup.find_all("div", class_=lambda c: c and "article-item" in c.split() and len(c.split()) <= 2)
    logger.info("Found %d article cards", len(cards))

    today = datetime.utcnow().date().isoformat()
    signals = []
    seen_urls = set()

    for card in cards[:limit]:
        # Le lien principal de l'article
        a = card.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Titre = texte du a ou du h2/h3 enfant
        title_el = card.find(["h2", "h3", "h4"])
        title = (title_el.get_text(strip=True) if title_el else a.get_text(strip=True))[:200]
        if not title or len(title) < 8:
            continue

        # Description = texte du article-item__description si présent
        desc_el = card.find(class_=re.compile(r"description|teaser|chapo"))
        description = desc_el.get_text(strip=True)[:400] if desc_el else ""

        # Date — chercher un élément avec class contenant "date" ou un <time>
        date_el = card.find(class_=re.compile(r"date")) or card.find("time")
        date_iso = today  # fallback
        if date_el:
            date_text = date_el.get_text(strip=True)
            # Tentative parsing simple
            m = re.search(r"(\d{1,2})[/\.-](\d{1,2})[/\.-](\d{2,4})", date_text)
            if m:
                try:
                    d, m_, y = m.groups()
                    y = int(y) if int(y) > 100 else 2000 + int(y)
                    date_iso = f"{y:04d}-{int(m_):02d}-{int(d):02d}"
                except Exception:
                    pass

        signal_type, sous_segment = _classify(title, description)
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)
        action_info = generate_action(signal_type, VERTICAL, compte="HEC Paris")

        sig = Signal(
            id=fingerprint(title, "HEC Paris", date_iso),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte="HEC Paris",
            titre=title,
            description=description,
            source=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            url=url,
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner=None,
            action_reco=action_info["action"],
            deadline_action=action_info["deadline_action"],
            status="new",
            date_publication=date_iso if date_iso != today else None,
        )
        signals.append(sig)
        logger.info("[%s] [%s/%s] [pub=%s] %s", SOURCE_NAME, VERTICAL, signal_type, date_iso, title[:70])

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
