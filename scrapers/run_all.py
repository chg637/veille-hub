"""
Runner principal — lance tous les scrapers et sauve les résultats.

Appelé par GitHub Actions chaque jour à 6h UTC, et utilisable manuellement.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers.lib.schema import load_signals, merge_signals, save_signals, is_purchase_signal  # noqa: E402
from scrapers.lib.triage import update_triage  # noqa: E402

logger = logging.getLogger(__name__)


def filter_purchase_signals(signals: list, scraper_name: str = "?") -> list:
    """
    Applique le filtre strict signal d'achat. Logue les rejets pour transparence.
    """
    kept = []
    for s in signals:
        ok, reason = is_purchase_signal(s)
        if ok:
            kept.append(s)
        else:
            logger.info("[%s] REJET (%s) : %s | %s", scraper_name, reason, s.compte[:30], s.titre[:70])
    return kept


def run_scraper(module_path: str, vertical: str, repo_root: Path) -> int:
    """
    Lance un scraper individuel et fusionne ses résultats dans le bon vertical.

    module_path : ex. "scrapers.of.maddyness"
    Retourne le nombre de nouveaux signaux capturés (avant dédup).
    """
    import importlib
    mod = importlib.import_module(module_path)
    try:
        new_signals = mod.scrape()
    except AttributeError:
        # Fallback : si le scraper retourne un dict {vertical: [signaux]} (Maddyness principal)
        new_signals = mod.scrape()
        if isinstance(new_signals, dict):
            total = 0
            for v, sigs in new_signals.items():
                if not sigs:
                    continue
                path = repo_root / "data" / v / "signals.json"
                existing = load_signals(path)
                merged = merge_signals(existing, sigs)
                save_signals(merged, path)
                logger.info("[%s] saved %d signals (%d new) in %s", module_path, len(merged), len(sigs), v)
                total += len(sigs)
            return total
        return 0

    # Si retour = list[Signal], on prend le vertical du 1er signal
    if isinstance(new_signals, list):
        if not new_signals:
            logger.info("[%s] no signals captured", module_path)
            return 0
        # Group by vertical (un scraper peut multi-cibler)
        by_v = {}
        for s in new_signals:
            by_v.setdefault(s.vertical, []).append(s)
        total = 0
        for v, sigs in by_v.items():
            kept = filter_purchase_signals(sigs, scraper_name=module_path)
            if not kept:
                logger.info("[%s] 0 signaux retenus sur %d (tous filtrés)", module_path, len(sigs))
                continue
            path = repo_root / "data" / v / "signals.json"
            existing = load_signals(path)
            merged = merge_signals(existing, kept)
            save_signals(merged, path)
            logger.info("[%s] saved %d signals (%d new après filtre, %d brut) in %s", module_path, len(merged), len(kept), len(sigs), v)
            total += len(kept)
        return total

    if isinstance(new_signals, dict):
        total = 0
        for v, sigs in new_signals.items():
            if not sigs:
                continue
            path = repo_root / "data" / v / "signals.json"
            existing = load_signals(path)
            merged = merge_signals(existing, sigs)
            save_signals(merged, path)
            logger.info("[%s] saved %d signals (%d new) in %s", module_path, len(merged), len(sigs), v)
            total += len(sigs)
        return total

    return 0


# Liste des scrapers à exécuter, dans l'ordre.
#
# Politique éditoriale (21 mai 2026) — simplification drastique :
# on ne garde QUE les sources qui ramènent des signaux DIRECTEMENT ACTIONNABLES
# par un commercial (compte identifié + trigger précis + action commerciale claire).
#
# ✅ ACTIFS — sources actionnables
SCRAPERS = [
    # Curated manuel — la pépite, signaux qualifiés à 100% (SKEMA, Polytechnique, etc.)
    ("scrapers.education.radar_hebdo_tosa", "education"),
    # Presse sup multi-feeds RSS (Educpros, MGE, PGE, Business Cool) — v0.7
    ("scrapers.education.presse_sup", "education"),
    # AO curated manuel — Charles ajoute lui-même les AO identifiés ailleurs
    # (centraledesmarches, LinkedIn, collègues...). data/curated/ao_curated.csv
    ("scrapers.ao.ao_curated", "ao"),
    # BOAMP direct — API officielle DILA, capte large + filtre v5.2 (résout le cas Neoma)
    ("scrapers.ao.boamp_direct", "ao"),
    # TED — Tenders Electronic Daily UE, capte les gros tickets > seuils communautaires
    # (215 k€ services pour acheteurs publics FR), donc ESR + santé publique + État central.
    ("scrapers.ao.ted_europe", "ao"),
    # France Marchés — agrégateur public français (BOAMP + JOUE + profils acheteurs).
    # Site protégé anti-bot, scrape via Apify rag-web-browser. Skip propre si APIFY_TOKEN absent.
    ("scrapers.ao.france_marches", "ao"),
    # Marchés publics formation/certif via Radar AO live (TED + BOAMP)
    ("scrapers.ao.seed_from_radar", "ao"),
    # Maximilien IDF — profil acheteur Île-de-France (lycées, IUT, collectivités, hôpitaux)
    # Skip propre si APIFY_TOKEN absent
    ("scrapers.ao.maximilien_idf", "ao"),
    # Profils acheteurs PLACE — catégorie EOESRI (tous ESR/recherche/innovation)
    # 1 seul scraper capte Sorbonne, Paris-Saclay, Polytechnique, HEC, ESSEC, etc.
    ("scrapers.ao.profils_place.esr_global", "ao"),
    # Profils acheteurs PLACE — catégorie ESMS (FPH : AP-HP, CHU, EHPAD publics)
    # 1 seul scraper capte tous les établissements de santé publique
    ("scrapers.ao.profils_place.fph_sante", "ao"),
    # Conférence des Grandes Écoles — uniquement les labellisations passent le filtre
    ("scrapers.education.cge", "education"),
    # Corporate — Sprint A1 — levées de fonds Series B+ (Maddyness FR + Sifted EU)
    ("scrapers.corporate.levees_rss", "corporate"),
    # Corporate — Sprint A2 — signaux marché RH (pivots concurrents + nominations) via myRHline + Parlons RH
    ("scrapers.corporate.signaux_marche_rh", "corporate"),
    # Google News RSS — nominations DRH/CHRO + plans de recrutement (≥50 postes)
    # + plans de formation IA. Les 3 signaux d'achat ITS les mieux scorés. v0.7
    ("scrapers.corporate.google_news_rh", "corporate"),
    # OF — Phase 1 — levées EdTech (Maddyness + Sifted filtrés EdTech)
    ("scrapers.of.levees_edtech", "of"),
    # Presse formation pro RSS (Centre Inffo, Digiformag) — levées/rachats OF,
    # nouvelles offres certif/bureautique/IA, actu Qualiopi. v0.8
    ("scrapers.of.presse_of", "of"),
    # RNCP — nouvelles fiches RNCP/RS via data.gouv.fr (France Compétences)
    # Vertical dédié distinct de OF : ici = certificateurs qui déposent.
    ("scrapers.of.france_competences", "rncp"),
]

# ❌ DÉSACTIVÉS — sources de contenu éditorial sans signal d'achat direct
# (gardés en commentaire pour réactivation rapide si besoin)
#
# ("scrapers.of.maddyness", "of"),               # levées startup IA — pas un signal Tosa direct
# ("scrapers.of.maddyness_edtech", "of"),        # flux abandonné par Maddyness (articles 2018)
# ("scrapers.education.hec_paris", "education"), # séminaires, débats — faux positifs récurrents
# ("scrapers.education.escp", "education"),      # classements/conférences académiques
# ("scrapers.education.hceres", "education"),    # évalue la recherche, pas la formation pro
# ("scrapers.corporate.myrhline", "corporate"),  # tribunes, analyses macro
# ("scrapers.corporate.parlonsrh", "corporate"), # tribunes, articles de fond
#
# Sources futures à brancher en S3-S4 (vraiment actionnables) :
# ("scrapers.corporate.linkedin_nominations", "corporate"),  # nominations CHRO via Apify
# ("scrapers.corporate.aef_rh", "corporate"),                # AEF RH avec creds
# ("scrapers.of.france_competences", "of"),                  # nouvelles fiches RNCP


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    repo_root = Path(__file__).resolve().parent.parent

    # Reset les signals.json au début de chaque run : on ne veut garder QUE
    # les signaux produits par les scrapers actifs du run actuel. Sinon, quand on
    # désactive un scraper, ses anciens signaux restent à vie via merge_signals.
    for v in ("education", "of", "rncp", "corporate", "ao"):
        path = repo_root / "data" / v / "signals.json"
        path.parent.mkdir(parents=True, exist_ok=True)  # crée data/{v}/ si absent
        path.write_text("[]\n", encoding="utf-8")
        logger.info("Reset %s à []", path.relative_to(repo_root))

    grand_total = 0
    for module_path, vertical in SCRAPERS:
        logger.info("===== Running %s =====", module_path)
        try:
            n = run_scraper(module_path, vertical, repo_root)
            grand_total += n
        except Exception as e:
            logger.error("Scraper %s failed: %s", module_path, e, exc_info=True)

    logger.info("==== DONE — %d new signals captured across all scrapers ====", grand_total)

    # Maintenance du triage (Traité/Ignoré posés depuis le hub) : last_seen + purge.
    # data/triage.json n'est volontairement PAS reset en début de run.
    update_triage(repo_root)

    # Écrire le metadata du run (timestamp UTC) pour affichage côté hub
    meta_path = repo_root / "data" / "_meta.json"
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    meta = {
        "last_run_utc": now_utc.isoformat(),
        "last_run_iso": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_signals": grand_total,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote meta to %s : %s", meta_path.relative_to(repo_root), meta["last_run_iso"])


if __name__ == "__main__":
    main()
