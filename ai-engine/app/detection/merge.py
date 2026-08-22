"""Fusion des détections et résolution des chevauchements.

Les deux familles (règles, NER) produisent des empans qui se recouvrent :
« Awa Diouf née le 12/03/1990 » peut donner un NOM_PERSONNE de la NER et une
DATE_NAISSANCE de la règle, mais aussi deux candidats sur le même empan.

Ordre d'arbitrage, strict et sans exception :
  1. une détection **validée** l'emporte sur une non validée ;
  2. sinon, l'**empan le plus large** l'emporte ;
  3. sinon, le **score de confiance** le plus élevé l'emporte ;
  4. égalité résiduelle : **on conserve les deux détections**.

La règle 4 est la traduction directe de la priorité au rappel : quand le
système ne sait pas trancher, il protège davantage, jamais moins.
"""

from __future__ import annotations

from app.models import Entite, MethodeDetect


def _priorite(entite: Entite) -> tuple[int, int, float]:
    """Clé de comparaison dans l'ordre d'arbitrage documenté."""
    return (1 if entite.valide else 0, entite.longueur, round(entite.score, 6))


def _se_chevauchent(a: Entite, b: Entite) -> bool:
    return a.debut < b.fin and b.debut < a.fin


def dedupliquer(entites: list[Entite]) -> list[Entite]:
    """Supprime les doublons exacts (même type, même empan).

    Nécessaire à cause du recouvrement des fenêtres de segmentation : une
    entité proche d'une frontière est vue deux fois. On garde l'occurrence la
    plus fiable.
    """
    meilleures: dict[tuple[str, int, int], Entite] = {}
    for entite in entites:
        cle = (entite.typeEntite, entite.debut, entite.fin)
        courante = meilleures.get(cle)
        if courante is None or _priorite(entite) > _priorite(courante):
            meilleures[cle] = entite
        elif _priorite(entite) == _priorite(courante) and entite.methode != courante.methode:
            # Deux familles voient la même chose : la corroboration élève la
            # détection au rang « fusion » et renforce sa confiance.
            courante.methode = MethodeDetect.fusion
            courante.score = max(courante.score, entite.score)
    return list(meilleures.values())


def fusionner(entites: list[Entite]) -> list[Entite]:
    """Fusionne les détections des deux familles et arbitre les chevauchements."""
    if not entites:
        return []

    candidats = dedupliquer(entites)
    # Traiter les candidats les plus forts en premier rend le balayage stable :
    # un empan validé et large est accepté avant ses concurrents faibles.
    # Le tri par position d'abord, puis par priorité (tri stable), garantit un
    # résultat déterministe à priorité égale.
    candidats.sort(key=lambda e: (e.debut, e.fin, e.typeEntite))
    candidats.sort(key=_priorite, reverse=True)

    retenues: list[Entite] = []
    for candidat in candidats:
        conflits = [e for e in retenues if _se_chevauchent(e, candidat)]

        if not conflits:
            retenues.append(candidat)
            continue

        priorite_candidat = _priorite(candidat)
        perdants = [e for e in conflits if _priorite(e) < priorite_candidat]
        gagnants = [e for e in conflits if _priorite(e) > priorite_candidat]
        egalites = [
            e
            for e in conflits
            if _priorite(e) == priorite_candidat
        ]

        if gagnants:
            # Un concurrent déjà retenu domine : la corroboration inter-familles
            # est tout de même enregistrée.
            for gagnant in gagnants:
                if gagnant.methode != candidat.methode:
                    gagnant.methode = MethodeDetect.fusion
            continue

        if perdants:
            for perdant in perdants:
                if perdant.methode != candidat.methode:
                    candidat.methode = MethodeDetect.fusion
                retenues.remove(perdant)
            retenues.append(candidat)
            continue

        # Égalité résiduelle (règle 4) : on conserve la détection, sauf si
        # c'est strictement le même empan et le même type — déjà dédupliqué.
        doublon = any(
            e.typeEntite == candidat.typeEntite
            and e.debut == candidat.debut
            and e.fin == candidat.fin
            for e in egalites
        )
        if not doublon:
            retenues.append(candidat)

    retenues.sort(key=lambda e: (e.debut, e.fin))
    return retenues
