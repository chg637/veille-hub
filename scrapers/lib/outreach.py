"""
Génération de mails drafts + contacts cibles pour outreach commercial.

Centralise la logique d'enrichissement des signaux avec :
- email_draft : subject + body, paramétrés par signal_type
- contacts_cibles : typologie de postes prioritaires + URL LinkedIn Sales Nav préfilled

Tous les templates sont en français. Les contacts utilisent Sales Nav avec une
recherche pré-remplie par compte (`company`) + titre (`title`).
"""

from __future__ import annotations

import urllib.parse


# ─────────────────────────────────────────────────────────────────────────────
# Sales Nav URL builder
# ─────────────────────────────────────────────────────────────────────────────

def sales_nav_url(company: str, title_keywords: list[str]) -> str:
    """
    Construit une URL LinkedIn Sales Navigator avec recherche préfilled.
    Charles peut cliquer pour ouvrir directement la search dans Sales Nav.

    Fallback (sans Sales Nav) : LinkedIn search publique.
    """
    if not company or not title_keywords:
        return ""
    title_query = " OR ".join(f'"{t}"' for t in title_keywords)
    # LinkedIn Sales Navigator search URL (compte premium requis pour exploiter)
    # Format : recherche personnes par company + titre actuel
    params = {
        "keywords": title_query,
        "currentCompany": company,
    }
    qs = urllib.parse.urlencode(params)
    return f"https://www.linkedin.com/sales/search/people?{qs}"


def linkedin_search_url(company: str, title_keywords: list[str]) -> str:
    """LinkedIn public search (sans Sales Nav). Plus accessible mais moins puissant."""
    if not company or not title_keywords:
        return ""
    title_query = " ".join(title_keywords)
    query = f'"{company}" {title_query}'
    return f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(query)}"


# ─────────────────────────────────────────────────────────────────────────────
# Personas cibles ITS — par signal_type
# ─────────────────────────────────────────────────────────────────────────────

PERSONAS_BY_SIGNAL = {
    "levee_fonds": [
        {
            "poste": "Chief People Officer",
            "alternatives": ["Head of People", "VP People", "DRH"],
            "priorite": 1,
            "raison": "Décide outils RH stratégiques post-levée",
        },
        {
            "poste": "Head of Talent Acquisition",
            "alternatives": ["Talent Acquisition Director", "Head of Recruiting"],
            "priorite": 2,
            "raison": "Opérationnel — gère le plan de recrutement massif",
        },
        {
            "poste": "Head of Hiring",
            "alternatives": ["Hiring Manager", "Recruitment Director"],
            "priorite": 3,
            "raison": "Sous-décideur — peut tester l'outil rapidement",
        },
    ],
    "concurrent_news": [
        {
            "poste": "Head of Talent Acquisition",
            "alternatives": ["Talent Acquisition Director", "Head of Recruiting"],
            "priorite": 1,
            "raison": "Premier impact du pivot concurrent",
        },
        {
            "poste": "DRH",
            "alternatives": ["Chief People Officer", "Directrice des Ressources Humaines"],
            "priorite": 2,
            "raison": "Arbitre stratégique sur le choix de plateforme",
        },
        {
            "poste": "HRIS Director",
            "alternatives": ["Head of HR Tech", "SIRH Manager"],
            "priorite": 3,
            "raison": "Décideur technique sur l'intégration",
        },
    ],
    "nomination_chro": [
        {
            "poste": "La personne nommée (cible directe)",
            "alternatives": [],
            "priorite": 1,
            "raison": "Fenêtre 30j post-prise de poste = haute disposition aux nouveaux outils",
        },
    ],
    "ao_publie": [
        {
            "poste": "Acheteur public référencé sur l'AO",
            "alternatives": ["RAQ", "Responsable des achats"],
            "priorite": 1,
            "raison": "Référent direct de la consultation",
        },
        {
            "poste": "Décideur métier (variable selon segment)",
            "alternatives": ["Direction des examens (ESR)", "Direction des soins (FPH)", "DRH (Collectivité)"],
            "priorite": 2,
            "raison": "Sponsorise le besoin métier en amont",
        },
    ],
    "ao_pre_info": [
        {
            "poste": "Acheteur public référencé sur l'AO",
            "alternatives": ["RAQ", "Responsable des achats"],
            "priorite": 1,
            "raison": "Référent — sourcing pré-marché",
        },
    ],
}


