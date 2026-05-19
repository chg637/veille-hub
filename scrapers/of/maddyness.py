"""
Scraper Maddyness — flux RSS principal, filtrage EdTech & levées de fonds entreprise.

Maddyness publie quotidiennement des articles sur l'écosystème startup français.
Sont pertinents pour notre veille :
- Catégorie EdTech / Formation → vertical "of" (organismes de formation)
- Levées de fonds tech > 20 M€ → vertical "corporate" (signal Tier 1)
- Annonces produit IA → vertical "corporate" (plan IA = trigger)

Le RSS principal contient ~30 derniers articles. On filtre par mots-clés
dans le titre + description, on classifie par vertical, on score, on sauve.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import feedparser  # noqa: E402

# Permet le run en mode "python scrapers/of/maddyness.py" ou en module
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402

logger = logging.getLogger(__name__)


# URL du flux principal Maddyness
RSS_URL = "https://www.maddyness.com/feed/"

# Mots-clés EdTech / formation (vertical OF)
EDTECH_KEYWORDS = [
    "edtech", "formation", "apprentissage", "elearning", "e-learning",
    "certification", "compétences", "competence", "skill", "skills",
    "learning", "université", "ecole", "école",
    "rncp", "qualiopi", "moocs", "mooc", "lms", "lxp",
]

# Mots-clés Corporate (vertical Corporate)
# Levée de fonds + plan IA / recrutement
CORPO_LEVEE_PATTERNS = [
    r"\b\d+\s*(?:m€|millions?\s*d['']euros?|m\$|million\s*\$)",
    r"\bsér[ie]e?\s*[abc]\b",
    r"\blève\s+\d",
    r"\bbouclé?\s+un[e]?\s+lev",
]
CORPO_IA_KEYWORDS = [
    "intelligence artificielle", "ia générative", "ia generative", "llm",
    "ai", "machine learning", "deep learning", "gpt",
]
CORPO_RECRUT_KEYWORDS = [
    "recrut", "embauch", "recrue", "embauche",
]

# Mots-clés concurrents directs à flagger
CONCURRENTS = [
    "openclassrooms", "open classrooms", "cegos", "demos", "crossknowledge",
    "360learning", "pix", "m2i", "coorpacademy", "eni",
]


def _matches_any(text: str, keywords: list[str]) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


def _matches_regex(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _extract_compte(title: str, description: str) -> str:
    """
    Extraction heuristique du nom du compte depuis le titre.

    Stratégies, dans l'ordre :
    1. Pattern "X lève|annonce|lance|nomme..." n'importe où dans le titre (le verbe est suivi du nom)
    2. Pattern "Comment X..." / "Avec X..." / "Chez X..."
    3. Premier mot capitalisé propre en début de titre (en excluant les mots vides)
    4. Fallback : "Inconnu"

    On exclut les mots de liaison fréquents qui pourraient être pris à tort pour un nom propre.
    """
    STOP_WORDS = {
        "Le", "La", "Les", "Un", "Une", "Des", "Du", "De",
        "Comment", "Pourquoi", "Quand", "Où", "Avec", "Chez", "Selon", "Dans",
        "Cap", "Passée", "Passé", "Voici", "Avant", "Après", "Cette", "Ces",
        "IA", "Tech", "Startup", "Levée", "Acquisition",
    }

    # 1. Pattern "<Nom> + verbe-clé" — chercher dans tout le titre
    # On capture le mot avec majuscule juste avant le verbe-clé
    m = re.search(
        r"\b([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){0,3})\s+"
        r"(?:lève|lèvent|annonce|annoncent|lance|lancent|nomme|nomment|"
        r"recrute|recrutent|déploie|déploient|signe|signent|"
        r"acquiert|acquièrent|rachète|rachètent|boucle|bouclent|"
        r"fusionne|fusionnent|s['']introduit|investit)",
        title,
    )
    if m:
        cand = m.group(1).strip()
        # Si le candidat est composé de plusieurs mots, vérifier que le 1er n'est pas un stop word
        first = cand.split()[0]
        if first not in STOP_WORDS:
            return cand
        # Sinon, on prend le 2e mot s'il existe
        parts = cand.split()
        if len(parts) > 1:
            return " ".join(parts[1:])

    # 2. Pattern "Comment/Avec/Chez/Selon X"
    m = re.search(
        r"(?:Comment|Avec|Chez|Selon)\s+([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){0,2})",
        title,
    )
    if m:
        return m.group(1).strip()

    # 3. Pattern "IA : X lève" ou "Tech : X annonce" (après deux-points)
    m = re.search(
        r":\s+([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){0,2})\s+(?:lève|annonce|lance)",
        title,
    )
    if m:
        return m.group(1).strip()

    # 4. Premier mot capitalisé propre, en excluant les stop words
    words = title.split()
    for w in words:
        clean = re.sub(r"[^\w&\-\.]", "", w)
        if clean and clean[0].isupper() and clean not in STOP_WORDS and len(clean) > 2:
            return clean

    return "Inconnu"


def _classify(title: str, description: str) -> Optional[tuple[str, str, str]]:
    """
    Classifie un article Maddyness en (vertical, signal_type, sous_segment) ou None si pas pertinent.

    Retourne None si l'article n'est pas dans notre périmètre.
    """
    # Filtre éditorial : tribunes, hebdos agrégats, listicles → rejetés
    from scrapers.lib.rss_helpers import is_editorial_noise
    if is_editorial_noise(title):
        return None

    text = f"{title} {description}"

    # Vertical OF (EdTech / formation)
    if _matches_any(text, EDTECH_KEYWORDS):
        # Levée EdTech ?
        if _matches_regex(text, CORPO_LEVEE_PATTERNS):
            return ("of", "levee_edtech", "EdTech / formation")
        # Concurrent direct news ?
        if _matches_any(text, CONCURRENTS):
            return ("of", "concurrent_news", "EdTech / formation")
        # Article EdTech général
        return ("of", "autre", "EdTech / formation")

    # Vertical Corporate (levée + IA + recrutement)
    # Ordre de priorité : recrutement explicite > IA > levée pure
    if _matches_regex(text, CORPO_LEVEE_PATTERNS):
        # Une levée qui mentionne recrutement/embauche → signal le plus chaud pour ITS
        if _matches_any(text, CORPO_RECRUT_KEYWORDS):
            return ("corporate", "plan_recrutement", "ETI tech / scale-up + embauche")
        if _matches_any(text, CORPO_IA_KEYWORDS):
            return ("corporate", "plan_ia", "ETI tech / IA")
        return ("corporate", "levee_fonds", "ETI tech / scale-up")

    # Plan recrutement déclaré sans levée
    if _matches_any(text, CORPO_RECRUT_KEYWORDS) and any(k in text.lower() for k in ["postes", "personnes", "embauches", "talents"]):
        return ("corporate", "plan_recrutement", "ETI / plan embauche")

    if _matches_any(text, CORPO_IA_KEYWORDS) and len(text) > 200:
        return ("corporate", "plan_ia", "ETI tech / IA")

    return None


def scrape(limit: int = 50) -> dict[str, list[Signal]]:
    """
    Lance le scraping Maddyness et retourne un dict {vertical: [signaux]}.
    """
    logger.info("Fetching Maddyness RSS feed: %s", RSS_URL)
    feed = feedparser.parse(RSS_URL)
    if feed.bozo:
        logger.warning("Feed parse warning: %s", feed.bozo_exception)

    results = {"education": [], "of": [], "corporate": []}
    today = datetime.utcnow().date().isoformat()

    for entry in feed.entries[:limit]:
        title = entry.get("title", "")
        description = entry.get("summary", "") or entry.get("description", "")
        link = entry.get("link", "")
        published = entry.get("published_parsed")
        date_iso = (
            datetime(*published[:6]).date().isoformat()
            if published
            else today
        )

        # Strip HTML tags from description
        description = re.sub(r"<[^>]+>", " ", description).strip()
        description = re.sub(r"\s+", " ", description)[:400]

        classification = _classify(title, description)
        if classification is None:
            continue

        # Filtre fraîcheur : on ignore les articles > 14 jours
        if not is_recent(date_iso):
            logger.debug("Skipping stale: %s (%s)", title[:60], date_iso)
            continue

        vertical, signal_type, sous_segment = classification
        compte = _extract_compte(title, description)
        score = base_score(signal_type, source_tier=2)  # Maddyness = Tier 2
        tier = determine_tier(score)
        action_info = generate_action(signal_type, vertical, compte=compte)

        sig_id = fingerprint(title, compte, date_iso)
        signal = Signal(
            id=sig_id,
            date_capture=today,
            vertical=vertical,
            sous_segment=sous_segment,
            compte=compte,
            titre=title[:200],
            description=description,
            source="Maddyness",
            source_tier=2,
            url=link,
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, vertical),
            owner=None,
            action_reco=action_info["action"],
            deadline_action=action_info["deadline_action"],
            status="new",
            date_publication=date_iso,
        )
        results[vertical].append(signal)
        logger.info("Captured signal: [%s/%s] [pub=%s] %s", vertical, signal_type, date_iso, title[:70])

    return results


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = repo_root / "data"

    new_signals_by_vertical = scrape()

    for vertical, new_signals in new_signals_by_vertical.items():
        if not new_signals:
            continue
        path = data_dir / vertical / "signals.json"
        existing = load_signals(path)
        merged = merge_signals(existing, new_signals)
        save_signals(merged, path)
        logger.info(
            "Saved %d signals (%d new) to %s",
            len(merged),
            len(new_signals),
            path.relative_to(repo_root),
        )


if __name__ == "__main__":
    main()
