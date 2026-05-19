"""
Helpers communs pour les scrapers RSS.

Factorise la logique répétitive : fetch, parse, nettoyage HTML, extraction de compte.
Chaque scraper RSS individuel ne porte plus que la config (URL, source, tier, vertical)
et la logique de classification spécifique.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable, Optional

import feedparser

logger = logging.getLogger(__name__)


# Stop-words pour l'extraction de compte
STOP_WORDS = {
    "Le", "La", "Les", "Un", "Une", "Des", "Du", "De", "Et", "Ou",
    "Comment", "Pourquoi", "Quand", "Où", "Avec", "Chez", "Selon", "Dans",
    "Cap", "Passée", "Passé", "Voici", "Avant", "Après", "Cette", "Ces",
    "IA", "Tech", "Startup", "Levée", "Acquisition", "Nouveau", "Nouvelle",
    "Premier", "Première", "Top", "Grand", "Grande", "Plus", "Tout", "Toute",
    "Que", "Qui", "Sur", "Pour", "Sans", "Vers", "Par", "Aux", "Au",
}

VERBES_ACTION = (
    "lève|lèvent|annonce|annoncent|lance|lancent|nomme|nomment|"
    "recrute|recrutent|déploie|déploient|signe|signent|"
    "acquiert|acquièrent|rachète|rachètent|boucle|bouclent|"
    "fusionne|fusionnent|investit|investissent|"
    "inaugure|inaugurent|ouvre|ouvrent|crée|créent"
)


# Patterns de titres clairement éditoriaux (tribunes, interviews, hebdos, listicles).
# Si un titre match l'un de ces patterns, on le marque comme bruit éditorial,
# donc signal_type='autre' et il sera écarté par is_purchase_signal().
EDITORIAL_PATTERNS = [
    r"^Revue du web",
    r"^Tribune\b",
    r"^Décryptage\b",
    r"^Itw\b|^Interview\b",
    r"^Édito\b|^Editorial\b",
    r"^Portrait\b",
    r"^Pourquoi\s",
    r"^Comment\s",
    r"^Que faire",
    r"^Top\s+\d+",
    r"^\d+\s+conseils\b",
    r"^\d+\s+id[ée]es\b",
    r"^\d+\s+raisons\b",
    r"^\d+\s+choses\b",
    r": «.+»",                  # quote = interview/citation → éditorial
    r"\bconférence de lancement\b",
    r"^Soft skills\b",
    r"^Cap sur le",             # "Cap sur le Royaume-Uni" = conseil voyage, pas signal d'achat
    r"^Les \w+ \w+ ont levé",   # hebdo agrégat "Les startups françaises ont levé X cette semaine"
    r"\bcette semaine$",         # idem
    r"^“[^”]+”\s*:",            # titre en guillemets typo = guidance ou tribune
]


def is_editorial_noise(title: str) -> bool:
    """
    Vrai si le titre correspond à un format éditorial (tribune, hebdo, interview, listicle).
    Permet de marquer ces signaux comme 'autre' pour qu'ils soient écartés par
    is_purchase_signal() en aval.
    """
    for pat in EDITORIAL_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
            return True
    return False


def fetch_rss(url: str, limit: int = 50, timeout_warn: bool = True) -> list[dict]:
    """
    Récupère un flux RSS et retourne une liste d'entrées normalisées.

    Chaque entrée : {title, description, link, date_iso}.
    """
    logger.info("Fetching RSS: %s", url)
    feed = feedparser.parse(url)
    if feed.bozo and timeout_warn:
        logger.warning("Feed parse warning on %s: %s", url, feed.bozo_exception)

    items = []
    for entry in feed.entries[:limit]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        description = entry.get("summary", "") or entry.get("description", "") or ""
        description = clean_html(description)[:400]
        link = entry.get("link", "")
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        date_iso = (
            datetime(*published[:6]).date().isoformat()
            if published
            else datetime.utcnow().date().isoformat()
        )
        items.append({
            "title": title,
            "description": description,
            "link": link,
            "date_iso": date_iso,
        })
    return items


def clean_html(text: str) -> str:
    """Strip HTML tags, normalize whitespace."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&\w+;", " ", text)  # &nbsp;, &amp;, etc.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def matches_any(text: str, keywords: Iterable[str]) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def matches_regex(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def extract_compte(title: str, custom_stops: Optional[set[str]] = None) -> str:
    """
    Extraction heuristique du nom du compte depuis le titre d'un article.

    Stratégies, dans l'ordre :
    1. Pattern "X + verbe-action" (X est le sujet)
    2. Pattern "Comment/Avec/Chez/Selon X"
    3. Pattern après deux-points "Tech : X annonce"
    4. Premier mot capitalisé propre (hors stop-words)
    """
    stops = STOP_WORDS | (custom_stops or set())

    # 1. Pattern "<Nom> + verbe-clé"
    m = re.search(
        rf"\b([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){{0,3}})\s+(?:{VERBES_ACTION})",
        title,
    )
    if m:
        cand = m.group(1).strip()
        parts = cand.split()
        # Si le 1er mot est un stop word, prendre les suivants
        while parts and parts[0] in stops:
            parts.pop(0)
        if parts:
            return " ".join(parts)

    # 2. Pattern "Comment/Avec/Chez/Selon X"
    m = re.search(
        r"(?:Comment|Avec|Chez|Selon)\s+([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){0,2})",
        title,
    )
    if m:
        return m.group(1).strip()

    # 3. Pattern après deux-points
    m = re.search(
        rf":\s+([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){{0,2}})\s+(?:{VERBES_ACTION})",
        title,
    )
    if m:
        return m.group(1).strip()

    # 4. Premier mot capitalisé propre
    for w in title.split():
        clean = re.sub(r"[^\w&\-\.]", "", w)
        if clean and clean[0].isupper() and clean not in stops and len(clean) > 2:
            return clean

    return "Inconnu"
