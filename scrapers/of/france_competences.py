"""
Scraper OF Phase 2 — France Compétences (RNCP / RS) via data.gouv.fr.

data.gouv.fr publie CHAQUE JOUR un export CSV du Répertoire National des
Certifications Professionnelles et du Répertoire Spécifique. On le télécharge,
on parse les fiches actives récentes (< 30j) et on les transforme en signaux OF.

Source officielle, gratuite, sans Apify.

Pour chaque fiche récente :
- compte = certificateur principal (= notre cible commerciale)
- signal_type = "rncp_open"
- vertical = "of"
- action commerciale = pitch ITS pour passation d'épreuves + traçabilité
"""

from __future__ import annotations

import csv
import io
import logging
import os
import sys
import zipfile
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.outreach import email_draft_rncp_nouveau, get_contacts_cibles  # noqa: E402

logger = logging.getLogger(__name__)

VERTICAL = "rncp"  # Vertical dédié : certificateurs qui déposent des fiches RNCP/RS
SOURCE_NAME = "France Compétences"
SOURCE_TIER = 1

DATAGOUV_DATASET_API = (
    "https://www.data.gouv.fr/api/1/datasets/"
    "repertoire-national-des-certifications-professionnelles-et-repertoire-specifique/"
)

# Fenêtre : on ne garde que les fiches dont la Date_Decision est dans les N derniers jours.
WINDOW_DAYS = 30
MAX_SIGNALS_PER_RUN = 50  # Garde-fou pour ne pas noyer le hub

# NSF (Nomenclature des Spécialités de Formation) cibles ITS/Tosa.
# On garde les domaines numériques + tertiaire commercial où Tosa est très pertinent.
NSF_CIBLES_PREFIXES = (
    "326",  # Informatique, traitement de l'information
    "320",  # Communication & information (large)
    "324",  # Secrétariat, bureautique
    "323",  # Techniques image et son
    "310",  # Spécialités plurivalentes de l'échange et de la gestion
    "311",  # Transport, manutention, magasinage
    "313",  # Finances, banque, assurance
    "314",  # Comptabilité, gestion
    "315",  # Ressources humaines, gestion du personnel
    "121",  # Géographie, sciences sociales
    "412",  # Développement des capacités d'orientation
    "415",  # Développement des capacités comportementales
    "999",  # Domaine disciplinaire (programmes sup)
)

# Types d'enregistrement les plus actionnables (OF commerciaux qui ont fait la démarche)
TYPES_PRIORITAIRES = (
    "Enregistrement sur demande",
)


