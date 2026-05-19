"""
Scraper MyRHline — flux RSS RH.

Source presse RH grand public, intéressante pour détecter :
- Nominations CHRO / DRH (signaux Tier 1)
- Lancements d'outils RH concurrents (Central Test, etc.)
- Tendances marché recrutement (signaux secondaires)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_any, extract_compte, is_editorial_noise  # noqa: E402

logger = logging.getLogger(__name__)

RSS_URL = "https://www.myrhline.com/?feed=rss2"
SOURCE_NAME = "MyRHline"
SOURCE_TIER = 2
VERTICAL = "corporate"

KEYWORDS_NOMINATION = ["nomme", "nomination", "rejoint", "arrive", "devient", "nouveau directeur", "nouvelle directrice"]
KEYWORDS_RECRUT = ["recrut", "embauch", "talent acquisition", "ta ", "sourcing"]
KEYWORDS_IA = ["intelligence artificielle", "ia ", " ai ", "gpt", "llm"]
KEYWORDS_TRANSFO = ["transformation", "digital", "data", "skills"]
KEYWORDS_TEST = ["test", "assessment", "évaluation", "evaluation", "compétence"]


def _classify(title: str, description: str) -> tuple[str, str]:
    # Filtre éditorial en amont
    if is_editorial_noise(title):
        return ("autre", "Bruit éditorial")
    text = f"{title} {description}".lower()
    if matches_any(text, KEYWORDS_NOMINATION):
        return ("nomination_chro", "ETI / nomination RH")
    if matches_any(text, KEYWORDS_RECRUT):
        return ("plan_recrutement", "ETI / recrutement")
    if matches_any(text, KEYWORDS_IA):
        return ("plan_ia", "ETI / IA RH")
    if matches_any(text, KEYWORDS_TRANSFO):
        return ("transformation_digitale", "ETI / transfo")
    return ("autre", "Article RH général")


def scrape(limit: int = 30) -> list[Signal]:
    items = fetch_rss(RSS_URL, limit=limit)
    today = datetime.utcnow().date().isoformat()
    signals = []
    for item in items:
        if not is_recent(item["date_iso"]):
            continue
        signal_type, sous_segment = _classify(item["title"], item["description"])
        # On filtre les "autre" pour ne pas spammer le hub
        if signal_type == "autre":
            continue
        compte = extract_compte(item["title"])
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)
        sig = Signal(
            id=fingerprint(item["title"], compte, item["date_iso"]),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=compte,
            titre=item["title"][:200],
            description=item["description"],
            source=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            url=item["link"],
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner=None,
            action_reco=generate_action(signal_type, VERTICAL, compte=compte)["action"],
            deadline_action=generate_action(signal_type, VERTICAL, compte=compte)["deadline_action"],
            status="new",
            date_publication=item["date_iso"],
        )
        signals.append(sig)
        logger.info("[%s] [%s/%s] [pub=%s] %s", SOURCE_NAME, VERTICAL, signal_type, item["date_iso"], item["title"][:70])
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
