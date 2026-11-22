import os

import pandas as pd
from tensorflow import keras

MODELE = "mon_modele.keras"
COLONNES = ["open", "high", "low", "close", "volume", "trades"]


def predire():
    if not os.path.exists(MODELE):
        print("AVERTISSEMENT : modele absent, PRED neutre=5")
        print("PRED=5")
        return 5
    donnees = pd.read_csv(
        "donnees_entree.csv", parse_dates=["open_time"], date_format="%d/%m/%Y %H:%M"
    )
    modele = keras.models.load_model(MODELE)
    x = donnees[COLONNES].values.reshape(1, len(donnees), len(COLONNES))
    resultat = modele.predict(x, verbose=0)
    pred = int(pd.Series(resultat.flatten()).idxmax())
    print(f"PRED={pred}")
    return pred


if __name__ == "__main__":
    predire()
