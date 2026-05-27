import argparse
import json
import requests
import geopandas as gpd
import pandas as pd
from tqdm import tqdm

COMMUNES_API = "https://geo.api.gouv.fr/communes"

DEFAULT_DEPARTEMENTS = [
    "07",  # Ardèche
    "26",  # Drôme
    "84",  # Vaucluse
    "30",  # Gard
    "34",  # Hérault
    "04",  # Alpes-de-Haute-Provence
    "05",  # Hautes-Alpes
    "06",  # Alpes-Maritimes
    "83",  # Var
    "13",  # Bouches-du-Rhône
    "38",  # Isère
    "73",  # Savoie
]


def load_soil_zones(path: str) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)

    if gdf.empty:
        raise ValueError("Le fichier GeoJSON ne contient aucune zone.")

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")

    return gdf.to_crs("EPSG:4326")


def fetch_communes_for_department(dep_code: str) -> gpd.GeoDataFrame:
    params = {
        "codeDepartement": dep_code,
        "format": "geojson",
        "geometry": "contour",
        "fields": "nom,code,codeDepartement,codeRegion,population,centre",
    }

    r = requests.get(COMMUNES_API, params=params, timeout=60)
    r.raise_for_status()

    data = r.json()

    if not data.get("features"):
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs="EPSG:4326")

    return gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")


def fetch_communes(dep_codes: list[str]) -> gpd.GeoDataFrame:
    frames = []

    for dep in tqdm(dep_codes, desc="Téléchargement communes"):
        try:
            gdf = fetch_communes_for_department(dep)
            if not gdf.empty:
                frames.append(gdf)
        except Exception as e:
            print(f"Erreur département {dep}: {e}")

    if not frames:
        raise RuntimeError("Aucune commune récupérée.")

    communes = pd.concat(frames, ignore_index=True)
    communes = gpd.GeoDataFrame(communes, geometry="geometry", crs="EPSG:4326")
    communes = communes.drop_duplicates(subset=["code"])

    return communes


def main():
    parser = argparse.ArgumentParser(
        description="Trouve toutes les communes qui intersectent les zones d'un GeoJSON de sols."
    )

    parser.add_argument(
        "input_geojson",
        help="Exemple : sols_sud_est_argilo_calcaires.geojson",
    )

    parser.add_argument(
        "--departements",
        nargs="*",
        default=DEFAULT_DEPARTEMENTS,
        help="Codes départements à analyser. Exemple : --departements 07 26 30",
    )

    parser.add_argument(
        "--output",
        default="communes_dans_zones.csv",
        help="Fichier CSV de sortie.",
    )

    parser.add_argument(
        "--output-geojson",
        default="communes_dans_zones.geojson",
        help="GeoJSON de sortie avec les communes trouvées.",
    )

    args = parser.parse_args()

    zones = load_soil_zones(args.input_geojson)
    communes = fetch_communes(args.departements)

    zones_l93 = zones.to_crs("EPSG:2154")
    communes_l93 = communes.to_crs("EPSG:2154")

    intersections = gpd.overlay(
        communes_l93,
        zones_l93[["geometry"]],
        how="intersection",
        keep_geom_type=False,
    )

    if intersections.empty:
        print("Aucune commune trouvée")
        return

    intersections["surface_intersection_m2"] = intersections.geometry.area

    result = (
        intersections
        .groupby(["code", "nom", "codeDepartement"], as_index=False)
        .agg(surface_intersection_m2=("surface_intersection_m2", "sum"))
        .sort_values(["codeDepartement", "nom"])
    )

    communes_l93["surface_commune_m2"] = communes_l93.geometry.area
    result = result.merge(
        communes_l93[["code", "surface_commune_m2"]],
        on="code",
        how="left",
    )

    result["part_commune_couverte_%"] = (
        result["surface_intersection_m2"] / result["surface_commune_m2"] * 100
    ).round(2)

    result["surface_intersection_ha"] = (
        result["surface_intersection_m2"] / 10_000
    ).round(2)

    result = result[
        [
            "code",
            "nom",
            "codeDepartement",
            "surface_intersection_ha",
            "part_commune_couverte_%",
        ]
    ]

    result.to_csv(args.output, index=False, encoding="utf-8-sig")

    communes_found = communes[communes["code"].isin(result["code"])].copy()
    communes_found = communes_found.merge(result, on=["code", "nom", "codeDepartement"])
    communes_found.to_file(args.output_geojson, driver="GeoJSON")

    print("\nFichiers générés :")
    print(f"- {args.output}")
    print(f"- {args.output_geojson}")

    print("\nTop 30 communes par surface de zone intéressante :")
    print(
        result
        .sort_values("surface_intersection_ha", ascending=False)
        .head(30)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()