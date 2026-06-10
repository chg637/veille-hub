"""
Maintenance de data/triage.json — statuts Traité / Ignoré posés depuis le hub.

Le fichier est écrit par le front (API GitHub contents) et préservé par run_all
(jamais reset). Ici on fait deux choses à chaque run :
1. last_seen = aujourd'hui pour chaque entrée dont le signal existe encore ;
2. purge des entrées dont le signal a disparu depuis plus de GRACE_DAYS jours
   (évite que le fichier gonfle à vie, tout en survivant à un scraper en panne).

Schéma d'une entrée : {"status": "traite"|"ignore"|"actif", "at": iso, "last_seen": date}
"actif" = tombstone posé par le bouton Rétablir (sans lui, un simple delete côté
front serait ressuscité au merge avec la copie distante).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

GRACE_DAYS = 14
VERTICALS = ("education", "of", "rncp", "corporate", "ao")


def update_triage(repo_root: Path) -> None:
    path = repo_root / "data" / "triage.json"
    try:
        triage = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        logger.warning("triage.json illisible — repart de zéro")
        triage = {}
    if not isinstance(triage, dict):
        triage = {}

    current_ids: set[str] = set()
    for v in VERTICALS:
        p = repo_root / "data" / v / "signals.json"
        try:
            sigs = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(sigs, list):
            current_ids.update(s.get("id", "") for s in sigs if isinstance(s, dict))

    today = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=GRACE_DAYS)).isoformat()
    out: dict = {}
    pruned = 0
    for sid, entry in triage.items():
        if not isinstance(entry, dict) or not sid:
            continue
        if sid in current_ids:
            entry["last_seen"] = today
            out[sid] = entry
        else:
            # Signal absent du run : on démarre/consulte la période de grâce
            last = entry.setdefault("last_seen", today)
            if last >= cutoff:
                out[sid] = entry
            else:
                pruned += 1

    path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    logger.info("Triage : %d entrée(s) conservée(s), %d purgée(s)", len(out), pruned)
