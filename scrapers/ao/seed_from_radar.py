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


# ─────────────────────────────────────────────────────────────────────────────
# FILTRE MÉTIER STRICT (côté hub, en complément du Radar AO)
# Reframe : Isograd vend ÉVALUATION / CERTIFICATION de compétences,
#           PAS de la prestation de formation pure.
# ─────────────────────────────────────────────────────────────────────────────

# Préfixes CPV à exclure systématiquement (formation pure, hors périmètre Isograd)
# Match par préfixe pour couvrir tous les sous-codes (ex: 80511xxx, 80512xxx).
CPV_FORMATION_PREFIXES = (
    "803",   # Enseignement supérieur (formation initiale)
    "804",   # Enseignement adultes (formation)
    "805",   # 80500000 → 80599999 : tous services de formation
    "806",   # 80600000 → 80699999 : sécurité / droit / défense
    "79632", # Formation de personnel
    "79633", # Développement professionnel — uniquement si VAE/bilan, sinon trop large
)

# CPV à exclure (faux positifs hors compétences) — signature électronique, gardiennage…
CPV_HORS_PERIMETRE_PREFIXES = (
    "79132100",  # Certification de signature électronique
    "79710",     # Surveillance / gardiennage
    "79711",     # Alarme / contrôle d'accès
    "79713",     # Gardiennage
    "79714",     # Surveillance
    "79715",     # Patrouille
)

# Mots-clés OBLIGATOIRES : au moins un doit matcher (titre + description)
# pour qu'un AO soit conservé. Sinon = écarté.
# IMPORTANT : éviter les termes trop génériques ("habilitation" seul matche
# "habilitations électriques", "habilitations d'accès IAM", etc.).
MANDATORY_KEYWORDS = [
    # FR — évaluation/certification de compétences (formes spécifiques)
    "certification de compétences", "certification des compétences",
    "certification professionnelle", "qualification professionnelle",
    "évaluation des compétences", "évaluation de compétences",
    "test de compétences", "tests de compétences",
    "psychométrie",
    "banque de questions",
    "proctoring", "télésurveillance d'examens", "télésurveillance des épreuves",
    "plateforme d'évaluation", "plateforme de certification",
    "plateforme d'examen", "plateforme de tests",
    "DigComp", "compétences numériques",
    "QCM", "test adaptatif", "test de positionnement",
    "VAE", "validation des acquis",
    "bilan de compétences",
    "audit de compétences", "audit des compétences",
    "GPEC", "gestion prévisionnelle des emplois", "gestion prévisionnelle de l'emploi",
    "cartographie des compétences", "référentiel de compétences",
    "développement des compétences", "professionnalisation des compétences",
    "habilitation à délivrer", "habilitation à certifier",
    "habilitation France compétences", "habilitation Qualiopi",
    "RNCP", "Répertoire spécifique",
    "Qualiopi",
    "accréditation des certifications", "ré-accréditation",
    "renouvellement de certification", "renouvellement de la certification",
    "ingénierie d'évaluation",
    # EN
    "competence assessment", "competency assessment", "skills assessment",
    "skills certification", "examination platform",
    "online assessment", "online examination", "online exam",
    "computer-based testing", "test delivery",
    "validation of prior learning",
    "competency framework", "skills mapping", "skills audit",
    "talent assessment platform",  # plus spécifique que "talent assessment"
    "item banking", "psychometrics",
    # Bureautique en contexte certif uniquement
    "TOSA", "Tosa", "PCIE", "ICDL",
    # Examens spécifiques (formes longues pour éviter "examen environnemental")
    "passation d'épreuves", "session de certification", "session d'évaluation",
    "examens en ligne", "examens à distance",
    "épreuves dématérialisées", "dématérialisation des épreuves",
]

# Mots-clés négatifs : phrases qui invalident un match (formation pure, etc.)
NEGATIVE_PHRASES = [
    # Formation pure
    "prestation de formation", "prestations de formation",
    "actions de formation", "action de formation",
    "animer des sessions", "animation de formation",
    "former les agents", "former les personnels", "former les collaborateurs",
    "former les salariés", "former les enseignants", "former les stagiaires",
    "conception de modules", "conception pédagogique", "ingénierie pédagogique",
    "accompagnement pédagogique",
    "coaching individuel", "tutorat", "cours particuliers",
    "stages pratiques", "alternance",
    # Signature électronique (FR + DE + variantes)
    "signature électronique", "signatures électroniques",
    "signature numérique", "signatures numériques",
    "signaturkarten", "elektronische signatur", "elektronischer signaturen",
    "elektronische signaturen", "qualifizierte signaturen", "eidas",
    # Surveillance / sécurité physique
    "videosurveillance", "vidéosurveillance",
    "agent de sécurité", "agent de surveillance",
    "patrouille", "gardiennage",
    # Habilitations sécurité (pas compétences)
    "habilitations électriques", "habilitation électrique",
    "habilitations IAM", "habilitations d'accès",
    "identity governance", "identity & access management", "identity and access management",
    # Interim management
    "interim management", "interim manager", "temporary deployment",
    "deployment of external professionals",
]


