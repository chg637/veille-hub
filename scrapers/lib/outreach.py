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
    # ─── Education ─────────────────────────────────────────────────────────
    "accreditation": [
        {
            "poste": "Directeur(rice) des certifications",
            "alternatives": ["Responsable Qualiopi", "Responsable des certifications"],
            "priorite": 1,
            "raison": "Pilote la conformité audit et la valorisation du label",
        },
        {
            "poste": "Directeur(rice) des programmes / Académique",
            "alternatives": ["Doyen", "Doyenne", "VP Pédagogie", "Directeur(rice) pédagogique"],
            "priorite": 2,
            "raison": "Sponsorise les outils d'évaluation des étudiants",
        },
        {
            "poste": "Directeur(rice) Communication / Marketing",
            "alternatives": ["Responsable Communication", "Responsable Marketing"],
            "priorite": 3,
            "raison": "Valorise le label dans la promotion (Tosa = preuve compétences)",
        },
    ],
    "nouvelle_formation": [
        {
            "poste": "Responsable du programme / Directeur(rice) de la formation",
            "alternatives": ["Coordinateur(rice) pédagogique", "Responsable de filière"],
            "priorite": 1,
            "raison": "Définit le dispositif d'évaluation du nouveau programme",
        },
        {
            "poste": "Doyen / Directeur(rice) académique",
            "alternatives": ["VP Pédagogie", "Directeur(rice) des études"],
            "priorite": 2,
            "raison": "Arbitrage sur l'outillage évaluation à l'échelle de l'établissement",
        },
        {
            "poste": "Responsable RNCP / Certifications",
            "alternatives": ["Référent qualité", "Responsable Qualiopi"],
            "priorite": 3,
            "raison": "Cadrage Qualiopi / preuve d'évaluation pour la certification",
        },
    ],
    "nomination_dg": [
        {
            "poste": "Le(la) nouveau(elle) directeur(rice) directement",
            "alternatives": ["Directeur(rice) général(e)", "Présidence"],
            "priorite": 1,
            "raison": "Fenêtre 30-90j post-prise de poste — ouvert aux nouveaux chantiers",
        },
        {
            "poste": "Directeur(rice) de cabinet / Adjoint(e)",
            "alternatives": ["Bras droit", "Chief of Staff"],
            "priorite": 2,
            "raison": "Pré-qualifie les dossiers stratégiques du nouveau directeur",
        },
        {
            "poste": "Directeur(rice) des programmes / Académique",
            "alternatives": ["Doyen", "VP Pédagogie"],
            "priorite": 3,
            "raison": "Souvent en pleine relecture de la roadmap pédagogique post-nomination",
        },
    ],
    "fusion_ecole": [
        {
            "poste": "Direction de la transition / intégration",
            "alternatives": ["Directeur(rice) général(e)", "Chief Transformation Officer"],
            "priorite": 1,
            "raison": "Coordonne l'harmonisation des process — incluant l'évaluation",
        },
        {
            "poste": "Directeur(rice) des certifications",
            "alternatives": ["Responsable Qualiopi", "Responsable RNCP"],
            "priorite": 2,
            "raison": "Doit unifier les référentiels certifs des entités fusionnées",
        },
    ],
    "rncp_nouveau": [
        {
            "poste": "Responsable RNCP / France Compétences",
            "alternatives": ["Responsable des certifications", "Référent qualité"],
            "priorite": 1,
            "raison": "Gère la passation et la traçabilité de la nouvelle certification",
        },
        {
            "poste": "Directeur(rice) pédagogique",
            "alternatives": ["Directeur(rice) des programmes", "Doyen(ne)"],
            "priorite": 2,
            "raison": "Conçoit le dispositif d'évaluation associé à la fiche RNCP",
        },
    ],

    # ─── RNCP (certificateur qui dépose une nouvelle fiche France Compétences) ─
    "rncp_open": [
        {
            "poste": "Responsable RNCP / Référent certifications",
            "alternatives": ["Responsable RS", "Responsable habilitation", "Référent France Compétences"],
            "priorite": 1,
            "raison": "Pilote la déclaration et l'animation de la fiche déposée",
        },
        {
            "poste": "Directeur(rice) qualité / Responsable Qualiopi",
            "alternatives": ["RAQ", "Référent qualité"],
            "priorite": 2,
            "raison": "Garant de la traçabilité et de l'opposabilité en audit",
        },
        {
            "poste": "Directeur(rice) pédagogique / Responsable ingénierie",
            "alternatives": ["Directeur(rice) des programmes", "Responsable ingénierie certification"],
            "priorite": 3,
            "raison": "Conçoit le dispositif d'évaluation aligné avec les blocs de compétences",
        },
    ],

    # ─── OF (Organismes de formation) ──────────────────────────────────────
    "levee_edtech": [
        {
            "poste": "Chief Product Officer / Product Director",
            "alternatives": ["VP Product", "Directeur produit"],
            "priorite": 1,
            "raison": "Decide les briques techniques après levée (white-label, infra évaluation)",
        },
        {
            "poste": "Head of Content / Pédagogie",
            "alternatives": ["Directeur pédagogique", "Head of Learning"],
            "priorite": 2,
            "raison": "Pilote la qualité pédagogique — banque de questions, certifs",
        },
    ],

    # ─── Corporate ─────────────────────────────────────────────────────────
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


