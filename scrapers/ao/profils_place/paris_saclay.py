"""
Scraper PLACE — profil acheteur Université Paris-Saclay (orgAcronyme = f2h).

Profil pilote Sprint 1 du comité Sourcing AO 360°.
Cas perdu déclencheur : AO 2026-A009 « Outil de positionnement CAP PAC 2030 »
publié sur ce profil et raté par notre Radar AO actuel.

Cadence : appel quotidien via le runner. Skip propre si APIFY_TOKEN absent.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.place_helpers import scrape_place_profil  # noqa: E402
from scrapers.lib.outreach import email_draft_ao, get_contacts_cibles  # noqa: E402

from scrapers.ao.seed_from_radar import (  # noqa: E402
    _passes_metier_filter,
    _detect_segment_from_acheteur,
    _map_sous_segment,
    _generate_ao_action,
)

logger = logging.getLogger(__name__)

VERTICAL = "ao"
ORG_ACRONYME = "f2h"
NOM_PROFIL = "Université Paris-Saclay"


def scrape() -> list[Signal]:
    today_iso = datetime.utcnow().date().isoformat()
    notices = scrape_place_profil(ORG_ACRONYME, NOM_PROFIL)
    if not notices:
        return []

    signals = []
    for n in notices:
        passes, reason = _passes_metier_filter(n)
        if not passes:
            logger.info("[PLACE %s] FILTRÉ (%s) : %s — %s",
                        NOM_PROFIL[:20], reason, n["acheteur"][:35], n["objet"][:60])
            continue

        score = int(n.get("score", 80))
        tier = determine_tier(score)
        signal_type = "ao_publie"
        sous_segment = _map_sous_segment(n)

        segment_brut = n.get("segment") or "Autre"
        if segment_brut in ("", "Autre"):
            detected = _detect_segment_from_acheteur(n["acheteur"])
            if detected:
                segment_brut = detected

        action = _generate_ao_action(n, signal_type, segment_brut)
        email_dr = email_draft_ao(n["acheteur"], n["objet"],
                                   n.get("deadline") or "à définir",
                                   n["url"])
        contacts = get_contacts_cibles(signal_type, n["acheteur"])

        sig = Signal(
            id=fingerprint(n["objet"], n["acheteur"], n.get("publication") or today_iso),
            date_capture=today_iso,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=n["acheteur"],
            titre=n["objet"][:200],
            description=n["description"][:400] if n["description"] else n["objet"][:400],
            source=n["source"],
            source_tier=1,  # Profil acheteur direct = Tier 1
            url=n["url"],
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner="Charles",
            action_reco=action,
            deadline_action=n.get("deadline"),
            status="new",
            date_publication=n.get("publication"),
            email_draft=email_dr,
            contacts_cibles=contacts,
        )
        signals.append(sig)
        logger.info("[PLACE %s] [%d/T%d] %s — %s",
                    NOM_PROFIL[:20], score, tier, n["acheteur"][:35], n["objet"][:60])
    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux PLACE %s captés ===", len(sigs), NOM_PROFIL)


if __name__ == "__main__":
    main()
