"""
Scraper Conférence des Grandes Écoles (CGE).

Source institutionnelle Tier 1 — actualités du réseau Grandes Écoles françaises.
Capture : accréditations, fusions, nouveaux programmes, nominations DG.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_any, extract_compte, is_editorial_noise  # noqa: E402
from scrapers.lib.outreach import email_draft_for_education, get_contacts_cibles, format_action_education  # noqa: E402

logger = logging.getLogger(__name__)

RSS_URL = "https://www.cge.asso.fr/feed/"
SOURCE_NAME = "CGE"
SOURCE_TIER = 1
VERTICAL = "education"

# Mots-clés pour classifier le type de signal
KEYWORDS_ACCREDITATION = ["aacsb", "equis", "amba", "accréditation", "accreditation", "labellis"]
KEYWORDS_NOMINATION = ["nomme", "nomination", "nouveau directeur", "nouvelle directrice", "nouveau doyen"]
KEYWORDS_NOUVELLE_FORMATION = [
    "lance", "inaugure", "ouvre", "nouveau programme", "nouvelle formation",
    "nouveau master", "msc", "ms ", "mba", "bachelor",
]
KEYWORDS_FUSION = ["fusion", "rapprochement", "regroupe", "alliance"]
KEYWORDS_PARTENARIAT = ["partenariat", "convention", "alliance", "rejoint"]

# Stop-words spécifiques à CGE (mots qui apparaissent souvent en début de titre sans être des noms d'école)
EXTRA_STOPS = {"Décisions", "Décision", "Programme", "Webinaire", "Communiqué"}


def _classify(title: str, description: str) -> tuple[str, str]:
    """
    Retourne (signal_type, sous_segment).
    """
    if is_editorial_noise(title):
        return ("autre", "Bruit éditorial")
    text = f"{title} {description}".lower()

    if matches_any(text, KEYWORDS_ACCREDITATION):
        return ("accreditation", "grande-ecole")
    if matches_any(text, KEYWORDS_NOMINATION):
        return ("nomination_dg", "grande-ecole")
    if matches_any(text, KEYWORDS_NOUVELLE_FORMATION):
        return ("nouvelle_formation", "grande-ecole")
    if matches_any(text, KEYWORDS_FUSION):
        return ("fusion_ecole", "grande-ecole")
    return ("autre", "grande-ecole")


def scrape(limit: int = 30) -> list[Signal]:
    items = fetch_rss(RSS_URL, limit=limit)
    today = datetime.utcnow().date().isoformat()
    signals = []

    for item in items:
        if not is_recent(item["date_iso"], max_age_days=30):  # CGE moins de volume → fenêtre plus large
            continue
        title = item["title"]
        description = item["description"]
        signal_type, sous_segment = _classify(title, description)
        compte = extract_compte(title, custom_stops=EXTRA_STOPS)
        score = base_score(signal_type, source_tier=SOURCE_TIER)
        tier = determine_tier(score)
        action_info = generate_action(signal_type, VERTICAL, compte=compte)

        # Enrichissement outreach : mail drafté + contacts cibles typologiques
        email_dr = email_draft_for_education(
            signal_type=signal_type,
            compte=compte,
            signal_text=description,
            url_source=item["link"],
        )
        contacts = get_contacts_cibles(signal_type, compte)

        # Action commerciale structurée Education
        structured_action = format_action_education(
            signal_type=signal_type,
            signal_text=description,
            action_custom=action_info["action"],
        )

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
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner=None,
            action_reco=structured_action,
            deadline_action=action_info["deadline_action"],
            status="new",
            date_publication=item["date_iso"],
            email_draft=email_dr,
            contacts_cibles=contacts,
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
