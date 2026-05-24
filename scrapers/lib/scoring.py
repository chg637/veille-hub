"""
Scoring ICP commun aux 3 verticaux.

La logique de scoring est inspirée du framework gtm-tosa et adaptée par vertical.
Chaque signal entre avec un score brut basé sur son type, sa source et le compte,
puis est pondéré par les triggers détectés.
"""

from __future__ import annotations

from typing import Optional


# Pondérations par type de signal (signal_type → score brut)
SIGNAL_TYPE_SCORES = {
    # Education — triggers forts
    "accreditation": 85,
    "nouvelle_formation": 75,
    "nomination_dg": 80,
    "fusion_ecole": 70,
    "appel_offre": 80,
    "rncp_nouveau": 70,
    # OF
    "levee_edtech": 70,
    "rncp_open": 75,
    "qualiopi": 60,
    "concurrent_news": 55,
    # AO (appels d'offres)
    "ao_publie": 85,
    "ao_pre_info": 70,
    "ao_attribue": 45,
    "ao_modificatif": 50,
    "rncp_open_ao": 70,
    "opco_ao": 80,
    # Corporate — triggers forts (produit phare = ITS pour recrutement)
    "nomination_chro": 85,
    "levee_fonds": 85,           # ITS pour industrialiser la qualif post-levée
    "plan_ia": 80,
    "plan_recrutement": 88,      # signal le plus chaud — utilisateur primaire ITS = Head of TA
    "top_employer": 60,
    "transformation_digitale": 75,
    # Fallback
    "autre": 50,
}

# Pondérations par tier de source (plus le tier est fort, plus le score monte)
SOURCE_TIER_BONUS = {1: 10, 2: 5, 3: 0}


def base_score(signal_type: str, source_tier: int) -> int:
    """Score brut d'un signal avant pondérations ICP du compte."""
    type_score = SIGNAL_TYPE_SCORES.get(signal_type, 50)
    tier_bonus = SOURCE_TIER_BONUS.get(source_tier, 0)
    return min(100, type_score + tier_bonus)


def determine_tier(score: int) -> int:
    """Détermine le tier d'action (1/2/3) à partir du score final."""
    if score >= 80:
        return 1  # Action sous 7 jours (chaud)
    if score >= 60:
        return 2  # Action sous 30 jours (tiède)
    return 3  # Surveillance (froid)


def produit_match_for(signal_type: str, vertical: str) -> list:
    """
    Retourne la liste des produits Isograd à pitcher selon le type de signal et le vertical.

    Logique produit :
    - Corporate → ITS d'abord (testing recrutement), Tosa en complément sur signaux maturité
    - Education → Pack Education Tosa + ITS pour hébergement examens + Cert IA
    - OF → Pack OF Tosa + ITS pour les certifs en aval
    - AO → selon CPV, mais le plus souvent Pack Education + ITS
    """
    if vertical == "corporate":
        # Signaux recrutement / volume → ITS en priorité
        if signal_type in ("plan_recrutement", "levee_fonds"):
            return ["ITS"]
        # Signaux stratégiques RH / IA → ITS + Tosa cross-sell
        if signal_type in ("nomination_chro", "plan_ia", "transformation_digitale"):
            return ["ITS", "Tosa Corporate"]
        # Top Employer / labels → ITS + Tosa pour valorisation
        if signal_type == "top_employer":
            return ["ITS", "Tosa Corporate"]
        return ["ITS"]

    if vertical == "education":
        if signal_type == "accreditation":
            return ["Pack Education Tosa", "ITS"]
        if signal_type == "nouvelle_formation":
            return ["Pack Education Tosa", "Cert IA"]
        if signal_type == "nomination_dg":
            return ["Pack Education Tosa"]
        return ["Pack Education Tosa"]

    if vertical == "of":
        if signal_type in ("levee_edtech", "concurrent_news"):
            return ["Pack OF Tosa"]
        if signal_type == "rncp_open":
            return ["Cert IA", "Pack OF Tosa"]
        return ["Pack OF Tosa"]

    if vertical == "rncp":
        # Certificateur qui vient de déposer une fiche : on pitche ITS pour héberger
        # leurs sessions d'examens (banque de questions, proctoring, attestations)
        # + Tosa si fiche orientée numérique/bureautique
        if signal_type == "rncp_open":
            return ["ITS", "Pack Education Tosa"]
        return ["ITS"]

    if vertical == "ao":
        if signal_type in ("ao_publie", "ao_pre_info"):
            return ["Pack Education Tosa", "ITS"]
        return ["Pack Education Tosa"]

    return []


def apply_icp_boost(base: int, icp_score: Optional[int]) -> int:
    """
    Applique une pondération supplémentaire si le compte est dans l'ICP (look-alike pré-scoré).

    icp_score est le score ICP du compte (0-100) issu de la grille de cadrage.
    Un compte 80+ ICP fit donne +10 au score du signal ; un compte < 40 ICP retire -15.
    """
    if icp_score is None:
        return base
    if icp_score >= 80:
        return min(100, base + 10)
    if icp_score >= 60:
        return base + 5
    if icp_score < 40:
        return max(0, base - 15)
    return base
