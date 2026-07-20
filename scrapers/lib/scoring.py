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
    "of_nouvelle_offre": 68,   # OF qui lance une offre bureautique/IA = revendeur Tosa potentiel
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


AO_BASE_SCORES = {
    "ao_publie": 55,
    "ao_pre_info": 45,
    "ao_modificatif": 40,
    "ao_attribue": 25,
}


def score_ao(
    signal_type: str,
    metier_score: Optional[int] = None,
    deadline_iso: Optional[str] = None,
    whitelist: bool = False,
) -> int:
    """
    Score AO discriminant (v5.4) — remplace le 80 fixe qui rendait le tiering plat.

    Composantes :
    - base par type d'avis (publié 55 > pré-info 45 > modificatif 40 > attribué 25)
    - fit métier : le score pondéré de _passes_metier_filter (tiers S/A/B + CPV +
      combos - pénalité peer), cappé à 30. Seuil de passage = 8, donc un AO
      tout juste passé apporte ~8 pts, un AO plateforme/proctoring 25-30 pts.
    - acheteur whitelist ICP : +8
    - fenêtre de réponse : J-7..J-45 = +5 (idéale) ; < J-7 = -10 (dossier
      difficile à monter) ; échue = -25 (ne devrait plus arriver, les scrapers
      skippent en amont).

    Étendue résultante ≈ 45-98 → tiers 1/2/3 redeviennent discriminants.
    """
    from datetime import date

    base = AO_BASE_SCORES.get(signal_type, 50)
    fit = max(0, min(int(metier_score or 0), 30))
    score = base + fit
    if whitelist:
        score += 8
    if deadline_iso:
        try:
            d = date.fromisoformat(str(deadline_iso)[:10])
            days = (d - date.today()).days
            if days < 0:
                score -= 25
            elif days < 7:
                score -= 10
            elif days <= 45:
                score += 5
        except ValueError:
            pass
    return max(0, min(98, score))


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
        # OF revendeur Tosa → ce vertical est dédié à la revente du catalogue Tosa
        if signal_type in ("levee_edtech", "concurrent_news"):
            return ["ITS"]  # éditeur EdTech = white-label ITS, pas catalogue
        if signal_type == "rncp_open":
            return ["ITS"]
        return ["ITS"]

    if vertical == "rncp":
        # Certificateur qui dépose une fiche RNCP/RS = besoin d'une PLATEFORME
        # pour héberger les sessions d'examens (banque de questions, proctoring,
        # attestations). C'est ITS pur, jamais Tosa (Tosa = catalogue fermé).
        return ["ITS"]

    if vertical == "ao":
        # AO public = besoin d'une plateforme d'hébergement d'examens sur laquelle
        # l'acheteur met SES contenus (tests recrutement, examens académiques,
        # contrôles internes). C'est ITS, pas Tosa.
        return ["ITS"]

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
