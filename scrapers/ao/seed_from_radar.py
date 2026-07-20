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
from scrapers.lib.scoring import determine_tier, produit_match_for, score_ao  # noqa: E402
from scrapers.lib.actions import generate_action  # noqa: E402
from scrapers.lib.outreach import email_draft_ao, get_contacts_cibles  # noqa: E402


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

# Valeur métier à pitcher selon le CPV — angle 100% ITS (plateforme SaaS d'hébergement d'examens)
def _valeur_metier_par_cpv(cpv: str) -> str:
    """Retourne l'angle pitch ITS selon le CPV."""
    cpv = (cpv or "").strip()
    if cpv.startswith("79132"):
        return "ITS comme plateforme de passation de la certification : banque de questions, proctoring, attestations opposables en audit"
    if cpv.startswith("72416"):
        return "ITS en SaaS multi-tenant : déploiement 4-6 semaines, scalable, zéro infra à maintenir côté acheteur"
    if cpv.startswith("48190") or cpv.startswith("72212190"):
        return "ITS comme back-end éval intégrable à votre SI : banque de questions paramétrable, exports complets, multi-rôles candidat/admin/OF"
    if cpv.startswith("73111"):
        return "ITS pour la passation des batteries psychométriques : tests adaptatifs, banque de questions calibrées, rapports automatiques"
    if cpv.startswith("72"):
        return "ITS comme plateforme d'évaluation : sécurité examens, RGPD UE, accessibilité RGAA, intégration LMS/ERP"
    if cpv.startswith("805"):
        return "ATTENTION CPV formation — vérifier que le volet plateforme d'évaluation/passation est central, sinon écarter"
    if cpv.startswith("803"):
        return "ITS pour l'enseignement sup : examens dématérialisés à scale, proctoring, traçabilité Qualiopi/France Compétences"
    return "ITS : plateforme d'hébergement d'examens (tests recrutement, contrôles, certifications internes) avec correction auto et reporting"


