"""
Fetch des AO depuis le dashboard live du Radar AO Isograd.

Le Radar AO existant (repo chg637/radar-ao-isograd) tourne en Node.js et publie
chaque jour son JSON consolidé (TED + BOAMP + Profils Tier-1) sur :
    https://radar-ao-isograd.vercel.app/data/latest.json

Ce module consomme ce JSON et le transforme en Signals du hub veille-isograd.
Pas de duplication de code Node.js : on consomme la sortie, on ajoute la mise
en forme commune aux 4 verticaux. Le scoring est celui du Radar AO.

Si le fetch échoue (réseau / dashboard down), on retombe sur les mocks.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scrapers.lib.schema import Signal, fingerprint, save_signals  # noqa: E402
from scrapers.lib.scoring import determine_tier, produit_match_for  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402


# Décideur cible par segment acheteur — guide commercial pour qui contacter
DECIDEUR_PAR_SEGMENT = {
    "ESR": "Direction des examens + VP Pédagogie + DSI (vérifier organigramme via site officiel + LinkedIn Sales Nav)",
    "Collectivités": "DRH + Direction Numérique + RAQ Qualiopi (rechercher CNFPT territorial si volet formation)",
    "Consulaire": "Direction de la formation + responsable certifications (réseau CCI / CMA national)",
    "FPH": "Direction des soins + ANFH territorial + Resp. Qualité (DPC concerné)",
    "État": "Direction du recrutement + RAQ + DSI + RGAA/RGPD officer",
    "Formation pro": "Direction des certifications + responsable Qualiopi + responsable RNCP",
    "OPCO": "Direction des certifications professionnelles + chargé(e) Qualiopi de la branche",
    "UE": "Bureau coopération + responsable évaluation pédagogique + Erasmus+ unit",
    "Autre": "À enrichir via LinkedIn Sales Nav + site officiel de l'acheteur",
}

# Valeur métier à pitcher selon le CPV — angle commercial différencié
def _valeur_metier_par_cpv(cpv: str) -> str:
    """Retourne l'angle commercial selon le CPV."""
    cpv = (cpv or "").strip()
    if cpv.startswith("79132"):
        return "Certification : standardisation des compétences, opposable en audit / accréditation"
    if cpv.startswith("72416"):
        return "SaaS : déploiement rapide, scalabilité, zéro infra à maintenir côté client"
    if cpv.startswith("48190"):
        return "Logiciel éducatif : intégration LMS existant, examens sécurisés, banque de questions"
    if cpv.startswith("72"):
        return "Plateforme : sécurité examens, RGPD, accessibilité RGAA"
    if cpv.startswith("805"):
        return "ATTENTION CPV formation — vérifier que le volet évaluation/certification est central, sinon écarter"
    if cpv.startswith("803"):
        return "Enseignement sup : examens dématérialisés, certification post-cursus, accréditation internationale"
    return "Standardisation + traçabilité + ROI mesurable + opposable audit"


# Concurrents à anticiper selon segment (battle card mentale)
def _concurrents_par_segment(segment: str) -> str:
    if segment in ("ESR", "Formation pro"):
        return "Concurrents probables : Pix (DigComp), Microsoft MOS, TOEIC/Cambridge, Adobe Certified, PCIE/ICDL"
    if segment in ("Collectivités", "État"):
        return "Concurrents : prestataires historiques territoriaux, CNFPT (offre interne), Adobe Connect"
    if segment in ("Consulaire", "OPCO"):
        return "Concurrents : Cegos, Demos, OpenClassrooms B2B, Adobe Certified Associate"
    if segment == "FPH":
        return "Concurrents : ANFH catalogue, INSEEC santé, plateformes hospitalières internes"
    return "Mapper les solutions existantes via questions de cadrage (Central Test, ATS interne, etc.)"


def _generate_ao_action(notice: dict, signal_type: str, segment: str) -> str:
    """Génère une action commerciale poussée pour un AO."""
    acheteur = (notice.get("acheteur") or "").strip()
    montant = notice.get("montant") or 0
    cpv = notice.get("cpv") or ""
    deadline = notice.get("deadline") or ""
    url = notice.get("url") or ""

    decideur = DECIDEUR_PAR_SEGMENT.get(segment, DECIDEUR_PAR_SEGMENT["Autre"])
    valeur = _valeur_metier_par_cpv(cpv)
    concurrents = _concurrents_par_segment(segment)

    # Volume estimé
    if montant and montant > 0:
        if montant >= 500:
            taille = f"💰 Montant estimé : {montant} k€ → enjeu fort, mobiliser direction commerciale"
        elif montant >= 100:
            taille = f"💰 Montant estimé : {montant} k€ → opportunité moyenne, traitement standard"
        else:
            taille = f"💰 Montant estimé : {montant} k€ → petit ticket, automatiser la candidature"
    else:
        taille = "💰 Montant : à estimer via le DCE (chercher la section budget prévisionnel)"

    # Urgence deadline
    urgence = ""
    if deadline:
        urgence = f"⏰ Deadline : {deadline} → calculer J-jours et caler les ressources dès maintenant."

    action = (
        f"📋 **Récupérer le DCE complet** sur {url}\n"
        f"🎯 **Décideur cible** : {decideur}\n"
        f"💡 **Angle de valeur** : {valeur}\n"
        f"{taille}\n"
        f"🥊 {concurrents}\n"
        f"{urgence}"
    )
    return action.strip()

logger = logging.getLogger(__name__)

