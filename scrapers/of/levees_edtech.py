"""
Scraper OF Phase 1 — Levées EdTech (Maddyness + Sifted).

Re-utilise les RSS des sources Corporate, mais détecte les startups EdTech /
learning / training. Quand match EdTech → signal vers vertical "of" avec
signal_type "levee_edtech" + email white-label ITS + contacts CPO/Head of Content.

Ne double pas avec levees_rss.py : un signal détecté ici n'apparaît pas
côté Corporate (car son signal_type = levee_edtech, géré ailleurs).
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
from scrapers.lib.rss_helpers import fetch_rss, is_editorial_noise  # noqa: E402
from scrapers.lib.outreach import (  # noqa: E402
    email_draft_levee_edtech,
    get_contacts_cibles,
)
from scrapers.lib.edtech_filter import is_edtech  # noqa: E402

# Réutilise les helpers existants côté Corporate (extraction montant + compte EN/FR)
from scrapers.corporate.levees_rss import (  # noqa: E402
    SOURCES,
    _extract_montant_meur,
    _extract_compte_levee,
    _is_levee,
    _is_excluded,
)

logger = logging.getLogger(__name__)

VERTICAL = "of"

# Note : EDTECH_KEYWORDS, EDTECH_KNOWN_COMPANIES et is_edtech() sont définis
# dans scrapers.lib.edtech_filter pour être partagés avec levees_rss.py
# (qui skip les EdTech afin d'éviter le doublon Corporate + OF).


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    signals = []

    for src in SOURCES:
        try:
            items = fetch_rss(src["url"], limit=30)
        except Exception as e:
            logger.warning("[OF/%s] fetch failed: %s", src["name"], e)
            continue
        logger.info("[OF/%s] %d items fetched", src["name"], len(items))

        for item in items:
            title = item["title"]
            description = item["description"]
            link = item["link"]
            date_iso = item["date_iso"]

            # 1. Filtres éditoriaux globaux (héritage Corporate)
            if is_editorial_noise(title):
                continue
            excl = _is_excluded(title, description)
            if excl:
                continue

            # 2. Est-ce une levée ?
            if not _is_levee(title, description):
                continue

            # 3. Montant ?
            montant = _extract_montant_meur(f"{title} {description}")
            if not montant:
                continue
            meur, montant_raw = montant
            # Seuil OF plus bas : 5M€ (les EdTech early-stage sont déjà de la cible)
            if meur < 5:
                continue

            # 4. Extraction du compte
            compte = _extract_compte_levee(title, src.get("lang", "fr"))
            if compte == "Inconnu" or len(compte) < 2:
                continue

            # 5. EdTech ?
            is_edtech_match, edtech_reason = is_edtech(title, description, compte)
            if not is_edtech_match:
                continue  # pas EdTech → laissé à levees_rss.py (Corporate)

            # 6. Build signal OF
            score = 80 if meur >= 30 else (65 if meur >= 15 else 50)
            tier = 1 if meur >= 30 else (2 if meur >= 15 else 3)
            signal_type = "levee_edtech"

            email_dr = email_draft_levee_edtech(compte, montant_raw, meur, link, signal_text=title)
            contacts = get_contacts_cibles(signal_type, compte)

            # Action commerciale OF — format propre 4 blocs
            action_reco = (
                f"📋 **Signal détecté**\n"
                f"{title}\n"
                f"\n"
                f"🎯 **Action à mener**\n"
                f"LinkedIn DM au CPO/CTO ou Head of Content + proposition "
                f"démo ITS white-label sous 30j.\n"
                f"\n"
                f"💡 **Angle pitch ITS**\n"
                f"Plateforme back-end de certification white-label — vous "
                f"délivrez vos certifs sous votre marque, on s'occupe de la "
                f"passation, du proctoring et de la traçabilité Qualiopi/RNCP.\n"
                f"\n"
                f"📅 **Timing**\n"
                f"30-60 jours post-levée — phase de roadmap produit + "
                f"recrutement, ouverte aux partenariats stratégiques.\n"
                f"\n"
                f"🔎 **Pourquoi EdTech (détecté) :** {edtech_reason}"
            )

            sig = Signal(
                id=fingerprint(title, compte, date_iso),
                date_capture=today,
                vertical=VERTICAL,
                sous_segment=f"EdTech / Learning platform ({src['name']})",
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
                action_reco=action_reco,
                deadline_action=None,
                status="new",
                date_publication=date_iso,
                email_draft=email_dr,
                contacts_cibles=contacts,
            )
            signals.append(sig)
            logger.info(
                "[OF/%s] [levee_edtech/%d] %s — %s (%.0fM€) [%s]",
                src["name"], score, compte, title[:50], meur, edtech_reason,
            )

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux OF (EdTech) captés ===", len(sigs))
    for s in sigs:
        logger.info("  [%d/T%d] %s — %s", s.score, s.tier, s.compte, s.titre[:80])


if __name__ == "__main__":
    main()