# Concurrents ITS par segment acheteur — battle card pour le commercial
def _concurrents_par_segment(segment: str) -> str:
    if segment == "ESR":
        return "Concurrents ITS probables : Explorance (cas Neoma), EvaluationKIT, Bluepulse, Aurion (ERP scolarité), ExamSoft, Pearson VUE, Caveon"
    if segment == "Formation pro":
        return "Concurrents ITS : Eval&Go, Sphinx, plateformes LMS internes, Cornerstone, TalentSoft, Skillup"
    if segment == "Collectivités":
        return "Concurrents ITS : prestataires SIRH territoriaux, plateformes internes maison, Sphinx, EvalandGo"
    if segment == "État":
        return "Concurrents ITS : Pix (compétences numériques agents), plateformes internes ministérielles, Sphinx"
    if segment == "Consulaire":
        return "Concurrents ITS : CCI/CMA plateformes internes, EvalandGo, Sphinx, Inwicast"
    if segment == "OPCO":
        return "Concurrents ITS : plateformes internes OPCO, Sphinx, EvalandGo (rare en AO direct OPCO)"
    if segment == "FPH":
        return "Concurrents ITS : ANFH plateforme interne, plateformes hospitalières maison, Sphinx, EvalandGo"
    if segment == "UE":
        return "Concurrents ITS : ProctorU, Honorlock, ExamSoft, Caveon, Pearson VUE, Prometric"
    return "Concurrents ITS à mapper via questions de cadrage : Explorance, EvaluationKIT, Sphinx, EvalandGo, ExamSoft, plateformes internes"


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

    # Drapeau rouge peer-to-peer assessment (leçon Neoma juin 2026)
    peer_flag = ""
    if notice.get("_peer_flag"):
        kw = notice.get("_peer_keyword") or "peer assessment"
        peer_flag = (
            f"🚩 **ATTENTION — PEER ASSESSMENT DÉTECTÉ** "
            f"(mot-clé : « {kw} »)\n"
            f"Cet AO sent l'évaluation collaborative / par les pairs. "
            f"Leçon AO Neoma 2026-TIC-NBS-0008 (retrait Isograd, juin 2026) : "
            f"ce type d'AO demande du dev spécifique pour tordre ITS (rôle hybride "
            f"candidat+correcteur, algo d'affectation, note composite), et un "
            f"concurrent spécialisé est structurellement mieux placé. "
            f"**QUALIFIER en amont avant d'investir le temps de réponse.**\n\n"
        )

    action = (
        f"{peer_flag}"
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

# v5.1 — CPV cibles ITS/Tosa. Si le CPV match un de ces préfixes,
# on booste le score de +10 pts (équivalent à un keyword Tier S).
# Cas typique : un AO académique "Évaluation des enseignements" (CPV 48190)
# avec peu de mots-clés explicites doit quand même passer le seuil.
CPV_TARGET_PREFIXES = (
    "48190",     # Logiciels éducatifs (cas Neoma BS — plateforme évaluation enseignements)
    "79132",     # Services de certification (sauf 79132100 déjà exclu plus haut)
    "72416",     # Fournisseurs ASP / SaaS (souvent plateformes test SaaS)
    "72212190",  # Services de développement de logiciels PÉDAGOGIQUES (cas Paris-Saclay 2026-A009)
    "48311",     # Logiciels de gestion de documents (cibles formation continue)
    "73111",     # Services de recherche (psychométrie/évaluation) — v5.2
    "48160",     # Logiciels bibliothèque / catalogues — v5.2 (si combiné évaluation)
)
SCORE_CPV_TARGET = 10

# v5.2 — Combos composites (Céline R. — Linguiste Sémantique)
# Si plusieurs familles de mots se combinent dans le texte, on booste de +8 pts.
# Chaque entrée = liste de groupes ; un combo est trouvé si on a 1 mot dans CHAQUE groupe.
COMBOS_COMPOSITES = [
    # outil/dispositif/plateforme + numérique/digital + positionnement/orientation/évaluation/diagnostic
    [
        ["outil", "dispositif", "plateforme", "environnement", "portail", "solution"],
        ["numérique", "digital"],
        ["positionnement", "orientation", "évaluation", "diagnostic", "test"],
    ],
    # logiciel + pédagogique/éducatif/évaluation/orientation
    [
        ["logiciel", "progiciel"],
        ["pédagogique", "éducatif", "évaluation", "orientation", "examen"],
    ],
    # parcours + individualisé/sur mesure/personnalisé
    [
        ["parcours", "trajectoire"],
        ["individualisé", "sur mesure", "personnalisé", "sur-mesure"],
    ],
    # auto + évaluation/positionnement/diagnostic
    [
        ["auto"],
        ["évaluation", "positionnement", "diagnostic"],
    ],
]
SCORE_COMBO = 8
CAP_COMBO = 24  # max 3 combos cumulés

# ─────────────────────────────────────────────────────────────────────────────
# SCORING PONDÉRÉ — Comité experts ITS/Tosa (24 mai 2026)
# Recentrage strict : on cherche une PLATEFORME/OUTIL d'évaluation/certification,
# pas une prestation de conseil RH (VAE, bilan, GPEC, audit Qualiopi).
# Seuil : 8 pts cumulés (5 pts si acheteur whitelist).
# ─────────────────────────────────────────────────────────────────────────────

SCORE_THRESHOLD = 8
SCORE_THRESHOLD_WHITELIST = 3  # v5.2 — abaissé de 5 à 3 (compte ICP déjà, risque FP faible)

# Tier S — Signal direct ITS/Tosa (10 pts chacun, cap 30 pts)
KW_TIER_S = [
    "plateforme d'évaluation", "plateforme de certification",
    "plateforme d'examen", "plateforme de test", "plateforme de tests",
    "plateforme de testing", "plateforme d'hébergement d'examens",
    "solution de testing", "solution d'évaluation",
    "proctoring", "remote proctoring",
    "télésurveillance d'examens", "télésurveillance des épreuves",
    "surveillance à distance d'examens",
    "banque de questions", "item banking",
    "computer-based testing", "test delivery", "exam delivery",
    "online examination platform", "examination platform",
    "digital assessment platform", "e-assessment", "assessment software",
    # NL — marchés Benelux (TED couvre BEL/LUX/NLD depuis v5.5)
    "digitaal toetsen", "toetssoftware", "toetsplatform", "digitale examens",
    "evaluatieplatform", "evaluatie- en oefenplatform", "toetsen op afstand",
    "psychométri", "psychometri", "analyse psychométrique",
    "dématérialisation des épreuves", "passation dématérialisée",
    "épreuves dématérialisées",
    "dispositif numérique de passation",
    "session de certification", "session d'évaluation",
    "test adaptatif", "QCM en ligne", "QCM dématérialisé",
    "psychométrie", "psychometrics",
    "ingénierie d'évaluation",
    "outil de positionnement", "outil d'évaluation continue",
    "logiciel de QCM", "logiciel d'évaluation", "logiciel de test",
    # v5.1 — vocabulaire académique (cas Neoma BS / business schools / universités)
    "évaluation des enseignements", "evaluation des enseignements",
    "système d'évaluation des enseignements",
    "système d'évaluation", "système de testing",
    "modernisation du système d'évaluation",
    "automatiser l'évaluation", "automatiser les évaluations",
    "automatiser l'analyse des résultats",
    "logiciel pédagogique", "logiciels pédagogiques",
    "logiciel d'assessment", "logiciels d'assessment",
    # v5.2 — Apprentissage cas Paris-Saclay (sémantique positionnement/orientation)
    "outil de positionnement", "outil de positionnement numérique",
    "outil d'orientation", "outil d'auto-évaluation",
    "outil d'auto-positionnement",
    "outil numérique de positionnement",
    "outil de diagnostic", "outil pédagogique",
    "dispositif numérique de positionnement",
    "dispositif numérique d'évaluation",
    "dispositif numérique d'orientation",
    "environnement numérique d'évaluation",
    "portail d'évaluation",
    "plateforme d'orientation pédagogique",
    "plateforme d'orientation",
    "plateforme de positionnement",
    "plateforme de diagnostic",
    "auto-évaluation", "auto-positionnement", "auto-diagnostic",
    "grille d'auto-évaluation",
    "moteur de recommandation",
    "recommandation de parcours",
    "parcours individualisé", "parcours sur mesure",
    "parcours individualisé de formation",
    "profilage des candidats", "profilage candidats",
    "évaluation comportementale", "évaluation sommative",
    "évaluation formative", "évaluation diagnostique",
    "évaluation des aptitudes", "évaluation des pratiques professionnelles",
    "test d'aptitudes", "test d'orientation",
    "test de niveau", "tests de niveau",
    "assessment center", "assessment center digital",
    "bilan de positionnement",
    "logiciel d'orientation", "progiciel pédagogique",
    "solution de testing pédagogique",
]
SCORE_TIER_S = 10
CAP_TIER_S = 30

# Tier A — Contexte fort (5 pts chacun, cap 15 pts)
KW_TIER_A = [
    "examens en ligne", "examens à distance",
    "online examination", "online exam",
    "évaluation des compétences", "évaluation de compétences",
    "évaluation des pratiques professionnelles",
    "certification des compétences", "certification de compétences",
    "test de positionnement", "tests de positionnement",
    "compétences numériques", "DigComp",
    "TOSA", "Tosa", "PCIE", "ICDL",
    "MOS Microsoft Office Specialist",
    "skills certification", "skills assessment",
    "talent assessment platform",
    "competency framework",
]
SCORE_TIER_A = 5
CAP_TIER_A = 15

# Tier B — Mots génériques (2 pts chacun, cap 6 pts — n'est utile que combiné)
KW_TIER_B = [
    "évaluation", "certification", "examen", "assessment",
]
SCORE_TIER_B = 2
CAP_TIER_B = 6

# Concurrents — signal de remplacement (10 pts chacun, cap 20 pts)
KW_CONCURRENTS = [
    "ProctorU", "Honorlock", "Examity",
    "ExamSoft", "Caveon",
    "Eval&Go", "Tests4U",
    "Pearson Vue", "Prometric",
    "OnlineExams", "Drimify", "Skill Mirror",
    "PIX",
    # v5.1 — concurrents identifiés via attribution AO académiques
    "Explorance", "Bluepulse", "EvaluationKIT",
    "Aurion",  # ERP scolarité — souvent intégré avec plateforme évaluation
    "Course Evaluations",
    # v5.2 — comité experts (Bertrand K. + Mathilde B.)
    "Sphinx", "EvalandGo", "LimeSurvey",
    "Klaxoon", "Wooclap", "Beekast", "Plickers",
    "TalentSoft", "Talentia", "Cornerstone OnDemand",
    "Mereo", "Lattice", "Culture Amp",
]
SCORE_CONCURRENT = 10
CAP_CONCURRENT = 20

# Whitelist acheteurs — seuil abaissé à 5 pts si match
ACHETEURS_WHITELIST = [
    # Universités RCE
    "université paris-saclay", "paris-saclay",
    "sorbonne université",
    "aix-marseille université", "université aix-marseille",
    "université de lyon", "lyon 1", "lyon 2", "lyon 3",
    "université de bordeaux",
    "université de lille",
    "université de strasbourg",
    "université toulouse", "toulouse 1 capitole", "toulouse 3",
    "université de rennes", "rennes 1", "rennes 2",
    "université de nantes",
    "université grenoble alpes",
    "université de montpellier",
    "université de nice", "université côte d'azur",
    "psl", "université paris sciences et lettres",
    "université paris cité", "université paris-cité",
    "université paris 1", "université paris i",
    "université paris dauphine",
    "comue",
    # Grandes écoles
    "école polytechnique", "polytechnique",
    "centrale supélec", "centralesupélec",
    "mines paris", "mines paristech",
    "insa lyon", "insa toulouse",
    "agroparistech",
    "espci",
    "hec paris",
    "essec",
    "escp", "escp business school",
    "em lyon", "emlyon",
    "edhec",
    "sciences po",
    "skema",
    "neoma", "neoma bs", "neoma business school",
    "kedge", "kedge business school",
    "audencia",
    "grenoble ecole de management", "grenoble em", "gem",
    "tbs education", "toulouse business school",
    "iéseg", "ieseg",
    "rennes school of business", "rsb",
    "burgundy school of business",
    "ipag", "ipag business school",
    "icn business school",
    "excelia",
    "epita", "epitech", "supinfo",
    "efrei", "esiea", "esme",
    "iéna", "iena",
    # Hôpitaux universitaires
    "ap-hp", "aphp", "assistance publique - hôpitaux de paris",
    "centre hospitalier universitaire", "chu de",
    "hospices civils de lyon",
    # Ministères / État
    "ministère", "préfecture",
    "dgfip", "intérieur", "défense",
    "dinum",
    # Régions / Métropoles top
    "région île-de-france", "région ile-de-france",
    "région auvergne-rhône-alpes",
    "métropole du grand paris", "grand paris",
    "ville de paris",
    # France Compétences / Carif
    "france compétences",
    # OPCO whitelistés (volume potentiel)
    "opco atlas", "opco akto", "opco mobilités",
]

# Mots-clés négatifs : phrases qui invalident un match — KILL-SWITCH immédiat
# Comité experts 24 mai : ajout consulting RH (VAE/bilan/GPEC) + audit qualité OF.
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

    # Consulting RH — NE PAS marquer comme opportunité ITS/Tosa (comité 24 mai)
    "bilan de compétences", "bilan professionnel",
    "validation des acquis", "validation des acquis de l'expérience", "vae",
    "audit de compétences", "audit des compétences",
    "cartographie des compétences",
    "gestion prévisionnelle des emplois", "gestion prévisionnelle de l'emploi",
    "développement des compétences",

    # Audit qualité d'organisme (renouvellement Qualiopi seul = pas ITS)
    "renouvellement de certification qualiopi",
    "renouvellement de la certification qualiopi",
    "audit qualiopi", "audit de la certification qualiopi",
    "accréditation qualiopi",
    "audit iso 9001", "renouvellement iso 9001",
    "renouvellement de la certification iso",
    "renouvellement de certification iso",
    "audit qualité organisme",
    "habilitation à délivrer",
    "habilitation france compétences",

    # Référentiels (déposer ≠ acheter une plateforme)
    "fiche rncp",
    "répertoire spécifique",
    "dépôt rncp",

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
    "habilitations iam", "habilitations d'accès",
    "identity governance", "identity & access management", "identity and access management",

    # Interim management
    "interim management", "interim manager", "temporary deployment",
    "deployment of external professionals",

    # Certification financière (commissaires aux comptes, etc.)
    "certification des comptes", "certification de comptes",
    "commissaire aux comptes", "commissaires aux comptes",

    # Faux amis observés en prod (audit AO 20 juillet 2026)
    "certificats d'économies d'énergie", "certificats d'économie d'énergie",  # CEE ≠ certification de compétences
    "chèque emploi service", "chèques emploi service",                        # CESU
    "disclosure management",                                                  # reporting financier
    # Bruit NL observé (extension Benelux v5.5)
    "verbalisering",                    # PV de police numérique
    "kunstbeheer",                      # gestion de collections d'art
    "collectie informatie systeem",
    "onderwijscatalogus",               # catalogue de cours
    "leerlingvolgsysteem",              # suivi d'élèves K-12 (hors cible sup)
    "tierce maintenance",                                                     # TMA informatique
    "système de qualification des fournisseurs", "système de qualification",  # utilities (EDF/RATP)
]