def get_contacts_cibles(signal_type: str, compte: str, contact_known_nom: str | None = None, contact_known_fonction: str | None = None) -> list[dict]:
    """
    Retourne la liste de contacts cibles avec URL Sales Nav préfilled.

    Si `contact_known_nom` est fourni (cas du CSV Radar Hebdo Tosa ou
    enrichissement manuel), il est placé en priorité 0 (cible directe).
    """
    contacts = []

    # P0 : contact réel connu (CSV curated, enrichissement manuel)
    if contact_known_nom and contact_known_nom.strip() and contact_known_nom.upper() != "A ENRICHIR":
        nom = contact_known_nom.strip()
        fonction = (contact_known_fonction or "Contact identifié").strip()
        # Construire URL LinkedIn search par nom + entreprise
        keywords = f'"{nom}" {compte}'
        public_url = f"https://www.linkedin.com/search/results/people/?keywords={urllib.parse.quote(keywords)}"
        contacts.append({
            "poste": f"{nom} — {fonction}",
            "alternatives": [],
            "priorite": 0,
            "raison": "Contact identifié — cible directe",
            "sales_nav_url": public_url,
            "linkedin_public_url": public_url,
        })

    # P1, P2, P3 : typologie de postes selon signal_type
    personas = PERSONAS_BY_SIGNAL.get(signal_type, [])
    for p in personas:
        # Si on a déjà ce contact en P0, on ne re-propose pas la typologie qui matche
        if contact_known_nom and contact_known_fonction:
            if p["poste"].lower() in contact_known_fonction.lower() or contact_known_fonction.lower() in p["poste"].lower():
                continue
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


# ─────────────────────────────────────────────────────────────────────────────
# Templates EDUCATION
# ─────────────────────────────────────────────────────────────────────────────

def _salutation(contact_nom: str | None) -> str:
    """Salutation personnalisée si on a un nom, sinon générique."""
    if contact_nom and contact_nom.strip() and contact_nom.upper() != "A ENRICHIR":
        # Extraire le prénom si format "Prénom NOM" ou "Prénom Nom"
        parts = contact_nom.strip().split()
        if parts:
            prenom = parts[0]
            return f"Bonjour {prenom},"
    return "Bonjour,"


def _shorten_signal(text: str, max_chars: int = 140) -> str:
    """Raccourcit un signal_text pour intégration dans subject/body sans coupure brutale."""
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Couper sur le dernier espace pour ne pas casser un mot
    space = cut.rfind(" ")
    if space > max_chars * 0.6:
        cut = cut[:space]
    return cut.rstrip(",.;:") + "…"


def _subject_keyword(text: str, max_words: int = 6) -> str:
    """Extrait les premiers mots significatifs du signal pour le subject."""
    text = (text or "").strip()
    if not text:
        return ""
    words = text.split()
    keep = words[:max_words]
    return " ".join(keep).rstrip(",.;:")


