"""
Scraper BOAMP direct — API officielle DILA (gratuite, ouverte).

Pourquoi ce scraper : le Radar AO (Node.js) filtrait BOAMP trop strictement en
amont (exige un mot-clé long type "plateforme d'évaluation"), et jetait des AO
ITS-pertinents AVANT que notre filtre v5.2 puisse les voir. Cas concret : l'AO
Neoma 2026-TIC-NBS-0008 "solution logicielle d'évaluation collaborative" était
sur BOAMP mais n'a jamais atteint le hub.

Principe corrigé : capter LARGE en amont (recherche full-text sur termes ITS) +
filtrer FIN en aval (notre filtre v5.2). On ne dépend plus du Radar AO pour BOAMP.

API : https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.outreach import email_draft_ao, get_contacts_cibles  # noqa: E402

from scrapers.ao.seed_from_radar import (  # noqa: E402
    _passes_metier_filter,
    _detect_segment_from_acheteur,
    _map_sous_segment,
    _generate_ao_action,
)
from scrapers.ao.ao_curated import curated_keys, is_curated  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "ao"
SOURCE_NAME = "BOAMP (API directe)"
API_URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
WINDOW_DAYS = 30

# Termes de recherche full-text ITS — larges mais ciblés.
# Le filtre v5.2 (negative phrases + scoring) fait le tri fin en aval.
SEARCH_TERMS = [
    "évaluation des compétences",
    "évaluation collaborative",
    "certification des compétences",
    "positionnement",
    "outil de positionnement",
    "plateforme d'examen",
    "plateforme d'évaluation",
    "examen en ligne",
    "examens à distance",
    "logiciel pédagogique",
    "logiciel d'évaluation",
    "proctoring",
    "QCM",
    "psychométrie",
    "test de positionnement",
    "banque de questions",
]

# Codes CPV cibles connus, recherchés dans le JSON donnees (best effort)
CPV_PATTERN = re.compile(r"\b(4819\d{4}|7221219\d|79132\d{3}|72416\d{3}|73111\d{3})\b")


def _extract_cpv(rec: dict) -> str:
    """Best effort : extrait un code CPV cible du champ donnees (JSON imbriqué)."""
    donnees = rec.get("donnees")
    if not donnees:
        return ""
    blob = donnees if isinstance(donnees, str) else json.dumps(donnees, ensure_ascii=False)
    m = CPV_PATTERN.search(blob)
    return m.group(1) if m else ""


def _fetch_term(term: str, since: str) -> list[dict]:
    """Une requête API BOAMP pour un terme, fenêtre 30j."""
    params = {
        "where": f'search("{term}") and dateparution >= "{since}"',
        "limit": 50,
        "order_by": "dateparution desc",
    }
    try:
        r = requests.get(API_URL, params=params, timeout=20)
        if r.status_code != 200:
            logger.warning("[BOAMP] '%s' HTTP %s", term, r.status_code)
            return []
        return r.json().get("results", [])
    except Exception as e:
        logger.warning("[BOAMP] '%s' failed: %s", term, e)
        return []


def scrape() -> list[Signal]:
    today_iso = datetime.utcnow().date().isoformat()
    since = (date.today() - timedelta(days=WINDOW_DAYS)).isoformat()

    # 1. Collecte multi-termes, dédup par idweb
    by_idweb: dict[str, dict] = {}
    for term in SEARCH_TERMS:
        recs = _fetch_term(term, since)
        for rec in recs:
            idw = rec.get("idweb")
            if idw and idw not in by_idweb:
                by_idweb[idw] = rec
    logger.info("[BOAMP direct] %d AO uniques captés sur %d termes (fenêtre %dj)",
                len(by_idweb), len(SEARCH_TERMS), WINDOW_DAYS)

    # 2. Mapper + filtrer v5.2
    ck = curated_keys()  # AO déjà gérés en curated (priorité aux notes Charles)
    signals = []
    for idw, rec in by_idweb.items():
        objet = (rec.get("objet") or "").strip()
        acheteur = (rec.get("nomacheteur") or "").strip()
        if not objet or not acheteur:
            continue

        # Dédup : si déjà en curated, on skip (le curated porte les notes enrichies)
        if is_curated(acheteur, objet, ck):
            logger.info("[BOAMP direct] DÉJÀ EN CURATED, skip : %s — %s", acheteur[:30], objet[:50])
            continue

        cpv = _extract_cpv(rec)
        deadline = rec.get("datelimitereponse") or rec.get("datefindiffusion") or ""
        deadline = deadline[:10] if deadline else None  # YYYY-MM-DD
        publication = (rec.get("dateparution") or today_iso)[:10]
        url = rec.get("url_avis") or f"https://www.boamp.fr/pages/avis/?q=idweb:{idw}"
        descripteurs = ", ".join(rec.get("descripteur_libelle") or [])

        notice = {
            "id": f"boamp-{idw}",
            "ref": idw,
            "acheteur": acheteur,
            "objet": objet,
            "description": f"{objet}. Descripteurs : {descripteurs}." if descripteurs else objet,
            "cpv": cpv,
            "pays": "FR",
            "deadline": deadline,
            "publication": publication,
            "source": SOURCE_NAME,
            "url": url,
            "score": 80,
            "segment": "",
        }

        passes, reason = _passes_metier_filter(notice)
        if not passes:
            logger.info("[BOAMP direct] FILTRÉ (%s) : %s — %s", reason, acheteur[:30], objet[:55])
            continue

        segment = _detect_segment_from_acheteur(acheteur) or "Autre"
        notice["segment"] = segment
        signal_type = "ao_publie"
        sous_segment = _map_sous_segment(notice)
        score = 80
        tier = determine_tier(score)

        action = _generate_ao_action(notice, signal_type, segment)
        email_dr = email_draft_ao(acheteur, objet, deadline or "à définir", url)
        contacts = get_contacts_cibles(signal_type, acheteur)

        sig = Signal(
            id=fingerprint(objet, acheteur, publication),
            date_capture=today_iso,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=acheteur,
            titre=objet[:200],
            description=notice["description"][:400],
            source=SOURCE_NAME,
            source_tier=1,
            url=url,
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner="Charles",
            action_reco=action,
            deadline_action=deadline,
            status="new",
            date_publication=publication,
            email_draft=email_dr,
            contacts_cibles=contacts,
        )
        signals.append(sig)
        logger.info("[BOAMP direct] [%d/T%d] %s — %s (%s)", score, tier, acheteur[:30], objet[:50], reason)

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux BOAMP direct captés ===", len(sigs))


if __name__ == "__main__":
    main()
