# pip install requests pandas tqdm

import re
import json
import time
import requests
import pandas as pd
from tqdm import tqdm


BBOX = (2.0, 42.0, 7.8, 46.8)
TILE_SIZE = 0.25

WFS_URL = "https://data.geopf.fr/wfs/ows"
TYPE_NAME = "INRA.CARTE.SOLS:geoportail_vf"

SLEEP_BETWEEN_REQUESTS = 0.3
TIMEOUT = 60

KEYWORDS_POSITIVE = re.compile(
    r"\b(calcair\w*|dolomiti\w*)\b",
    re.IGNORECASE
)

KEYWORDS_NEGATIVE = re.compile(
    r"\b(non|sans|peu)\s+(de\s+)?(calcair\w*|dolomiti\w*)\b",
    re.IGNORECASE
)


def frange(start, stop, step):
    x = start
    while x < stop:
        yield round(x, 6)
        x += step

def make_tiles(bbox, tile_size):
    lon_min, lat_min, lon_max, lat_max = bbox
    tiles = []

    for lon in frange(lon_min, lon_max, tile_size):
        for lat in frange(lat_min, lat_max, tile_size):
            tiles.append((
                lon,
                lat,
                min(lon + tile_size, lon_max),
                min(lat + tile_size, lat_max),
            ))

    return tiles

def feature_text(feature):
    props = feature.get("properties", {})
    return " ".join(str(v) for v in props.values() if v is not None)

def is_argilo_calcaire(feature):
    text = feature_text(feature)

    has_positive = bool(KEYWORDS_POSITIVE.search(text))
    has_negative = bool(KEYWORDS_NEGATIVE.search(text))

    return has_positive and not has_negative
def fetch_tile(tile, retries=3):
    lon_min, lat_min, lon_max, lat_max = tile

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": TYPE_NAME,
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{lon_min},{lat_min},{lon_max},{lat_max},EPSG:4326",
        "OUTPUTFORMAT": "application/json",
    }

    for attempt in range(retries):
        try:
            r = requests.get(WFS_URL, params=params, timeout=TIMEOUT)

            if r.status_code != 200:
                print(f"\nHTTP {r.status_code} sur tuile {tile}")
                print(r.text[:500])
                time.sleep(2)
                continue

            return r.json()

        except Exception as e:
            print(f"\nErreur tuile {tile}, tentative {attempt + 1}/{retries}")
            print(e)
            time.sleep(2)

    return None

def main():
    tiles = make_tiles(BBOX, TILE_SIZE)

    all_features_by_id = {}
    filtered_features_by_id = {}

    for tile in tqdm(tiles):
        data = fetch_tile(tile)

        if not data:
            continue

        for feature in data.get("features", []):
            fid = feature.get("id")

            if not fid:
                fid = json.dumps(feature.get("geometry", {}), sort_keys=True)

            all_features_by_id[fid] = feature

            if is_argilo_calcaire(feature):
                filtered_features_by_id[fid] = feature

        time.sleep(SLEEP_BETWEEN_REQUESTS)

    all_features = list(all_features_by_id.values())
    filtered_features = list(filtered_features_by_id.values())


    with open("zones_completes.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": all_features}, f, ensure_ascii=False)

    with open("zones_filtrées.geojson", "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": filtered_features}, f, ensure_ascii=False)

    rows = []

    for feature in filtered_features:
        props = feature.get("properties", {})
        row = {
            "id": feature.get("id"),
            "matched_text": feature_text(feature)[:1500],
        }
        row.update(props)
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv("sols_sud_est_argilo_calcaires.csv", index=False)


if __name__ == "__main__":
    main()