# URL du JSON consolidé exposé par le dashboard Radar AO
RADAR_AO_JSON_URL = "https://radar-ao-isograd.vercel.app/data/latest.json"

SOURCE_NAME_RADAR = "Radar AO Isograd"
VERTICAL = "ao"

USER_AGENT = "IsogradVeilleHub/1.0 (+contact@isograd.com)"


def _map_signal_type(notice: dict) -> str:
    """
    Map le type d'AO du Radar AO vers les signal_types du hub.

    Le Radar AO ne classe pas explicitement, on déduit depuis :
    - nature BOAMP si disponible ("Avis de marché" → ao_publie, "Avis d'intention" → ao_pre_info)
    - sinon, ao_publie par défaut
    """
    boamp = notice.get("_boamp") or {}
    nature = (boamp.get("nature") or "").lower()
    if "intention" in nature or "périodique" in nature:
        return "ao_pre_info"
    if "rectificatif" in nature or "modificatif" in nature:
        return "ao_modificatif"
    return "ao_publie"


def _map_sous_segment(notice: dict) -> str:
    """
    Mapping du segment Radar AO vers un libellé lisible.
    """
    seg = notice.get("segment") or ""
    if seg == "Collectivités":
        return "Marché public Collectivité"
    if seg == "Consulaire":
        return "Marché public Consulaire (CCI/CMA)"
    if seg == "Autre":
        return "Marché public — secteur à qualifier"
    if seg == "Universités":
        return "Marché public Université"
    if seg == "OPCO":
        return "Marché public OPCO"
    return seg or "Marché public formation"


def _source_tier_for(source: str) -> int:
    """TED et BOAMP = sources officielles Tier 1. Profil scrappé = Tier 2."""
    if source in ("TED", "BOAMP"):
        return 1
    return 2


def _fetch_radar_ao_json() -> Optional[dict]:
    """Fetch le JSON consolidé du Radar AO. Retourne None en cas d'échec réseau."""
    logger.info("Fetching Radar AO JSON: %s", RADAR_AO_JSON_URL)
    try:
        r = requests.get(RADAR_AO_JSON_URL, headers={"User-Agent": USER_AGENT}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("Failed to fetch Radar AO JSON: %s", e)
        return None


def scrape() -> list[Signal]:
    today = datetime.utcnow().date().isoformat()
    payload = _fetch_radar_ao_json()
    if not payload:
        logger.warning("No data from Radar AO — returning empty list")
        return []

    notices = payload.get("notices", [])
    generated_at = payload.get("generated_at", "")
    logger.info(
        "Radar AO returned %d notices (TED=%d, BOAMP=%d, Profil=%d) generated_at=%s",
        len(notices),
        (payload.get("sources_summary", {}).get("TED") or {}).get("matched", 0),
        (payload.get("sources_summary", {}).get("BOAMP") or {}).get("matched", 0),
        (payload.get("sources_summary", {}).get("Profil") or {}).get("matched", 0),
        generated_at,
    )

    signals = []
    for n in notices:
        # Extraction des champs
        notice_id = n.get("id") or n.get("ref") or ""
        acheteur = (n.get("acheteur") or "").strip()
        objet = (n.get("objet") or "").strip()
        description = (n.get("description") or "").strip()
        cpv = n.get("cpv") or ""
        pays = n.get("pays") or ""
        deadline = n.get("deadline") or None
        publication = n.get("publication") or None
        source = n.get("source") or "Radar AO"
        url = n.get("url") or RADAR_AO_JSON_URL  # fallback vers le dashboard si pas d'URL spécifique
        score = int(n.get("score") or 60)

        if not acheteur or not objet:
            continue  # entrée incomplète, skip

        signal_type = _map_signal_type(n)
        sous_segment = _map_sous_segment(n)
        tier = determine_tier(score)
        source_tier = _source_tier_for(source)

        # Action commerciale enrichie selon segment acheteur + CPV
        segment_brut = n.get("segment") or "Autre"
        enriched_action = _generate_ao_action(n, signal_type, segment_brut)
        action_info = {
            "action": enriched_action,
            "deadline_action": deadline or generate_action(signal_type, VERTICAL, compte=acheteur)["deadline_action"],
        }

        # Description tronquée
        desc_short = description[:400]
        # Préciser CPV dans la description si présent
        if cpv:
            desc_short = f"[CPV {cpv}] {desc_short}"

        sig = Signal(
            id=fingerprint(objet, acheteur, publication or today),
            date_capture=today,
            vertical=VERTICAL,
            sous_segment=sous_segment,
            compte=acheteur,
            titre=objet[:200],
            description=desc_short,
            source=f"{source} (via Radar AO)",
            source_tier=source_tier,
            url=url,
            signal_type=signal_type,
            tier=tier,
            score=score,
            produit_match=produit_match_for(signal_type, VERTICAL),
            owner="Charles",
            action_reco=action_info["action"],
            deadline_action=deadline or action_info["deadline_action"],
            status="new",
            date_publication=publication,
        )
        signals.append(sig)
        logger.info(
            "[Radar AO] [%s/%s] [%d] %s — %s",
            VERTICAL,
            signal_type,
            score,
            acheteur[:35],
            objet[:60],
        )

    return signals


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "data" / VERTICAL / "signals.json"
    sigs = scrape()
    save_signals(sigs, path)
    logger.info("Saved %d AO signals (fetched from Radar AO live) to %s", len(sigs), path.relative_to(repo_root))


if __name__ == "__main__":
    main()
