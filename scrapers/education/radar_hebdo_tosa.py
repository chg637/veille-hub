"""
Scraper Radar Hebdo Tosa — source curated manuelle hebdomadaire de Charles.

Le Radar Hebdo Tosa est produit chaque mercredi par Charles via un artifact Cowork.
Il contient le signal le plus qualifié du hub : ICP score calibré manuellement,
sources multi-vérifiées, contacts ciblés, action immédiate, badges Cert IA.

Pour intégrer ce contenu au hub, Charles copie l'export CSV embarqué dans
l'artifact (bouton "Copier dans le presse-papier") et le colle dans
`data/curated/radar_hebdo_tosa.csv`. Le scraper lit ce CSV et le transforme
en Signals format hub.

Cadence : Charles met à jour le CSV chaque mercredi matin → commit → le hub
se rafraîchit auto au prochain cron daily.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402

logger = logging.getLogger(__name__)

SOURCE_NAME = "Radar Hebdo Tosa"
SOURCE_TIER = 1
VERTICAL = "education"


# Mapping section CSV → signal_type + sous_segment
SECTION_TO_SIGNAL_TYPE = {
    "Section 1": ("nouvelle_formation", "Prospect froid — supérieur"),
    "Section 2": ("autre", "Campagne lemlist"),
    "Section 3": ("nomination_dg", "Relance compte tiède"),
    "Section 4": ("nouvelle_formation", "Cert IA — partenaire de lancement"),
}


def _section_to_signal_type(section: str, cert_ia: str) -> tuple[str, str]:
    """Retourne (signal_type, sous_segment) selon la section + flag Cert IA."""
    base = SECTION_TO_SIGNAL_TYPE.get(section, ("nouvelle_formation", "Curated"))
    signal_type, sous_segment = base

    # Override pour Cert IA candidate (Beta/Pilote)
    if cert_ia and cert_ia.lower() in ("beta", "pilote"):
        sous_segment = f"Cert IA — {cert_ia.lower()}"

    return signal_type, sous_segment


def _parse_score(s: str) -> int:
    """Convertit le Score_ICP du CSV en int. 'N/A' → 70 (relance par défaut)."""
    s = (s or "").strip()
    if not s or s.upper() == "N/A":
        return 70
    try:
        return int(s)
    except ValueError:
        return 70


def _parse_date(s: str) -> Optional[str]:
    """Parse Date_Signal du CSV en date ISO YYYY-MM-DD. Tolère 'Q1 2026', 'à confirmer', etc."""
    s = (s or "").strip()
    if not s or s.lower() in ("date a verifier", "à confirmer", "n/a"):
        return None
    # Format ISO direct
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    # Format "2026-Q2" / "2026-Q1"
    m = re.match(r"^(\d{4})-Q(\d)$", s)
    if m:
        y, q = m.groups()
        # Convertit en milieu de trimestre
        month = {"1": "02", "2": "05", "3": "08", "4": "11"}.get(q, "01")
        return f"{y}-{month}-01"
    return None


def _format_action(action: str, contact_nom: str, contact_fonction: str) -> str:
    """Enrichit l'action avec le contact ciblé."""
    parts = []
    if contact_nom and contact_nom.upper() != "A ENRICHIR":
        parts.append(f"Contact : {contact_nom} ({contact_fonction})")
    if action:
        parts.append(action)
    return " · ".join(parts)


def _build_signal(row: dict, today_iso: str) -> Optional[Signal]:
    etab = (row.get("Etablissement") or "").strip()
    if not etab:
        return None

    section = (row.get("Section") or "").strip()
    cert_ia = (row.get("Cert_IA_Candidate") or "").strip()
    signal_type, sous_segment = _section_to_signal_type(section, cert_ia)

    score = _parse_score(row.get("Score_ICP", ""))
    tier = determine_tier(score)

    signal_text = (row.get("Signal") or "").strip()
    contact_nom = (row.get("Contact_Nom") or "").strip()
    contact_fonction = (row.get("Contact_Fonction") or "").strip()
    action_brute = (row.get("Action") or "").strip()
    action_reco = _format_action(action_brute, contact_nom, contact_fonction)

    description = signal_text[:400]
    url = (row.get("Source_URL") or "").strip()
    date_pub = _parse_date(row.get("Date_Signal", ""))

    # Produits — base + Cert IA si applicable
    produits = list(produit_match_for(signal_type, VERTICAL))
    if cert_ia and cert_ia.lower() in ("beta", "pilote") and "Cert IA" not in produits:
        produits.append("Cert IA")

    titre = f"{etab} — {signal_text[:120]}" if signal_text else etab

    sig = Signal(
        id=fingerprint(titre + " " + section, etab, date_pub or today_iso),
        date_capture=today_iso,
        vertical=VERTICAL,
        sous_segment=sous_segment,
        compte=etab,
        titre=titre[:200],
        description=description,
        source=f"{SOURCE_NAME} ({section})",
        source_tier=SOURCE_TIER,
        url=url,
        signal_type=signal_type,
        tier=tier,
        score=score,
        produit_match=produits,
        owner="Charles",
        action_reco=action_reco,
        deadline_action=None,
        status="new",
        date_publication=date_pub or today_iso,
    )
    return sig


def scrape() -> list[Signal]:
    """Lit data/curated/radar_hebdo_tosa.csv et retourne les signaux."""
    repo_root = Path(__file__).resolve().parents[2]
    csv_path = repo_root / "data" / "curated" / "radar_hebdo_tosa.csv"

    if not csv_path.exists():
        logger.warning("Radar Hebdo Tosa CSV not found at %s — skipping", csv_path)
        return []

    logger.info("Reading Radar Hebdo Tosa CSV from %s", csv_path)
    today_iso = datetime.utcnow().date().isoformat()
    signals = []

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                sig = _build_signal(row, today_iso)
                if sig:
                    signals.append(sig)
                    logger.info(
                        "[Radar Hebdo] [%s] [%d/T%d] %s",
                        sig.sous_segment,
                        sig.score,
                        sig.tier,
                        sig.compte[:60],
                    )
            except Exception as e:
                logger.warning("Failed to parse row: %s — %s", row.get("Etablissement"), e)

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "data" / VERTICAL / "signals.json"

    new = scrape()
    existing = load_signals(path)
    merged = merge_signals(existing, new)
    save_signals(merged, path)
    logger.info("Saved %d signals total (+%d new from Radar Hebdo Tosa) to %s", len(merged), len(new), path.relative_to(repo_root))


if __name__ == "__main__":
    main()
