import re
import pandas as pd

"""
Creates a vehicle fleet based on a default vehicle type for the dummy passenger mode
"""

def configure(context):
    context.stage("synthesis.population.enriched")

def execute(context):
    df_persons = context.stage("synthesis.population.enriched")

    modes = ("carpooling", "carsharing", "taxi")
    df_vehicle_types = pd.DataFrame.from_records([
        {
            "type_id": "default_%s" % mode,
            "nb_seats": 4,
            "length": 5.0,
            "width": 1.0,
            "pce": 1.0,
            "mode": mode,
            "hbefa_cat": "pass. car",
            "hbefa_tech": "average",
            "hbefa_size": "average",
            "hbefa_emission": "average",
            "cnossos_cat": "1",
        }
        for mode in modes
    ])

    frames = []
    for mode in modes:
        df_mode = df_persons[["person_id"]].copy()
        df_mode = df_mode.rename(columns={"person_id": "owner_id"})
        df_mode["mode"] = mode
        df_mode["vehicle_id"] = df_mode["owner_id"].astype(str) + ":" + mode
        df_mode["type_id"] = "default_%s" % mode
        df_mode["critair"] = "Crit'air 1"
        df_mode["technology"] = "Gazole"
        df_mode["age"] = 0
        df_mode["euro"] = 6
        frames.append(df_mode)

    df_vehicles = pd.concat(frames, ignore_index=True)

    return df_vehicle_types, df_vehicles