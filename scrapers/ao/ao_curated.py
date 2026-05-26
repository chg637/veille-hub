"""
Scraper AO curated — source manuelle pour les AO identifiés hors radar auto.

Quand Charles repère un AO pertinent via centraledesmarches.com, Sales Nav,
LinkedIn, un collègue, ou tout autre canal manuel, il peut l'ajouter à
`data/curated/ao_curated.csv`. Le scraper le transforme en signal hub avec
toute la mécanique standard (mail drafté, contacts cibles, action 4 blocs).

Format CSV (séparateur virgule, quotes guillemets pour valeurs avec virgules) :
    Acheteur, Reference, Titre, Description, CPV, Deadline (YYYY-MM-DD),
    Date_Publication (YYYY-MM-DD), URL_DCE, Segment, Type_Marche, Notes

Cadence : Charles édite le CSV → commit → prochain cron daily 6h UTC l'intègre.
"""

from __future__ import annotations

import csv
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.outreach import email_draft_ao, get_contacts_cibles  # noqa: E402

# Réutilise helpers du scraper TED/BOAMP
from scrapers.ao.seed_from_radar import (  # noqa: E402
    _detect_segment_from_acheteur,
    _map_sous_segment,
    _generate_ao_action,
)

logger = logging.getLogger(__name__)

VERTICAL = "ao"
SOURCE_NAME = "Curated manuel"
SOURCE_TIER = 1  # Curated = Tier 1 confiance maximale (Charles a déjà qualifié)


def _build_signal(row: dict, today_iso: str) -> Optional[Signal]:
    acheteur = (row.get("Acheteur") or "").strip()
    ref = (row.get("Reference") or "").strip()
    titre = (row.get("Titre") or "").strip()
    description = (row.get("Description") or "").strip()
    cpv = (row.get("CPV") or "").strip()
    deadline = (row.get("Deadline") or "").strip() or None
    publication = (row.get("Date_Publication") or "").strip() or today_iso
    url = (row.get("URL_DCE") or "").strip()
    segment = (row.get("Segment") or "").strip() or "Autre"
    type_marche = (row.get("Type_Marche") or "").strip()
    notes = (row.get("Notes") or "").strip()

    if not acheteur or not titre:
        return None

    # Détection segment (fallback auto si vide)
    if segment in ("", "Autre"):
        detected = _detect_segment_from_acheteur(acheteur)
        if detected:
            segment = detected

    # Notice simulée pour réutiliser les helpers de seed_from_radar
    notice = {
        "id": f"curated-{ref or fingerprint(titre, acheteur, publication)[:8]}",
        "ref": ref,
        "acheteur": acheteur,
        "objet": titre,
        "description": description,
        "cpv": cpv,
        "pays": "FR",
        "deadline": deadline,
        "publication": publication,
        "source": SOURCE_NAME,
        "url": url,
        "score": 85,  # curated = score élevé par défaut (Charles a déjà qualifié)
        "segment": segment,
    }

    signal_type = "ao_publie"
    sous_segment = _map_sous_segment(notice)

    # Action commerciale enrichie + mention "curated"
    enriched_action = _generate_ao_action(notice, signal_type, segment)
    if notes:
        enriched_action += f"\n\n📝 **Notes Charles** : {notes}"

    score = 85
    tier = 1  # tous les curated sont T1 par construction

    sig = Signal(
        id=fingerprint(titre, acheteur, publication),
        date_capture=today_iso,
        vertical=VERTICAL,
        sous_segment=sous_segment,
        compte=acheteur,
        titre=titre[:200],
        description=description[:400],
        source=f"{SOURCE_NAME}{' (' + type_marche + ')' if type_marche else ''}",
        source_tier=SOURCE_TIER,
        url=url or "https://www.marches-publics.gouv.fr",
        signal_type=signal_type,
        tier=tier,
        score=score,
        produit_match=produit_match_for(signal_type, VERTICAL),
        owner="Charles",
        action_reco=enriched_action,
        deadline_action=deadline,
        status="new",
        date_publication=publication,
        email_draft=email_draft_ao(acheteur, titre, deadline or "à définir", url or ""),
        contacts_cibles=get_contacts_cibles(signal_type, acheteur),
    )
    return sig


def scrape() -> list[Signal]:
    repo_root = Path(__file__).resolve().parents[2]
    csv_path = repo_root / "data" / "curated" / "ao_curated.csv"
    today_iso = datetime.utcnow().date().isoformat()

    if not csv_path.exists():
        logger.info("[AO curated] CSV introuvable %s — skip", csv_path)
        return []

    signals = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                sig = _build_signal(row, today_iso)
                if sig:
                    signals.append(sig)
                    logger.info(
                        "[AO curated] [%s] %s — %s",
                        sig.compte[:30], sig.titre[:60], sig.deadline_action or "(pas de deadline)",
                    )
            except Exception as e:
                logger.warning("[AO curated] parse error sur ligne %s: %s", row.get("Reference", "?"), e)

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux AO curated captés ===", len(sigs))
    for s in sigs:
        logger.info("  [%d/T%d] %s — %s", s.score, s.tier, s.compte, s.titre[:60])


if __name__ == "__main__":
    main()