# ─────────────────────────────────────────────────────────────────────────────
# Téléchargement + cache du ZIP du jour
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_latest_csv_resource_url() -> Optional[str]:
    """
    Interroge l'API data.gouv.fr et retourne l'URL du fichier export-fiches-csv le + récent.
    """
    try:
        r = requests.get(DATAGOUV_DATASET_API, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("[France Compétences] data.gouv.fr API failed: %s", e)
        return None

    # Chercher la 1re ressource dont le title contient "export-fiches-csv-"
    # ET dont la date est la plus récente (les ressources sont triées en général)
    candidates = []
    for r in data.get("resources", []):
        title = r.get("title", "")
        if "export-fiches-csv-" in title.lower():
            candidates.append((title, r.get("url"), r.get("last_modified", "")))
    if not candidates:
        return None
    # Sort par titre desc (le titre contient la date YYYY_MM_DD)
    candidates.sort(reverse=True)
    return candidates[0][1]


def _download_and_extract(url: str, cache_dir: Path) -> Optional[Path]:
    """Télécharge le ZIP, l'extrait, retourne le dossier d'extraction."""
    today = date.today().isoformat()
    zip_path = cache_dir / f"export-fiches-csv-{today}.zip"
    extract_dir = cache_dir / f"extracted-{today}"

    if extract_dir.exists() and any(extract_dir.iterdir()):
        logger.info("[France Compétences] cache hit (extracted %s)", extract_dir.name)
        return extract_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        logger.info("[France Compétences] download %s", url)
        r = requests.get(url, timeout=120, stream=True)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
        logger.info("[France Compétences] downloaded %d bytes", zip_path.stat().st_size)
    except Exception as e:
        logger.warning("[France Compétences] download failed: %s", e)
        return None

    extract_dir.mkdir(exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
    except Exception as e:
        logger.warning("[France Compétences] unzip failed: %s", e)
        return None

    return extract_dir


def _find_csv(extract_dir: Path, pattern: str) -> Optional[Path]:
    """Trouve un CSV dont le nom contient pattern (case-insensitive)."""
    for f in extract_dir.iterdir():
        if pattern.lower() in f.name.lower() and f.suffix.lower() == ".csv":
            return f
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Parsing des CSV
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date_fr(s: str) -> Optional[date]:
    """Parse 'DD/MM/YYYY' en date object. None si invalide."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def _load_standard(csv_path: Path, since: date) -> dict[str, dict]:
    """
    Charge les fiches actives dont Date_Decision >= since.
    Retourne un dict {Numero_Fiche: row_dict}.
    """
    out = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if (row.get("Actif") or "").strip().upper() != "ACTIVE":
                continue
            d = _parse_date_fr(row.get("Date_Decision", ""))
            if not d or d < since:
                continue
            num = (row.get("Numero_Fiche") or "").strip()
            if not num:
                continue
            out[num] = row
    return out


def _load_certificateurs(csv_path: Path) -> dict[str, list[str]]:
    """
    Charge le mapping {Numero_Fiche: [liste de certificateurs]}.

    Le CSV "Certificateurs" a en général colonnes :
      Numero_Fiche;Siret_Certificateur;Nom_Certificateur;...
    """
    out = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            num = (row.get("Numero_Fiche") or "").strip()
            nom = (row.get("Nom_Certificateur") or row.get("Certificateur") or "").strip()
            if not num or not nom:
                continue
            out.setdefault(num, []).append(nom)
    return out


def _load_nsf(csv_path: Path) -> dict[str, list[str]]:
    """Mapping {Numero_Fiche: [codes NSF]} pour filtrer par domaine."""
    out = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            num = (row.get("Numero_Fiche") or "").strip()
            code = (row.get("Code_Nsf") or row.get("Nsf_Code") or "").strip()
            if not num or not code:
                continue
            out.setdefault(num, []).append(code)
    return out


def _is_nsf_cible(nsf_codes: list[str]) -> bool:
    """Vrai si au moins un code NSF est dans les domaines cibles ITS/Tosa."""
    if not nsf_codes:
        return True  # pas d'info NSF = on garde (on filtre en aval par autre logique)
    for code in nsf_codes:
        for prefix in NSF_CIBLES_PREFIXES:
            if code.startswith(prefix):
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Main scrape
# ─────────────────────────────────────────────────────────────────────────────

def scrape() -> list[Signal]:
    today_iso = datetime.utcnow().date().isoformat()
    today_date = date.today()
    since = today_date - timedelta(days=WINDOW_DAYS)

    repo_root = Path(__file__).resolve().parents[2]
    cache_dir = repo_root / "data" / "cache" / "france_competences"

    # 1. URL la plus récente
    url = _fetch_latest_csv_resource_url()
    if not url:
        logger.warning("[France Compétences] no CSV resource URL — skip")
        return []

    # 2. Download + extract
    extract_dir = _download_and_extract(url, cache_dir)
    if not extract_dir:
        return []

    # 3. Trouver les 3 CSV qu'on utilise
    f_standard = _find_csv(extract_dir, "Standard")
    f_certif = _find_csv(extract_dir, "Certificateurs")
    f_nsf = _find_csv(extract_dir, "Nsf")
    if not f_standard or not f_certif:
        logger.warning("[France Compétences] CSV Standard ou Certificateurs introuvable dans %s", extract_dir)
        return []

    # 4. Charger les fiches actives récentes
    fiches = _load_standard(f_standard, since)
    logger.info("[France Compétences] %d fiches actives Date_Decision >= %s", len(fiches), since)
    if not fiches:
        return []

    certificateurs = _load_certificateurs(f_certif)
    nsf_map = _load_nsf(f_nsf) if f_nsf else {}

    # 5. Construire les signaux
    signals = []
    for num, row in fiches.items():
        # Type d'enregistrement prioritaire
        type_enreg = (row.get("Type_Enregistrement") or "").strip()
        if TYPES_PRIORITAIRES and type_enreg not in TYPES_PRIORITAIRES:
            continue

        # NSF dans domaines cibles ?
        nsf_codes = nsf_map.get(num, [])
        if not _is_nsf_cible(nsf_codes):
            continue

        # Compte = 1er certificateur (souvent il y en a plusieurs, on prend le 1er)
        cert_list = certificateurs.get(num, [])
        if not cert_list:
            continue
        compte = cert_list[0]

        intitule = (row.get("Intitule") or "").strip()
        abrege = (row.get("Abrege_Libelle") or "").strip()
        niveau = (row.get("Nomenclature_Europe_Intitule") or "").strip()
        date_dec = _parse_date_fr(row.get("Date_Decision", ""))

        titre = f"Nouvelle fiche {num} — {intitule[:120]}"
        url_fiche = f"https://www.francecompetences.fr/recherche/{'rs' if num.startswith('RS') else 'rncp'}/{num.replace('RNCP', '').replace('RS', '')}/"

        # Score : on prend les fiches sup (niveau 6/7) plus haut
        score = 75
        if "6" in niveau or "7" in niveau:
            score = 82
        tier = determine_tier(score)

        # Description riche pour le mail
        description = (
            f"{intitule}. Type : {abrege} ({niveau}). "
            f"{type_enreg}. Décision du {date_dec.isoformat() if date_dec else '?'}. "
            f"Certificateur(s) : {', '.join(cert_list[:3])}"
            f"{' …' if len(cert_list) > 3 else ''}."
        )

        signal_type = "rncp_open"
        email_dr = email_draft_rncp_nouveau(
            compte=compte,
            signal_text=intitule,
            url_source=url_fiche,
            contact_nom=None,
            contact_fonction=None,
        )
        contacts = get_contacts_cibles("rncp_open", compte)  # personas dédiés au certificateur

        action_reco = (
            f"📋 **Signal détecté**\n"
            f"Nouvelle fiche {num} déposée le "
            f"{date_dec.strftime('%d/%m/%Y') if date_dec else '?'} — {intitule}\n"
            f"\n"
            f"🎯 **Action à mener**\n"
            f"Email à la direction certifications/RNCP du certificateur. "
            f"Proposer démo ITS sous 30j (avant que leur 1re session "
            f"d'examen soit organisée avec un outil concurrent).\n"
            f"\n"
            f"💡 **Angle pitch ITS**\n"
            f"Pour passer la 1re session de cette nouvelle fiche : "
            f"banque de questions par bloc de compétences, proctoring, "
            f"attestations auto, traçabilité opposable en audit France "
            f"Compétences. Déploiement en 4-6 semaines.\n"
            f"\n"
            f"📅 **Timing**\n"
            f"30 jours après la décision = phase de montage de la 1re "
            f"session. C'est le moment d'arriver."
        )

        sig = Signal(
            id=fingerprint(titre, compte, date_dec.isoformat() if date_dec else today_iso),
            date_capture=today_iso,
            vertical=VERTICAL,
            sous_segment=f"Nouvelle fiche {abrege} {niveau}".strip(),
            compte=compte[:200],
            titre=titre[:200],
            description=description[:400],
            source=SOURCE_NAME,
            source_tier=SOURCE_TIER,
            url=url_fiche,
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner="Charles",
            action_reco=action_reco,
            deadline_action=None,
            status="new",
            date_publication=date_dec.isoformat() if date_dec else today_iso,
            email_draft=email_dr,
            contacts_cibles=contacts,
        )
        signals.append(sig)
        logger.info(
            "[France Compétences] [rncp_open/%d] %s — %s (%s)",
            score, compte[:30], num, intitule[:50],
        )

    # 6. Tri par date desc + cap MAX_SIGNALS_PER_RUN
    signals.sort(key=lambda s: s.date_publication or "", reverse=True)
    if len(signals) > MAX_SIGNALS_PER_RUN:
        logger.info("[France Compétences] cap : %d → %d signaux", len(signals), MAX_SIGNALS_PER_RUN)
        signals = signals[:MAX_SIGNALS_PER_RUN]

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sigs = scrape()
    logger.info("=== %d signaux France Compétences captés ===", len(sigs))


if __name__ == "__main__":
    main()
