"""
Scraper Maximilien IDF — profil acheteur Île-de-France (lycées, IUT, collectivités).

Maximilien IDF (https://marches.maximilien.fr) est une plateforme PRADO PHP
server-rendered avec ViewState POST. Pour la scraper, on délègue à l'actor
Apify `apify/rag-web-browser` qui exécute le JS et nous retourne le markdown
de la page de résultats. On lui balance N requêtes (1 par mot-clé), on parse
les notices, on applique le filtre métier strict (réutilisé de seed_from_radar).

Coût Apify estimé : ~$0.002/keyword. 10 keywords/jour = $0.60/mois.

Pré-requis : variable d'environnement APIFY_TOKEN exposée (en CI via secret
GitHub `APIFY_TOKEN`).
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402

# Réutilise le filtre métier strict défini dans seed_from_radar.py
from scrapers.ao.seed_from_radar import (  # noqa: E402
    _passes_metier_filter,
    _detect_segment_from_acheteur,
    _map_sous_segment,
    _generate_ao_action,
)

logger = logging.getLogger(__name__)

VERTICAL = "ao"
SOURCE_NAME = "Maximilien IDF"

# Apify config
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
APIFY_ACTOR = "apify/rag-web-browser"
APIFY_BASE = "https://api.apify.com/v2"
POLL_INTERVAL = 3  # secondes
TIMEOUT = 90  # secondes max par run

# URL de recherche keyword sur Maximilien IDF
SEARCH_URL_TMPL = (
    "https://marches.maximilien.fr/?page=Entreprise.EntrepriseAdvancedSearch"
    "&AllCons&keyWord={keyword}"
)

# Mots-clés à requêter — comité experts 24 mai (recentrage ITS/Tosa).
# Optimisé : on cherche des AO de PLATEFORME, pas de prestation de service.
# Les keywords trop génériques (certification, compétences, évaluation) sont
# retirés car ils ramènent surtout du consulting RH / audit Qualiopi qui sont
# filtrés en aval — autant ne pas les requêter (économie crédit Apify).
SEARCH_KEYWORDS = [
    # Termes plateforme/outil (signaux directs ITS)
    "proctoring",
    "examens à distance",
    "examens en ligne",
    "télésurveillance",
    "QCM",
    "psychométrie",
    # Termes Tosa (signaux secondaires)
    "TOSA",
    "compétences numériques",
    "DigComp",
    # Concurrents (signal de remplacement)
    "PIX",
    # Termes mid (peuvent matcher si combinés)
    "passation",
    "test de positionnement",
]


# ─────────────────────────────────────────────────────────────────────────────
# Apify call
# ─────────────────────────────────────────────────────────────────────────────

def _apify_run_actor(input_payload: dict) -> Optional[dict]:
    """Lance un run sur apify/rag-web-browser et retourne le dataset items."""
    if not APIFY_TOKEN:
        logger.warning("[Maximilien IDF] APIFY_TOKEN absent — skip")
        return None

    url = f"{APIFY_BASE}/acts/apify~rag-web-browser/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    try:
        r = requests.post(url, json=input_payload, timeout=TIMEOUT)
        r.raise_for_status()
        items = r.json()
        if isinstance(items, list):
            return {"items": items}
        return None
    except Exception as e:
        logger.warning("[Maximilien IDF] Apify call failed: %s", e)
        return None


def _fetch_search_page(keyword: str) -> Optional[str]:
    """Fetch le markdown de la page de résultats Maximilien pour un keyword."""
    url = SEARCH_URL_TMPL.format(keyword=requests.utils.quote(keyword))
    logger.info("[Maximilien IDF] Apify fetch: %s", keyword)
    payload = {
        "query": url,
        "maxResults": 1,
        "outputFormats": ["markdown"],
        "requestTimeoutSecs": 30,
    }
    result = _apify_run_actor(payload)
    if not result or not result.get("items"):
        return None
    item = result["items"][0]
    markdown = item.get("markdown") or item.get("text") or ""
    if not markdown:
        logger.warning("[Maximilien IDF] empty markdown for keyword=%s", keyword)
    return markdown


# ─────────────────────────────────────────────────────────────────────────────
# Markdown parsing
# ─────────────────────────────────────────────────────────────────────────────

# Le markdown d'une notice contient des blocs avec :
# - Type de procédure (AOO, AAPC, MAPA…)
# - Catégorie (Services, Fournitures, Travaux)
# - Date publication (DD MM YYYY)
# - Référence | Intitulé
# - Objet : ...
# - Organisme : ... (CP - ville)
# - Date limite (DD Month YYYY HH:MM)
# - URL : /entreprise/consultation/<id>?orgAcronyme=<acronym>

MOIS_FR = {
    "janv": "01", "févr": "02", "fevr": "02", "mars": "03", "avr": "04",
    "mai": "05", "juin": "06", "juil": "07", "août": "08", "aout": "08",
    "sept": "09", "oct": "10", "nov": "11", "déc": "12", "dec": "12",
}


def _parse_date_fr(day: str, month: str, year: str) -> Optional[str]:
    """Convertit '19 Mai 2026' en '2026-05-19'."""
    m = month.lower()[:4].rstrip(".")
    mm = MOIS_FR.get(m[:4]) or MOIS_FR.get(m[:3])
    if not mm:
        return None
    try:
        d = int(day)
        y = int(year)
        return f"{y}-{mm}-{d:02d}"
    except (ValueError, TypeError):
        return None


def _extract_notices(markdown: str) -> list[dict]:
    """
    Parse le markdown retourné par Maximilien et extrait les notices.

    Stratégie : on cherche les URLs de consultation `/entreprise/consultation/<id>?orgAcronyme=<x>`
    et pour chaque match, on remonte dans le texte pour extraire les champs autour.
    """
    notices = []

    # Chaque notice contient un URL de consultation détaillée
    pattern = re.compile(
        r"/entreprise/consultation/(\d+)\?orgAcronyme=([^&\)\s]+)"
    )
    matches = list(pattern.finditer(markdown))
    if not matches:
        return notices

    # Borne le contexte d'une notice à la zone située APRÈS la précédente URL trouvée
    # et avant la fin du match courant. Sinon on capture les dates de l'AO voisin.
    seen = set()
    prev_end = 0
    for idx, m in enumerate(matches):
        cons_id = m.group(1)
        if cons_id in seen:
            continue
        seen.add(cons_id)
        org_acronyme = m.group(2)

        # Trouver le dernier URL match PRÉCÉDANT m, pour borner le contexte par le bas
        ctx_start = prev_end
        for prev_m in matches:
            if prev_m.end() < m.start() and prev_m.group(1) != cons_id:
                ctx_start = max(ctx_start, prev_m.end())
        ctx_end = min(len(markdown), m.end() + 200)
        ctx = markdown[ctx_start:ctx_end]
        prev_end = m.end()

        # Objet
        objet_m = re.search(r"\|\s*([A-ZÉÈÊÀÂÔÛÎÇa-zA-Z][^\n|]{20,300})", ctx)
        # Plus précis : ligne entre `|` et avant Objet/Organisme
        intitule_m = re.search(r"\|\s*\n?\s*([A-ZÉÈÊÀÂÔÛÎÇ][^\n|]{15,300})\s*\n", ctx)
        intitule = intitule_m.group(1).strip() if intitule_m else ""

        objet_full_m = re.search(r"\*\*Objet :\*\*\s*([^\n]{15,800})", ctx)
        objet = objet_full_m.group(1).strip() if objet_full_m else ""

        # Organisme
        org_m = re.search(r"\*\*Organisme :\*\*\s*([^\n(]{3,200})(?:\(([^)]+)\))?", ctx)
        organisme = org_m.group(1).strip() if org_m else ""
        organisme_loc = (org_m.group(2).strip() if org_m and org_m.group(2) else "")

        # Dates : Maximilien affiche la publication SANS heure, la deadline AVEC heure (HH:MM).
        # On extrait toutes les dates du ctx et on discrimine via la présence d'une heure.
        date_pattern = re.compile(
            r"(\d{1,2})\s*(Janv|Févr|Fevr|Mars|Avr|Mai|Juin|Juil|Août|Aout|Sept|Oct|Nov|Déc|Dec)[a-zé.]*\s*(20\d{2})(\s*\d{1,2}:\d{2})?",
            re.IGNORECASE,
        )
        dates_in_ctx = list(date_pattern.finditer(ctx))
        date_pub = None
        deadline = None
        for dm in dates_in_ctx:
            parsed = _parse_date_fr(dm.group(1), dm.group(2), dm.group(3))
            if not parsed:
                continue
            has_time = bool(dm.group(4))
            if has_time and not deadline:
                deadline = parsed
            elif not has_time and not date_pub:
                date_pub = parsed
        # Si pas de date avec HH:MM trouvée, fallback: dernière date = deadline
        if not deadline and dates_in_ctx:
            last = dates_in_ctx[-1]
            deadline = _parse_date_fr(last.group(1), last.group(2), last.group(3))

        # Référence
        ref_m = re.search(r"(?:^|\n)\s*(\d{6,12}|[A-Z0-9]{4,15})\s*\n\s*\|", ctx)
        ref = ref_m.group(1) if ref_m else ""

        if not organisme or not (intitule or objet):
            continue

        # Construction notice format unifié (compatible filtre _passes_metier_filter)
        notice = {
            "id": f"max-{cons_id}",
            "ref": ref,
            "acheteur": organisme,
            "objet": intitule or objet[:200],
            "description": objet,
            "cpv": "",  # Maximilien n'expose pas le CPV en page de résultats
            "pays": "FR",
            "deadline": deadline,
            "publication": date_pub,
            "source": SOURCE_NAME,
            "url": f"https://marches.maximilien.fr/entreprise/consultation/{cons_id}?orgAcronyme={org_acronyme}",
            "score": 60,  # score par défaut, sera ajusté par scoring si besoin
            "segment": "",  # déduit plus tard via _detect_segment_from_acheteur
        }
        notices.append(notice)

    return notices


# ─────────────────────────────────────────────────────────────────────────────
# Main scraper
# ─────────────────────────────────────────────────────────────────────────────

def scrape() -> list[Signal]:
    """Lance N recherches keyword sur Maximilien IDF et retourne les Signals."""
    today = datetime.utcnow().date().isoformat()

    if not APIFY_TOKEN:
        logger.warning(
            "[Maximilien IDF] APIFY_TOKEN absent — scraper skip. "
            "Définir le secret GitHub `APIFY_TOKEN` pour activer."
        )
        return []

    all_notices = {}
    for kw in SEARCH_KEYWORDS:
        markdown = _fetch_search_page(kw)
        if not markdown:
            continue
        notices = _extract_notices(markdown)
        for n in notices:
            # Dédup par id sur tous les keywords
            all_notices.setdefault(n["id"], n)

    logger.info("[Maximilien IDF] %d notices uniques captées sur %d keywords", len(all_notices), len(SEARCH_KEYWORDS))

    signals = []
    for n in all_notices.values():
        # Filtre métier strict
        passes, reason = _passes_metier_filter(n)
        if not passes:
            logger.info(
                "[Maximilien IDF] FILTRÉ (%s) : %s — %s",
                reason, n["acheteur"][:35], n["objet"][:60],
            )
            continue

        score = int(n.get("score", 60))
        tier = determine_tier(score)
        signal_type = "ao_publie"
        sous_segment = _map_sous_segment(n)

        # Segment pour action commerciale
        segment_brut = n.get("segment") or "Autre"
        if segment_brut in ("", "Autre"):
            detected = _detect_segment_from_acheteur(n["acheteur"])
            if detected:
                segment_brut = detected

        action = _generate_ao_action(n, signal_type, segment_brut)

        sig = Signal(
            id=fingerprint(n["objet"], n["acheteur"], n.get("publication") or today),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=n["acheteur"],
            titre=n["objet"][:200],
            description=n["description"][:400] if n["description"] else n["objet"][:400],
            source=SOURCE_NAME,
            source_tier=2,  # plateforme régionale = Tier 2
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
        )
        signals.append(sig)
        logger.info(
            "[Maximilien IDF] [%s/%s] [%d] %s — %s",
            VERTICAL, signal_type, score, n["acheteur"][:35], n["objet"][:60],
        )

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("[Maximilien IDF] %d signaux retournés", len(sigs))
    for s in sigs:
        logger.info("  - [%d] %s | %s", s.score, s.compte, s.titre[:80])


if __name__ == "__main__":
    main()
