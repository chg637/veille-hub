"""
Scraper TED — Tenders Electronic Daily (Office des publications de l'UE).

TED publie tous les AO européens dépassant les seuils communautaires
(215 k€ services pour les acheteurs publics français hors travaux). Pour Isograd,
c'est la source qui ramène les GROS tickets ESR / santé publique / État central
qui ne passent pas systématiquement par BOAMP ou PLACE.

API v3 publique (sans clé) : https://api.ted.europa.eu/v3/notices/search
Documentation : https://docs.ted.europa.eu/api/index.html

Stratégie :
- Filtrer par CPV cibles ITS (48190, 79132, 72416, 72212190, 48311, 48160, 73111)
- Limiter à la France (buyer-country=FRA) — élargissable à l'UE plus tard
- Fenêtre 60 jours glissants
- Filtre v5.3 commun en aval

Cadence : appel quotidien via le runner.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for, score_ao# noqa: E402
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
SOURCE_NAME = "TED (Tenders Electronic Daily UE)"
API_URL = "https://api.ted.europa.eu/v3/notices/search"
WINDOW_DAYS = 60

# CPV cibles ITS — même liste que boamp_direct, en codes complets pour TED
CPV_TARGETS = [
    "48190000",   # logiciels pédagogiques
    "79132000",   # services de certification
    "72416000",   # fournisseurs de services applicatifs
    "72212190",   # développement de logiciels pédagogiques
    "48311000",   # logiciels de gestion de documents
    "48160000",   # logiciels bibliothèque (incluant gestion d'examens)
    "73111000",   # services de R&D liés à l'éducation
]

# Champs renvoyés par l'API TED — assez pour caractériser un AO
TED_FIELDS = [
    "notice-identifier",
    "publication-number",
    "publication-date",
    "deadline-date-lot",
    "buyer-name",
    "title-proc",
    "description-proc",
    "classification-cpv",
    "links",
]


def _build_query(since_iso: str) -> str:
    """Construit la query expert TED v3."""
    cpv_or = " OR ".join(f"classification-cpv={c}" for c in CPV_TARGETS)
    return f"({cpv_or}) AND buyer-country=FRA AND publication-date>={since_iso}"


def _fetch_notices(query: str, limit: int = 100) -> list[dict]:
    """Appel POST sur l'API TED v3 — retourne la liste des notices."""
    payload = {
        "query": query,
        "fields": TED_FIELDS,
        "limit": limit,
    }
    try:
        r = requests.post(API_URL, json=payload, timeout=30)
        if r.status_code != 200:
            logger.warning("[TED] HTTP %s : %s", r.status_code, r.text[:200])
            return []
        data = r.json()
        return data.get("notices") or []
    except Exception as e:
        logger.warning("[TED] requête échouée : %s", e)
        return []


def _extract_text(field) -> str:
    """
    Les champs TED multilingues renvoient un dict {langue: valeur}.
    On préfère le français, fallback anglais, sinon première valeur.
    """
    if not field:
        return ""
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        for lang in ("fra", "eng", "fr", "en"):
            v = field.get(lang)
            if v:
                # Certains champs sont des listes par langue
                return v[0] if isinstance(v, list) else v
        # Sinon première valeur trouvée
        for v in field.values():
            if v:
                return v[0] if isinstance(v, list) else v
    if isinstance(field, list):
        return field[0] if field else ""
    return str(field)


def _extract_html_url(links: dict) -> str:
    """Récupère l'URL HTML française du notice (ou anglaise fallback)."""
    if not isinstance(links, dict):
        return ""
    html = links.get("html") or {}
    return html.get("FRA") or html.get("ENG") or ""


def scrape() -> list[Signal]:
    today_iso = datetime.utcnow().date().isoformat()
    since = (date.today() - timedelta(days=WINDOW_DAYS)).strftime("%Y%m%d")

    query = _build_query(since)
    logger.info("[TED] query : %s", query)
    notices = _fetch_notices(query, limit=100)
    logger.info("[TED] %d notices captées (fenêtre %dj)", len(notices), WINDOW_DAYS)

    if not notices:
        return []

    ck = curated_keys()
    signals = []

    for rec in notices:
        notice_id = rec.get("notice-identifier") or ""
        pub_number = rec.get("publication-number") or ""
        publication = (rec.get("publication-date") or today_iso)[:10]
        # deadline-date-lot peut être une LISTE (avis multi-lots) → on prend la
        # plus proche échéance, et on tronque le fuseau ("2026-06-27+02:00" → date)
        raw_deadline = rec.get("deadline-date-lot") or ""
        if isinstance(raw_deadline, list):
            raw_deadline = min((str(x) for x in raw_deadline if x), default="")
        deadline = str(raw_deadline)[:10] or None

        objet = _extract_text(rec.get("title-proc"))
        desc = _extract_text(rec.get("description-proc"))
        acheteur = _extract_text(rec.get("buyer-name"))
        cpv_list = rec.get("classification-cpv") or []
        cpv = cpv_list[0] if cpv_list else ""

        url = _extract_html_url(rec.get("links") or {})
        if not url and pub_number:
            url = f"https://ted.europa.eu/fr/notice/-/detail/{pub_number}"

        if not objet or not acheteur:
            continue

        # Dédup : si déjà en curated, on skip
        if is_curated(acheteur, objet, ck):
            logger.info("[TED] DÉJÀ EN CURATED, skip : %s — %s", acheteur[:30], objet[:50])
            continue

        notice = {
            "id": f"ted-{notice_id[:12]}",
            "ref": pub_number or notice_id,
            "acheteur": acheteur,
            "objet": objet,
            "description": desc or objet,
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
            logger.info("[TED] FILTRÉ (%s) : %s — %s", reason, acheteur[:30], objet[:55])
            continue

        # Skip les AO dont la date limite de réponse est déjà passée
        if deadline and deadline < today_iso:
            logger.info("[TED] ÉCHU (%s), skip : %s — %s", deadline, acheteur[:30], objet[:50])
            continue

        segment = _detect_segment_from_acheteur(acheteur) or "Autre"
        notice["segment"] = segment
        signal_type = "ao_publie"
        sous_segment = _map_sous_segment(notice)
        score = score_ao(signal_type, notice.get("_metier_score"), deadline, notice.get("_whitelist", False))
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
            description=(desc or objet)[:400],
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
        logger.info("[TED] [%d/T%d] %s — %s (%s)", score, tier, acheteur[:30], objet[:50], reason)

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux TED captés ===", len(sigs))


if __name__ == "__main__":
    main()
