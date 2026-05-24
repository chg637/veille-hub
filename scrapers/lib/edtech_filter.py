"""
Détecteur EdTech partagé entre levees_rss (Corporate) et levees_edtech (OF).

Une levée détectée EdTech :
- est routée vers le vertical OF (signal_type = levee_edtech)
- est SKIPPÉE par levees_rss côté Corporate (sinon doublon)

Donc la même boîte ne peut apparaître qu'une fois dans le hub.
"""

from __future__ import annotations

import re

# Mots-clés EdTech à matcher dans titre OU description (case-insensitive)
EDTECH_KEYWORDS = [
    # FR
    "edtech", "ed-tech",
    "e-learning", "elearning",
    "formation en ligne", "plateforme de formation",
    "plateforme d'apprentissage", "apprentissage en ligne",
    "MOOC", "SPOC",
    "LMS", "système de gestion de l'apprentissage",
    "academy", "académie",
    "upskilling", "reskilling",
    "skills training", "certification professionnelle",
    "formation continue",
    # EN
    "learning platform", "online learning", "online education",
    "training platform", "skills platform", "talent platform",
    "L&D platform", "L&D ",
    "corporate training", "workforce learning",
    "skills development", "skills assessment",
    "academy", "bootcamp",
]

# Boîtes EdTech connues — whitelist (match même sans le mot "edtech" dans le titre)
EDTECH_KNOWN_COMPANIES = {
    "OpenClassrooms", "Coursera", "Udemy", "edX", "Udacity",
    "360Learning", "Cornerstone", "Docebo", "TalentLMS",
    "Pluralsight", "DataCamp", "Workera", "Riipen",
    "MasterClass", "LinkedIn Learning", "Skillshare",
    "Le Wagon", "Ironhack", "OpenAcademy",
    "Pix", "Skillup", "Studyrama", "MaFormation",
    "Sparted", "Edflex", "Beedeez", "Tactiq",
    "Numa", "Wild Code School",
    "OpenSesame", "Cypher Learning", "Coorpacademy",
    "Knowledgehook", "Multiverse", "Springboard",
    "Outschool", "Brightwheel", "GoStudent", "Photomath",
    "ClassDojo", "Quizlet", "Duolingo",
}


def is_edtech(title: str, description: str, compte: str) -> tuple[bool, str]:
    """
    Détecte si une levée concerne un acteur EdTech.
    Retourne (is_edtech, raison).
    """
    blob = f"{title} {description}".lower()

    # 1. Boîte connue EdTech
    for known in EDTECH_KNOWN_COMPANIES:
        if known.lower() in blob:
            return True, f"compagnie EdTech connue ({known})"
        if compte and known.lower() == compte.lower().strip():
            return True, f"compte = {known}"

    # 2. Mot-clé EdTech
    for kw in EDTECH_KEYWORDS:
        if kw.lower() in blob:
            return True, f"keyword EdTech : '{kw}'"

    # 3. Pattern d'audience apprenante
    if re.search(r"\b(?:learners?|trainees?|students?|apprenants?)\s+(?:on\s+)?(?:the\s+)?platform", blob):
        return True, "audience apprenants détectée"
    if re.search(r"trains?\s+\d+", blob) and ("worker" in blob or "employee" in blob or "professional" in blob):
        return True, "scale-up formation pro détectée"

    return False, ""