# ─────────────────────────────────────────────────────────────────────────────
# Peer-to-peer assessment — LEÇON NEOMA 2026-TIC-NBS-0008 (retrait Isograd, 8 juin 2026)
#
# Les AO type « évaluation collaborative / par les pairs / peer assessment » sont
# HORS-CIBLE ITS : la plateforme demande du dev spécifique pour tordre son moteur
# (rôle hybride candidat + correcteur, algo d'affectation de copies, calcul note
# composite multi-évaluateurs). Des concurrents spécialisés (acteur montpelliérain
# notamment) sont structurellement mieux placés.
#
# On NE rejette PAS d'office — on FLAGGE pour que Charles puisse qualifier en amont
# au lieu d'investir le temps de réponse. Pénalité de score -8 pts pour faire
# descendre l'AO dans le hub, mais il reste visible avec un drapeau rouge.
# ─────────────────────────────────────────────────────────────────────────────
KW_PEER_ASSESSMENT = [
    "évaluation collaborative", "evaluation collaborative",
    "évaluation par les pairs", "evaluation par les pairs",
    "évaluation entre pairs", "evaluation entre pairs",
    "co-évaluation", "co evaluation", "coévaluation",
    "peer assessment", "peer-to-peer assessment", "peer to peer assessment",
    "peer review", "peer feedback",
    "évaluation croisée", "evaluation croisee",
    "auto-évaluation entre pairs", "auto evaluation entre pairs",
]
SCORE_PENALITE_PEER = -8  # retrancher du score total si peer assessment détecté


