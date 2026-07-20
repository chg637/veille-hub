"""
Scraper Corporate — Google News RSS, signaux d'achat ITS.

Couvre les 3 signaux corporate les mieux scorés, introuvables dans les feeds
RH classiques (myRHline/Parlons RH = éditorial) :

1. nomination_chro (85) — nominations DRH / CHRO / DRH groupe.
   Fenêtre prise de poste ~30j : le nouveau DRH revoit ses outils d'évaluation.
2. plan_recrutement (88) — plans d'embauche massifs (seuil 50 postes dans le titre).
   Volume = besoin d'industrialiser la pré-qualification candidats → ITS.
3. plan_ia (80) — plans de formation IA des collaborateurs.
   Besoin de mesurer un socle de compétences → Cert IA / Tosa + ITS.

Google News agrège Les Échos, Usine Digitale, presse régionale, presse métier —
recall très supérieur aux feeds RH unitaires. Titres au format "Titre - Source" :
on extrait la vraie source pour le champ `source`.
"""

from __future__ import annotations

import logging
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, is_recent  # noqa: E402
from scrapers.lib.scoring import base_score, determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.rss_helpers import fetch_rss, matches_regex, extract_compte, is_editorial_noise  # noqa: E402
from scrapers.lib.outreach import email_draft_nomination, get_contacts_cibles  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "corporate"
SOURCE_TIER = 2  # presse via agrégateur — à croiser avant outreach


def _gnews_url(query: str) -> str:
    return ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
            + "&hl=fr&gl=FR&ceid=FR:fr")


# (signal_type, query, fenêtre jours, max items)
# `when:Nd` force Google News à ne retourner que les N derniers jours — sans lui,
# le flux est trié par pertinence et gaspille le cap d'items sur de l'ancien.
QUERIES = [
    ("nomination_chro",
     '("nommé DRH" OR "nommée DRH" OR "nouveau DRH" OR "nouvelle DRH" OR '
     '"nommé directeur des ressources humaines" OR "nommée directrice des ressources humaines") when:21d',
     21, 60),
    ("plan_recrutement",
     '("va recruter" OR "plan de recrutement" OR "prévoit de recruter" OR "compte recruter") when:30d',
     30, 60),
    ("plan_ia",
     '("former" "intelligence artificielle" salariés OR collaborateurs) when:45d',
     45, 40),
]

# Bruit hors-cible : sport, sécurité publique/armées (recrutent en masse mais
# hors ICP ITS corporate — le public passe par les AO), politique.
NEGATIVE_PATTERNS = [
    r"\bmercato\b", r"\bjoueur", r"\bfootball\b", r"\brugby\b", r"\bclub\b",
    r"\bpoliciers?\b", r"\bsapeurs?-pompiers?\b", r"\bmilitaires?\b", r"\bsoldats?\b",
    r"\bfonctionnaires?\b", r"\benseignants?\b", r"\bmagistrats?\b",
    r"\b(?:Manchester|Liverpool|Chelsea|Arsenal|Real Madrid|Barcelone|PSG|Marseille|OM|OL)\b",
    r"\battaquant\b", r"\bdéfenseur\b", r"\bmilieu de terrain\b", r"\bgardien de but\b",
    r"\btransfert\b", r"\bligue \d\b",
    r"\barmée\b", r"\bgendarmerie\b", r"\bpolice\b", r"\bmilitaire",
    r"\bministre\b", r"\bélection", r"\bsyndicat\b",
    r"qui recrutent\b",          # listicles "ces entreprises qui recrutent"
    r"^comment\b", r"^pourquoi\b",
]

# Mots-outils en tête de nom d'entreprise (+ tournures temporelles "En 2026, …")
LEADING_NOISE = re.compile(
    r"^(?:en\s+\d{4}\s*,?\s*)?"
    r"(?:(?:le groupe|la société|l['’]entreprise|l['’]enseigne|la start-?up|la scale-?up|le|la|les|l['’])\s+)?"
    r"(?:(?:française?|indienne?|américaine?|allemande?|britannique|espagnole?|italienne?|"
    r"chinoise?|japonaise?|suisse|belge|néerlandaise?)\s+)?", re.IGNORECASE)