def _passes_metier_filter(notice: dict) -> tuple[bool, str]:
    """
    Retourne (True, "ok") si l'AO passe le filtre métier Isograd,
    (False, "raison") sinon.
    """
    cpv = (notice.get("cpv") or "").strip()
    titre = (notice.get("objet") or "").lower()
    desc = (notice.get("description") or "").lower()
    full_text = f"{titre} {desc}"

    # 1. Exclure CPV formation pure (match par préfixe)
    for prefix in CPV_FORMATION_PREFIXES:
        if cpv.startswith(prefix):
            return False, f"CPV {cpv} = formation (préfixe {prefix})"

    # 2. Exclure CPV hors périmètre (signature électronique, gardiennage…)
    for prefix in CPV_HORS_PERIMETRE_PREFIXES:
        if cpv.startswith(prefix):
            return False, f"CPV {cpv} hors périmètre (préfixe {prefix})"

    # 3. Negative phrases : si une phrase négative match, on rejette
    for phrase in NEGATIVE_PHRASES:
        if phrase.lower() in full_text:
            return False, f"phrase négative : '{phrase}'"

    # 4. Mandatory keywords : au moins UN doit matcher
    matched = [kw for kw in MANDATORY_KEYWORDS if kw.lower() in full_text]
    if not matched:
        return False, "aucun mandatory keyword (certif/éval/test/VAE/bilan/…) ne match"

    return True, f"ok (matched: {matched[0]})"


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


def _detect_segment_from_acheteur(acheteur: str) -> Optional[str]:
    """
    Détection segment à partir du nom de l'acheteur (fallback quand le Radar AO
    n'a pas pu segmenter).
    """
    a = (acheteur or "").lower()
    # FPH — Fonction publique hospitalière
    fph_markers = ["ap-hp", "aphp", "ap hp", "chu ", "chu-", "centre hospitalier",
                   "hôpital", "hopital", "ars ", "anfh", "ght ", "ehpad",
                   "cfdc", "centre de formation des soins"]
    if any(m in a for m in fph_markers):
        return "FPH"
    # ESR
    esr_markers = ["université", "universite", "iut ", "école", "ecole sup",
                   "polytech", "iae ", "comue", "epscp", "school", "college"]
    if any(m in a for m in esr_markers):
        return "ESR"
    # Consulaire
    if any(m in a for m in ["cci ", "cci-", "cma ", "chambre de métiers",
                             "chambre des métiers", "chambre de commerce"]):
        return "Consulaire"
    # État
    if any(m in a for m in ["ministère", "ministere", "préfecture", "prefecture",
                             "dgfip", "douanes", "armée", "intérieur", "interior",
                             "ena", "insp", "dinum"]):
        return "État"
    # Collectivités
    if any(m in a for m in ["région ", "region ", "conseil régional", "département",
                             "departement", "conseil départemental", "métropole",
                             "metropole", "communauté", "communaute", "ville de",
                             "mairie", "cnfpt"]):
        return "Collectivités"
    # OPCO
    if "opco" in a or "afdas" in a or "akto" in a or "atlas" in a:
        return "OPCO"
    return None


def _map_sous_segment(notice: dict) -> str:
    """
    Mapping du segment Radar AO vers un libellé lisible.
    Fallback : détection à partir du nom de l'acheteur si Radar AO renvoie "Autre".
    """
    seg = notice.get("segment") or ""
    acheteur = notice.get("acheteur") or ""

    # Fallback intelligent si le Radar AO n'a pas su segmenter
    if seg in ("", "Autre"):
        detected = _detect_segment_from_acheteur(acheteur)
        if detected:
            seg = detected

    if seg == "Collectivités":
        return "Marché public Collectivité"
    if seg == "Consulaire":
        return "Marché public Consulaire (CCI/CMA)"
    if seg == "Universités" or seg == "ESR":
        return "Marché public ESR (Enseignement Supérieur)"
    if seg == "OPCO":
        return "Marché public OPCO"
    if seg == "FPH":
        return "Marché public FPH (Hôpitaux / CHU / AP-HP)"
    if seg == "État":
        return "Marché public État / Ministères"
    if seg == "Autre" or not seg:
        return "Marché public — secteur à qualifier"
    return seg


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

        # FILTRE MÉTIER ISOGRAD : on ne garde que les AO évaluation/certification
        passes, reason = _passes_metier_filter(n)
        if not passes:
            logger.info(
                "[Radar AO] FILTRÉ (%s) : %s — %s",
                reason,
                acheteur[:35],
                objet[:60],
            )
            continue

        signal_type = _map_signal_type(n)
        sous_segment = _map_sous_segment(n)
        tier = determine_tier(score)
        source_tier = _source_tier_for(source)

        # Segment : on prend ce que renvoie le Radar AO, sinon on déduit
        segment_brut = n.get("segment") or "Autre"
        if segment_brut in ("", "Autre"):
            detected = _detect_segment_from_acheteur(acheteur)
            if detected:
                segment_brut = detected

        # Action commerciale enrichie selon segment acheteur + CPV
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