def _passes_metier_filter(notice: dict) -> tuple[bool, str]:
    """
    Filtre métier ITS/Tosa — logique pondérée (comité experts 24 mai).

    Algorithme :
      1. Kill-switch : CPV formation pure → rejet
      2. Kill-switch : CPV hors périmètre (signature élec, gardiennage) → rejet
      3. Kill-switch : phrase négative (VAE, bilan, GPEC, Qualiopi seul, etc.) → rejet
      4. Score pondéré :
         - Tier S (plateforme/proctoring/item banking…) = 10 pts × matches, cap 30
         - Tier A (examens à distance, TOSA, compétences numériques…) = 5 pts × matches, cap 15
         - Tier B (évaluation, certification génériques) = 2 pts × matches, cap 6
         - Concurrents (ProctorU, ExamSoft…) = 10 pts × matches, cap 20
      5. Seuil : 8 pts (5 pts si acheteur whitelist)

    Retourne (True, "ok détaillé") ou (False, "raison rejet").
    """
    cpv = (notice.get("cpv") or "").strip()
    titre = (notice.get("objet") or "").lower()
    desc = (notice.get("description") or "").lower()
    acheteur = (notice.get("acheteur") or "").lower()
    full_text = f"{titre} {desc}"

    # 1. Kill-switch CPV formation pure
    for prefix in CPV_FORMATION_PREFIXES:
        if cpv.startswith(prefix):
            return False, f"CPV {cpv} = formation (préfixe {prefix})"

    # 2. Kill-switch CPV hors périmètre
    for prefix in CPV_HORS_PERIMETRE_PREFIXES:
        if cpv.startswith(prefix):
            return False, f"CPV {cpv} hors périmètre (préfixe {prefix})"

    # 3. Kill-switch phrases négatives (VAE / bilan / GPEC / Qualiopi seul / etc.)
    for phrase in NEGATIVE_PHRASES:
        if phrase.lower() in full_text:
            return False, f"phrase négative : '{phrase}'"

    # 4. Score pondéré
    s_matches = [kw for kw in KW_TIER_S if kw.lower() in full_text]
    a_matches = [kw for kw in KW_TIER_A if kw.lower() in full_text]
    b_matches = [kw for kw in KW_TIER_B if kw.lower() in full_text]
    c_matches = [kw for kw in KW_CONCURRENTS if kw.lower() in full_text]

    s_score = min(len(s_matches) * SCORE_TIER_S, CAP_TIER_S)
    a_score = min(len(a_matches) * SCORE_TIER_A, CAP_TIER_A)
    b_score = min(len(b_matches) * SCORE_TIER_B, CAP_TIER_B)
    c_score = min(len(c_matches) * SCORE_CONCURRENT, CAP_CONCURRENT)

    # v5.1 — Boost CPV cible (+10 pts si CPV ITS-cible)
    cpv_target_match = None
    for prefix in CPV_TARGET_PREFIXES:
        if cpv.startswith(prefix):
            cpv_target_match = prefix
            break
    cpv_boost = SCORE_CPV_TARGET if cpv_target_match else 0

    # v5.2 — Boost combos composites (+8 pts par combo trouvé, cap CAP_COMBO)
    combos_matched = 0
    for combo in COMBOS_COMPOSITES:
        # Un combo matche si au moins un mot de CHAQUE groupe est dans full_text
        if all(any(w in full_text for w in groupe) for groupe in combo):
            combos_matched += 1
    combo_score = min(combos_matched * SCORE_COMBO, CAP_COMBO)

    # v5.3 — Pénalité peer-to-peer assessment (leçon Neoma juin 2026).
    # Si l'AO sent le peer assessment, on retranche -8 pts pour faire descendre
    # son rang et on flagge la notice pour que l'action commerciale porte un
    # drapeau rouge "à qualifier en amont".
    peer_matches = [kw for kw in KW_PEER_ASSESSMENT if kw.lower() in full_text]
    peer_penalty = SCORE_PENALITE_PEER if peer_matches else 0
    if peer_matches:
        # Mutation contrôlée — le drapeau est lu par _generate_ao_action en aval
        notice["_peer_flag"] = True
        notice["_peer_keyword"] = peer_matches[0]

    total = s_score + a_score + b_score + c_score + cpv_boost + combo_score + peer_penalty

    # 5. Seuil : abaissé à 5 si acheteur whitelist
    is_whitelist = any(w in acheteur for w in ACHETEURS_WHITELIST)

    # v5.4 — on stocke le détail pour le scoring aval (score_ao) au lieu de le jeter
    notice["_metier_score"] = total
    notice["_whitelist"] = is_whitelist
    threshold = SCORE_THRESHOLD_WHITELIST if is_whitelist else SCORE_THRESHOLD

    if total < threshold:
        parts = []
        if s_matches: parts.append(f"S({s_score}):{s_matches[0]}")
        if a_matches: parts.append(f"A({a_score}):{a_matches[0]}")
        if b_matches: parts.append(f"B({b_score}):{b_matches[0]}")
        if c_matches: parts.append(f"C({c_score}):{c_matches[0]}")
        if cpv_target_match: parts.append(f"CPV+{cpv_boost}:{cpv_target_match}")
        if combos_matched: parts.append(f"COMBO+{combo_score}({combos_matched})")
        summary = ", ".join(parts) if parts else "aucun match"
        wl_tag = " [acheteur whitelist]" if is_whitelist else ""
        return False, f"score {total} < seuil {threshold}{wl_tag} [{summary}]"

    # PASSE — détail des matches
    parts = []
    if s_matches: parts.append(f"S:{s_matches[0]}")
    if a_matches: parts.append(f"A:{a_matches[0]}")
    if b_matches: parts.append(f"B:{b_matches[0]}")
    if c_matches: parts.append(f"C:{c_matches[0]}")
    if cpv_target_match: parts.append(f"CPV+:{cpv_target_match}")
    if combos_matched: parts.append(f"COMBO+:{combos_matched}")
    if peer_matches: parts.append(f"🚩PEER({peer_penalty}):{peer_matches[0]}")
    wl_tag = " [WL]" if is_whitelist else ""
    return True, f"score={total}{wl_tag} ({','.join(parts)})"


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
        # v5.4 — scoring discriminant (le score du radar amont reste un plancher)
        score = max(score if n.get("score") else 0,
                    score_ao(signal_type, n.get("_metier_score"), deadline, n.get("_whitelist", False), publication_iso=publication))
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
            email_draft=email_draft_ao(acheteur, objet, deadline or "à définir", url),
            contacts_cibles=get_contacts_cibles(signal_type, acheteur),
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
