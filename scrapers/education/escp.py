"""
Scraper ESCP Business School — page news.

Source Tier 1 école de commerce internationale. Capture lancements de programmes,
classements, conférences, accréditations.
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

PAGE_URL = "https://escp.eu/news"
BASE_URL = "https://escp.eu"
SOURCE_NAME = "ESCP"
SOURCE_TIER = 1
VERTICAL = "education"
COMPTE = "ESCP Business School"

USER_AGENT = "Mozilla/5.0 (compatible; IsogradVeilleBot/1.0; +contact@isograd.com)"

KW_ACCREDIT = ["aacsb", "equis", "amba", "accreditation", "accréditation", "ranking", "classement"]
KW_NEW_PROGRAM = ["launches", "lance", "new program", "msc", "mba", "executive", "bachelor"]
KW_NOMINATION = ["appoints", "nomination", "new president", "new dean", "nouveau"]


def _classify(title: str, description: str) -> tuple[str, str]:
    text = f"{title} {description}".lower()
    if matches_any(text, KW_ACCREDIT):
        return ("accreditation", "Grande École internationale")
    if matches_any(text, KW_NEW_PROGRAM):
        return ("nouvelle_formation", "Grande École internationale")
    if matches_any(text, KW_NOMINATION):
        return ("nomination_dg", "Grande École internationale")
    return ("autre", "Grande École internationale")


def scrape(limit: int = 20) -> list[Signal]:
    logger.info("Fetching ESCP: %s", PAGE_URL)
    r = requests.get(PAGE_URL, headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # ESCP : chaque news = un <article> ou h2/h3 avec lien parent
    items = []
    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(strip=True)
        if not title or len(title) < 20 or len(title) > 250:
            continue
        # Trouver le lien : <a> dans le h ou parent
        a = h.find("a") or (h.find_parent("a") if h.find_parent("a") else None)
        if not a:
            # Tenter le parent
            parent = h.parent
            if parent:
                a = parent.find("a", href=True)
        if not a or not a.get("href"):
            continue
        href = a["href"]
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        # Description : voisin
        desc = ""
        nxt = h.find_next_sibling("p") or h.find_next_sibling("div")
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

    logger.info("Found %d ESCP actualities", len(items))

    today = datetime.utcnow().date().isoformat()
    signals = []
    for it in items:
        signal_type, sous_segment = _classify(it["title"], it["description"])
        # On filtre les "autre" pour pas spammer
        if signal_type == "autre":
            continue
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)
        action_info = generate_action(signal_type, VERTICAL, compte=COMPTE)
        sig = Signal(
            id=fingerprint(it["title"], COMPTE, today),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=COMPTE,
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
            action_reco=action_info["action"],
            deadline_action=action_info["deadline_action"],
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
