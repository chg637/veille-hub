"""
Scraper presse enseignement supérieur — multi-feeds RSS Tier 1.

Couvre la white-list presse sup du radar hebdo (hors AEF/NewsTank, paywall) :
- L'Étudiant Educpros (éditorial dense, bon volume)
- Monde des Grandes Écoles
- Planète Grandes Écoles
- Business Cool

Campus Matin : pas de flux RSS public détecté (testé /rss, /feed, /site/rss.xml
le 10 juin 2026) — à brancher si un flux apparaît.

Même logique que cge.py : classification par mots-clés → signal_type de la
white-list achat, puis is_purchase_signal() écarte le bruit éditorial en aval.
Spécificité : détection des programmes IA (fenêtre Cert IA Tosa sept 2026) via
le sous_segment "programme-ia" pour que Charles repère les candidates waitlist.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, merge_signals, save_signals, load_signals, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_regex, extract_compte, is_editorial_noise  # noqa: E402
import re  # noqa: E402
from scrapers.lib.outreach import email_draft_for_education, get_contacts_cibles, format_action_education  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "education"

# (nom source, url RSS, source_tier, fenêtre jours, stop-words spécifiques)
FEEDS = [
    ("Educpros (L'Étudiant)", "https://www.letudiant.fr/educpros/rss.xml", 1, 14, {"Classement", "Palmarès"}),
    ("Monde des Grandes Écoles", "https://www.mondedesgrandesecoles.fr/feed/", 2, 14, {"Recruter", "Réussir"}),
    ("Planète Grandes Écoles", "https://www.planetegrandesecoles.com/feed", 2, 14, {"Classement", "Salaire"}),
    ("Business Cool", "https://business-cool.com/feed/", 2, 14, {"Classement", "Salaire", "Admissibles"}),
]

# Patterns word-boundary (matches_regex) — un substring naïf matche "ouvre" dans
# "Découvrez" ou "lance" dans "relance", d'où les regex.
PATTERNS_ACCREDITATION = [r"\baacsb\b", r"\bequis\b", r"\bamba\b", r"accrédit", r"labellis", r"grade de (?:licence|master)"]
PATTERNS_NOMINATION = [r"\bnomm[ée]e?\b", r"\bnomination\b", r"nouveau directeur", r"nouvelle directrice",
                       r"nouveau doyen", r"nouvelle doyenne", r"prend la (?:direction|tête)", r"à la tête d",
                       r"nouveau président", r"nouvelle présidente"]
PATTERNS_NOUVELLE_FORMATION = [r"\blance(?:nt)?\b", r"\binaugure(?:nt)?\b", r"\bouvre(?:nt|ra)?\b", r"\bouverture d",
                               r"nouveau (?:programme|master|msc|bachelor|campus|cursus|diplôme)",
                               r"nouvelle (?:formation|école|filière|chaire)", r"rentrée 202[6-8]",
                               r"crée (?:un|une|son|sa)"]
PATTERNS_FUSION = [r"fusionn", r"\bfusion\b", r"rapprochement", r"\babsorbe\b"]
PATTERNS_IA = [r"intelligence artificielle", r"\bia\b", r"ia générative", r"\bllm\b", r"data science", r"chaire ia", r"institut ia"]

# Bruit éditorial spécifique presse grandes écoles (admissions, classements, sponsorisé)
SKIP_PATTERNS = [r"^Découvrez", r"^Éclairez", r"admissibilité", r"\badmissibles\b", r"\bclassement", r"\bpalmarès",
                 r"^Filières\b", r"résultats d", r"contenu partenaire", r"sponsoris", r"^Retour sur", r"\boraux\b",
                 r"\bsalaires?\b", r"^Que (?:faire|valent)", r"^Combien", r"témoignage"]

VERBE_SPLIT = (r"\s+(?:lance(?:nt)?|inaugure(?:nt)?|ouvre(?:nt|ra)?|annonce(?:nt)?|nomme(?:nt)?|signe(?:nt)?|"
               r"crée(?:nt)?|obtient|décroche|fusionne(?:nt)?|absorbe|rejoint|dévoile(?:nt)?)\b")
CONNECTEURS = {"of", "de", "des", "du", "la", "le", "et", "d'", "l'"}


def _extract_compte_edu(title: str, extra_stops: set) -> str:
    """
    Le helper lib rate les noms avec connecteurs ("Rennes School of Business
    lance…" → "Business"). Ici : on coupe au verbe d'action et on garde tout le
    membre gauche, connecteurs inclus, en élaguant les mots-outils en tête.
    """
    m = re.search(VERBE_SPLIT, title, re.IGNORECASE)
    if m:
        left = title[: m.start()].strip().strip("«»\"'’ :,–—-")
        # Si une virgule/deux-points segmente, garder le dernier membre (le sujet)
        for sep in (":", ","):
            if sep in left:
                left = left.split(sep)[-1].strip()
        words = left.split()
        while words and (words[0].lower() in CONNECTEURS or words[0] in extra_stops or not words[0][0].isupper()):
            words.pop(0)
        cand = " ".join(words).strip()
        if 3 <= len(cand) <= 60 and any(w[0].isupper() for w in cand.split()):
            return cand
    # Pattern "… de/d'<École>" ("les nouveautés d'Audencia en 2026") — on prend
    # la DERNIÈRE occurrence du titre (le sujet est en général en fin de tournure)
    matches = re.findall(r"(?:\bde\s+|\bd['’]\s*)([A-Z][\w&\-\.]+(?:\s+[A-Z][\w&\-\.]+){0,3})", title)
    if matches:
        return matches[-1].strip()
    return extract_compte(title, custom_stops=extra_stops)


def _classify(title: str, description: str) -> tuple[str, str]:
    """Retourne (signal_type, sous_segment)."""
    if is_editorial_noise(title) or matches_regex(title, SKIP_PATTERNS):
        return ("autre", "Bruit éditorial")
    text = f"{title} {description}"

    is_ia = matches_regex(text, PATTERNS_IA)
    sous_segment = "programme-ia" if is_ia else "grande-ecole"

    if matches_regex(text, PATTERNS_ACCREDITATION):
        return ("accreditation", sous_segment)
    if matches_regex(text, PATTERNS_NOMINATION):
        return ("nomination_dg", sous_segment)
    if matches_regex(text, PATTERNS_FUSION):
        return ("fusion_ecole", sous_segment)
    if matches_regex(title, PATTERNS_NOUVELLE_FORMATION):
        # On exige le verbe de lancement dans le TITRE (pas seulement la desc),
        # sinon chaque article qui mentionne "rentrée 2026" en passant remonte.
        return ("nouvelle_formation", sous_segment)
    return ("autre", sous_segment)


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    signals: list[Signal] = []

    for source_name, url, source_tier, max_age, extra_stops in FEEDS:
        try:
            items = fetch_rss(url, limit=40)
        except Exception as e:
            logger.warning("[%s] fetch RSS KO (%s) — feed skippé", source_name, e)
            continue
        if not items:
            logger.warning("[%s] 0 item — feed vide ou indisponible", source_name)
            continue

        for item in items:
            if not is_recent(item["date_iso"], max_age_days=max_age):
                continue
            title = item["title"]
            description = item["description"]
            signal_type, sous_segment = _classify(title, description)
            compte = _extract_compte_edu(title, extra_stops)
            score = base_score(signal_type, source_tier=source_tier)
            tier = determine_tier(score)
            action_info = generate_action(signal_type, VERTICAL, compte=compte)

            email_dr = email_draft_for_education(
                signal_type=signal_type,
                compte=compte,
                signal_text=description,
                url_source=item["link"],
            )
            contacts = get_contacts_cibles(signal_type, compte)
            structured_action = format_action_education(
                signal_type=signal_type,
                signal_text=description,
                action_custom=action_info["action"],
            )

            sig = Signal(
                id=fingerprint(title, compte, item["date_iso"]),
                date_capture=today,
                vertical=VERTICAL,
                sous_segment=sous_segment,
                compte=compte,
                titre=title[:200],
                description=description,
                source=source_name,
                source_tier=source_tier,
                url=item["link"],
                signal_type=signal_type,
                tier=tier,
                score=score,
                produit_match=produit_match_for(signal_type, VERTICAL),
                owner=None,
                action_reco=structured_action,
                deadline_action=action_info["deadline_action"],
                status="new",
                date_publication=item["date_iso"],
                email_draft=email_dr,
                contacts_cibles=contacts,
            )
            signals.append(sig)
            logger.info("[%s] [%s/%s] [pub=%s] %s", source_name, VERTICAL, signal_type, item["date_iso"], title[:70])

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "data" / VERTICAL / "signals.json"

    new = scrape()
    existing = load_signals(path)
    merged = merge_signals(existing, new)
    save_signals(merged, path)
    logger.info("Saved %d signals total (+%d new) to %s", len(merged), len(new), path.relative_to(repo_root))


if __name__ == "__main__":
    main()