# Comptes hors-cible corporate : public et éducation (couverts par les volets
# education et AO), collectivités. On ne veut que des entreprises privées.
COMPANY_REJECT = re.compile(
    r"universit|école|ecole|institut|académie|lycée|minist|région|département|"
    r"ville de|mairie|métropole|agglomération|CHU|hôpital|hopital|préfecture",
    re.IGNORECASE)


def _split_gnews_title(raw_title: str) -> tuple[str, str]:
    """'Titre de l'article - Le Figaro' → ('Titre de l'article', 'Le Figaro')."""
    if " - " in raw_title:
        title, _, src = raw_title.rpartition(" - ")
        if 0 < len(src) <= 40:
            return title.strip(), src.strip()
    return raw_title.strip(), "Google News"


def _clean_company(cand: str) -> str:
    cand = re.sub(r"^en\s+\d{4}\s*,?\s*", "", cand.strip(), flags=re.IGNORECASE)
    cand = LEADING_NOISE.sub("", cand.strip("«»\"'’ ,;:–—-"))
    cand = re.sub(r"\s*\(.*?\)\s*$", "", cand)  # "(976)" etc.
    cand = cand.strip()
    if len(cand) > 40 or COMPANY_REJECT.search(cand):
        return ""
    return cand


def _extract_nomination(title: str) -> tuple[str, str]:
    """Retourne (compte, personne) pour un titre de nomination."""
    # "Aline Chevalier, nouvelle DRH de Kerria AM"
    m = re.search(
        r"(?:DRH|CHRO|directeur(?:trice)? des ressources humaines)\s+(?:de|du|des|chez|d['’])\s*(.+)$",
        title, re.IGNORECASE)
    compte = _clean_company(m.group(1)) if m else ""
    # "X nomme Aline Chevalier DRH"
    if not compte:
        m2 = re.search(r"^(.{3,40}?)\s+(?:nomme|recrute|accueille|promeut)\b", title, re.IGNORECASE)
        if m2:
            compte = _clean_company(m2.group(1))
    pers = re.match(r"^([A-ZÉÈ][\w'’\-]+(?:\s+[A-ZÉÈ][\w'’\-]+){1,2})\s*,", title)
    personne = pers.group(1) if pers else ""
    return compte, personne


def _extract_plan_recrutement(title: str) -> tuple[str, int]:
    """Retourne (compte, volume). Volume requis ≥ 50 pour rester un signal ITS."""
    m = re.search(r"^(.{3,45}?)\s+(?:va recruter|recrutera|prévoit de recruter|compte recruter|veut recruter|recrute)\b",
                  title, re.IGNORECASE)
    compte = _clean_company(m.group(1)) if m else ""
    vol = 0
    # Le nombre ne doit PAS être un montant ("51 millions d'euros") ni un âge/%
    mv = re.search(r"(\d{1,3}(?:[\s.,]\d{3})+|\d{2,6})\s*"
                   r"(?:personnes|postes|salariés|collaborateurs|recrutements|embauches|CDI|"
                   r"talents|ingénieurs|techniciens|conseillers|experts|alternants)\b",
                   title, re.IGNORECASE)
    if mv:
        try:
            vol = int(re.sub(r"[\s.,]", "", mv.group(1)))
        except ValueError:
            vol = 0
    return compte, vol


# Un vrai plan de formation IA d'entreprise — pas une tribune sur l'IA au travail
PLAN_IA_GATE = re.compile(
    r"(?:va former|former ses|forme ses|pour former|formation de ses|"
    r"académie (?:IA|interne)|plan de formation|upskilling)", re.IGNORECASE)


def _extract_plan_ia(title: str) -> str:
    if not PLAN_IA_GATE.search(title):
        return ""
    m = re.search(r"^(.{3,45}?)\s+(?:rejoint|lance|veut former|va former|forme|annonce|déploie|investit|s['’]allie)\b",
                  title, re.IGNORECASE)
    return _clean_company(m.group(1)) if m else ""