def email_draft_accreditation(compte: str, signal_text: str, url_source: str, contact_nom: str | None = None, contact_fonction: str | None = None) -> dict:
    """Email post-accréditation/labellisation — intègre le signal spécifique."""
    sig_short = _shorten_signal(signal_text, 120)
    sig_key = _subject_keyword(signal_text, 5)
    subject = f"{compte} — {sig_key}, capitaliser avec Tosa ?" if sig_key else f"{compte} — votre labellisation, et après ?"

    body = (
        f"{_salutation(contact_nom)}\n"
        f"\n"
        f"J'ai noté votre actualité : « {sig_short} ».\n"
        f"Bravo, c'est une étape importante.\n"
        f"\n"
        f"On accompagne pas mal d'écoles dans votre cas chez Isograd. Le "
        f"point qui revient à 3 mois post-labellisation, c'est comment "
        f"capitaliser concrètement sur cette reconnaissance — au-delà du "
        f"communiqué.\n"
        f"\n"
        f"Deux leviers qu'on déploie chez nos clients labellisés :\n"
        f"\n"
        f"1. **Tosa comme preuve opposable** sur la qualité d'évaluation "
        f"des compétences numériques de vos étudiants (bureautique, code, "
        f"digital). Très bien vu en audit Qualiopi et dans les dossiers "
        f"France Compétences.\n"
        f"\n"
        f"2. **Doublement du signal extérieur** : Tosa comme argument "
        f"concret pour les candidats, les recruteurs et les classements "
        f"qui pèsent sur le programme labellisé.\n"
        f"\n"
        f"15 minutes pour vous montrer ce que ça donnerait chez {compte} ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / Tosa\n"
        f"\n"
        f"Source : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_nouvelle_formation(compte: str, signal_text: str, url_source: str, contact_nom: str | None = None, contact_fonction: str | None = None) -> dict:
    """Email post-lancement nouvelle formation — intègre le nom/contenu spécifique du programme."""
    sig_short = _shorten_signal(signal_text, 120)
    sig_key = _subject_keyword(signal_text, 6)

    # Détecter si le signal mentionne IA pour adapter l'angle Cert IA
    is_ia = any(t in signal_text.lower() for t in ["ia ", "intelligence artificielle", "artificial intelligence"])

    subject = f"{compte} — {sig_key} : quelle évaluation prévue ?" if sig_key else f"{compte} — votre nouveau programme : quel dispositif d'évaluation ?"

    if is_ia:
        bloc_cert = (
            f"\n"
            f"3. **Cert IA** — notre badge co-construit avec des écoles "
            f"partenaires pour les programmes IA. Concrètement, vos "
            f"étudiants ressortent du programme avec une certification "
            f"externe sur les compétences IA appliquées. On a une program "
            f"beta en cours, vous pourriez en faire partie.\n"
        )
    else:
        bloc_cert = ""

    body = (
        f"{_salutation(contact_nom)}\n"
        f"\n"
        f"J'ai vu votre actualité : « {sig_short} ». Beau lancement.\n"
        f"\n"
        f"Sur ce type de nouveau programme, le timing pour penser le "
        f"dispositif d'évaluation des compétences est en général la "
        f"période juste avant la première cohorte — ça permet de cadrer "
        f"proprement la maquette pédagogique et les outils.\n"
        f"\n"
        f"Chez Isograd, on opère 2 solutions complémentaires pour un "
        f"programme comme le vôtre :\n"
        f"\n"
        f"1. **Tosa** pour certifier les compétences numériques de vos "
        f"étudiants (bureautique, code, digital). Argument concret en "
        f"diplômation, sur le CV et auprès des entreprises partenaires.\n"
        f"\n"
        f"2. **ITS** pour héberger les sessions d'examen en ligne avec "
        f"banque de questions, surveillance à distance, traçabilité "
        f"Qualiopi.\n"
        f"{bloc_cert}"
        f"\n"
        f"Déploiement en 4-6 semaines, budget calibré sur le volume "
        f"étudiants. 15 minutes pour échanger sur votre cible ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / Tosa\n"
        f"\n"
        f"Source : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_nomination_dg(compte: str, signal_text: str, url_source: str, contact_nom: str | None = None, contact_fonction: str | None = None) -> dict:
    """Email post-nomination — intègre le poste précis + le contexte de l'annonce."""
    poste_label = (contact_fonction or "à la direction").strip()
    sig_short = _shorten_signal(signal_text, 130)

    if contact_nom and contact_nom.strip() and contact_nom.upper() != "A ENRICHIR":
        subject = f"Félicitations pour votre prise de poste {poste_label} chez {compte}"
    else:
        subject = f"{compte} — nouvelle direction : quels chantiers évaluation prévus ?"

    body = (
        f"{_salutation(contact_nom)}\n"
        f"\n"
        f"J'ai noté votre arrivée {poste_label} chez {compte}.\n"
        f"Contexte que j'ai vu passer : « {sig_short} ».\n"
        f"\n"
        f"Félicitations pour cette prise de poste — belle étape.\n"
        f"\n"
        f"Je me permets de vous écrire car beaucoup de directeurs récemment "
        f"nommés dans le supérieur partagent le même constat à 60-90 "
        f"jours : besoin de poser rapidement une stratégie claire sur "
        f"l'évaluation des compétences étudiants — pour répondre aux "
        f"exigences Qualiopi/RNCP et aux attentes des entreprises "
        f"partenaires.\n"
        f"\n"
        f"Chez Isograd, deux solutions utilisées par des écoles "
        f"comparables :\n"
        f"\n"
        f"1. **Tosa** — certification des compétences numériques "
        f"étudiants (bureautique, code, digital). Argument fort en "
        f"diplômation, CV, et classements.\n"
        f"\n"
        f"2. **ITS** — plateforme d'hébergement d'examens en ligne avec "
        f"proctoring et banque de questions, opposable en audit.\n"
        f"\n"
        f"15 minutes pour vous montrer ce que d'autres directions ont mis "
        f"en place dans leurs premiers mois ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / Tosa\n"
        f"\n"
        f"Source de l'info : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_rncp_nouveau(compte: str, signal_text: str, url_source: str, contact_nom: str | None = None, contact_fonction: str | None = None) -> dict:
    """Email post-nouvelle fiche RNCP — intègre l'intitulé spécifique de la fiche."""
    sig_short = _shorten_signal(signal_text, 120)
    sig_key = _subject_keyword(signal_text, 6)
    subject = f"{compte} — {sig_key} : comment vous outillez la passation ?" if sig_key else f"{compte} — votre nouvelle fiche RNCP : outillage examen ?"

    body = (
        f"{_salutation(contact_nom)}\n"
        f"\n"
        f"J'ai noté votre actualité : « {sig_short} ».\n"
        f"\n"
        f"Sur une nouvelle fiche RNCP, deux sujets pèsent vite côté "
        f"opérationnel : la passation d'épreuves à scale, et la "
        f"traçabilité des résultats (audit Qualiopi, contrôle France "
        f"Compétences).\n"
        f"\n"
        f"Isograd opère ITS, plateforme d'hébergement d'examens utilisée "
        f"par 60+ établissements pour leurs sessions de certification "
        f"RNCP. Ce qui résoud concrètement le sujet :\n"
        f"\n"
        f"- **Banque de questions** structurée par bloc de compétences "
        f"(directement aligné sur votre fiche)\n"
        f"- **Surveillance à distance** (proctoring) avec preuves "
        f"opposables\n"
        f"- **Traçabilité complète** des sessions, exportable pour audit\n"
        f"- **Génération automatique** des attestations et duplicatas\n"
        f"\n"
        f"20 minutes pour vous montrer comment ça tourne chez une école "
        f"de taille comparable à {compte} ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS\n"
        f"\n"
        f"Source : {url_source}"
    )
    return {"subject": subject, "body": body}


def email_draft_for_education(signal_type: str, compte: str, signal_text: str, url_source: str, contact_nom: str | None = None, contact_fonction: str | None = None) -> dict | None:
    """Dispatcher : retourne le bon template selon signal_type, ou None si non supporté."""
    if signal_type == "accreditation":
        return email_draft_accreditation(compte, signal_text, url_source, contact_nom, contact_fonction)
    if signal_type == "nouvelle_formation":
        return email_draft_nouvelle_formation(compte, signal_text, url_source, contact_nom, contact_fonction)
    if signal_type == "nomination_dg":
        return email_draft_nomination_dg(compte, signal_text, url_source, contact_nom, contact_fonction)
    if signal_type == "rncp_nouveau":
        return email_draft_rncp_nouveau(compte, signal_text, url_source, contact_nom, contact_fonction)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Résumé action commerciale Education — format structuré, 4 blocs
# ─────────────────────────────────────────────────────────────────────────────

ACTION_BLOCKS_EDUCATION = {
    "accreditation": {
        "angle": "Tosa = preuve opposable de la qualité d'évaluation des compétences (audit Qualiopi, France Compétences). Doublement du signal extérieur dans la promotion du programme labellisé.",
        "timing": "3 mois post-annonce — fenêtre de capitalisation médiatique encore active.",
    },
    "nouvelle_formation": {
        "angle": "Cadrer le dispositif d'évaluation AVANT la 1re cohorte : Tosa pour certifier les compétences numériques, ITS pour héberger les examens. Si programme IA → Cert IA beta possible.",
        "timing": "Avant le lancement de la 1re promo (4-6 semaines de déploiement).",
    },
    "nomination_dg": {
        "angle": "Fenêtre stratégique post-prise de poste : nouveau directeur cherche à poser sa marque. Apport rapide = Tosa pour signal externe + ITS pour structurer la passation.",
        "timing": "30-90 jours après l'annonce. Au-delà, la roadmap est figée.",
    },
    "fusion_ecole": {
        "angle": "Harmoniser les référentiels d'évaluation entre les entités fusionnées. ITS = plateforme unifiée pour tous les programmes du nouvel ensemble.",
        "timing": "6-12 mois post-annonce — phase d'intégration opérationnelle.",
    },
    "rncp_nouveau": {
        "angle": "Outillage de la passation à scale + traçabilité opposable en audit. Banque de questions par bloc, proctoring, attestations auto.",
        "timing": "Période de mise en place de la 1re session de certification (3-6 mois).",
    },
}


def format_action_education(signal_type: str, signal_text: str, action_custom: str | None = None) -> str:
    """
    Construit une action commerciale Education structurée en 4 blocs :
    - Signal détecté
    - Action concrète à mener
    - Angle pitch ITS/Tosa
    - Timing / fenêtre
    """
    sig_short = _shorten_signal(signal_text, 200) if signal_text else "(signal sans description)"
    block = ACTION_BLOCKS_EDUCATION.get(signal_type, {})
    angle = block.get("angle", "Tosa pour valoriser les compétences numériques, ITS pour standardiser l'évaluation à scale.")
    timing = block.get("timing", "À traiter sous 30 jours pour rester dans la fenêtre d'opportunité.")

    action_line = action_custom.strip() if action_custom and action_custom.strip() else "LinkedIn DM + email court FR avec one-pager Tosa adapté."

    return (
        f"📋 **Signal détecté**\n"
        f"{sig_short}\n"
        f"\n"
        f"🎯 **Action à mener**\n"
        f"{action_line}\n"
        f"\n"
        f"💡 **Angle pitch ITS/Tosa**\n"
        f"{angle}\n"
        f"\n"
        f"📅 **Timing**\n"
        f"{timing}"
    )


def email_draft_levee_edtech(compte: str, montant_raw: str, meur: float, url_source: str, signal_text: str = "") -> dict:
    """Email post-levée EdTech — angle ITS white-label + certification opposable."""
    sig_short = _shorten_signal(signal_text, 130)

    if meur >= 30:
        contexte_phrase = (
            f"Une levée à {montant_raw} s'accompagne souvent d'un pivot "
            f"vers une offre certifiante : c'est le moment où une plateforme "
            f"EdTech devient vraiment un produit B2B."
        )
    else:
        contexte_phrase = (
            f"Avec {montant_raw}, vous êtes probablement en phase de "
            f"renforcement produit et de premier go-to-market B2B."
        )

    subject = f"{compte} — votre levée + certification : partenariat ?"
    body = (
        f"Bonjour,\n"
        f"\n"
        f"Bravo pour votre levée — {montant_raw} c'est une belle étape.\n"
        f"{f'Contexte que j ai vu passer : « {sig_short} ».' + chr(10) if sig_short else ''}"
        f"\n"
        f"Je vous écris parce que sur les plateformes EdTech à votre stade, "
        f"un sujet revient souvent côté roadmap : **passer de la production "
        f"de contenu à un produit certifiant**.\n"
        f"\n"
        f"{contexte_phrase}\n"
        f"\n"
        f"Chez Isograd, on opère ITS — une plateforme de back-end "
        f"d'évaluation et de certification utilisée en white-label par des "
        f"acteurs comme vous :\n"
        f"\n"
        f"1. **Délivrance de certifications opposables** (Qualiopi, France "
        f"Compétences, dépôt RNCP) sans construire votre propre infra "
        f"d'éval\n"
        f"\n"
        f"2. **Passation à scale** (proctoring, banque de questions, "
        f"surveillance à distance) pour des volumes 100 à 100 000 "
        f"candidats/an\n"
        f"\n"
        f"3. **Traçabilité complète** des sessions, exportable en cas "
        f"d'audit France Compétences\n"
        f"\n"
        f"L'idée pour vous : votre offre EdTech reste votre marque, et "
        f"vous gagnez la dimension certifiante en quelques semaines au "
        f"lieu de 12-18 mois de R&D.\n"
        f"\n"
        f"15 minutes pour échanger sur votre roadmap certification ?\n"
        f"\n"
        f"Charles GOSSET\n"
        f"Sales Manager — Isograd / ITS\n"
        f"\n"
        f"Source : {url_source}"
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
