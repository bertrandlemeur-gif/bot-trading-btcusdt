# Bot de trading BTCUSDT (futures, testnet Binance)

## Paramètres de départ

- Toutes les données (CSV de suivi, journal des positions, capital) sont
  sauvegardées dans le répertoire local du script.
- Le compte utilisé est le **testnet Binance Futures**. Créer un compte sur
  [testnet.binancefuture.com](https://testnet.binancefuture.com), puis générer
  une clé API (onglet « API Key ») et reporter `API_KEY` / `API_SECRET` dans
  `parametres.py`.
- Le capital initial est fixé à **5000 $** (`CAPITAL_INITIAL` dans
  `parametres.py`), sauvegardé localement dans `capital.json` et ensuite
  synchronisé avec le solde USDT du testnet.

## Installation

```bash
pip install -r requirements.txt
```

Renseigner `API_KEY` et `API_SECRET` dans `parametres.py`.

## Fichiers générés localement

| Fichier | Contenu |
|---|---|
| `donnees_entree.csv` | 7 bougies horaires BTCUSDT (open_time en `jj/mm/aaaa hh:mm`, puis open, high, low, close, volume, trades) |
| `suivi.csv` | heure et PRED à chaque cycle |
| `journal_positions.csv` | ouvertures et fermetures de positions (heure, action, côté, sens, quantité, prix d'exécution, stop, id d'ordre, PnL) |
| `capital.json` | capital courant |

## Modèle

`mon_modele.py` charge le modèle Keras `mon_modele.keras` (à déposer dans le
même répertoire), lit `donnees_entree.csv` et affiche `PRED=<valeur>`.
Adapter la préparation des données (`reshape`, normalisation) à votre modèle :
le bot n'analyse que la ligne `PRED=...` imprimée sur la sortie standard.

## Logique du bot (bot_trading.py)

1. À chaque **H:00** : récupération des 7 dernières bougies horaires BTCUSDT,
   écriture de `donnees_entree.csv`, exécution de `mon_modele.py`, PRED
   enregistrée dans `suivi.csv`.
2. Si PRED ∈ {0, 1} : vente à découvert de BTCUSDT (futures) pour 95 % du
   capital, avec un STOP_MARKET à +4 % (pertes limitées à 4 %).
3. Si PRED ∈ {8, 9} : achat de BTCUSDT pour 95 % du capital, STOP_MARKET à −4 %.
4. À chaque **H:59:00** : annulation des ordres en attente puis fermeture
   (market, reduceOnly) de toutes les positions ouvertes.
5. Retour à l'étape 1, en boucle sans limite de temps (Ctrl+C pour arrêter).

## Lancement

```bash
python bot_trading.py
```
