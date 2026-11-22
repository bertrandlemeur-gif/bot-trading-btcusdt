import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL

from parametres import (
    ALLOCATION,
    CAPITAL_INITIAL,
    COLONNES,
    FORMAT_DATE,
    INTERVALLE,
    PERIODES,
    PRED_ACHAT,
    PRED_VENTE,
    STOP_PCT,
    SYMBOL,
    API_KEY,
    API_SECRET,
)

REPERTOIRE = os.path.dirname(os.path.abspath(__file__))
FICHIER_DONNEES = os.path.join(REPERTOIRE, "donnees_entree.csv")
FICHIER_SUIVI = os.path.join(REPERTOIRE, "suivi.csv")
FICHIER_POSITIONS = os.path.join(REPERTOIRE, "journal_positions.csv")
FICHIER_CAPITAL = os.path.join(REPERTOIRE, "capital.json")

client = Client(API_KEY, API_SECRET, testnet=True)
_filtres_cache = None


def journaliser(message):
    print(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] {message}", flush=True)


def charger_capital():
    if os.path.exists(FICHIER_CAPITAL):
        try:
            with open(FICHIER_CAPITAL, "r", encoding="utf-8") as fichier:
                return float(json_load(fichier).get("capital", CAPITAL_INITIAL))
        except (ValueError, OSError):
            pass
    sauvegarder_capital(CAPITAL_INITIAL)
    return CAPITAL_INITIAL


def json_load(fichier):
    import json

    return json.load(fichier)


def sauvegarder_capital(capital):
    import json

    with open(FICHIER_CAPITAL, "w", encoding="utf-8") as fichier:
        json.dump({"capital": capital, "maj": datetime.now().strftime(FORMAT_DATE)}, fichier)


def rafraichir_capital():
    capital = charger_capital()
    try:
        soldes = client.futures_account_balance()
        for solde in soldes:
            if solde.get("asset") == "USDT":
                capital = float(solde.get("balance", capital))
                break
    except Exception as erreur:
        journaliser(f"Solde indisponible, capital local conserve : {erreur}")
    sauvegarder_capital(capital)
    return capital


def infos_filtres():
    global _filtres_cache
    if _filtres_cache is None:
        for symbole in client.futures_exchange_info()["symbols"]:
            if symbole["symbol"] == SYMBOL:
                _filtres_cache = {f["filterType"]: f for f in symbole["filters"]}
                break
    return _filtres_cache


