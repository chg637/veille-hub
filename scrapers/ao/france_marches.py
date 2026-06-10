"""
Scraper France Marchés — agrégateur AO public français.

https://www.francemarches.com/ agrège les AO BOAMP + JOUE + profils acheteurs
de tous les acteurs publics français. Le site est protégé anti-bot (HTTP 403
sur requêtes directes), on passe donc par Apify rag-web-browser qui gère le
rendu JS et les défenses basiques.

Stratégie : 1 recherche Apify par mot-clé ITS, on parse le markdown rendu
pour extraire les AO, on déduplique par référence/URL, on passe le tout au
filtre v5.3 commun.

Cadence : quotidienne via le runner. Skip propre si APIFY_TOKEN absent.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

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
SOURCE_NAME = "France Marchés"
BASE_URL = "https://www.francemarches.com"
SEARCH_URL = f"{BASE_URL}/recherche?q="

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
APIFY_BASE = "https://api.apify.com/v2"
APIFY_ACTOR = "apify~rag-web-browser"
USER_AGENT = "IsogradVeilleHub/1.0 (+contact@isograd.com)"

# Mots-clés ITS pour la recherche France Marchés.
# On vise les phrases produit pour éviter le bruit (lesson du run #43 Maximilien IDF).
SEARCH_KEYWORDS = [
    "plateforme d'évaluation",
    "logiciel d'évaluation",
    "outil de positionnement",
    "moteur d'examen",
    "banque de questions",
    "proctoring",
    "examens en ligne",
    "examens à distance",
    "certification compétences numériques",
    "évaluation des enseignements",
    "TOSA",
]


def _apify_call(url: str, timeout: int = 90) -> Optional[str]:
    """Appelle Apify rag-web-browser, retourne le markdown rendu."""
    if not APIFY_TOKEN:
        logger.warning("[France Marchés] APIFY_TOKEN absent — skip %s", url)
        return None
    api_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    payload = {
        "query": url,
        "maxResults": 1,
        "outputFormats": ["markdown"],
        "requestTimeoutSecs": 60,
    }
    try:
        r = requests.post(api_url, json=payload, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        items = r.json()
        if isinstance(items, list) and items:
            return items[0].get("markdown") or items[0].get("text") or ""
    except Exception as e:
        logger.warning("[France Marchés] Apify call failed pour %s : %s", url[:80], e)
    return None


# Patterns pour extraire les notices du markdown rendu France Marchés.
# La structure exacte peut varier : on essaie plusieurs heuristiques.
RE_NOTICE_BLOCK = re.compile(
    r"\[([^\]]{15,200})\]\(([^)]*?/(?:marche|annonce|appel-d-offre|consultation)/[^)\s]+)\)",
    re.IGNORECASE,
)
RE_ACHETEUR = re.compile(
    r"(?:par|publi[ée] par|Organisme|Acheteur)\s*[:\-]\s*([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ\s'\-\.]{2,80})",
    re.IGNORECASE,
)
RE_DATE_LIMITE = re.compile(
    r"(?:Date limite|Limite|Échéance)\s*[:\-]\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
    re.IGNORECASE,
)
RE_DATE_PUBLI = re.compile(
    r"(?:Publié|Date de publication|Publication)\s*[:\-]\s*(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})",
    re.IGNORECASE,
)


def _parse_date_fr(d: int, m: int, y: int) -> Optional[str]:
    try:
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None


def _extract_notices_from_markdown(markdown: str, keyword: str) -> list[dict]:
    """
    Extrait les notices AO du markdown rendu de la page recherche France Marchés.

    Heuristique : on cherche des liens markdown vers des pages individuelles
    de marchés ([titre](url)), puis on essaie d'extraire dans les ~500 caractères
    suivants l'acheteur, la date de publication, la date limite.

    Si la structure du site change, ce parser sera silencieusement à 0 — surveiller
    le log "0 notices extraites" pour signal d'alerte.
    """
    notices = []
    if not markdown:
        return notices

    seen_urls = set()
    for match in RE_NOTICE_BLOCK.finditer(markdown):
        titre = match.group(1).strip()
        url = match.group(2).strip()
        if not url.startswith("http"):
            url = BASE_URL.rstrip("/") + "/" + url.lstrip("/")
        if url in seen_urls or len(titre) < 15:
            continue
        seen_urls.add(url)

        # Contexte = 600 caractères après le lien (souvent contient acheteur, dates)
        context_start = match.end()
        context = markdown[context_start:context_start + 600]

        acheteur = ""
        m_ach = RE_ACHETEUR.search(context)
        if m_ach:
            acheteur = m_ach.group(1).strip()

        date_publi = None
        m_pub = RE_DATE_PUBLI.search(context)
        if m_pub:
            date_publi = _parse_date_fr(int(m_pub.group(1)), int(m_pub.group(2)), int(m_pub.group(3)))

        deadline = None
        m_dl = RE_DATE_LIMITE.search(context)
        if m_dl:
            deadline = _parse_date_fr(int(m_dl.group(1)), int(m_dl.group(2)), int(m_dl.group(3)))

        notices.append({
            "titre": titre[:200],
            "url": url,
            "acheteur": acheteur or "France Marchés (acheteur à confirmer)",
            "date_publication": date_publi,
            "deadline": deadline,
            "keyword": keyword,
            "description_context": context[:400],
        })

    return notices


def scrape() -> list[Signal]:
    today_iso = datetime.utcnow().date().isoformat()

    if not APIFY_TOKEN:
        logger.warning("[France Marchés] APIFY_TOKEN absent — scraper skip. "
                       "Définir le secret GitHub `APIFY_TOKEN` pour activer.")
        return []

    # 1. Une recherche Apify par mot-clé, dédupliquer par URL
    all_notices: dict[str, dict] = {}
    for kw_idx, kw in enumerate(SEARCH_KEYWORDS):
        url = SEARCH_URL + quote_plus(kw)
        logger.info("[France Marchés] Apify fetch : %s", kw)
        markdown = _apify_call(url)
        if not markdown:
            logger.info("[France Marchés] '%s' → Apify markdown vide ou None", kw)
            continue
        # DEBUG : sur le 1er mot-clé seulement, logger les 800 premiers chars du markdown
        # pour pouvoir diagnostiquer la structure rendue par Apify (à retirer après calibrage).
        if kw_idx == 0:
            preview = markdown[:800].replace("\n", " ⏎ ")
            logger.info("[France Marchés] DEBUG markdown[0:800] = %s", preview)
        notices = _extract_notices_from_markdown(markdown, kw)
        for n in notices:
            if n["url"] not in all_notices:
                all_notices[n["url"]] = n
        logger.info("[France Marchés] '%s' → %d notices (markdown %d chars, cumul unique : %d)",
                    kw, len(notices), len(markdown), len(all_notices))

    if not all_notices:
        logger.info("[France Marchés] 0 notices captées — soit pas d'AO pertinent en cours, "
                    "soit la structure du site a changé (parser à vérifier).")
        return []

    logger.info("[France Marchés] %d notices uniques sur %d mots-clés",
                len(all_notices), len(SEARCH_KEYWORDS))

    # 2. Mapper + filtrer v5.3
    ck = curated_keys()
    signals = []
    for notice_data in all_notices.values():
        titre = notice_data["titre"]
        acheteur = notice_data["acheteur"]
        url = notice_data["url"]

        if is_curated(acheteur, titre, ck):
            logger.info("[France Marchés] DÉJÀ EN CURATED, skip : %s — %s",
                        acheteur[:30], titre[:50])
            continue

        notice = {
            "id": f"fm-{fingerprint(titre, acheteur, notice_data.get('date_publication') or today_iso)[:10]}",
            "ref": "",
            "acheteur": acheteur,
            "objet": titre,
            "description": notice_data["description_context"] or titre,
            "cpv": "",
            "pays": "FR",
            "deadline": notice_data["deadline"],
            "publication": notice_data["date_publication"] or today_iso,
            "source": SOURCE_NAME,
            "url": url,
            "score": 80,
            "segment": "",
        }

        passes, reason = _passes_metier_filter(notice)
        if not passes:
            logger.info("[France Marchés] FILTRÉ (%s) : %s — %s",
                        reason, acheteur[:30], titre[:55])
            continue

        fm_deadline = str(notice["deadline"] or "")[:10] or None
        if fm_deadline and fm_deadline < today_iso:
            logger.info("[France Marchés] ÉCHU (%s), skip : %s — %s", fm_deadline, acheteur[:30], titre[:50])
            continue

        segment = _detect_segment_from_acheteur(acheteur) or "Autre"
        notice["segment"] = segment
        signal_type = "ao_publie"
        sous_segment = _map_sous_segment(notice)
        score = score_ao(signal_type, notice.get("_metier_score"), fm_deadline, notice.get("_whitelist", False))
        tier = determine_tier(score)

        action = _generate_ao_action(notice, signal_type, segment)
        email_dr = email_draft_ao(acheteur, titre, notice["deadline"] or "à définir", url)
        contacts = get_contacts_cibles(signal_type, acheteur)

        sig = Signal(
            id=fingerprint(titre, acheteur, notice["publication"]),
            date_capture=today_iso,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=acheteur,
            titre=titre[:200],
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
            deadline_action=notice["deadline"],
            status="new",
            date_publication=notice["publication"],
            email_draft=email_dr,
            contacts_cibles=contacts,
        )
        signals.append(sig)
        logger.info("[France Marchés] [%d/T%d] %s — %s (%s)",
                    score, tier, acheteur[:30], titre[:50], reason)

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux France Marchés captés ===", len(sigs))


if __name__ == "__main__":
    main()
