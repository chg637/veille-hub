"""
Scraper OF — presse spécialisée formation professionnelle (RSS).

Le volet OF était vide depuis l'origine. Tentative Google News abandonnée
(« centre de formation » en presse FR = football à 80 %). Sources dédiées :

- Centre Inffo (centre-inffo.fr) — institutionnel formation pro, Tier 1.
- Digiformag (digiformag.com) — magazine des organismes de formation, Tier 2.

Signaux captés :
- levee_edtech : levée / rachat / consolidation d'OF ou EdTech → structuration
  = fenêtre pour standardiser l'évaluation (catalogue Tosa revendeur, ITS).
- of_nouvelle_offre : un acteur lance une offre certification / bureautique /
  compétences numériques / IA → revendeur Tosa potentiel ou client ITS.
- qualiopi : actualité certification qualité → signal de contexte (froid).
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_regex, extract_compte, is_editorial_noise  # noqa: E402
from scrapers.lib.outreach import get_contacts_cibles  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "of"

FEEDS = [
    ("Centre Inffo", "https://www.centre-inffo.fr/feed", 1, 21),
    ("Digiformag", "https://www.digiformag.com/feed/", 2, 21),
]

PATTERNS_LEVEE = [r"\blève\b", r"levée de fonds", r"\brachète\b", r"\brachat\b",
                  r"\bacquisition\b", r"\bacquiert\b", r"\bfusionne", r"\bcède\b"]
PATTERNS_OFFRE = [r"\blance(?:nt)?\b", r"\bdévoile(?:nt)?\b", r"\bouvre(?:nt)?\b",
                  r"\bcrée(?:nt)?\b", r"\bdéploie(?:nt)?\b", r"nouvelle (?:offre|certification|plateforme)"]
KW_OFFRE_SUJET = [r"certif", r"bureautique", r"compétences numériques", r"\bIA\b",
                  r"intelligence artificielle", r"\bCPF\b", r"digital", r"e-learning", r"évaluation"]
PATTERNS_QUALIOPI = [r"\bqualiopi\b"]

# Bruit : dossiers réglementaires, tribunes, agenda
SKIP_PATTERNS = [r"^comment\b", r"^pourquoi\b", r"^que (?:faire|retenir)", r"\bwebinaire\b",
                 r"\bagenda\b", r"\bdécret\b", r"\bjurisprudence\b", r"^les limites\b",
                 r"\bmode d['’]emploi\b", r"\bguide\b", r"\binfographie\b"]


def _classify(title: str) -> str:
    if is_editorial_noise(title) or matches_regex(title, SKIP_PATTERNS):
        return "autre"
    if matches_regex(title, PATTERNS_LEVEE):
        return "levee_edtech"
    if matches_regex(title, PATTERNS_QUALIOPI):
        return "qualiopi"
    if matches_regex(title, PATTERNS_OFFRE) and matches_regex(title, KW_OFFRE_SUJET):
        return "of_nouvelle_offre"
    return "autre"


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    signals: list[Signal] = []

    for source_name, url, source_tier, max_age in FEEDS:
        try:
            items = fetch_rss(url, limit=30)
        except Exception as e:
            logger.warning("[%s] fetch KO : %s", source_name, e)
            continue

        for item in items:
            if not is_recent(item["date_iso"], max_age_days=max_age):
                continue
            title = item["title"]
            signal_type = _classify(title)
            if signal_type == "autre":
                continue
            compte = extract_compte(title)
            if not compte or len(compte) < 3:
                continue

            score = base_score(signal_type, source_tier=source_tier)
            tier = determine_tier(score)
            actions = {
                "levee_edtech": f"{compte} : consolidation/levée. Fenêtre pour standardiser l'évaluation — catalogue Tosa revendeur ou ITS white-label. Cibler direction générale/pédagogique.",
                "of_nouvelle_offre": f"{compte} lance une offre digitale : pitch revendeur Tosa (certification en aval) ou ITS (hébergement examens).",
                "qualiopi": f"{compte} : actualité Qualiopi — angle « preuve de qualité d'évaluation » avec Tosa/ITS en appui du référentiel.",
            }

            signals.append(Signal(
                id=fingerprint(title, compte, item["date_iso"]),
                date_capture=today,
                vertical=VERTICAL,
                sous_segment="organisme-formation",
                compte=compte,
                titre=title[:200],
                description=item["description"][:400] or title,
                source=source_name,
                source_tier=source_tier,
                url=item["link"],
                signal_type=signal_type,
                tier=tier,
                score=score,
                produit_match=produit_match_for(signal_type, VERTICAL),
                owner=None,
                action_reco=actions[signal_type],
                deadline_action=None,
                status="new",
                date_publication=item["date_iso"],
                email_draft=None,
                contacts_cibles=get_contacts_cibles(signal_type, compte),
            ))
            logger.info("[%s] [%s] %s · %s", source_name, signal_type, compte[:25], title[:60])
    return signals
