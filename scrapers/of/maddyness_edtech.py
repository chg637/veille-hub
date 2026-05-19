"""
Scraper Maddyness — tag EdTech.

Flux dédié EdTech / formation. Plus ciblé que le flux principal pour le vertical OF.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_any, matches_regex, extract_compte  # noqa: E402

logger = logging.getLogger(__name__)

RSS_URL = "https://www.maddyness.com/tag/edtech/feed/"
SOURCE_NAME = "Maddyness EdTech"
SOURCE_TIER = 2
VERTICAL = "of"

LEVEE_PATTERNS = [
    r"\b\d+\s*(?:m€|millions?\s*d['']euros?|m\$|million\s*\$)",
    r"\bsér[ie]e?\s*[abc]\b",
    r"\blève\s+\d",
    r"\bbouclé?\s+un[e]?\s+lev",
]
RNCP_KEYWORDS = ["rncp", "rs ", "qualiopi", "certification"]
PARTENARIAT_KEYWORDS = ["partenariat", "rejoint", "alliance"]


def _classify(title: str, description: str) -> tuple[str, str]:
    text = f"{title} {description}".lower()
    if matches_regex(text, LEVEE_PATTERNS):
        return ("levee_edtech", "EdTech / startup formation")
    if matches_any(text, RNCP_KEYWORDS):
        return ("rncp_open", "EdTech / certif")
    if matches_any(text, PARTENARIAT_KEYWORDS):
        return ("autre", "EdTech / partenariat")
    return ("autre", "EdTech / formation")


def scrape(limit: int = 30) -> list[Signal]:
    items = fetch_rss(RSS_URL, limit=limit)
    today = datetime.utcnow().date().isoformat()
    signals = []

    for item in items:
        if not is_recent(item["date_iso"]):
            continue
        title = item["title"]
        description = item["description"]
        signal_type, sous_segment = _classify(title, description)
        compte = extract_compte(title)
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)

        sig = Signal(
            id=fingerprint(title, compte, item["date_iso"]),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=compte,
            titre=title[:200],
            description=description,
            source=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            url=item["link"],
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=[],
            owner=None,
            action_reco=None,
            deadline_action=None,
            status="new",
            date_publication=item["date_iso"],
        )
        signals.append(sig)
        logger.info("[%s] [%s/%s] [pub=%s] %s", SOURCE_NAME, VERTICAL, signal_type, item["date_iso"], title[:70])

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