def _generic_draft(signal_type: str, compte: str, titre: str, url: str) -> dict:
    if signal_type == "plan_recrutement":
        subject = f"{compte} — fiabiliser la pré-qualification de vos recrutements"
        body = (f"Bonjour,\n\nJ'ai lu que {compte} prépare une campagne de recrutement importante "
                f"({titre[:90]}…).\n\nIsograd Testing Services (ITS) permet d'évaluer objectivement les "
                "compétences (bureautique, data, tech, IA) des candidats en amont des entretiens — "
                "vos équipes TA gagnent du temps de screening et fiabilisent les shortlists.\n\n"
                "Seriez-vous disponible pour un échange de 20 minutes ?\n\nBien cordialement,\nCharles Gosset — Isograd")
    else:  # plan_ia
        subject = f"{compte} — mesurer le socle de compétences IA de vos équipes"
        body = (f"Bonjour,\n\nVotre initiative de formation à l'IA ({titre[:90]}…) m'a interpellé.\n\n"
                "Pour piloter ce type de programme, nos clients mesurent un socle de compétences avant/après "
                "(certification Tosa, plateforme ITS pour vos contenus propres). La Certification IA Tosa sort "
                "en septembre 2026 — programme partenaires de lancement en cours.\n\n"
                "Un échange de 20 minutes pour voir si cela peut soutenir votre déploiement ?\n\n"
                "Bien cordialement,\nCharles Gosset — Isograd")
    return {"subject": subject, "body": body, "url_source": url}


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    signals: list[Signal] = []
    seen_ids: set[str] = set()

    for signal_type, query, max_age, limit in QUERIES:
        try:
            items = fetch_rss(_gnews_url(query), limit=limit)
        except Exception as e:
            logger.warning("[GNews %s] fetch KO : %s", signal_type, e)
            continue

        kept = 0
        for item in items:
            if not is_recent(item["date_iso"], max_age_days=max_age):
                continue
            title, real_source = _split_gnews_title(item["title"])
            # Presse locale : "Isère. Maxi Zoo prévoit…" → strip le préfixe région
            title = re.sub(r"^[A-ZÉÈ][\w'’-]{2,20}(?:\s[A-ZÉÈ][\w'’-]{2,20})?\.\s+", "", title)
            if is_editorial_noise(title) or matches_regex(title, NEGATIVE_PATTERNS):
                continue

            personne = ""
            volume = 0
            if signal_type == "nomination_chro":
                compte, personne = _extract_nomination(title)
            elif signal_type == "plan_recrutement":
                compte, volume = _extract_plan_recrutement(title)
                if volume < 50:
                    continue  # petit volume = pas un cas ITS
            else:
                compte = _extract_plan_ia(title)

            if not compte or len(compte) < 3:
                continue

            dedup_key = f"{signal_type}|{compte.lower()}"
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)
            sig_id = fingerprint(title, compte, item["date_iso"])

            score = base_score(signal_type, source_tier=SOURCE_TIER)
            tier = determine_tier(score)

            if signal_type == "nomination_chro":
                email_dr = email_draft_nomination(personne or "la personne nommée", "DRH", compte, item["link"])
                action = (f"Fenêtre prise de poste ~30j : InMail/email à {personne or 'la nouvelle DRH'} "
                          f"({compte}) — angle outillage évaluation des compétences (ITS + Tosa).")
            elif signal_type == "plan_recrutement":
                email_dr = _generic_draft(signal_type, compte, title, item["link"])
                action = (f"{compte} : ~{volume} recrutements annoncés. Cibler Head of TA / DRH — "
                          "pitch ITS pré-qualification candidats à volume.")
            else:
                email_dr = _generic_draft(signal_type, compte, title, item["link"])
                action = (f"{compte} : plan de formation IA. Cibler Head of L&D / CDO — "
                          "pitch mesure de socle (Cert IA Tosa sept 2026, programme partenaires).")

            signals.append(Signal(
                id=sig_id,
                date_capture=today,
                vertical=VERTICAL,
                sous_segment="entreprise",
                compte=compte,
                titre=title[:200],
                description=item["description"][:400] or title,
                source=f"{real_source} (via Google News)",
                source_tier=SOURCE_TIER,
                url=item["link"],
                signal_type=signal_type,
                tier=tier,
                score=score,
                produit_match=produit_match_for(signal_type, VERTICAL),
                owner=None,
                action_reco=action,
                deadline_action=None,
                status="new",
                date_publication=item["date_iso"],
                email_draft=email_dr,
                contacts_cibles=get_contacts_cibles(signal_type, compte),
            ))
            kept += 1
            logger.info("[GNews %s] [%s] %s · %s", signal_type, item["date_iso"], compte[:28], title[:60])
        logger.info("[GNews %s] %d items → %d signaux", signal_type, len(items), kept)

    return signals