def arrondi_pas(valeur, pas):
    try:
        pas_decimal = Decimal(str(pas))
        if pas_decimal <= 0:
            return valeur
        return float((Decimal(str(valeur)) // pas_decimal) * pas_decimal)
    except (InvalidOperation, ValueError):
        return valeur


def recuperer_donnees():
    brutes = client.futures_klines(
        symbol=SYMBOL, interval=INTERVALLE, limit=PERIODES
    )
    colonnes_brutes = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    donnees = pd.DataFrame(brutes, columns=colonnes_brutes)
    donnees["open_time"] = pd.to_datetime(
        donnees["open_time"], unit="ms"
    ).dt.strftime(FORMAT_DATE)
    donnees[COLONNES] = donnees[COLONNES].apply(pd.to_numeric)
    donnees = donnees[["open_time"] + COLONNES]
    donnees = donnees.sort_values("open_time", key=lambda s: pd.to_datetime(s, format=FORMAT_DATE))
    donnees.to_csv(FICHIER_DONNEES, index=False)
    journaliser(f"Donnees enregistrees dans {FICHIER_DONNEES}")
    return donnees


def executer_modele():
    try:
        resultat = subprocess.run(
            [sys.executable, "mon_modele.py"],
            cwd=REPERTOIRE,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (subprocess.TimeoutExpired, OSError) as erreur:
        journaliser(f"Echec de mon_modele.py : {erreur}")
        return None
    sortie = (resultat.stdout or "") + (resultat.stderr or "")
    correspondance = re.search(r"PRED\s*[:=]\s*(-?\d+)", sortie)
    if correspondance is None:
        journaliser(f"PRED introuvable dans la sortie de mon_modele.py : {sortie.strip()[:200]}")
        return None
    return int(correspondance.group(1))


def ajouter_ligne(fichier, valeurs, entetes):
    entete_existe = os.path.exists(fichier)
    with open(fichier, "a", encoding="utf-8", newline="") as sortie:
        pd.DataFrame([dict(zip(entetes, valeurs))]).to_csv(
            sortie, header=not entete_existe, index=False
        )


def ecrire_suivi(heure, pred):
    ajouter_ligne(FICHIER_SUIVI, [heure, pred], ["heure", "PRED"])
    journaliser(f"Suivi : {heure} / PRED={pred}")


def journal_position(action, cote, sens, quantite, prix_exec, stop_prix, ordre_id, pnl=""):
    ajouter_ligne(
        FICHIER_POSITIONS,
        [
            datetime.now().strftime(FORMAT_DATE),
            action,
            cote,
            sens,
            quantite,
            prix_exec,
            stop_prix,
            ordre_id,
            pnl,
        ],
        ["heure", "action", "cote", "sens", "quantite", "prix_exec", "stop_prix", "ordre_id", "pnl"],
    )


def prix_marche():
    return float(client.futures_mark_price(symbol=SYMBOL)["markPrice"])


def ouvrir_position(sens, prix_reference):
    capital = rafraichir_capital()
    filtres = infos_filtres()
    pas_lot = filtres["LOT_SIZE"]["stepSize"]
    pas_prix = filtres["PRICE_FILTER"]["tickSize"]

    prix = prix_marche()
    quantite = arrondi_pas(ALLOCATION * capital / prix, pas_lot)
    if quantite <= 0:
        journaliser("Quantite nulle, ouverture ignoree")
        return

    cote = SIDE_BUY if sens == "ACHAT" else SIDE_SELL
    ordre = client.futures_create_order(
        symbol=SYMBOL,
        side=cote,
        type="MARKET",
        quantity=str(quantite),
        newOrderRespType="RESULT",
    )
    prix_exec = float(ordre.get("avgPrice") or prix)
    multiplicateur = (1 + STOP_PCT) if sens == "VENTE" else (1 - STOP_PCT)
    stop_prix = arrondi_pas(prix_exec * multiplicateur, pas_prix)
    cote_stop = SIDE_SELL if sens == "ACHAT" else SIDE_BUY
    client.futures_create_order(
        symbol=SYMBOL,
        side=cote_stop,
        type="STOP_MARKET",
        stopPrice=str(stop_prix),
        closePosition="true",
    )
    journal_position(
        "OUVERTURE", SYMBOL, sens, quantite, prix_exec, stop_prix, ordre.get("orderId", "")
    )
    journaliser(
        f"OUVERTURE {sens} {quantite} {SYMBOL} a {prix_exec}, STOP a {stop_prix} (-{STOP_PCT:.0%})"
    )


def fermer_toutes_positions():
    try:
        client.futures_cancel_all_open_orders(symbol=SYMBOL)
    except Exception as erreur:
        journaliser(f"Annulation des ordres en attente : {erreur}")
    try:
        positions = client.futures_position_information(symbol=SYMBOL)
    except Exception as erreur:
        journaliser(f"Lecture des positions impossible : {erreur}")
        return
    for position in positions:
        montant = float(position.get("positionAmt", 0))
        if montant == 0:
            continue
        sens = "VENTE" if montant > 0 else "ACHAT"
        cote = SIDE_SELL if montant > 0 else SIDE_BUY
        try:
            ordre = client.futures_create_order(
                symbol=SYMBOL,
                side=cote,
                type="MARKET",
                quantity=str(abs(montant)),
                reduceOnly="true",
                newOrderRespType="RESULT",
            )
        except Exception as erreur:
            journaliser(f"Fermeture impossible : {erreur}")
            continue
        prix_exec = float(ordre.get("avgPrice") or 0)
        pnl = position.get("unRealizedProfit", "")
        journal_position(
            "FERMETURE", SYMBOL, sens, abs(montant), prix_exec, "", ordre.get("orderId", ""), pnl
        )
        journaliser(f"FERMETURE {sens} {abs(montant)} {SYMBOL} a {prix_exec}, PnL={pnl}")
    rafraichir_capital()


def cycle_ouverture():
    heure = datetime.now().strftime(FORMAT_DATE)
    try:
        donnees = recuperer_donnees()
        pred = executer_modele()
        ecrire_suivi(heure, pred)
        if pred is None:
            return
        dernier_prix = float(donnees["close"].iloc[-1])
        if pred in PRED_VENTE:
            ouvrir_position("VENTE", dernier_prix)
        elif pred in PRED_ACHAT:
            ouvrir_position("ACHAT", dernier_prix)
        else:
            journaliser(f"PRED={pred} : aucune action")
    except Exception as erreur:
        journaliser(f"Erreur pendant le cycle d'ouverture : {erreur}")


def prochain_top(minute):
    maintenant = datetime.now()
    candidat = maintenant.replace(second=0, microsecond=0, minute=minute)
    if candidat <= maintenant:
        candidat += timedelta(hours=1)
    return candidat


def main():
    journaliser("Demarrage du bot sur le testnet Binance (futures)")
    charger_capital()
    try:
        client.futures_change_leverage(symbol=SYMBOL, leverage=1)
        client.futures_change_margin_type(symbol=SYMBOL, marginType="ISOLATED")
    except Exception as erreur:
        journaliser(f"Configuration du compte ignoree : {erreur}")

    t_ouverture = prochain_top(0)
    t_fermeture = prochain_top(59)
    while True:
        maintenant = datetime.now()
        if maintenant >= t_ouverture:
            t_ouverture += timedelta(hours=1)
            cycle_ouverture()
        if datetime.now() >= t_fermeture:
            t_fermeture += timedelta(hours=1)
            fermer_toutes_positions()
        cible = min(t_ouverture, t_fermeture)
        attente = (cible - datetime.now()).total_seconds()
        if attente > 0:
            time.sleep(min(attente, 60))


if __name__ == "__main__":
    main()
