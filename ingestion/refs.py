"""Fetch PIHPS reference lists (tiers, commodities, provinces, cities) and regenerate seeds.

Run rarely (when PIHPS adds a city): `python -m ingestion.refs`.
Raw answers go to bronze/pihps_refs/<date>/; the seeds written are
dbt/seeds/pihps_cities.csv and dbt/seeds/pihps_commodity_names.csv.
"""

from __future__ import annotations

import csv
import json
import logging

from ingestion.config import BRONZE_DIR, SEEDS_DIR, commodities, sources
from ingestion.http import PoliteClient
from ingestion.pihps import today_wib

log = logging.getLogger(__name__)


def _get(client: PoliteClient, endpoint: str, name: str, params: dict | None = None) -> list:
    cfg = sources()["pihps"]
    r = client.get(f"{cfg['base_url']}/{cfg['endpoints'][endpoint]}", params=params)
    if r.status != 200:
        raise RuntimeError(f"{endpoint} returned HTTP {r.status}")
    out = BRONZE_DIR / "pihps_refs" / today_wib().isoformat() / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(r.body)
    return json.loads(r.body)["data"]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tiers = sources()["pihps"]["market_tiers"]  # name -> PIHPS price_type_id
    with PoliteClient() as client:
        provinces = _get(client, "provinces", "provinces")
        coms = _get(client, "commodities", "commodities")

        # city -> (name, pihps province id, tiers it reports in)
        cities: dict[int, dict] = {}
        for prov in provinces:
            for tier, code in tiers.items():
                rows = _get(
                    client, "regencies", f"regencies_p{prov['id']}_t{code}",
                    {"ref_prov_id": prov["id"], "price_type_id": code},
                )
                for c in rows:
                    entry = cities.setdefault(
                        c["id"],
                        {"name": c["name"].strip(), "pihps_province_id": prov["id"], "tiers": []},
                    )
                    entry["tiers"].append(tier)
            log.info("province %s done (%s cities so far)", prov["name"], len(cities))

    with (SEEDS_DIR / "pihps_cities.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["city_id", "city_name", "pihps_province_id", *[f"has_{t}" for t in tiers]])
        for cid in sorted(cities):
            c = cities[cid]
            w.writerow([cid, c["name"], c["pihps_province_id"], *[t in c["tiers"] for t in tiers]])

    # Grid rows carry names, not ids, so silver maps raw names -> commodity_id.
    by_pihps = {c["pihps_id"]: c["commodity_id"] for c in commodities()}
    with (SEEDS_DIR / "pihps_commodity_names.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pihps_name", "pihps_id", "commodity_id"])
        for c in coms:
            if c["cat_id"] is None:  # category header rows (level 1) are not commodities
                continue
            w.writerow([c["name"].strip(), c["id"], by_pihps[c["id"]]])
    log.info("wrote %s cities and %s commodity names", len(cities), len(by_pihps))


if __name__ == "__main__":
    main()