def get_contacts_cibles(signal_type: str, compte: str) -> list[dict]:
    """
    Retourne la liste de contacts cibles avec URL Sales Nav préfilled.
    """
    personas = PERSONAS_BY_SIGNAL.get(signal_type, [])
    contacts = []
    for p in personas:
        # Construire l'URL Sales Nav avec poste + alternatives
        all_titles = [p["poste"]] + p.get("alternatives", [])
        contacts.append({
            "poste": p["poste"],
            "alternatives": p.get("alternatives", []),
            "priorite": p["priorite"],
            "raison": p["raison"],
            "sales_nav_url": sales_nav_url(compte, all_titles) if compte else "",
            "linkedin_public_url": linkedin_search_url(compte, all_titles) if compte else "",
        })
    return contacts


# ─────────────────────────────────────────────────────────────────────────────
# Templates d'emails par signal_type
# Chaque template prend des variables interpolables : {compte}, {montant}, {concurrent}, etc.
# ─────────────────────────────────────────────────────────────────────────────


def email_draft_levee(compte: str, montant_raw: str, meur: float, url_source: str) -> dict:
    """Email post-levée Series B+ — angle scale-up + standardisation éval candidats."""
    if meur >= 50:
        urgence_line = "Sur les 12 prochains mois, vous allez probablement recruter 100+ profils. C'est exactement le moment où la qualité du process d'évaluation devient un goulot d'étranglement."
    elif meur >= 20:
        urgence_line = "Post-Series B, c'est le moment où la plupart des scale-ups structurent leur process d'éval candidats. Avant que le volume devienne incontrôlable."
    else:
        urgence_line = "Une levée à cette taille s'accompagne souvent d'un plan de recrutement ambitieux. Anticiper l'outillage évite la dette technique RH."

    subject = f"{compte} — votre Series — sur l'évaluation candidats à scale"
    body = (
        f"Bonjour,\n"
        f"\n"
        f"Je viens de voir que {compte} a bouclé une levée de {montant_raw}. "
        f"Bravo pour cette étape.\n"
        f"\n"
        f"{urgence_line}\n"
        f"\n"
        f"Chez Isograd, on opère ITS, une plateforme SaaS d'évaluation des "
        f"compétences techniques utilisée par des scale-ups qui recrutent 50 à "
        f"500 personnes par an. Le principe : standardiser le screening "
        f"technique des candidats (devs, data, ops, sales) avec des tests "
        f"calibrés, automatisés, et opposables.\n"
        f"\n"
        f"Trois cas concrets de clients comparables :\n"
        f"- Réduction du temps de qualif technique de 45min à 12min par "
        f"candidat\n"
        f"- Doublement du taux de présence en entretien final (candidats "
        f"qualifiés en amont)\n"
        f"- Standardisation entre les recruteurs (fini les évaluations "
        f"subjectives selon qui interview)\n"
        f"\n"
        f"15 minutes pour vous montrer concrètement la plateforme ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS\n"
        f"\n"
        f"Source de l'info : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_concurrent(compte: str, titre_article: str, url_source: str) -> dict:
    """Email post-pivot/news concurrent — angle alternative stable + transition fluide."""
    is_pivot = "devient" in titre_article.lower() or "pivot" in titre_article.lower()
    subject = (
        f"Suite à l'annonce {compte}{' → nouveau nom' if is_pivot else ''} — alternative ITS"
    )
    body = (
        f"Bonjour,\n"
        f"\n"
        f"J'ai vu passer cette annonce concernant {compte} :\n"
        f"\"{titre_article}\"\n"
        f"({url_source})\n"
        f"\n"
        f"Si vous utilisez aujourd'hui leur plateforme, ce type d'évolution "
        f"{'(changement de marque + repositionnement)' if is_pivot else '(évolution stratégique)'} "
        f"soulève souvent des questions côté équipe RH : continuité du "
        f"support, roadmap, migration éventuelle, impact tarifaire.\n"
        f"\n"
        f"Je suis Charles, je vends ITS chez Isograd — une plateforme "
        f"d'évaluation des compétences (techniques et bureautiques) "
        f"positionnée comme alternative stable et opérationnelle depuis "
        f"plus de 10 ans. Plus de 50 000 candidats évalués par mois en "
        f"France et à l'international.\n"
        f"\n"
        f"Ce qui peut vous intéresser :\n"
        f"- Import facile depuis votre plateforme actuelle (tests, candidats, "
        f"résultats historiques)\n"
        f"- Stack stable, équipe française, support en direct\n"
        f"- Démarche de transition fluide : on commence par un test sur un "
        f"cas d'usage, puis on étend si ça vous convient\n"
        f"\n"
        f"15 minutes pour échanger ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS"
    )
    return {"subject": subject, "body": body}


def email_draft_nomination(personne: str, poste: str, entreprise: str, url_source: str) -> dict:
    """Email post-nomination — angle nouvelle prise de poste + apport rapide."""
    subject = f"Félicitations pour votre nomination {poste} chez {entreprise}"
    body = (
        f"Bonjour,\n"
        f"\n"
        f"Félicitations pour votre prise de poste en tant que {poste} chez "
        f"{entreprise}. Belle étape.\n"
        f"\n"
        f"Je me permets de vous écrire car beaucoup de DRH récemment nommés "
        f"me partagent le même constat dans leurs premières semaines : un "
        f"manque de visibilité sur le niveau réel des compétences en "
        f"interne, et un process d'évaluation candidats hétérogène selon "
        f"qui recrute.\n"
        f"\n"
        f"Je vends ITS chez Isograd — une plateforme d'évaluation utilisée "
        f"par des entreprises comparables pour deux usages :\n"
        f"\n"
        f"1. **Cartographier les compétences existantes** (techniques, "
        f"bureautiques) avec des tests calibrés. Vous obtenez en 2 semaines "
        f"une photo objective de votre population.\n"
        f"\n"
        f"2. **Industrialiser le screening candidats** avec des tests "
        f"automatisés intégrés à votre ATS. Standardise les décisions "
        f"d'embauche.\n"
        f"\n"
        f"L'avantage de prendre 15 minutes maintenant : voir si ça peut "
        f"vous servir d'argument dans vos premiers chantiers (audit "
        f"compétences, refonte process recrutement, plan d'embauche, "
        f"transition Qualiopi…).\n"
        f"\n"
        f"Disponible cette semaine ou la suivante ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS\n"
        f"\n"
        f"Source de l'annonce : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_ao(compte: str, titre_ao: str, deadline: str, url_dce: str) -> dict:
    """Email préparation réponse AO — sourcing complémentaire avant DCE."""
    subject = f"AO {compte} — Isograd souhaite candidater"
    body = (
        f"Bonjour,\n"
        f"\n"
        f"Nous avons identifié votre consultation publiée sur les marchés "
        f"publics :\n"
        f"\"{titre_ao}\"\n"
        f"Deadline : {deadline}\n"
        f"\n"
        f"Isograd opère ITS, une plateforme SaaS d'hébergement d'examens "
        f"et de certification des compétences, déployée chez 60+ "
        f"établissements de l'enseignement supérieur français (universités, "
        f"grandes écoles, CFA) et grandes administrations publiques.\n"
        f"\n"
        f"Nous souhaitons candidater. Avant la finalisation de notre "
        f"dossier, nous aurions besoin de quelques clarifications sur le "
        f"périmètre, en particulier :\n"
        f"- Volume cible de candidats / sessions par an\n"
        f"- Modalités de surveillance (proctoring, télésurveillance)\n"
        f"- Périmètre fonctionnel attendu (banque de questions, génération "
        f"d'attestations, intégration SI existant)\n"
        f"- Calendrier prévisionnel de mise en œuvre\n"
        f"\n"
        f"Pouvons-nous organiser un échange de 30 minutes ? Cela nous "
        f"permettrait d'affiner notre proposition pour qu'elle réponde au "
        f"mieux à votre besoin.\n"
        f"\n"
        f"Bien cordialement,\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS\n"
        f"\n"
        f"DCE : {url_dce}"
    )
    return {"subject": subject, "body": body}
