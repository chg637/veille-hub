"""
Schema commun pour tous les signaux du Hub Veille Marché Isograd.

Un signal = une opportunité commerciale détectée par un scraper sur une source.
La taxonomie est unifiée pour permettre l'agrégation cross-verticaux dans le hub.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


# Verticaux supportés
VERTICAUX = ("education", "of", "rncp", "corporate", "ao")

# Types de signaux normalisés (utilisé pour filtrage et scoring)
SIGNAL_TYPES = (
    # Education
    "accreditation", "nouvelle_formation", "nomination_dg", "fusion_ecole",
    "rncp_nouveau",
    # OF
    "levee_edtech", "rncp_open", "qualiopi", "concurrent_news",
    # Corporate
    "nomination_chro", "levee_fonds", "plan_ia", "plan_recrutement",
    "top_employer", "transformation_digitale",
    # AO (appels d'offres)
    "ao_publie", "ao_pre_info", "ao_attribue", "ao_modificatif", "rncp_open_ao",
    "opco_ao",
    # Transverse
    "autre",
)

# Tiers de signal
TIER_1 = 1  # Action sous 7 jours
TIER_2 = 2  # Action sous 30 jours
TIER_3 = 3  # Surveillance / nurturing


# Fenêtre de fraîcheur par défaut (en jours)
# Au-delà, un article RSS est considéré comme dépassé et écarté du flux.
DEFAULT_MAX_AGE_DAYS = 14


def is_recent(date_iso: Optional[str], max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> bool:
    """Vrai si la date donnée (YYYY-MM-DD) est dans la fenêtre des X derniers jours."""
    if not date_iso:
        return True  # pas de date = on garde (mieux vaut un signal sans date qu'un signal raté)
    try:
        d = datetime.strptime(date_iso, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return (date.today() - d).days <= max_age_days


# ─────────────────────────────────────────────────────────────────────────
# Définition d'un signal d'achat Isograd
# ─────────────────────────────────────────────────────────────────────────

# Signal types qui sont des signaux d'achat reconnus.
# Tout ce qui n'est pas dans cette liste blanche est considéré comme du bruit
# éditorial (tribune, analyse, revue hebdo, séminaire) et écarté.
PURCHASE_SIGNAL_TYPES = {
    # Education — fenêtre d'opportunité claire
    "accreditation",
    "nouvelle_formation",
    "nomination_dg",
    "fusion_ecole",
    "rncp_nouveau",
    # OF
    "levee_edtech",
    "rncp_open",
    "qualiopi",
    "concurrent_news",
    "opco_ao",
    # Corporate — déclencheur d'achat ITS / Tosa Corporate
    "nomination_chro",
    "levee_fonds",
    "plan_ia",
    "plan_recrutement",
    "top_employer",
    "transformation_digitale",
    # AO
    "ao_publie",
    "ao_pre_info",
    "ao_modificatif",
    "rncp_open_ao",
}

# Comptes "poubelle" qui apparaissent à cause de faux positifs d'extraction.
# Si un signal a l'un de ces noms comme compte, on l'écarte.
BLACKLIST_COMPTES = {
    "Inconnu",
    "Royaume-Uni",
    "Éric",
    "Eric",
    "Cap",
    "Les",
    "Dans",
    "Comment",
    "Avec",
    "Chez",
    "Passée",
    "Passé",
    "Tribune",
    "Webinaire",
    "Décisions",
    "France",  # trop générique ; les vraies institutions seront "France Universités", etc.
    "Territoires",
    "Établissement non identifié",
}


def is_purchase_signal(signal: "Signal") -> tuple[bool, str]:
    """
    Vrai si le signal est un vrai signal d'achat (3 critères cumulatifs).

    Retourne (ok, raison_si_ko) — pratique pour le logging.
    """
    # 1. Type de signal dans la liste blanche
    if signal.signal_type not in PURCHASE_SIGNAL_TYPES:
        return False, f"signal_type='{signal.signal_type}' hors liste blanche"

    # 2. Compte identifiable
    compte = (signal.compte or "").strip()
    if not compte or len(compte) < 3:
        return False, f"compte vide ou trop court ('{compte}')"
    if compte in BLACKLIST_COMPTES:
        return False, f"compte blacklisté ('{compte}')"

    # 3. Produit Isograd matchable
    if not signal.produit_match:
        return False, "aucun produit Isograd matché"

    return True, "ok"


@dataclass
class Signal:
    """Un signal d'opportunité commerciale détecté par un scraper."""

    # Identité
    id: str  # généré par fingerprint
    date_capture: str  # ISO date YYYY-MM-DD — quand le scraper a vu le signal
    vertical: str  # "education" | "of" | "corporate" | "ao"
    sous_segment: str  # ex. "universite-grande-ecole", "ESN", "ETI-tech"

    # Compte
    compte: str  # nom de l'entreprise / établissement
    titre: str  # titre du signal (max 200 chars)
    description: str  # contexte court (1-3 phrases)

    # Source
    source: str  # nom court de la source ("AEF", "Maddyness", "TED"...)
    source_tier: int  # 1, 2, 3
    url: str  # URL canonique du signal

    # Type & scoring
    signal_type: str  # un des SIGNAL_TYPES
    tier: int  # 1, 2, 3 (priorité opérationnelle)
    score: int  # 0-100, calculé par scoring.py

    # Action recommandée
    produit_match: list = field(default_factory=list)  # ["Tosa", "ITS", "ILP", "Cert IA"]
    owner: Optional[str] = None  # commercial assigné
    action_reco: Optional[str] = None  # action à mener
    deadline_action: Optional[str] = None  # ISO date

    # Statut
    status: str = "new"  # "new" | "in_review" | "actioned" | "dismissed"

    # Date de publication réelle (de l'article / de l'AO), distincte de date_capture.
    # Optionnelle : si None ou absente, le frontend utilise date_capture en fallback.
    date_publication: Optional[str] = None  # ISO date YYYY-MM-DD

    # Email drafté pour outreach commercial (subject + body en plain text).
    # Le commercial peut le copier dans Gmail/Outlook et l'envoyer après ajustement.
    email_draft: Optional[dict] = None  # {"subject": "...", "body": "..."}

    # Contacts cibles : liste de typologies de poste à contacter (avec URL Sales Nav préfilled
    # quand on connaît le nom du compte). Sans nom de personne pour l'instant — futur sprint A3 LinkedIn.
    # Format : [{"poste": "Head of TA", "priorite": 1, "sales_nav_url": "https://...", "raison": "..."}]
    contacts_cibles: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def slugify(text: str) -> str:
    """Normalise une chaîne pour fingerprinting (lowercase, sans accents, alphanum + tirets)."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:80]


def fingerprint(titre: str, compte: str, date_iso: str) -> str:
    """
    Génère un ID stable basé sur (titre slugifié, compte, date jour).

    Permet de dédupliquer un même signal repris par plusieurs sources.
    Deux signaux avec même titre + même compte + même jour ont le même fingerprint.
    """
    base = f"{slugify(titre)}|{slugify(compte)}|{date_iso}"
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
    vertical_prefix = ""  # à enrichir par l'appelant si besoin
    return f"sig-{date_iso}-{h}"


def load_signals(path: Path) -> list[Signal]:
    """Charge les signaux existants depuis un fichier JSON. Tolère fichier vide/inexistant."""
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    data = json.loads(raw)
    return [Signal(**item) for item in data]


def save_signals(signals: list[Signal], path: Path) -> None:
    """Sauvegarde les signaux dans un fichier JSON (sorted by score desc, then date desc)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sorted_signals = sorted(signals, key=lambda s: (-s.score, s.date_capture), reverse=False)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            [s.to_dict() for s in sorted_signals],
            f,
            ensure_ascii=False,
            indent=2,
        )


def merge_signals(existing: list[Signal], new: list[Signal]) -> list[Signal]:
    """
    Fusionne deux listes de signaux en dédupliquant par fingerprint.

    Règle : si même id, on garde celui avec le source_tier le plus fort (= chiffre le plus petit).
    En cas d'égalité, on garde le plus récent.
    """
    by_id: dict[str, Signal] = {s.id: s for s in existing}
    for s in new:
        if s.id not in by_id:
            by_id[s.id] = s
        else:
            current = by_id[s.id]
            # Plus fort tier (chiffre plus petit) gagne
            if s.source_tier < current.source_tier:
                by_id[s.id] = s
            elif s.source_tier == current.source_tier:
                if s.date_capture > current.date_capture:
                    by_id[s.id] = s
    return list(by_id.values())
