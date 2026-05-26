"""
Helpers PLACE (marches-publics.gouv.fr) — scraping de profils acheteurs spécifiques.

Sur PLACE, le filtre `keyword=` côté URL ne fonctionne pas (filtre client-side
via POST ViewState .NET). En revanche, l'URL profil acheteur direct avec
`orgAcronyme=XXX` permet de récupérer la liste des AO publiés par UN acheteur
spécifique. Cas typique : Université Paris-Saclay, Sorbonne, AP-HP, etc.

Architecture :
- Une fonction factorisée `scrape_place_profil(orgAcronyme, nom)` qui appelle
  apify/rag-web-browser et parse le markdown rendu
- Un scraper par profil acheteur dans `scrapers/ao/profils_place/` qui appelle
  cette fonction avec son orgAcronyme
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
APIFY_BASE = "https://api.apify.com/v2"
APIFY_ACTOR = "apify~rag-web-browser"
USER_AGENT = "IsogradVeilleHub/1.0 (+contact@isograd.com)"

# Mois français → numéro pour parsing dates "23 Mai 2026"
MOIS_FR = {
    "janv": "01", "févr": "02", "fevr": "02", "mars": "03", "avr": "04",
    "mai": "05", "juin": "06", "juil": "07", "août": "08", "aout": "08",
    "sept": "09", "oct": "10", "nov": "11", "déc": "12", "dec": "12",
}


def _parse_date_fr(day: str, month: str, year: str) -> Optional[str]:
    """Convertit '23 Mai 2026' en '2026-05-23'."""
    m = (month or "").lower().rstrip(".").strip()
    mm = MOIS_FR.get(m[:4]) or MOIS_FR.get(m[:3])
    if not mm:
        return None
    try:
        return f"{int(year)}-{mm}-{int(day):02d}"
    except (ValueError, TypeError):
        return None


def _apify_call(url: str, timeout: int = 60) -> Optional[str]:
    """Appelle apify/rag-web-browser et retourne le markdown rendu."""
    if not APIFY_TOKEN:
        logger.warning("[PLACE helper] APIFY_TOKEN absent — skip %s", url)
        return None
    api_url = f"{APIFY_BASE}/acts/{APIFY_ACTOR}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    payload = {
        "query": url,
        "maxResults": 1,
        "outputFormats": ["markdown"],
        "requestTimeoutSecs": 45,
    }
    try:
        r = requests.post(api_url, json=payload, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        items = r.json()
        if isinstance(items, list) and items:
            return items[0].get("markdown") or items[0].get("text") or ""
    except Exception as e:
        logger.warning("[PLACE helper] Apify call failed: %s", e)
    return None


def _extract_notices_from_markdown(markdown: str, source_label: str) -> list[dict]:
    """
    Parse le markdown PLACE et extrait les notices d'AO.

    Sur PLACE, chaque notice contient :
    - Type de procédure (MAPA, AOO, AOR, etc.)
    - Catégorie (Services, Travaux, Fournitures)
    - Date de publication (DD Mois YYYY)
    - Référence
    - Intitulé
    - Objet
    - Organisme
    - Date limite (DD Mois YYYY HH:MM)
    - URL consultation : /app.php/entreprise/consultation/<id>?orgAcronyme=<x>
    """
    notices = []
    if not markdown:
        return notices

    # Pattern URL consultation PLACE
    pattern = re.compile(
        r"/app\.php/entreprise/consultation/(\d+)\?orgAcronyme=([^&\)\s\"]+)"
    )
    matches = list(pattern.finditer(markdown))
    if not matches:
        return notices

    seen = set()
    prev_end = 0
    for m in matches:
        cons_id = m.group(1)
        if cons_id in seen:
            continue
        seen.add(cons_id)
        org_acronyme = m.group(2)

        # Contexte : entre la précédente URL et le match courant (+ peu après)
        ctx_start = prev_end
        for prev_m in matches:
            if prev_m.end() < m.start() and prev_m.group(1) != cons_id:
                ctx_start = max(ctx_start, prev_m.end())
        ctx_end = min(len(markdown), m.end() + 200)
        ctx = markdown[ctx_start:ctx_end]
        prev_end = m.end()

        # Intitulé (entre `|` et fin de ligne en début de notice)
        intitule_m = re.search(r"\|\s*\n?\s*([A-ZÉÈÊÀÂÔÛÎÇ][^\n|]{15,300})\s*\n", ctx)
        intitule = intitule_m.group(1).strip() if intitule_m else ""

        # Objet
        objet_full_m = re.search(r"\*\*Objet :\*\*\s*([^\n]{15,800})", ctx)
        objet = objet_full_m.group(1).strip() if objet_full_m else ""

        # Organisme
        org_m = re.search(r"\*\*Organisme :\*\*\s*([^\n(]{3,200})(?:\(([^)]+)\))?", ctx)
        organisme = org_m.group(1).strip() if org_m else ""

        # Dates : extraire toutes, discriminer publication (sans heure) vs deadline (avec heure)
        date_pattern = re.compile(
            r"(\d{1,2})\s*(Janv|Févr|Fevr|Mars|Avr|Mai|Juin|Juil|Août|Aout|Sept|Oct|Nov|Déc|Dec)[a-zé.]*\s*(20\d{2})(\s*\d{1,2}:\d{2})?",
            re.IGNORECASE,
        )
        date_pub = None
        deadline = None
        for dm in date_pattern.finditer(ctx):
            parsed = _parse_date_fr(dm.group(1), dm.group(2), dm.group(3))
            if not parsed:
                continue
            has_time = bool(dm.group(4))
            if has_time and not deadline:
                deadline = parsed
            elif not has_time and not date_pub:
                date_pub = parsed

        # Référence
        ref_m = re.search(r"(?:^|\n)\s*(\d{6,12}|[A-Z0-9-]{4,20})\s*\n\s*\|", ctx)
        ref = ref_m.group(1) if ref_m else ""

        if not organisme or not (intitule or objet):
            continue

        notice = {
            "id": f"place-{org_acronyme}-{cons_id}",
            "ref": ref,
            "acheteur": organisme,
            "objet": intitule or objet[:200],
            "description": objet,
            "cpv": "",  # PLACE liste n'expose pas le CPV — récupérable via page détail
            "pays": "FR",
            "deadline": deadline,
            "publication": date_pub,
            "source": source_label,
            "url": f"https://www.marches-publics.gouv.fr/app.php/entreprise/consultation/{cons_id}?orgAcronyme={org_acronyme}",
            "score": 70,
            "segment": "ESR" if "université" in organisme.lower() else "Autre",
        }
        notices.append(notice)

    return notices


def scrape_place_profil(org_acronyme: str, nom_profil: str) -> list[dict]:
    """
    Scrape un profil acheteur PLACE par son orgAcronyme.

    Retourne la liste des notices brutes (à filtrer ensuite via _passes_metier_filter).
    """
    url = (
        f"https://www.marches-publics.gouv.fr/?page=Entreprise.EntrepriseAdvancedSearch"
        f"&AllCons&orgAcronyme={org_acronyme}"
    )
    logger.info("[PLACE profil] fetching %s (acronyme=%s)", nom_profil, org_acronyme)
    markdown = _apify_call(url)
    if not markdown:
        return []
    source_label = f"PLACE — {nom_profil}"
    notices = _extract_notices_from_markdown(markdown, source_label)
    logger.info("[PLACE profil] %s : %d notices brutes captées", nom_profil, len(notices))
    return notices
