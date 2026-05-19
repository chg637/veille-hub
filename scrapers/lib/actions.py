"""
Actions commerciales recommandées par type de signal.

Chaque signal du hub doit déclencher une action commerciale concrète et datée.
Cette logique transforme un (vertical, signal_type, compte) en :
- action_reco : phrase d'instruction actionnable pour le commercial
- deadline_action : date butoir suggérée (ISO YYYY-MM-DD)
- canal : email / linkedin / inmail / téléphone / dossier — pour filtrage ultérieur

Les templates sont calibrés selon le framework des "Plays" du skill gtm-tosa.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional


# Délais standards par tier d'action
DEADLINE_TIER_1 = 7    # jours
DEADLINE_TIER_2 = 30
DEADLINE_TIER_3 = 90


def _deadline_from_tier(tier: int) -> str:
    """Retourne une date butoir ISO selon le tier de priorité."""
    if tier <= 1:
        days = DEADLINE_TIER_1
    elif tier == 2:
        days = DEADLINE_TIER_2
    else:
        days = DEADLINE_TIER_3
    return (date.today() + timedelta(days=days)).isoformat()


# Templates d'action par (vertical, signal_type)
ACTION_TEMPLATES = {
    # ─── Education ──────────────────────────────────────────────
    ("education", "accreditation"): {
        "tier": 1,
        "action": "Email au responsable maquette + pitch « Pack Edu Tosa = preuve mesurable compétences digitales pour le dossier {accred} ». Joindre 2 cas pairs. RDV sous 14j.",
        "canal": "email",
    },
    ("education", "nouvelle_formation"): {
        "tier": 1,
        "action": "Note de connexion LinkedIn au directeur de programme {compte}. Pitch « Intégrer la certification dans la maquette dès le lancement ». Demande de RDV 30 min.",
        "canal": "linkedin",
    },
    ("education", "nomination_dg"): {
        "tier": 1,
        "action": "Note LinkedIn 100 premiers jours du nouveau DG. Angle « bilan rapide du dispositif certification ». Brief équipe sur les comptes Tosa déjà présents chez {compte}.",
        "canal": "linkedin",
    },
    ("education", "fusion_ecole"): {
        "tier": 2,
        "action": "Email direction Harmonisation. Pitch « standard commun certification post-fusion ». RDV pédagogique + DSI sous 30j.",
        "canal": "email",
    },
    ("education", "rncp_nouveau"): {
        "tier": 2,
        "action": "Veiller publication officielle France Compétences. Préparer pitch positionnement Tosa comme brique d'évaluation.",
        "canal": "dossier",
    },

    # ─── OF ─────────────────────────────────────────────────────
    ("of", "levee_edtech"): {
        "tier": 2,
        "action": "Battle card actualisée. Analyser positionnement {compte} vs Pack OF Tosa. Si concurrent direct, partage en équipe + brief comptes communs.",
        "canal": "dossier",
    },
    ("of", "rncp_open"): {
        "tier": 1,
        "action": "Cartographier les 10-20 premiers OF qui vont déposer dossier RNCP sur ce thème. Outreach proactif Cert IA Tosa avant que la concurrence se positionne.",
        "canal": "dossier",
    },
    ("of", "qualiopi"): {
        "tier": 2,
        "action": "Surveiller mouvement liste organismes Qualiopi. Identifier les OF qui perdent le label = opportunité de repositionnement avec preuve Tosa.",
        "canal": "dossier",
    },
    ("of", "concurrent_news"): {
        "tier": 3,
        "action": "Battle card mise à jour Cegos/OpenClassrooms/Demos. Synthèse 1 page + diffusion équipe commerciale. Identifier les comptes communs.",
        "canal": "dossier",
    },
    ("of", "opco_ao"): {
        "tier": 1,
        "action": "Récupérer cahier des charges OPCO. Si match formation Tosa, monter dossier candidature ou se positionner via OF partenaire avant deadline.",
        "canal": "dossier",
    },

    # ─── Corporate (produit phare = ITS) ────────────────────────
    ("corporate", "nomination_chro"): {
        "tier": 1,
        "action": "InMail LinkedIn dans les 100 premiers jours. Angle « ITS = outil testing certifiant, mutualisable TA + L&D, traçable GPEC ». Proposer démo 20 min. RDV sous 30j.",
        "canal": "linkedin",
    },
    ("corporate", "levee_fonds"): {
        "tier": 1,
        "action": "LinkedIn DM Head of TA de {compte}. Angle « levée = plan embauche dans 90j → industrialiser la qualif candidats avec ITS, divisez par 2 le coût d'un mauvais hire ». RDV démo sous 14j.",
        "canal": "linkedin",
    },
    ("corporate", "plan_ia"): {
        "tier": 1,
        "action": "Email CHRO + Head of L&D de {compte}. Angle « plan IA = besoin de prouver la maîtrise compétences digitales → ITS pour mesurer avant/après formation IA ». RDV pédagogique sous 30j.",
        "canal": "email",
    },
    ("corporate", "plan_recrutement"): {
        "tier": 1,
        "action": "LinkedIn DM Head of TA de {compte}. Pitch « démo ITS 15 min, conversion en POC sur 1 cohorte de recrutement ». RDV sous 14j.",
        "canal": "linkedin",
    },
    ("corporate", "top_employer"): {
        "tier": 3,
        "action": "Email DRH de {compte}. Angle « classement Top Employer confirme votre investissement compétences — ajouter la preuve mesurable côté outils via ITS ». Nurturing 60j.",
        "canal": "email",
    },
    ("corporate", "transformation_digitale"): {
        "tier": 2,
        "action": "Email CDO + CHRO de {compte}. Angle « transformation digitale = besoin de prouver la maîtrise des compétences digitales sur Excel/Power BI/Word avec ITS ». RDV sous 30j.",
        "canal": "email",
    },

    # ─── AO (Appels d'Offres) ───────────────────────────────────
    ("ao", "ao_publie"): {
        "tier": 1,
        "action": "Récupérer DCE + analyser scoring CPV. Si match Tosa/ITS, monter dossier candidature avant deadline. Coordonner avec ITS pour hébergement examens si applicable.",
        "canal": "dossier",
    },
    ("ao", "ao_pre_info"): {
        "tier": 2,
        "action": "Surveiller publication AO formel. Identifier acheteur public et préparer dossier de candidature en amont. Réseautage auprès des décideurs identifiés.",
        "canal": "dossier",
    },
    ("ao", "ao_modificatif"): {
        "tier": 2,
        "action": "Vérifier impact du modificatif sur notre positionnement. Réajuster offre si nécessaire avant nouvelle deadline.",
        "canal": "dossier",
    },
    ("ao", "rncp_open_ao"): {
        "tier": 1,
        "action": "Si fiche RNCP cible compétences digitales, monter dossier de positionnement Tosa comme certification adossée.",
        "canal": "dossier",
    },
    ("ao", "opco_ao"): {
        "tier": 1,
        "action": "Récupérer cahier des charges OPCO. Identifier OF partenaire pour candidature commune si pertinent. Deadline à respecter.",
        "canal": "dossier",
    },
}


# Fallback action si pas de template précis (ne devrait pas arriver après filtrage)
FALLBACK_ACTION = {
    "tier": 3,
    "action": "Vérifier la pertinence du signal manuellement et qualifier le compte avant action.",
    "canal": "dossier",
}


def generate_action(
    signal_type: str,
    vertical: str,
    compte: Optional[str] = None,
    accreditation: Optional[str] = None,
) -> dict:
    """
    Génère une action commerciale concrète pour un signal donné.

    Retourne un dict {action: str, deadline_action: ISO date, canal: str, tier_action: int}.
    """
    tpl = ACTION_TEMPLATES.get((vertical, signal_type), FALLBACK_ACTION)

    # Substitutions de variables dans le template
    action_text = tpl["action"]
    if "{compte}" in action_text:
        action_text = action_text.replace("{compte}", compte or "[compte à identifier]")
    if "{accred}" in action_text:
        action_text = action_text.replace("{accred}", accreditation or "accréditation")

    return {
        "action": action_text,
        "deadline_action": _deadline_from_tier(tpl["tier"]),
        "canal": tpl["canal"],
        "tier_action": tpl["tier"],
    }
