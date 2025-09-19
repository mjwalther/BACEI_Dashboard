import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import matplotlib.pyplot as plt
import math
import numpy as np
import requests
import plotly.express as px
import plotly.io as pio
import plotly.graph_objects as go
import os
import json, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import re
from data_mappings import state_code_map, series_mapping, series_mapping_v2, bay_area_counties, regions, office_metros_mapping, rename_mapping, color_map, sonoma_mapping, us_series_mapping
series_mapping.setdefault("states", state_code_map)

# Try to load environment variables from a local .env file (for local dev).
# If dotenv isn't installed, just skip without failing.
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Flag to detect if running in CI (Continuous Integration) mode.
ON_CI = os.getenv("DASHBOARD_BUILD") == "1"

def _warn(msg):
    """
    Show a warning depending on the environment:
    - In CI: print to logs
    - Locally: display a Streamlit warning in the UI
    """
    if ON_CI:
        print(f"[build warning] {msg}")
    else:
        st.warning(msg)

def get_secret(name: str) -> str | None:
    """
    Retrieve a secret value in the following order:
    1. Environment variable (os.getenv)
    2. Streamlit secrets manager (st.secrets)
    Returns None if not found.
    """
    val = os.getenv(name)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets[name]
    except Exception:
        return None

# Load required secrets
BLS_API_KEY = get_secret("BLS_API_KEY")                 # BLS API key
PREBUILT_BASE_URL = get_secret("PREBUILT_BASE_URL")     # URL for prebuilt data

if not BLS_API_KEY:
    st.error("Missing BLS_API_KEY. Set it as an environment variable or Streamlit secret.")
    st.stop()

# Directory where generated artifacts (parquet, JSON, etc.) are stored.
PAGES_OUT = Path("docs/data_build")
PAGES_OUT.mkdir(parents=True, exist_ok=True)

# Re-check PREBUILT_BASE_URL directly from env vars (default to blank if not set).
PREBUILT_BASE_URL = os.getenv(
    "PREBUILT_BASE_URL",
    ""  # Leave empty → use local files instead of remote
)

def _write_parquet(df, name: str):
    """
    Save a DataFrame as a .parquet file into docs/data_build/.
    - Removes any existing file with the same name before writing.
    - Uses the provided 'name' as the filename stem.
    """
    (PAGES_OUT / f"{name}.parquet").unlink(missing_ok=True)
    df.to_parquet(PAGES_OUT / f"{name}.parquet", index=False)

def _read_parquet(name: str):
    """
    Read a .parquet file into a pandas DataFrame.
    - If PREBUILT_BASE_URL is set, load remotely from GitHub Pages / CDN.
    - Otherwise, load from the local docs/data_build/ directory.
    """
    import pandas as pd
    if PREBUILT_BASE_URL:
        # Remote read (production / GitHub Pages)
        return pd.read_parquet(f"{PREBUILT_BASE_URL}/data_build/{name}.parquet")
    # Local read (development / CI builds)
    return pd.read_parquet(PAGES_OUT / f"{name}.parquet")

def _write_version():
    """
    Write a version.json file into docs/data_build/ with metadata:
    - last_updated_unix: current time as a Unix timestamp
    - last_updated_utc: current time in UTC (ISO 8601 format)
    Used to track when data artifacts were last generated.
    """
    (PAGES_OUT / "version.json").write_text(json.dumps({
        "last_updated_unix": int(time.time()),
        "last_updated_utc": pd.Timestamp.utcnow().isoformat()
    }), encoding="utf-8")


# === CSV + Manifest support ===
CSV_OUT = PAGES_OUT / "csv"
CSV_OUT.mkdir(parents=True, exist_ok=True)

_manifest_rows = []

def _write_csv(df, name: str):
    """docs/data_build/csv/{name}.csv"""
    out = CSV_OUT / f"{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    df.to_csv(out, index=False)

def _manifest_add(df, name: str, description: str | None = None):
    import hashlib, json
    target = CSV_OUT / f"{name}.csv"
    try:
        sha256 = hashlib.sha256(target.read_bytes()).hexdigest()
    except Exception:
        sha256 = ""
    schema = [{"name": c, "dtype": str(df[c].dtype)} for c in df.columns]
    _manifest_rows.append({
        "file": f"csv/{name}.csv",              # relative to data_build/
        "parquet": f"{name}.parquet",
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "sha256": sha256,
        "schema_json": json.dumps(schema, ensure_ascii=False),
        "description": (description or "").strip(),
        "generated_utc": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

def _write_manifest():
    if _manifest_rows:
        pd.DataFrame(_manifest_rows).to_csv(PAGES_OUT / "manifest.csv", index=False)

def _write_artifacts(df, name: str, description: str | None = None):
    """Write parquet + csv and record in manifest."""
    _write_parquet(df, name)
    _write_csv(df, name)
    _manifest_add(df, name, description)
# === end CSV + Manifest support ===


# ---------- Office/Tech by Metro export ----------
def build_metros_office_sector_employment_df_exact(api_key: str) -> pd.DataFrame:
    """
    Returns a tidy DataFrame that mirrors the chart's calculations for all UI timeframes.
    Columns:
      ['metro','timeframe','baseline_date','latest_date',
       'baseline_value','latest_value','net_change','pct_change']
    """
    import requests
    from datetime import datetime

    try:
        # Expect mapping: {series_id: (metro, sector)}
        from data_mappings import office_metros_mapping
    except Exception as e:
        raise RuntimeError("Could not import office_metros_mapping from data_mappings.py") from e

    # ---- Step 1: Fetch BLS data in batches of 25  ----
    series_ids = list(office_metros_mapping.keys())
    all_series = []
    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i:i+25]
        payload = {
            "seriesid": chunk,
            "startyear": "2020",
            "endyear": str(datetime.now().year),
            "registrationKey": api_key
        }
        resp = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json=payload, timeout=30)
        resp.raise_for_status()
        js = resp.json()
        if "Results" in js and "series" in js["Results"]:
            all_series.extend(js["Results"]["series"])
        else:
            # Soft-fail; keep going (same spirit as st.warning in UI)
            print(f"[build warning] No data returned for batch {(i//25)+1}")

    # ---- Step 2: Parse to long rows (exact parsing rules) ----
    recs = []
    for series in all_series:
        sid = series.get("seriesID")
        if sid not in office_metros_mapping:
            continue
        metro, sector = office_metros_mapping[sid]
        for entry in series.get("data", []):
            if entry.get("period") == "M13":
                continue  # annual
            try:
                # date via "year"+"periodName" (e.g., "2024"+"June")
                date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                # values (thousands) -> jobs; remove commas then *1000
                value = float(entry["value"].replace(",", "")) * 1000.0
                if pd.notnull(date):
                    recs.append({"metro": metro, "sector": sector, "date": date, "value": value})
            except Exception:
                continue

    df = pd.DataFrame(recs)
    if df.empty:
        # Keep behavior consistent: an empty export is allowed but flagged.
        print("[build warning] No valid data records could be processed for office/tech export.")
        return df

    # Normalize dates to period start like the chart
    df["date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()

    # ---- Step 3: Timeframes and baseline selection (exactly like the chart) ----
    timeframes = ["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"]
    months_map = {"6 Months": 6, "12 Months": 12, "18 Months": 18, "24 Months": 24, "36 Months": 36}

    data_last = pd.to_datetime(df["date"].max()).to_period("M").to_timestamp()

    # Choose baseline_target for each timeframe, then pick the NEAREST available date overall
    available_dates = df["date"].unique()

    def _nearest_date(target: pd.Timestamp) -> pd.Timestamp:
        return min(available_dates, key=lambda x: abs(x - target))

    tf_baselines: dict[str, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for tf in timeframes:
        if tf == "Since COVID-19":
            baseline_target = pd.to_datetime("2020-02-01")
        else:
            n_months = months_map[tf]
            # chart uses (data_last - (n-1) months), aligned to month start
            baseline_target = (data_last - pd.DateOffset(months=n_months - 1)).to_period("M").to_timestamp()
        baseline_date = _nearest_date(baseline_target)
        tf_baselines[tf] = (baseline_date, data_last)

    # ---- Step 4: Aggregate Office/Tech totals per metro (same sectors list) ----
    office_sectors = {"Information", "Financial and Business Services"}  # placeholder, replaced below
    # EXACT list used in chart:
    office_sectors = ["Information", "Financial Activities", "Professional and Business Services"]

    # For speed, precompute per-date totals (sector filter applied)
    df_office = df[df["sector"].isin(office_sectors)].copy()

    results = []
    for tf in timeframes:
        baseline_date, latest_date = tf_baselines[tf]

        baseline_totals = (
            df_office[df_office["date"] == baseline_date]
            .groupby("metro", as_index=True)["value"]
            .sum()
        )
        latest_totals = (
            df_office[df_office["date"] == latest_date]
            .groupby("metro", as_index=True)["value"]
            .sum()
        )

        # "Common metros" logic — only include metros with both dates present
        common_metros = sorted(list(set(baseline_totals.index) & set(latest_totals.index)))
        for m in common_metros:
            base = float(baseline_totals[m])
            latest = float(latest_totals[m])
            net_change = latest - base
            pct_change = (net_change / base * 100.0) if base > 0 else float("nan")
            results.append({
                "metro": m,
                "timeframe": tf,
                "baseline_date": baseline_date.date().isoformat(),
                "latest_date": latest_date.date().isoformat(),
                "baseline_value": base,
                "latest_value": latest,
                "net_change": net_change,
                "pct_change": pct_change,
            })

    out = pd.DataFrame(results).sort_values(["timeframe", "metro"]).reset_index(drop=True)
    return out
# ---------- end Office/Tech by Metro export ----------


def build_all_tables():
    """
    Fetch, process, and persist all core datasets required for the dashboard.

    This function orchestrates the execution of multiple specialized fetching
    and processing routines (e.g., Bay Area payroll, Sonoma payroll, U.S. payroll,
    unemployment, industry exports, office/tech metros). Each resulting DataFrame
    is written to disk (CSV/Parquet + metadata) via `_write_artifacts` and added
    to an in-memory dictionary for immediate downstream use.

    Behavior:
        - Calls region-specific fetch functions (Bay Area, Sonoma, Napa, U.S., states).
        - Processes unemployment and industry-level job recovery data.
        - Builds derived datasets such as office/tech metro employment.
        - Each dataset is wrapped in error handling; failures log a warning
          instead of halting the entire build.
        - Updates `manifest.csv` and `version.json` to reflect available artifacts.
        - In CI mode (`ON_CI`), raises an error if no manifest rows were produced.

    Returns:
        dict[str, pd.DataFrame]: A dictionary mapping dataset keys
        (e.g., "bay_area_payroll", "us_payroll", "industry_job_recovery")
        to their corresponding processed DataFrames.
    """
    tables = {}

    try:
        bay_df = fetch_bay_area_payroll_data()
        if bay_df is not None:
            _write_artifacts(bay_df, "bay_area_payroll", "Bay Area Non-Farm Payroll Employment by Month")
            tables["bay_area_payroll"] = bay_df

    except Exception as e:
        _warn(f"Build: failed bay_area_payroll: {e}")

    try:
        sonoma_df = fetch_sonoma_payroll_data()
        if sonoma_df is not None:
            # _write_parquet(sonoma_df, "sonoma_payroll")
            _write_artifacts(sonoma_df, "sonoma_payroll", "Sonoma Non-Farm Payroll Employment by Month")
            tables["sonoma_payroll"] = sonoma_df
    # except Exception as e:
    #     st.warning(f"Build: failed sonoma_payroll: {e}")
    except Exception as e:
        _warn(f"Build: failed sonoma_payroll: {e}")

    try:
        napa_df = fetch_napa_payroll_data()
        if napa_df is not None:
            # _write_parquet(napa_df, "napa_payroll")
            _write_artifacts(napa_df, "napa_payroll", "Napa Non-Farm Payroll Employment by Month")
            tables["napa_payroll"] = napa_df
    # except Exception as e:
    #     st.warning(f"Build: failed napa_payroll: {e}")
    except Exception as e:
        _warn(f"Build: failed napa_payroll: {e}")

    try:
        us_df = fetch_us_payroll_data()
        if us_df is not None:
            # _write_parquet(us_df, "us_payroll")
            _write_artifacts(us_df, "us_payroll", "U.S. Non-Farm Payroll Employment by Month")
            tables["us_payroll"] = us_df
    # except Exception as e:
    #     st.warning(f"Build: failed us_payroll: {e}")
    except Exception as e:
        _warn(f"Build: failed us_payroll: {e}")


    try:
        state_series_ids = list(series_mapping.get("states", {}).values()) if isinstance(series_mapping.get("states", {}), dict) else []
        if state_series_ids:
            states_df = fetch_states_job_data(state_series_ids)
            if states_df is not None:
                _write_artifacts(states_df, "states_payroll", "States Non-Farm Payroll Employment by Month")
                tables["states_payroll"] = states_df
    # except Exception as e:
    #     st.warning(f"Build: failed states_payroll: {e}")
    except Exception as e:
        _warn(f"Build: failed states_payroll: {e}")

    try:
        raw = fetch_unemployment_data()
        if raw:
            unemp_df = process_unemployment_data(raw)
            if unemp_df is not None:
                # _write_parquet(unemp_df, "unemployment_ca")
                _write_artifacts(unemp_df, "LAUS_Bay_Area", "CA Open Data Portal Local Area Unemployment Statistics (Bay Area only)")
                tables["LAUS_Bay_Area"] = unemp_df
    # except Exception as e:
    #     st.warning(f"Build: failed LAUS_Bay_Area: {e}")

    except Exception as e:
        _warn(f"Build: failed LAUS_Bay_Area: {e}")

    try:
        def _only_region_industry(mapping):
            # keep only {series_id: (region, industry, ...maybe extras)}
            clean = {}
            for k, v in mapping.items():
                if isinstance(v, (list, tuple)) and len(v) >= 2:
                    clean[k] = (v[0], v[1])  # normalize to first two
            return clean

        df_bay = _compute_industry_export_for_region(_only_region_industry(series_mapping), BLS_API_KEY)
        df_us  = _compute_industry_export_for_region(_only_region_industry(us_series_mapping), BLS_API_KEY)

        combined = pd.concat([df_bay, df_us], ignore_index=True) if not df_bay.empty or not df_us.empty else pd.DataFrame()

        if combined is not None and not combined.empty:
            _write_artifacts(
                combined,
                "industry_job_recovery",
                "Industry-level job recovery for Bay Area and U.S."
            )
            tables["industry_job_recovery"] = combined
        else:
            _warn("Build: industry_job_recovery produced no rows.")
    except Exception as e:
        _warn(f"Build: failed industry_job_recovery: {e}")

    try:
        metros_office_df = build_metros_office_sector_employment_df_exact(BLS_API_KEY)
        if metros_office_df is not None and not metros_office_df.empty:
            _write_artifacts(
                metros_office_df,
                "metros_office_sector_employment",
                "Office/Tech employment by metro with chart-matching baselines (6–36 months & Since COVID-19)."
            )
            tables["metros_office_sector_employment"] = metros_office_df
        else:
            _warn("Build: metros_office_sector_employment produced no rows.")
    except Exception as e:
        _warn(f"Build: failed metros_office_sector_employment: {e}")


    _write_manifest()
    _write_version()

    print(f"[build] manifest rows: {len(_manifest_rows)}") 
    if ON_CI and len(_manifest_rows) == 0:
        raise RuntimeError("No manifest rows were produced — build failed.")
    return tables

def load_prebuilt_or_fetch(name: str, fetch_fn):
    """
    Minimal change path:
    - If USE_PREBUILT=1 and a prebuilt file exists, use it
    - Otherwise call the original fetch function
    """
    use_prebuilt = os.getenv("USE_PREBUILT", "1") == "1"
    if use_prebuilt:
        try:
            return _read_parquet(name)
        except Exception:
            pass  # fall through to fetching
    return fetch_fn()


# --- Data Fetching ---

# Cache data with streamlit for 24 hours (data will be updated once a day)
# TO DO: Need a better method for having data be continuously called so as to not have loading time
@st.cache_data(ttl=86400)        
def fetch_unemployment_data():
    """
    Fetches labor force data from the California Open Data Portal (LAUS dataset).

    Gets full dataset in chunks from the API endpoint, handling pagination and connection.
    Returns a list of records containing monthly employment, unemployment, labor force size,
    and unemployment rates for California counties.

    Returns:
        list[dict] or None: A list of record dictionaries if successful, or None if an error occurs.
    """

    API_ENDPOINT = "https://data.ca.gov/api/3/action/datastore_search"
    RESOURCE_ID = "b4bc4656-7866-420f-8d87-4eda4c9996ed"

    try:
        # Fetch total records using an API request
        response = requests.get(API_ENDPOINT, params={"resource_id": RESOURCE_ID, "limit": 1}, timeout=30)
        if response.status_code != 200:
            st.error(f"Failed to connect to API. Status code: {response.status_code}")
            return None

        total_records = response.json()["result"]["total"]
        all_data = []
        chunk_size = 10000

        # Look through total records in chunks to fetch data
        for offset in range(0, total_records, chunk_size):
            response = requests.get(API_ENDPOINT, params={
                "resource_id": RESOURCE_ID,
                "limit": min(chunk_size, total_records - offset),
                "offset": offset
            }, timeout=30)
            if response.status_code == 200:
                all_data.extend(response.json()["result"]["records"])
            else:
                st.warning(f"Failed to fetch chunk at offset {offset}")

        return all_data

    except Exception as e:
        st.error(f"Error fetching data: {str(e)}")
        return None
    

@st.cache_data(ttl=86400)
def fetch_rest_of_ca_payroll_data():
    """
    Fetches seasonally adjusted nonfarm payroll employment data for California from the U.S. Bureau of Labor Statistics (BLS).

    Uses the BLS Public API to retrieve monthly statewide employment figures from 2020 to the present. 
    The function processes the time series into a pandas DataFrame and computes the percent change in 
    employment relative to February 2020 (pre-pandemic baseline).

    Returns:
        pd.DataFrame or None: A DataFrame with columns ['date', 'value', 'pct_change'], where:
            - 'date' is a datetime object representing the month,
            - 'value' is the number of jobs (in actual counts),
            - 'pct_change' is the percent change in employment from February 2020.
            Returns None if the API call fails or data is missing.
    """

    rest_of_ca_series_ids = [
        "SMS06125400000000001",  # Bakersfield-Delano, CA
        "SMS06170200000000001",  # Chico, CA
        "SMS06209400000000001",  # El Centro, CA
        "SMS06234200000000001",  # Fresno, CA
        "SMS06252600000000001",  # Hanford-Corcoran, CA
        "SMS06310800000000001",  # Los Angeles-Long Beach-Anaheim, CA
        "SMS06329000000000001",  # Merced, CA
        "SMS06337000000000001",  # Modesto, CA
        "SMS06371000000000001",  # Oxnard-Thousand Oaks-Ventura, CA
        "SMS06398200000000001",  # Redding, CA
        "SMS06401400000000001",  # Riverside-San Bernardino-Ontario, CA
        "SMS06409000000000001",  # Sacramento-Roseville-Folsom, CA
        "SMS06415000000000001",  # Salinas, CA
        "SMS06417400000000001",  # San Diego-Chula Vista-Carlsbad, CA
        "SMS06420200000000001",  # San Luis Obispo-Paso Robles, CA
        "SMS06421000000000001",  # Santa Cruz-Watsonville, CA
        "SMS06422000000000001",  # Santa Maria-Santa Barbara, CA
        "SMS06447000000000001",  # Stockton-Lodi, CA
        "SMS06473000000000001",  # Visalia, CA
        "SMS06497000000000001",  # Yuba City, CA
    ]

    payload = {
        "seriesid": rest_of_ca_series_ids,
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload, timeout=30
        )
        data = response.json()
        if "Results" not in data or "series" not in data["Results"]:
            st.error("BLS API error: No results returned for Rest of CA.")
            return None

        all_series = []
        for series in data["Results"]["series"]:
            df = pd.DataFrame(series["data"])
            df = df[df["period"] != "M13"]
            df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
            df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
            df = df[["date", "value"]].sort_values("date")
            all_series.append(df)

        merged_df = all_series[0].copy()
        for other_df in all_series[1:]:
            merged_df = pd.merge(merged_df, other_df, on="date", how="outer", suffixes=("", "_x"))
            value_cols = [col for col in merged_df.columns if "value" in col]
            merged_df["value"] = merged_df[value_cols].sum(axis=1, skipna=True)
            merged_df = merged_df[["date", "value"]]

        baseline = merged_df.loc[merged_df["date"] == "2020-02-01", "value"]
        if baseline.empty or pd.isna(baseline.iloc[0]):
            st.warning("Missing baseline for Rest of CA.")
            return None

        baseline_value = baseline.iloc[0]
        merged_df["pct_change"] = (merged_df["value"] / baseline_value - 1) * 100
        return merged_df

    except Exception as e:
        st.error(f"Failed to fetch Rest of CA data: {e}")
        return None
    

@st.cache_data(ttl=86400)
def fetch_bay_area_payroll_data():
    """
    Fetches and aggregates nonfarm payroll employment data for selected Bay Area regions
    from the U.S. Bureau of Labor Statistics (BLS).

    Combines multiple MSA/MD series to approximate a regional Bay Area total.
    Computes percent change in employment relative to February 2020.

    Returns:
        pd.DataFrame or None: DataFrame with ['date', 'value', 'pct_change'] columns,
        or None if all data fetches fail.
    """

    series_ids = [
        "SMS06349000000000001",  # Napa MSA
        "SMS06360840000000001",  # Oakland-Fremont-Hayward MD
        "SMS06418840000000001",  # San Francisco-San Mateo-Redwood City MD
        "SMS06419400000000001",  # San Jose-Sunnyvale-Santa Clara MSA
        "SMS06420340000000001",  # San Rafael MD
        "SMS06422200000000001",  # Santa Rosa-Petaluma MSA
        "SMS06467000000000001"   # Vallejo MSA
    ]

    payload = {
        "seriesid": series_ids,
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload, timeout=30
        )
        data = response.json()
        if "Results" not in data or "series" not in data["Results"]:
            st.error("BLS API error: No results returned.")
            return None

        all_series = []
        for series in data["Results"]["series"]:
            if not series["data"]:
                st.warning(f"No data found for series ID: {series['seriesID']}")
                continue
            try:
                df = pd.DataFrame(series["data"])
                df = df[df["period"] != "M13"]  # Exclude annual average rows
                df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")

                df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
                df = df[["date", "value"]].sort_values("date")
                all_series.append(df)
            except Exception as e:
                st.warning(f"Error processing series {series['seriesID']}: {e}")

        if not all_series:
            st.error("No Bay Area payroll data could be processed.")
            return None

        # Merge all series on date by summing values
        merged_df = all_series[0].copy()
        for other_df in all_series[1:]:
            merged_df = pd.merge(merged_df, other_df, on="date", how="outer", suffixes=("", "_x"))

            # If multiple columns named 'value', sum and clean
            value_cols = [col for col in merged_df.columns if "value" in col]
            merged_df["value"] = merged_df[value_cols].sum(axis=1, skipna=True)
            merged_df = merged_df[["date", "value"]]

        merged_df = merged_df.sort_values("date")

        # Baseline = Feb 2020
        baseline = merged_df.loc[merged_df["date"] == "2020-02-01", "value"]
        if baseline.empty or pd.isna(baseline.iloc[0]):
            st.warning("No baseline value found for Bay Area (Feb 2020).")
            return None

        baseline_value = baseline.iloc[0]
        merged_df["pct_change"] = (merged_df["value"] / baseline_value - 1) * 100

        return merged_df

    except Exception as e:
        st.error(f"Failed to fetch Bay Area BLS data: {e}")
        return None
    

@st.cache_data(ttl=86400)
def fetch_sonoma_payroll_data():
    """
    SONOMA COUNTY ONLY
    """

    series_ids = [
        "SMS06422200000000001"  # Santa Rosa-Petaluma MSA  
    ]

    payload = {
        "seriesid": series_ids,
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload, timeout=30
        )
        data = response.json()
        if "Results" not in data or "series" not in data["Results"]:
            st.error("BLS API error: No results returned.")
            return None

        all_series = []
        for series in data["Results"]["series"]:
            if not series["data"]:
                st.warning(f"No data found for series ID: {series['seriesID']}")
                continue
            try:
                df = pd.DataFrame(series["data"])
                df = df[df["period"] != "M13"]  # Exclude annual average rows
                df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")

                df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
                df = df[["date", "value"]].sort_values("date")
                all_series.append(df)
            except Exception as e:
                st.warning(f"Error processing series {series['seriesID']}: {e}")

        if not all_series:
            st.error("No Sonoma payroll data could be processed.")
            return None

        # Merge all series on date by summing values
        merged_df = all_series[0].copy()
        for other_df in all_series[1:]:
            merged_df = pd.merge(merged_df, other_df, on="date", how="outer", suffixes=("", "_x"))

            # If multiple columns named 'value', sum and clean
            value_cols = [col for col in merged_df.columns if "value" in col]
            merged_df["value"] = merged_df[value_cols].sum(axis=1, skipna=True)
            merged_df = merged_df[["date", "value"]]

        merged_df = merged_df.sort_values("date")

        # Baseline = Feb 2020
        baseline = merged_df.loc[merged_df["date"] == "2020-02-01", "value"]
        if baseline.empty or pd.isna(baseline.iloc[0]):
            st.warning("No baseline value found for Sonoma (Feb 2020).")
            return None

        baseline_value = baseline.iloc[0]
        merged_df["pct_change"] = (merged_df["value"] / baseline_value - 1) * 100

        return merged_df

    except Exception as e:
        st.error(f"Failed to fetch Sonoma BLS data: {e}")
        return None
    
@st.cache_data(ttl=86400)
def fetch_napa_payroll_data():
    """
    NAPA COUNTY ONLY
    """

    series_ids = [
        "SMS06349000000000001"  # Napa MSA
    ]

    payload = {
        "seriesid": series_ids,
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload, timeout=30
        )
        data = response.json()
        if "Results" not in data or "series" not in data["Results"]:
            st.error("BLS API error: No results returned.")
            return None

        all_series = []
        for series in data["Results"]["series"]:
            if not series["data"]:
                st.warning(f"No data found for series ID: {series['seriesID']}")
                continue
            try:
                df = pd.DataFrame(series["data"])
                df = df[df["period"] != "M13"]  # Exclude annual average rows
                df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")

                df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
                df = df[["date", "value"]].sort_values("date")
                all_series.append(df)
            except Exception as e:
                st.warning(f"Error processing series {series['seriesID']}: {e}")

        if not all_series:
            st.error("No Napa payroll data could be processed.")
            return None

        # Merge all series on date by summing values
        merged_df = all_series[0].copy()
        for other_df in all_series[1:]:
            merged_df = pd.merge(merged_df, other_df, on="date", how="outer", suffixes=("", "_x"))

            # If multiple columns named 'value', sum and clean
            value_cols = [col for col in merged_df.columns if "value" in col]
            merged_df["value"] = merged_df[value_cols].sum(axis=1, skipna=True)
            merged_df = merged_df[["date", "value"]]

        merged_df = merged_df.sort_values("date")

        # Baseline = Feb 2020
        baseline = merged_df.loc[merged_df["date"] == "2020-02-01", "value"]
        if baseline.empty or pd.isna(baseline.iloc[0]):
            st.warning("No baseline value found for Sonoma (Feb 2020).")
            return None

        baseline_value = baseline.iloc[0]
        merged_df["pct_change"] = (merged_df["value"] / baseline_value - 1) * 100

        return merged_df

    except Exception as e:
        st.error(f"Failed to fetch Sonoma BLS data: {e}")
        return None
    

@st.cache_data(ttl=86400)
def fetch_california_payroll_data():
    """
    Fetches seasonally adjusted total nonfarm payroll employment for California
    (BLS series: SMS06000000000000001), computes percent change since Feb 2020.

    Returns:
        DataFrame with columns: ['date', 'value', 'pct_change']
        or None on failure.
    """
    SERIES_ID = "SMS06000000000000001"  # CA total nonfarm, SA
    payload = {
        "seriesid": [SERIES_ID],
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY,
    }

    try:
        resp = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload,
            timeout=30,
        )
        data = resp.json()
        if "Results" not in data or not data["Results"].get("series"):
            st.error("No results returned from BLS for California.")
            return None

        series = data["Results"]["series"][0]["data"]
        if not series:
            st.error("Empty series for California.")
            return None

        df = pd.DataFrame(series)
        df = df[df["period"] != "M13"]  # drop annual
        # 'year' + 'periodName' (e.g., "2024" + "August")
        df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
        # State/area payrolls are reported in thousands → scale to actual counts
        df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
        df = df[["date", "value"]].dropna().sort_values("date")

        if df.empty:
            st.error("Parsed California dataframe is empty.")
            return None

        # Baseline: prefer exact Feb 2020, else first available >= Feb 2020, else first row
        feb2020 = pd.to_datetime("2020-02-01")
        baseline_series = df.loc[df["date"] == feb2020, "value"]
        if baseline_series.empty:
            after_feb = df[df["date"] >= feb2020]
            if not after_feb.empty:
                baseline_val = after_feb.iloc[0]["value"]
            else:
                baseline_val = df.iloc[0]["value"]
        else:
            baseline_val = baseline_series.iloc[0]

        if baseline_val is None or baseline_val == 0:
            st.error("Invalid baseline for California.")
            return None

        df["pct_change"] = (df["value"] / baseline_val - 1) * 100
        return df

    except Exception as e:
        st.error(f"Failed to fetch California payroll data: {e}")
        return None


@st.cache_data(ttl=86400)
def fetch_us_payroll_data():
    """
    Fetches and processes national-level seasonally adjusted nonfarm payroll employment data
    for the United States from the U.S. Bureau of Labor Statistics (BLS) API.

    Retrieves monthly total nonfarm employment counts from January 2020 to the latest available month. 
    Calculates the percent change in employment relative to February 2020 (pre-pandemic baseline).

    Returns:
        pd.DataFrame or None: DataFrame with the following columns:
            - 'date': pandas datetime object representing each month.
            - 'value': Number of jobs (in actual counts, not thousands).
            - 'pct_change': Percent change in employment since February 2020.
        
        Returns None if the API call fails or the required data is unavailable.
    """

    SERIES_ID = "CES0000000001"  # U.S. nonfarm payroll, seasonally adjusted
    payload = {
        "seriesid": [SERIES_ID],
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload,
            timeout=30
        )
        data = response.json()
        if "Results" not in data:
            st.error("No results returned from BLS for U.S.")
            return None

        series = data["Results"]["series"][0]["data"]
        df = pd.DataFrame(series)
        df = df[df["period"] != "M13"]
        df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
        df["value"] = df["value"].astype(float) * 1000
        df = df[["date", "value"]].sort_values("date")

        baseline = df.loc[df["date"] == "2020-02-01", "value"].iloc[0]
        df["pct_change"] = (df["value"] / baseline - 1) * 100

        return df

    except Exception as e:
        st.error(f"Failed to fetch U.S. payroll data: {e}")
        return None


@st.cache_data(ttl=86400)
def fetch_states_job_data(series_ids):
    """
    Fetches and processes monthly seasonally adjusted nonfarm payroll employment data 
    for multiple U.S. states from the Bureau of Labor Statistics (BLS) API.

    Handles API limitations by batching requests in chunks of 25 series IDs. 
    For each state, calculates the percent change in employment relative to February 2020 (pre-pandemic baseline).
    Associates each series ID with its corresponding state name using the provided `state_code_map`.

    Args:
        series_ids (list of str): List of BLS series IDs representing state-level nonfarm payroll data.

    Returns:
        pd.DataFrame or None: A concatenated DataFrame containing:
            - 'date': pandas datetime object for each month.
            - 'value': Number of jobs (in actual counts, not thousands).
            - 'pct_change': Percent change in employment since February 2020.
            - 'State': Name of the U.S. state corresponding to each series.
        
        Returns None if no data is successfully fetched or processed.
    """

    def chunk_list(lst, size):
        return [lst[i:i+size] for i in range(0, len(lst), size)]

    chunks = chunk_list(series_ids, 25)  # Safe limit per API docs
    all_dfs = []
    received_ids = set()

    # Chunking API requests
    for chunk in chunks:
        payload = {
            "seriesid": chunk,
            "startyear": "2020",
            "endyear": str(datetime.now().year),
            "registrationKey": BLS_API_KEY
        }

        try:
            response = requests.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json=payload,
                timeout=30
            )
            data = response.json()
            for series in data.get("Results", {}).get("series", []):
                sid = series["seriesID"]
                received_ids.add(sid)
                state_name = next((name for name, code in state_code_map.items() if code == sid), sid)
                if not series["data"]:
                    st.warning(f"No data returned for {state_name}.")
                    continue

                df = pd.DataFrame(series["data"])
                df = df[df["period"] != "M13"]
                df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
                df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
                df = df[["date", "value"]].sort_values("date")

                # Calculate percent change from February 2020
                baseline = df.loc[df["date"] == "2020-02-01", "value"]
                if not baseline.empty:
                    df["pct_change"] = (df["value"] / baseline.iloc[0] - 1) * 100
                    df["State"] = state_name
                    all_dfs.append(df)

        except Exception as e:
            st.error(f"Error fetching chunk: {e}")

    missing = set(series_ids) - received_ids
    for sid in missing:
        state_name = next((name for name, code in state_code_map.items() if code == sid), sid)
        st.warning(f"BLS API did not return data for {state_name}.")

    return pd.concat(all_dfs, ignore_index=True) if all_dfs else None


# --- POPULATION  ---
@st.cache_data(show_spinner=False)
def load_population_data() -> tuple[pd.DataFrame, str]:
    """
    Returns (df, source_str). If df is empty, caller may show a file_uploader.
    """
    from pathlib import Path

    candidates = [
        Path("docs/data_build/County_Population.csv")
    ]
    
    for p in candidates:
        if p.exists():
            is_excel = p.suffix.lower() in (".xlsx", ".xls")
            df = _read_population_table(p, is_excel=is_excel)
            return df, str(p)
    
    return pd.DataFrame(columns=["year","region","population"]), "NOT FOUND"


def _read_population_table(file_path: Path, is_excel: bool = False) -> pd.DataFrame:
    """
    Read population data and convert from wide to long format.
    """
    try:
        if is_excel:
            df = pd.read_excel(file_path)
        else:
            df = pd.read_csv(file_path)
        
        # Convert from wide to long format
        # Melt the dataframe - Year column stays as identifier, all other columns become regions
        df_long = df.melt(
            id_vars=['Year'], 
            var_name='region', 
            value_name='population'
        )
        
        # Rename Year to year for consistency
        df_long = df_long.rename(columns={'Year': 'year'})
        
        # Clean the data
        df_long = df_long.dropna()  # Remove any missing values
        df_long['population'] = pd.to_numeric(df_long['population'], errors='coerce')  # Ensure numeric
        df_long = df_long.dropna()  # Remove any rows that couldn't be converted to numeric
        
        # Sort by region and year
        df_long = df_long.sort_values(['region', 'year']).reset_index(drop=True)
        
        return df_long
        
    except Exception as e:
        st.error(f"Error reading population data from {file_path}: {str(e)}")
        return pd.DataFrame(columns=["year","region","population"])


def _guess_bay_area_label(regions: list[str]) -> str | None:
    """
    Try to find the Bay Area 9-county column automatically.
    """
    lower = [r.lower() for r in regions]
    candidates = [
        "bay area (9-county)",
        "bay area 9-county",
        "bay area (9 county)",
        "bay area",
        "sf bay area",
    ]
    for cand in candidates:
        if cand in lower:
            idx = lower.index(cand)
            return regions[idx]
        
    # Heuristic: any region containing both "bay" and "area"
    for i, r in enumerate(lower):
        if "bay" in r and "area" in r:
            return regions[i]
    return None


def show_population_trend_chart():
    """
    Dashboard Section: Population
    Dashboard Subtab: Counties

    Renders the Population line chart with a region multiselect.
    - Defaults to Bay Area (9-County) if present, else the first region.
    """
    df, source_path = load_population_data()
    
    if df.empty:
        st.error("No population data found. Please try again later.")
        st.info("Expected file locations: docs/data_build/")
        return

    # Available regions
    regions = sorted(df["region"].dropna().unique().tolist())
    
    # Pick default = Bay Area 9-county if we can detect it
    default_region = _guess_bay_area_label(regions)
    if default_region is None and regions:
        default_region = regions[0]

    # UI controls
    selected = st.multiselect(
        "Select Region:",
        options=regions,
        default=[default_region] if default_region else [],
        key="population_region_multiselect",
    )

    # Filter
    if not selected:
        st.info("Select at least one region to display.")
        return
    
    plot_df = df[df["region"].isin(selected)].copy()

    # Plot
    fig = px.line(
        plot_df,
        x="year",
        y="population",
        color="region",
        markers=True,
        line_shape="linear",
        labels={"region": "Region"},
        color_discrete_map={"Bay Area (9-county)": "#00aca2"}
    )

    fig.update_layout(
        title=dict(
            text="<span style='font-size:26px; font-family:Avenir Black'>Population by County<br><span style='font-size:20px; color:#666; font-family:Avenir Medium'></span>",
            x=0.5,
            xanchor='center',
        ),
        height=450,
        legend=dict(orientation="h", y=-0.2),
        font=dict(family="Avenir", size=15),
        xaxis_title="Year",
        yaxis_title="Population",
        hovermode="x unified",
    )

    fig.update_xaxes(dtick=1,
                     tickformat="d",
                     title_font=dict(family="Avenir Medium", size=22, color="black"),
                     tickfont=dict(family="Avenir", size=16, color="black")
                    )
    
    fig.update_yaxes(separatethousands=True,
                     title_font=dict(family="Avenir Medium", size=22, color="black"),
                     tickfont=dict(family="Avenir", size=16, color="black")
                    )

    fig.update_traces(hovertemplate="<b>%{fullData.name}</b><br>Year: %{x}<br>Population: %{y:,}<extra></extra>")

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "county_population",
                    "scale": 10 
                }
            }
    )

    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>U.S. Census Bureau, Population Division.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    <br>
    """, unsafe_allow_html=True)


    # Download the filtered data
    csv = plot_df.sort_values(["region", "year"]).to_csv(index=False)
    st.download_button(
        "Download Data (CSV)",
        data=csv,
        file_name="population_selected_regions.csv",
        mime="text/csv",
        help="Download the data for the region(s) currently selected."
    )


# --- Data Processing ---


def process_unemployment_data(data):
    """
    Cleans and processes raw employment data from the CA Open Data Portal.

    Filters dataset to include only Bay Area counties and seasonally adjusted county-level data.
    Parses datetime column from available options. Renames key columns for clarity, sorts data,
    removes duplicates, and filters records to include only data from Feb 2020 onwards.

    Args:
        data (list[dict]): Raw records returned from the CA Open Data API.

    Returns:
        pd.DataFrame or None: A cleaned DataFrame with columns ['County', 'LaborForce', 'Employment',
        'UnemploymentRate', 'date'], or None if input data is invalid or no valid date column is found.    
    """

    if not data:
        return None

    df = pd.DataFrame(data)
    df = df[(df["Area Type"] == "County") & (df["Area Name"].isin(bay_area_counties))]

    if "Seasonally Adjusted" in df.columns:
        df = df[df["Seasonally Adjusted"] == "Y"]

    # Parse date column
    for col in ["Date_Numeric", "Date", "Period", "Month", "Year"]:
        if col in df.columns:
            df["date"] = pd.to_datetime(df[col], format="%m/%Y", errors='coerce')
            break
    else:
        st.error("No valid date column found.")
        return None
    
    # Renaming column names
    df = df.rename(columns={
        "Area Name": "County",
        "Labor Force": "LaborForce",
        "Employment": "Employment",
        "Unemployment Rate": "UnemploymentRate"
    })

    # Sort data by County names, then by date
    df = df.sort_values(by=["County", "date"])
    df = df.drop_duplicates(subset=["County", "date"], keep="first")
    
    # Filter for Feb 2020 and onwards
    cutoff = datetime(2020, 2, 1)
    df = df[df["date"] >= cutoff]

    return df

def fetch_and_process_job_data(series_id, region_name):
    """
    Fetches nonfarm payroll employment data from the BLS API for a specific region 
    and processes it to compute monthly job change.

    The function:
        - Sends a POST request to the BLS Public API for a given series ID.
        - Filters out annual summary rows (M13).
        - Converts data to monthly values in thousands of jobs.
        - Calculates month-over-month job changes.
        - Formats labels and assigns color codes for visualization (teal for gains, red for losses).

    Args:
        series_id (str): The BLS series ID for the selected region.
        region_name (str): Human-readable name of the region (for warnings or error messages).

    Returns:
        pd.DataFrame or None: A DataFrame containing:
            - 'date': Month and year as datetime.
            - 'value': Total employment.
            - 'monthly_change': Change in employment from previous month.
            - 'label': String label for bar chart display (e.g., "5K" or "250").
            - 'color': Color code for visualization (teal for gains, red for losses).
        Returns None if data is unavailable or the API call fails.
    """
    
    payload = {
        "seriesid": [series_id],
        "startyear": "2020",
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }

    try:
        response = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json=payload, timeout=30)
        data = response.json()

        if "Results" in data and data["Results"]["series"]:
            series = data["Results"]["series"][0]["data"]
            df = pd.DataFrame(series)
            df = df[df["period"] != "M13"]  # Remove annual data
            df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
            df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
            df = df.sort_values("date")
            df = df[df["date"] >= "2020-01-01"]     # Start date of employment job data
            df["monthly_change"] = df["value"].diff()
            df = df.dropna(subset=["monthly_change"])
            
            # Add formatting and color columns
            df["label"] = df["monthly_change"].apply(
                lambda x: f"{int(x/1000)}K" if abs(x) >= 1000 else f"{int(x)}"
            )
            df["color"] = df["monthly_change"].apply(lambda x: "#00aca2" if x >= 0 else "#e63946")
            
            return df
        else:
            st.warning(f"No data returned from BLS for {region_name}.")
            return None
            
    except Exception as e:
        st.error(f"Failed to fetch data for {region_name}: {e}")
        return None
    
def _debug(msg):
    import sys
    print(f"[build] {msg}", file=sys.stderr, flush=True)

def _fetch_bls_series_chunked(series_ids: list[str], start_year: int, end_year: int, api_key: str):
    import requests

    all_series = []
    if not series_ids:
        _debug("BLS fetch called with 0 series_ids.")
        return all_series

    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i:i+25]
        _debug(f"BLS chunk {i//25+1}: size={len(chunk)}, sample={chunk[:3]}, key_present={bool(api_key)}")

        try:
            resp = requests.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json={
                    "seriesid": chunk,
                    "startyear": str(start_year),
                    "endyear": str(end_year),
                    "registrationKey": api_key,
                },
                timeout=30,
            )
            _debug(f"HTTP {resp.status_code}; bytes={len(resp.content)}")
            resp.raise_for_status()

            data = resp.json()
            # after 'data = resp.json()'
            if "Results" in data and "series" in data["Results"]:
                ser = data["Results"]["series"]
                _debug(f"Returned series={len(ser)}; first id={ser[0].get('seriesID') if ser else None}")
                all_series.extend(ser)
            else:
                _debug(
                    "No 'Results.series' in payload. "
                    f"status={data.get('status')}, message={data.get('message')}, keys={list(data.keys())}"
                )
        except Exception as e:
            _debug(f"BLS fetch failed for chunk {i//25+1}: {e}")

    if not all_series:
        _debug("BLS fetch produced 0 series across all chunks.")

    return all_series


def _compute_industry_export_for_region(mapping: dict[str, tuple[str, str]], api_key: str):
    """
    Given a mapping: series_id -> (region, industry), fetch BLS data and return a tidy DataFrame
    for BOTH windows: since Feb 2020 and past 12 months. Drops TTU and adds derived WT&U.
    Columns: region, industry, metric_window, baseline_date, latest_date,
             baseline_jobs, latest_jobs, net_change, pct_change
    """
    import pandas as pd
    from datetime import datetime

    if not mapping:
        return pd.DataFrame()

    series_ids = list(mapping.keys())
    all_series = _fetch_bls_series_chunked(series_ids, start_year=2020,
                                           end_year=datetime.now().year, api_key=api_key)
    if not all_series:
        return pd.DataFrame()

    # Parse raw → records
    records = []
    for ser in all_series:
        sid = ser.get("seriesID")
        if sid not in mapping:
            continue
        region, industry = mapping[sid]
        for entry in ser.get("data", []):
            if entry.get("period") == "M13":
                continue
            try:
                date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                value = float(entry["value"].replace(",", "")) * 1000  # BLS CES is in thousands
                records.append({"series_id": sid, "region": region, "industry": industry, "date": date, "value": value})
            except Exception:
                continue

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).dropna(subset=["date"])
    if df.empty:
        return pd.DataFrame()

    results = []

    # Compute both windows PER REGION in this mapping
    for region in sorted(df["region"].unique()):
        df_r = df[df["region"] == region].copy()
        if df_r.empty:
            continue

        latest_date = df_r["date"].max()

        # past 12 months baseline: nearest available month
        baseline_12m_nominal = latest_date - pd.DateOffset(months=12)
        avail = df_r["date"].unique()
        baseline_12m = min(avail, key=lambda x: abs(x - baseline_12m_nominal)) if len(avail) else None

        # since covid baseline
        baseline_covid = pd.to_datetime("2020-02-01")

        for which, baseline_date, metric_window in [
            ("12m", baseline_12m, "past_12_months"),
            ("covid", baseline_covid, "since_feb_2020"),
        ]:
            if baseline_date is None:
                continue

            base_df = df_r[df_r["date"] == baseline_date]
            lat_df  = df_r[df_r["date"] == latest_date]
            if base_df.empty or lat_df.empty:
                continue

            base_tot = base_df.groupby("industry")["value"].sum()
            lat_tot  = lat_df.groupby("industry")["value"].sum()

            # Derived category: WT&U = TTU - Retail
            if "Trade, Transportation, and Utilities" in base_tot and "Retail Trade" in base_tot:
                base_tot["Wholesale, Transportation, and Utilities"] = (
                    base_tot["Trade, Transportation, and Utilities"] - base_tot["Retail Trade"]
                )
            if "Trade, Transportation, and Utilities" in lat_tot and "Retail Trade" in lat_tot:
                lat_tot["Wholesale, Transportation, and Utilities"] = (
                    lat_tot["Trade, Transportation, and Utilities"] - lat_tot["Retail Trade"]
                )

            inds = sorted(set(base_tot.index) & set(lat_tot.index))
            for ind in inds:
                if ind == "Trade, Transportation, and Utilities":
                    # drop TTU to match chart behavior
                    continue
                base = float(base_tot[ind])
                lat  = float(lat_tot[ind])
                pct  = ((lat - base) / base * 100.0) if base > 0 else float("nan")

                results.append({
                    "region": region,
                    "industry": ind,
                    "metric_window": metric_window,
                    "baseline_date": pd.Timestamp(baseline_date).strftime("%Y-%m-%d"),
                    "latest_date": pd.Timestamp(latest_date).strftime("%Y-%m-%d"),
                    "baseline_jobs": base,
                    "latest_jobs": lat,
                    "net_change": lat - base,
                    "pct_change": pct,
                })

    if not results:
        return pd.DataFrame()

    out = pd.DataFrame(results).sort_values(["region", "industry", "metric_window"]).reset_index(drop=True)
    return out
    


# === Build mode for GitHub Actions / local cron ===
if os.getenv("DASHBOARD_BUILD") == "1":
    try:
        build_all_tables()
        print("Built artifacts under docs/data_build/")
    except Exception as e:
        print(f"Build failed: {e}")
        raise
    import sys
    sys.exit(0)
# === end PREBUILT SUPPORT ===



def show_data_downloads():
    """
    Display a Streamlit page for exploring and downloading prebuilt CSV datasets.

    This function loads a `manifest.csv` file (either from a remote GitHub Pages/CDN
    URL defined in `PREBUILT_BASE_URL` or from a local `docs/data_build` folder) and
    provides an interactive interface to search, preview, and download datasets.

    Features:
        - Loads the dataset manifest (`manifest.csv`) describing available files,
          their paths, row/column counts, and optional schema information.
        - Provides a search bar to filter files by name or description.
        - Allows filtering by top-level folder (derived from file paths).
        - Displays metadata (rows, columns) and an expandable preview (first 200 rows).
        - Optionally shows schema information if present in the manifest.
        - Provides both:
            * A "Download CSV" button to download the file directly.
            * A link to open the raw CSV (local path or CDN URL).

    Behavior:
        - If `PREBUILT_BASE_URL` is set, files are loaded from that remote base URL.
        - If not set, falls back to local paths under `PAGES_OUT`.
        - If the manifest cannot be loaded, shows a Streamlit warning.

    Returns:
        None. Renders the interactive interface directly in Streamlit.
    """
    import pandas as pd, requests, os
    from io import StringIO

    def _csv_from_url(url: str) -> pd.DataFrame:
        r = requests.get(url, timeout=30); r.raise_for_status()
        return pd.read_csv(StringIO(r.text))

    def _bytes_from_url(url: str) -> bytes:
        r = requests.get(url, timeout=30); r.raise_for_status()
        return r.content

    base = PREBUILT_BASE_URL
    # Fallback to local dev
    if not base:
        st.info("Using local docs/data_build (no PREBUILT_BASE_URL set).")
        manifest_path = PAGES_OUT / "manifest.csv"
        if manifest_path.exists():
            dfm = pd.read_csv(manifest_path)
        else:
            st.warning("manifest.csv not found.")
            return
    else:
        manifest_url = f"{base}/data_build/manifest.csv"
        try:
            dfm = _csv_from_url(manifest_url)
        except Exception as e:
            st.warning(f"Could not load manifest: {e}")
            return

    # Simple search/filter
    col1, col2 = st.columns([2, 1])
    with col1:
        q = st.text_input("Search files or descriptions", "")
    with col2:
        # derive top-level folder from file path like "csv/employment/..."
        folders = sorted({str(f).split("/", 2)[1] for f in dfm["file"] if isinstance(f, str) and f.startswith("csv/")})
        folder = st.selectbox("Folder", ["(all)"] + folders)

    df_show = dfm.copy()
    if q:
        ql = q.lower()
        df_show = df_show[
            df_show["file"].str.lower().str.contains(ql) |
            df_show["description"].fillna("").str.lower().str.contains(ql)
        ]
    if folder != "(all)":
        df_show = df_show[df_show["file"].str.contains(rf"^csv/{folder}/")]

    if df_show.empty:
        st.info("No matching files.")
        return
    
    df_show = df_show.sort_values(["file"]).reset_index(drop=True)

    for _, row in df_show.iterrows():
        rel = str(row["file"])                  # e.g., "csv/employment/job_recovery_overall.csv"
        desc = str(row.get("description", "") or "")
        rows = int(row.get("rows", 0))
        cols = int(row.get("columns", 0))
        schema_json = str(row.get("schema_json", "[]"))

        # Build URLs/paths
        if base:
            raw_url = f"{base}/data_build/{rel}"
            data_bytes = None
        else:
            local_path = PAGES_OUT / rel
            raw_url = str(local_path)
            data_bytes = local_path.read_bytes() if local_path.exists() else None

        with st.expander(f"{rel} — {desc}"):
            st.caption(f"Rows: {rows} · Columns: {cols}")

            # Quick preview (first ~200 rows), best-effort
            try:
                if base:
                    # Avoid downloading twice: read once for preview, reuse for button
                    text = requests.get(raw_url, timeout=30)
                    text.raise_for_status()
                    csv_text = text.text
                    data_bytes = csv_text.encode("utf-8")
                    df_preview = pd.read_csv(StringIO(csv_text)).head(200)
                else:
                    df_preview = pd.read_csv(raw_url).head(200)
                st.dataframe(df_preview, use_container_width=True)
            except Exception as e:
                st.info(f"Preview unavailable: {e}")

            # (Optional) show schema from manifest
            if schema_json and schema_json != "[]":
                st.code(schema_json, language="json")

            # Download button (serves exact file bytes)
            filename = rel.split("/", 1)[1] if "/" in rel else rel  # drop leading "csv/"
            if data_bytes:
                st.download_button(
                    label="Download CSV",
                    data=data_bytes,
                    file_name=filename,
                    mime="text/csv",
                )

            st.markdown(f"[Open raw CSV]({raw_url})")


# --- Title ----
st.set_page_config(page_title="Bay Area Dashboard", layout="wide")


st.markdown(
    """
    <style>
      :root { --custom-header-height: 28px; }

      header[data-testid="stHeader"],
      header[data-testid="stHeader"] > div,
      div[data-testid="stToolbar"] {
        height: var(--custom-header-height) !important;
        min-height: var(--custom-header-height) !important;
        padding-top: 0 !important;
        padding-bottom: 0 !important;
      }

      header[data-testid="stHeader"] button,
      header[data-testid="stHeader"] a {
        transform: scale(0.75);
        margin: 0 2px !important;
      }

      /* Prevent overlap: push page content down by the new header height */
      [data-testid="stAppViewContainer"] > .main {
        padding-top: calc(var(--custom-header-height) + 6px) !important;
      }

      /* Fallback for older Streamlit DOMs */
      section.main > div {
        padding-top: calc(var(--custom-header-height) + 6px) !important;
      }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown(
    """
    <style>
        /* Adjust sidebar width */
        [data-testid="stSidebar"] {
            width: 230px !important;   /* Set your desired width */
            min-width: 230px !important;
            max-width: 230px !important;
        }
    </style>
    """,
    unsafe_allow_html=True
)

@st.cache_data(ttl=3600)
def _load_version():
    import requests, json
    if PREBUILT_BASE_URL:
        r = requests.get(f"{PREBUILT_BASE_URL}/data_build/version.json", timeout=10)
        r.raise_for_status()
        return r.json()
    # local fallback
    return json.loads((PAGES_OUT / "version.json").read_text())

try:
    v = _load_version()
    ts = v.get("last_updated_utc", "")
    if ts:
        # handle possible Z suffix in ISO timestamp
        ts_clean = ts.replace("Z", "+00:00")
        dt_utc = datetime.fromisoformat(ts_clean)
        # Convert UTC → Pacific Time
        dt_pt = dt_utc.astimezone(ZoneInfo("America/Los_Angeles"))
        formatted = dt_pt.strftime("%m-%d-%Y at %-I:%M %p PT")
    else:
        formatted = "Unknown"
except Exception:
        formatted = "Unknown"


st.markdown(
    """
    <style>
        .block-container {
            padding-top: 1rem;
        }
    </style>
    <h1 style='margin-top: 0; margin-bottom: 10px; color: #203864; font-family: "Avenir Black"; font-size: 50px;'>
        Bay Area Economic Dashboard
    </h1>
    """,
    unsafe_allow_html=True
)

# --- BACEI Logo ---
st.sidebar.image("BACEI Logo.png", use_container_width=True)

# --- Sidebar dropdown ---
section = st.sidebar.selectbox(
    "Select Indicator:",
    ["Employment", "Population", "Housing"],  #, "Investment", "Transit"]
    key="indicator_section"
)


# --- Sidebar Subtabs ---i
emp_subtab = None
pop_subtab = None
housing_subtab = None

if section == "Employment":
    emp_subtab = st.sidebar.radio(
        "Employment Views:",
        ["Job Recovery", "Monthly Change", "Jobs by Industry", "Office Jobs", "Unemployment Rate", "Employed Residents", "Job to Worker Ratio"],
        key="employment_subtab"
    )
elif section == "Population":
    pop_subtab = st.sidebar.radio(
        "Population Views:",
        ["Counties", "Metro Areas"],
        key="population_subtab"
    )
elif section == "Housing":
    housing_subtab = st.sidebar.radio(
        "Housing Views:",
        ["Rent Trends", "Housing Permits"],
        key="housing_subtab"
    )



# --- Bottom-of-sidebar "Download Data" button ---
st.sidebar.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)  # breathing room
if st.sidebar.button("Download Data", use_container_width=True):
    st.query_params["page"] = "downloads"
    st.rerun()


is_downloads = (st.query_params.get("page") == "downloads")
if is_downloads:
    st.markdown("### Download Data")

    if st.button("← Back", type="secondary"):
        qp = st.query_params
        if "page" in qp:
            del qp["page"]
        st.rerun()

    show_data_downloads()
    st.stop()

# --- Sidebar footer placement ---
with st.sidebar:
    st.markdown("<div style='flex:1'></div>", unsafe_allow_html=True)  # spacer
    st.markdown("---")
    st.caption(f"Last updated: {formatted}")


# --- Visualization ---

def show_employment_comparison_chart(df):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Employment

    Displays a side-by-side bar chart comparing employment levels in Bay Area counties 
    between February 2020 (pre-pandemic baseline) and the latest available month.

    The chart highlights job recovery progress by county and includes interactive bars 
    showing actual employment levels for both time periods. Below the chart, the function 
    provides summary statistics and a detailed table with changes in employment.

    Args:
        df (pd.DataFrame): A processed DataFrame containing at least the following columns:
            - 'County': Name of the county.
            - 'Employment': Number of employed persons.
            - 'date': pandas datetime object representing the observation month.

    Returns:
        None. Renders an interactive Plotly bar chart and Streamlit summary statistics.
    """

    latest_date = df["date"].max()

    # Get February 2020 data
    feb_2020 = df[df['date'] == '2020-02-01'].copy()
    
    # Get latest month data for each county
    latest_month = df.groupby('County')['date'].max().reset_index()
    latest_data = df.merge(latest_month, on=['County', 'date'], how='inner')
    
    # Create comparison dataframe
    comparison_data = []
    
    for county in df['County'].unique():
        feb_employment = feb_2020[feb_2020['County'] == county]['Employment'].iloc[0] if len(feb_2020[feb_2020['County'] == county]) > 0 else None
        latest_employment = latest_data[latest_data['County'] == county]['Employment'].iloc[0] if len(latest_data[latest_data['County'] == county]) > 0 else None
        latest_date = latest_data[latest_data['County'] == county]['date'].iloc[0] if len(latest_data[latest_data['County'] == county]) > 0 else None
        
        if feb_employment is not None and latest_employment is not None:
            comparison_data.append({
                'County': county,
                'Feb 2020': feb_employment,
                'Latest': latest_employment,
                'Latest Date': latest_date,
                'Change': latest_employment - feb_employment,
                'Pct Change': ((latest_employment - feb_employment) / feb_employment) * 100
            })
    
    if not comparison_data:
        st.error("No data available for comparison")
        return
    
    comparison_df = pd.DataFrame(comparison_data)
    
    # Create the bar chart
    fig = go.Figure()
    comparison_df['County'] = comparison_df['County'].str.replace(' County', '', regex=False)
    
    # Function to format numbers with k/M suffix
    def format_number(val):
        if val >= 1000000:
            return f"{int(round(val/1000000))}M"
        else:
            return f"{int(round(val/1000))}k"

    # Add February 2020 bars
    fig.add_trace(go.Bar(
        name='February 2020',
        x=comparison_df['County'],
        y=comparison_df['Feb 2020'],
        marker_color='#00aca2',
        text=[format_number(val) for val in comparison_df['Feb 2020']],
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>%{y:,.0f} residents employed<extra></extra>',
        textfont=dict(family="Avenir Black", size=16, color="#00aca2")
    ))
    
    # Add latest month bars
    fig.add_trace(go.Bar(
        name=f'{comparison_df["Latest Date"].iloc[0].strftime("%B %Y")}',
        x=comparison_df['County'],
        y=comparison_df['Latest'],
        marker_color='#eeaf30',
        text=[format_number(val) for val in comparison_df['Latest']],
        textposition='outside',
        hovertemplate='<b>%{x}</b><br>%{y:,.0f} residents employed<extra></extra>',
        textfont=dict(family="Avenir Black", size=16, color="#eeaf30")
    ))
    
    # Update layout
    fig.update_layout(
        title=dict(
            text="<span style='font-size:26px; font-family:Avenir Black'>Employed Residents by County<br><span style='font-size:20px; color:#666; font-family:Avenir Medium'>Comparing pre-pandemic baseline to " + latest_date.strftime('%B %Y') + "</span>",
            x=0.5,
            xanchor='center',
        ),
        xaxis=dict(
            title='County',
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=15, color="black"),
        ),
        yaxis=dict(
            title='Number of Employed Residents',
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            showgrid=True,
            gridcolor="#CCCCCC",
            gridwidth=1,
            griddash="dash",
            range=[0, comparison_df[['Feb 2020','Latest']].max().max() * 1.15]
        ),
        legend=dict(
            font=dict(family="Avenir", size=20)
        ),
        barmode='group',
        height=600,
        showlegend=True,
        xaxis_tickangle=0,
        title_font = dict(family="Avenir Black", size=20)
    )
    
    # Format y-axis to show numbers in thousands/millions
    fig.update_yaxes(tickformat='.0s')

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "county_employment",
                    "scale": 10         
                }
            }
    )
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong>  LAUS data includes total employment, covering both farm jobs and self-employed. <br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Employed Residents Snapshot
    st.subheader("Employed Residents Snapshot")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        recovered_counties = len(comparison_df[comparison_df['Change'] > 0])
        st.metric("Counties Above Feb 2020 Level", recovered_counties)
    
    with col2:
        avg_change = comparison_df['Pct Change'].mean()
        st.metric("Average Change", f"{avg_change:.1f}%")
    
    with col3:
        total_change = comparison_df['Change'].sum()
        st.metric("Total Employment Change", f"{total_change:,.0f}")

    # Summary Table
    st.subheader("Summary")
    latest_col_label = comparison_df["Latest Date"].iloc[0].strftime("%b %Y")

    display_df = comparison_df[['County', 'Feb 2020', 'Latest', 'Change', 'Pct Change']].copy()
    display_df = display_df.rename(columns={
        "Latest": latest_col_label,
        "Pct Change": "Percent Change"
    })

    # Apply formatting
    display_df['Feb 2020'] = display_df['Feb 2020'].apply(lambda x: f"{x:,.0f}")
    display_df[latest_col_label] = display_df[latest_col_label].apply(lambda x: f"{x:,.0f}")
    display_df['Change'] = display_df['Change'].apply(lambda x: f"{x:+,.0f}")
    display_df['Percent Change'] = display_df['Percent Change'].apply(lambda x: f"{x:+.1f}%")

    # Color code the percentage change
    def color_pct_change(val):
        if '+' in val:
            return 'color: #00aca2'
        else:
            return 'color: #d84f19'

    styled_df = display_df.style.map(color_pct_change, subset=['Percent Change'])
    st.dataframe(styled_df, use_container_width=True, hide_index=True)


def show_unemployment_rate_chart(df):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Unemployment

    Displays an interactive line chart of unemployment rate trends for Bay Area counties.

    Provides a checkbox to select all counties, and a multiselect option 
    for users to customize which counties to display. The chart shows the unemployment 
    rate over time, with quarterly ticks (January, April, July, October) on the x-axis.

    Args:
        df (pd.DataFrame): A DataFrame containing at least the following columns:
            - 'County': Name of the county.
            - 'UnemploymentRate': Unemployment rate as a percentage.
            - 'Unemployment': Total unemployment count.
            - 'LaborForce': Total labor force count.
            - 'date': pandas datetime object representing the observation month.

    Returns:
        None. Displays an interactive Plotly line chart and renders it in the Streamlit app.
    """
    
    counties = sorted(df["County"].unique().tolist())
    select_all = st.checkbox("Select all Bay Area Counties", value=False, key="select_all_checkbox")

    # Dropdown to select counties
    if select_all:
        default_counties = counties
    else:
        default_counties = []

    selected_counties = st.multiselect(
        "Select counties to display:",
        options = counties,
        default = default_counties
    )

    # Calculate Bay Area aggregate trend - always shown
    bay_area_agg = df.groupby('date').agg({
        'Unemployment': 'sum',
        'LaborForce': 'sum'
    }).reset_index()

    # Calculate Bay Area unemployment rate
    bay_area_agg['UnemploymentRate'] = (bay_area_agg['Unemployment'] / bay_area_agg['LaborForce']) * 100
    bay_area_agg['County'] = 'Bay Area (9-county)'
    
    bay_area_trend_df = bay_area_agg[['County', 'date', 'UnemploymentRate']]

    # Prepare data for plotting
    plot_data = [bay_area_trend_df]  # Always include Bay Area trend
    
    if selected_counties:
        county_data = df[df["County"].isin(selected_counties)]
        plot_data.append(county_data)
    
    # Combine all data for plotting
    combined_df = pd.concat(plot_data, ignore_index=True)
    
    fig = px.line(
        combined_df,
        x = "date",
        y = "UnemploymentRate",
        color = "County",
        color_discrete_map=color_map
    )

    # Style the Bay Area trend line differently
    for trace in fig.data:
        if trace.name == 'Bay Area (9-county)':
            trace.update(
                line=dict(width=2, color="black"),
                marker=dict(size=8, color="black")
            )

    quarterly_ticks = df["date"][df["date"].dt.month.isin([1, 4, 7, 10])].unique()

    fig.update_layout(
        hovermode="x unified",
        title=dict(
            text="Unemployment Rate Over Time",
            x=0.5,
            xanchor='center',
            font=dict(family="Avenir Black", size=20)
        ),
        xaxis=dict(
            title="Date",
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickvals = quarterly_ticks,
            tickformat="%b %Y",
            ticktext = [
                date.strftime("%b<br>%Y") if date.month == 1 else date.strftime("%b")
                for date in quarterly_ticks
            ],
            dtick="M1",
            tickangle=0,
            tickfont=dict(family="Avenir", size=16, color="black"),
        ),
        yaxis=dict(
            title="Unemployment Rate",
            ticksuffix="%",
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black")
        ),
        legend=dict(
            title=dict(
                text="",
                font=dict(
                    family="Avenir",
                    size=20,
                    color="Black"
                )
            ),
            font=dict(
                family="Avenir",
                size=20,
                color="black"
            ),
            orientation="v",
            x=1.01,
            y=1
        ),
        title_font = dict(family="Avenir Black", size=26)
    )

    fig.update_xaxes(hoverformat="%b")

    for trace in fig.data:
        trace.hovertemplate = f"{trace.name}: " + "%{y:.1f}%<extra></extra>"

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "county_unemployment_rates",
                    "scale": 10
                }
            }
    )

    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Summary Table
    st.subheader('Summary')
    summary_data = []
    
    for county in combined_df['County'].unique():
        county_data = combined_df[combined_df['County'] == county]
        
        # Get the most recent unemployment rate
        latest_rate = county_data.loc[county_data['date'].idxmax(), 'UnemploymentRate']
        
        # Calculate statistics
        min_rate = county_data['UnemploymentRate'].min()
        max_rate = county_data['UnemploymentRate'].max()
        
        # Find dates for min and max
        min_date = county_data.loc[county_data['UnemploymentRate'].idxmin(), 'date']
        max_date = county_data.loc[county_data['UnemploymentRate'].idxmax(), 'date']
        
        summary_data.append({
            'County': county,
            'Latest Rate': f"{latest_rate:.1f}%",
            'Minimum Rate': f"{min_rate:.1f}%",
            'Min Rate Date': f"{min_date.strftime('%m/%Y')}",
            'Maximum Rate': f"{max_rate:.1f}%",
            'Max Rate Date': f"{max_date.strftime('%m/%Y')}"
        })
    
    # Create DataFrame and display table
    summary_df = pd.DataFrame(summary_data)
    
    # Sort so Bay Area appears first
    bay_area_row = summary_df[summary_df['County'] == '9-county Bay Area']
    other_rows = summary_df[summary_df['County'] != '9-county Bay Area'].sort_values('County')
    summary_df = pd.concat([bay_area_row, other_rows], ignore_index=True)
    
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            'County': st.column_config.TextColumn('Region', width='medium'),
            'Latest Rate (%)': st.column_config.TextColumn('Latest Rate (%)', width='small'),
            'Minimum Rate (%)': st.column_config.TextColumn('Minimum Rate', width='medium'),
            'Maximum Rate (%)': st.column_config.TextColumn('Maximum Rate', width='medium')
        }
    )


def show_job_recovery_overall_v2(df_ca, df_bay, df_us, df_sonoma):
    """
    Show four lines: California, United States, Sonoma County, and Rest of Bay Area (Bay - Sonoma).
    Expects:
    - df_ca, df_us: columns ['date','pct_change'] (value optional)
    - df_bay, df_sonoma: MUST include ['date','value'] (and optionally 'pct_change')
    """
    # ---- Basic validation ----
    required_min = {
        "California": ["date", "pct_change"],
        "United States": ["date", "pct_change"],
        "Bay Area": ["date", "value"],        # need value to compute Rest of Bay
        "Sonoma County": ["date", "value"],   # need value to compute Rest of Bay
    }
    name_map = {
        "California": df_ca,
        "United States": df_us,
        "Bay Area": df_bay,
        "Sonoma County": df_sonoma,
    }

    for n, d in name_map.items():
        if d is None or d.empty:
            st.warning(f"{n} dataframe is missing or empty.")
            return
        if not set(required_min[n]).issubset(d.columns):
            st.warning(f"{n} is missing required columns {required_min[n]}.")
            return

    # ---- Align to latest common month across the four inputs ----
    latest_common_date = min(d["date"].max() for d in name_map.values())
    df_ca = df_ca[df_ca["date"] <= latest_common_date].copy()
    df_us = df_us[df_us["date"] <= latest_common_date].copy()
    df_bay = df_bay[df_bay["date"] <= latest_common_date].copy()
    df_sonoma = df_sonoma[df_sonoma["date"] <= latest_common_date].copy()

    # ---- Build Rest of Bay Area = Bay - Sonoma (values), then pct_change vs Feb 2020 ----
    m_rb = (
        df_bay[["date", "value"]].rename(columns={"value": "bay_value"})
        .merge(df_sonoma[["date", "value"]].rename(columns={"value": "sonoma_value"}), on="date", how="inner")
        .sort_values("date")
    )
    m_rb["value"] = m_rb["bay_value"] - m_rb["sonoma_value"]

    feb2020 = pd.to_datetime("2020-02-01")
    base_rb = m_rb.loc[m_rb["date"] == feb2020, "value"]
    if base_rb.empty:
        after_feb = m_rb[m_rb["date"] >= feb2020]
        baseline_val = after_feb.iloc[0]["value"] if not after_feb.empty else m_rb.iloc[0]["value"]
    else:
        baseline_val = base_rb.iloc[0]

    if baseline_val is None or baseline_val == 0:
        st.warning("Invalid baseline for Rest of Bay Area; skipping this line.")
        df_rest_bay = None
    else:
        m_rb["pct_change"] = (m_rb["value"] / baseline_val - 1) * 100
        df_rest_bay = m_rb[["date", "value", "pct_change"]].copy()

    # ---- Plot ----
    fig = go.Figure()
    fig.add_hline(y=0, line_dash="solid", line_color="#000000", line_width=1, opacity=1.0)

    def add_line(df, name, color, text_pos="bottom center", marker_size=10, font_size=10):
        fig.add_trace(
            go.Scatter(
                x=df["date"], y=df["pct_change"], mode="lines", name=name,
                line=dict(color=color),
                hovertemplate=f"{name}: "+"%{y:.2f}%<extra></extra>",
            )
        )
        last = df.iloc[-1]
        fig.add_trace(
            go.Scatter(
                x=[last["date"]], y=[last["pct_change"]],
                mode="markers+text",
                marker=dict(color=color, size=marker_size),
                text=[f"{last['pct_change']:.2f}%"],
                textposition=text_pos,
                textfont=dict(size=font_size, family="Avenir", color=color),
                name=name, hoverinfo="skip", showlegend=False,
            )
        )

    # Colors
    add_line(df_us,        "United States",    "#7e8082", "top center", marker_size=10, font_size=23)
    add_line(df_ca,        "California",       "#00aca2", "bottom center", marker_size=10, font_size=23)
    add_line(df_sonoma,    "Sonoma County",    "#d84f19", "bottom center", marker_size=10, font_size=23)
    if df_rest_bay is not None and not df_rest_bay.empty:
        add_line(df_rest_bay, "Rest of Bay Area", "#406a9c", "top center", marker_size=10, font_size=23)

    # Quarterly ticks (Jan/Apr/Jul/Oct)
    series_for_ticks = [df_ca["date"], df_us["date"], df_sonoma["date"]]
    if df_rest_bay is not None:
        series_for_ticks.append(df_rest_bay["date"])
    all_dates = pd.concat(series_for_ticks)
    quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())
    ticktext = [d.strftime("%b<br>%Y") if d.month == 1 else d.strftime("%b") for d in quarterly_ticks]

    # Avoid clipping end labels
    for i, tr in enumerate(fig.data):
        if getattr(tr, "mode", None) and "text" in tr.mode:
            fig.data[i].update(cliponaxis=False)

    latest_date = latest_common_date
    fig.update_layout(
        title=dict(
            text=(
                "<span style='font-size:20px; font-family:Avenir Black'>Job Recovery Since the Pandemic</span><br>"
                "<span style='font-size:17px; color:#666; font-family:Avenir Medium'>"
                "Percent Change in Non-Farm Payroll Jobs From February 2020 to "
                + latest_date.strftime('%B %Y') + "</span>"
            ),
            x=0.5,
            xanchor='center'
        ),
        xaxis=dict(
            title='Date',
            title_font=dict(family="Avenir Medium", size=18, color="black"),
            tickfont=dict(family="Avenir", size=22, color="black"),
            tickvals=quarterly_ticks,
            ticktext=ticktext,
            dtick="M1",
            range=["2020-02-01", (latest_date + timedelta(days=90)).strftime("%Y-%m-%d")],
        ),
        yaxis=dict(
            title='Percent Change Since Feb 2020',
            ticksuffix="%",
            title_font=dict(family="Avenir Medium", size=18, color="black"),
            tickfont=dict(family="Avenir", size=25, color="black"),
            showgrid=True, gridcolor="#CCCCCC", gridwidth=1, griddash="dash"
        ),
        hovermode="x unified",
        legend=dict(
            title=dict(text="Region", font=dict(family="Avenir Black", size=18, color="black")),
            font=dict(family="Avenir", size=20, color="black"),
            orientation="v", x=1.01, y=1
        ),
    )
    fig.update_xaxes(hoverformat="%b")

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"toImageButtonOptions": {"format": "svg", "filename": "job_recovery", "scale": 10}}
    )

    st.markdown("""
    <div style='font-size: 12px; color: #666;'>
    <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
    <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")



def show_job_recovery_overall(df_state, df_bay, df_us, df_sonoma, df_napa):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Job Recovery

    Visualizes overall job recovery trends since February 2020 for the Bay Area, 
    the rest of California, and the United States.

    Creates an interactive line chart comparing the percent change in nonfarm payroll 
    employment relative to February 2020. The function highlights the latest data points 
    for each region directly on the chart with labels. Quarterly ticks are used on the 
    x-axis for readability.

    Args:
        df_state (pd.DataFrame): Rest of California employment data with columns ['date', 'pct_change'].
        df_bay (pd.DataFrame): Bay Area employment data with columns ['date', 'pct_change'].
        df_us (pd.DataFrame): U.S. employment data with columns ['date', 'pct_change'].

    Returns:
        None. Renders a Plotly line chart and source notes in Streamlit.
    """

    if df_state is not None and df_bay is not None and df_us is not None and df_sonoma is not None and df_napa is not None:
        # # Filter data to a specific end date
        # target_date = "2025-06-01"
        # df_bay = df_bay[df_bay["date"] <= target_date]
        # df_state = df_state[df_state["date"] <= target_date]
        # df_us = df_us[df_us["date"] <= target_date]
        # df_sonoma = df_sonoma[df_sonoma["date"] <= target_date]
        # df_napa = df_napa[df_napa["date"] <= target_date]
        
        # Find latest common month of data available for aesthetics
        latest_common_date = min(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max())
        df_state = df_state[df_state["date"] <= latest_common_date]
        df_bay = df_bay[df_bay["date"] <= latest_common_date]
        df_us = df_us[df_us["date"] <= latest_common_date]
        df_sonoma = df_sonoma[df_sonoma["date"] <= latest_common_date]
        df_napa = df_napa[df_napa["date"] <= latest_common_date]


        fig = go.Figure()

        fig.add_hline(
            y=0,
            line_dash="solid",
            line_color="#000000",
            line_width=1,
            opacity=1.0
        )


        # U.S. (gray)
        fig.add_trace(
            go.Scatter(
                x=df_us["date"],
                y=df_us["pct_change"],
                mode="lines",
                name="United States",
                line=dict(color="#7e8082"),
                hovertemplate="United States: %{y:.2f}%<extra></extra>"
            )
        )

        latest_us = df_us.iloc[-1]
        fig.add_trace(
            go.Scatter(
                x=[latest_us["date"]],
                y=[latest_us["pct_change"]],
                mode="markers+text",
                marker=dict(color="#7e8082", size=10),
                text=[f"{latest_us['pct_change']:.2f}%"],
                textposition="top center",
                textfont=dict(size=16, family="Avenir", color="#7e8082"),
                name="United States",
                hoverinfo="skip",
                showlegend=False
            )
        )

        # Rest of California (teal)
        fig.add_trace(
            go.Scatter(
                x=df_state["date"],
                y=df_state["pct_change"],
                mode="lines",
                name="Rest of California",
                line=dict(color="#00aca2"),
                hovertemplate="Rest of California: %{y:.2f}%<extra></extra>"
            )
        )

        latest_row = df_state.iloc[-1]
        fig.add_trace(
            go.Scatter(
                x=[latest_row["date"]],
                y=[latest_row["pct_change"]],
                mode="markers+text",
                marker=dict(color="#00aca2", size=10),
                text=[f"{latest_row['pct_change']:.2f}%"],
                textposition="bottom center",
                textfont=dict(size=16, family="Avenir", color="#00aca2"),
                name="California",
                hoverinfo="skip",
                showlegend=False
            )
        )

        # Bay Area (dark blue)
        fig.add_trace(
            go.Scatter(
                x=df_bay["date"],
                y=df_bay["pct_change"],
                mode="lines",
                name="Bay Area",
                line=dict(color="#203864"),
                hovertemplate="Bay Area: %{y:.2f}%<extra></extra>"
            )
        )

        latest_bay = df_bay.iloc[-1]
        fig.add_trace(
            go.Scatter(
                x=[latest_bay["date"]],
                y=[latest_bay["pct_change"]],
                mode="markers+text",
                marker=dict(color="#203864", size=10),
                text=[f"{latest_bay['pct_change']:.2f}%"],
                textposition="bottom center",
                textfont=dict(size=16, family="Avenir", color="#203864"),
                name="Bay Area",
                hoverinfo="skip",
                showlegend=False
            )
        )

        # # SONOMA
        # fig.add_trace(
        #     go.Scatter(
        #         x=df_sonoma["date"],
        #         y=df_sonoma["pct_change"],
        #         mode="lines",
        #         name="Sonoma County",
        #         line=dict(color="#d84f19"),
        #         hovertemplate="Sonoma: %{y:.2f}%<extra></extra>"
        #     )
        # )

        # latest_son = df_sonoma.iloc[-1]
        # fig.add_trace(
        #     go.Scatter(
        #         x=[latest_son["date"]],
        #         y=[latest_son["pct_change"]],
        #         mode="markers+text",
        #         marker=dict(color="#d84f19", size=10),
        #         text=[f"{latest_son['pct_change']:.2f}%"],
        #         textposition="bottom center",
        #         textfont=dict(size=30, family="Avenir", color="#d84f19"),
        #         name="Sonoma",
        #         hoverinfo="skip",
        #         showlegend=False
        #     )
        # )

        # # NAPA
        # fig.add_trace(
        #     go.Scatter(
        #         x=df_napa["date"],
        #         y=df_napa["pct_change"],
        #         mode="lines",
        #         name="Napa County",
        #         line=dict(color="#00aca2"),
        #         hovertemplate="Napa: %{y:.2f}%<extra></extra>"
        #     )
        # )

        # latest_napa = df_napa.iloc[-1]
        # fig.add_trace(
        #     go.Scatter(
        #         x=[latest_napa["date"]],
        #         y=[latest_napa["pct_change"]],
        #         mode="markers+text",
        #         marker=dict(color="#00aca2", size=10),
        #         text=[f"{latest_napa['pct_change']:.2f}%"],
        #         textposition="bottom center",
        #         textfont=dict(size=30, family="Avenir", color="#00aca2"),
        #         name="Napa",
        #         hoverinfo="skip",
        #         showlegend=False
        #     )
        # )


        latest_date = max(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max(), df_napa["date"].max())
        buffered_latest = latest_date + timedelta(days=50)

        # Generate quarterly ticks (Jan, Apr, Jul, Oct) across all dates
        all_dates = pd.concat([df_state["date"], df_bay["date"], df_us["date"], df_napa["date"], df_sonoma["date"]])
        quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())
        ticktext=[
            date.strftime("%b<br> %Y") if date.month == 1 else date.strftime("%b")
            for date in quarterly_ticks
        ]
        
        # Prevent last-point labels from being clipped
        for i, tr in enumerate(fig.data):
            if tr.mode and "text" in tr.mode:  # your marker+text traces
                fig.data[i].update(cliponaxis=False)

        fig.update_layout(
            title=dict(
                text=(
                    "<span style='font-size:26px; font-family:Avenir Black'>Job Recovery Since the Pandemic</span><br>"
                    "<span style='font-size:17px; color:#666; font-family:Avenir Medium'>"
                    "Percent Change in Non-Farm Payroll Jobs From February 2020 to " 
                    + latest_date.strftime('%B %Y') + "</span>"
                ),
                x=0.5,
                xanchor='center'
            ),
            xaxis=dict(
                title='Date',
                title_font=dict(family="Avenir Medium", size=22, color="black"),
                tickfont=dict(family="Avenir", size=16, color="black"),
                tickvals=quarterly_ticks,
                ticktext=ticktext,
                dtick="M1",
                tickangle=0,
                range=["2020-02-01", (latest_date + timedelta(days=90)).strftime("%Y-%m-%d")],
            ),
            yaxis=dict(
                title='Percent Change Since Feb 2020',
                ticksuffix="%",
                title_font=dict(family="Avenir Medium", size=18, color="black"),
                tickfont=dict(family="Avenir", size=16, color="black"),
                showgrid=True,
                gridcolor="#CCCCCC",
                gridwidth=1,
                griddash="dash"
            ),
            hovermode="x unified",
            legend=dict(
                title=dict(
                    text="Region",
                    font=dict(
                        family="Avenir Black",
                        size=20,
                        color="black"
                    )
                ),
                font=dict(
                    family="Avenir",
                    size=18,
                    color="black"
                ),
                orientation="v",
                x=1.01,
                y=1
            ),
        )


        # # --- Vertical dashed lines to separate time series (e.g. tech recession, COVID, etc.) ---
        # fig.add_vline(
        #     x=pd.to_datetime("2021-02-01"),
        #     line_dash="dash",
        #     line_color="black",
        #     line_width=1,
        #     opacity=0.8
        # )

        # fig.add_vline(
        #     x=pd.to_datetime("2022-10-01"),
        #     line_dash="dash",
        #     line_color="black",
        #     line_width=1,
        #     opacity=0.8
        # )

        # fig.add_vline(
        #     x=pd.to_datetime("2023-08-01"),
        #     line_dash="dash",
        #     line_color="black",
        #     line_width=1,
        #     opacity=0.8
        # )

        fig.update_xaxes(hoverformat="%b")

        st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "job_recovery",
                    "scale": 10
                }
            }
        )
        st.markdown("""
        <div style='font-size: 12px; color: #666;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
        </div>
        <br>
        """, unsafe_allow_html=True)

        # st.markdown("---")


        # BAY AREA EMPLOYMENT SUMMARY
        bay_feb_2020 = df_bay[df_bay["date"] == "2020-02-01"]["value"]
        bay_latest = df_bay.iloc[-1]
        
        if not bay_feb_2020.empty:
            baseline_jobs = bay_feb_2020.iloc[0]
            latest_jobs = bay_latest["value"]
            job_change = latest_jobs - baseline_jobs
            
            # Display summary before the chart
            st.markdown("### Bay Area Employment Snapshot")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.metric(
                    label="February 2020 (Baseline)",
                    value=f"{baseline_jobs:,.0f}",
                    help="Total nonfarm payroll jobs in Bay Area"
                )
            
            with col2:
                st.metric(
                    label=f"{bay_latest['date'].strftime('%B %Y')} (Latest)",
                    value=f"{latest_jobs:,.0f}",
                    delta=f"{job_change:+,.0f}",
                    help="Current total nonfarm payroll jobs in Bay Area"
                )
            
            with col3:
                pct_change = bay_latest["pct_change"]
                st.metric(
                    label="Recovery Rate",
                    value=f"{pct_change:+.1f}%",
                    help="Percent change from February 2020 baseline"
                )
            
            st.markdown("---")
    


def show_job_recovery_by_state(state_code_map, fetch_states_job_data):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Job Recovery

    Visualizes state-level job recovery since February 2020 across selected U.S. states.

    Creates an interactive line chart showing the percent change in nonfarm payroll employment 
    relative to February 2020 for each selected state. Users can choose to compare individual states 
    or select all states at once. The function highlights the latest available data point for each state 
    directly on the graph for clarity.

    Args:
        state_code_map (dict): Dictionary mapping state names to BLS series IDs for nonfarm employment.
        fetch_states_job_data (function): Function that fetches and processes BLS employment data 
                                        for the provided list of series IDs.

    Returns:
        None. Displays an interactive Plotly line chart in Streamlit along with data source notes.
    """

    st.subheader("Job Recovery by State")

    all_states = list(state_code_map.keys())
    select_all_states = st.checkbox("Select All States", value=False)

    if select_all_states:
        selected_states = st.multiselect(
            "Choose states to compare:",
            options=all_states,
            default=all_states,
            key="states_multiselect"
        )
    else:
        selected_states = st.multiselect(
            "Choose states to compare:",
            options=all_states,
            default=["California"],
            key="states_multiselect"
        )

    state_series_ids = [state_code_map[state] for state in selected_states]
    df_states = fetch_states_job_data(state_series_ids)

    if df_states is not None and not df_states.empty:
        fig_states = px.line(
            df_states,
            x="date",
            y="pct_change",
            color="State",
            title="Percent Change in Nonfarm Payroll Jobs Since Feb 2020 by State"
        )

        color_map = {trace.name: trace.line.color for trace in fig_states.data}

        for state in selected_states:
            state_df = df_states[df_states["State"] == state].sort_values("date")
            if not state_df.empty:
                latest_row = state_df.iloc[-1]
                fig_states.add_trace(
                    go.Scatter(
                        x=[latest_row["date"]],
                        y=[latest_row["pct_change"]],
                        mode="markers+text",
                        marker=dict(size=10, color=color_map.get(state, "#000000")),
                        text=[f"{latest_row['pct_change']:.2f}%"],
                        textposition="top center",
                        textfont=dict(size=16, family="Avenir", color=color_map.get(state, "#000000")),
                        name=state,
                        hoverinfo="skip",
                        showlegend=False
                    )
                )
            else:
                st.warning(f"No data available for {state}.")

        max_date = df_states["date"].max() + timedelta(days=40)
        hover_mode = "x unified" if len(selected_states) <= 10 else "closest"
        all_dates = df_states["date"]
        latest_common_date = df_states.groupby("State")["date"].max().min()


        # Generate quarterly ticks (Jan, Apr, Jul, Oct) from all state dates
        all_dates = df_states["date"]
        quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())
        ticktext = [
            date.strftime("%b<br>%Y") if date.month == 1 else date.strftime("%b")
            for date in quarterly_ticks
        ]

        # Prevent last-point labels from being clipped
        for i, tr in enumerate(fig_states.data):
            if tr.mode and "text" in tr.mode:
                fig_states.data[i].update(cliponaxis=False)

        fig_states.add_hline(
            y=0,
            line_dash="solid",
            line_color="#000000",
            line_width=1,
            opacity=1.0
        )

        fig_states.update_layout(
            title=dict(
                text=(
                    "<span style='font-size:26px; font-family:Avenir Black'>Job Recovery by State Since the Pandemic</span><br>"
                    "<span style='font-size:17px; color:#666; font-family:Avenir Medium'>"
                    "Percent Change in Non-Farm Payroll Jobs From February 2020 to " 
                    + latest_common_date.strftime('%B %Y') + "</span>"
                ),
                x=0.5,
                xanchor='center'
            ),
            xaxis=dict(
                title='Date',
                title_font=dict(family="Avenir Medium", size=22, color="black"),
                tickfont=dict(family="Avenir", size=16, color="black"),
                tickvals=quarterly_ticks,
                ticktext=ticktext,
                dtick="M1",
                tickangle=0,
                range=["2020-02-01", max_date.strftime("%Y-%m-%d")]
            ),
            yaxis=dict(
                title='Percent Change Since Feb 2020',
                ticksuffix="%",
                title_font=dict(family="Avenir Medium", size=18, color="black"),
                tickfont=dict(family="Avenir", size=16, color="black"),
                showgrid=True,
                gridcolor="#CCCCCC",
                gridwidth=1,
                griddash="dash"
            ),
            hovermode=hover_mode,
            legend=dict(
                title=dict(
                    text="State",
                    font=dict(
                        family="Avenir Black",
                        size=20,
                        color="black"
                    )
                ),
                font=dict(
                    family="Avenir",
                    size=18,
                    color="black"
                ),
                orientation="v",
                x=1.01,
                y=1
            ),
        )

        for trace in fig_states.data:
            if "lines" in trace.mode:
                trace.hovertemplate = trace.name + ": %{y:.2f}%<extra></extra>"
            else:
                trace.hovertemplate = ""

        fig_states.update_xaxes(hoverformat="%b")

        st.plotly_chart(
            fig_states, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "states_job_recovery",
                    "scale": 10
                }
            }
        )
        st.markdown("""
        <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
        </div>
        """, unsafe_allow_html=True)


def show_monthly_job_change_chart(df, region_name):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Monthly Change

    Creates a monthly job change bar chart for a specified Bay Area region.

    The function:
        - Plots month-over-month changes in employment as a bar chart.
        - Colors bars teal for job gains and red for job losses.
        - Displays formatted labels on each bar (e.g., "5K" or "250").
        - Dynamically adjusts the y-axis range with padding, excluding the April 2020 outlier.
        - Shows only quarterly ticks (Jan, Apr, Jul, Oct) for readability.
        - Adds data source and analysis notes below the chart.

    Args:
        df (pd.DataFrame): DataFrame with columns ['date', 'monthly_change', 'label', 'color'].
        region_name (str): Name of the Bay Area region to display in the chart title and legend.

    Returns:
        None. The function directly renders the chart in Streamlit using `st.plotly_chart()`.
    """
    # --- Time-frame selector ---
    with st.container():
        tf_choice = st.radio(
            label="Select Time Frame:",
            options=["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"],
            index=5,  # default = Since COVID-19
            horizontal=True,
            key=f"timeframe_{region_name}"
        )

    # Figure out the latest date present in the data (end anchor)
    data_last = pd.to_datetime(df["date"].max()).to_period("M").to_timestamp()

    # Map choice -> months back
    months_map = {
        "6 Months": 6,
        "12 Months": 12,
        "18 Months": 18,
        "24 Months": 24,
        "36 Months": 36,
    }

    if tf_choice == "Since COVID-19":
        start_date = pd.to_datetime("2020-02-01")
    else:
        # Go back N months from the latest data month and normalize to 1st of month
        n_months = months_map[tf_choice]
        start_date = (data_last - pd.DateOffset(months=n_months-1)).to_period("M").to_timestamp()


    # # --- TEMPORARY OVERRIDE FOR CUSTOM WINDOW: EDIT AS DESIRED ---
    # FORCE_WINDOW = True
    # if FORCE_WINDOW:
    #     start_date = pd.to_datetime("2022-01-01")
    #     data_last = pd.to_datetime("2025-07-01").to_period("M").to_timestamp()
    # # --------------------------------------------------------------

    # --- Filter to selected window ---
    df = df[(df["date"] >= start_date) & (df["date"] <= data_last)].sort_values("date")


    # Calculate dynamic y-axis range excluding April 2020
    df_for_range = df[df["date"] != pd.to_datetime("2020-04-01")]
    y_min = df_for_range["monthly_change"].min()
    y_max = df_for_range["monthly_change"].max()
    
    # Add padding (10% of the range)
    y_range = y_max - y_min
    padding = y_range * 0.1 + 1000
    y_axis_min = y_min - padding
    y_axis_max = y_max + padding

    def format_label(val: float) -> str:
        neg = val < 0
        v = abs(val)
        if v >= 1_000_000:
            s = f"{v/1_000_000:.1f}".rstrip("0").rstrip(".")  # 1.0M -> 1M, 1.2M -> 1.2M
            out = f"{s}M"
        elif v >= 1_000:
            out = f"{v/1_000:.0f}K"                           # 2500 -> 3K (no decimals for K)
        else:
            out = f"{int(v)}"
        return f"-{out}" if neg else out


    df = df.copy()
    df["pretty_label"] = df["monthly_change"].apply(format_label)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["date"],
        y=df["monthly_change"],
        marker_color=df["color"],
        text=df["pretty_label"],
        textposition="outside",
        textfont=dict(
            family="Avenir",
            size=20,
            color="black"
        ),
        name=region_name,
        hovertemplate="%{x|%B %Y}<br>Change: %{y:,.0f} Jobs<extra></extra>"
    ))
    
    # Count bars
    n_bars = len(df)

    # Choose font size dynamically based on bar count
    if n_bars <= 12:       
        label_size = 16
    elif n_bars <= 24:     
        label_size = 14
    elif n_bars <= 36:     
        label_size = 12
    else:                 
        label_size = 7

    fig.update_traces(
        textposition="outside",
        outsidetextfont=dict(family="Avenir", size=label_size, color="black"),
        cliponaxis=False
    )

    fig.update_layout(
        uniformtext_minsize=label_size,
        uniformtext_mode="show"
    )

    quarterly_ticks = df["date"][df["date"].dt.month.isin([1, 4, 7, 10])].unique()
    latest_month = df["date"].max().strftime('%B %Y')

    subtitle = (
        f"{start_date.strftime('%B %Y')} to {data_last.strftime('%B %Y')}"
    )
    
    fig.update_layout(
        title=dict(
                text=(
                    f"<span style='font-size:24px; font-family:Avenir Black'>Monthly Job Changes in {region_name}</span><br>"
                    f"<span style='font-size:17px; color:#666; font-family:Avenir Medium'>{subtitle}</span>"
                ),
                x=0.5,
                xanchor='center'
        ),
        xaxis=dict(
            title='Month',
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            tickvals = quarterly_ticks,
            tickformat="%b\n%Y",
            ticktext = [
                date.strftime("%b<br>%Y") if date.month == 1 else date.strftime("%b")
                for date in quarterly_ticks
            ],
            tickangle=0
        ),
        showlegend=False,
        yaxis=dict(
            title='Monthly Change in Jobs',
            title_font=dict(family="Avenir Medium", size=18, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            showgrid=True,
            range=[y_axis_min, y_axis_max]
        ),
    )

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "monthly_job_change",
                    "scale": 10
                }
            }
    )
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong> Bureau of Labor Statistics (BLS).
    <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong> Data are seasonally adjusted.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis: </strong> Bay Area Council Economic Institute.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Regions:</strong> North Bay (Napa MSA, San Rafael MD, Santa Rosa-Petaluma, Vallejo).
                East Bay (Oakland-Fremont-Berkeley MD). South Bay (San Jose-Sunnyvale-Santa Clara). San Francisco-Peninsula (San Francisco-San Mateo-Redwood City MD).<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")


def create_job_change_summary_table(df):
    """
    Creates and displays a summary statistics table for monthly job changes.

    Calculates key employment change metrics such as:
        - Largest monthly job gain and loss (with date)
        - Average job change over the last 6 months
        - Number of months with job gains and losses
        - Total number of months analyzed

    The function outputs a styled summary table using Streamlit.

    Args:
        df (pd.DataFrame): A DataFrame containing monthly job change data with 
                        columns ['date', 'monthly_change', 'label', 'color'].
    """
        
    st.subheader("Summary")
    
    # Get key statistics
    largest_gain = df.loc[df["monthly_change"].idxmax()]
    largest_loss = df.loc[df["monthly_change"].idxmin()]
    recent_months = df.tail(6)  # Last 6 months
    avg_change_recent = recent_months["monthly_change"].mean()
    
    # Count positive vs negative months
    positive_months = len(df[df["monthly_change"] > 0])
    negative_months = len(df[df["monthly_change"] < 0])
    
    summary_stats = pd.DataFrame({
        'Metric': [
            'Largest Monthly Gain',
            'Largest Monthly Loss', 
            'Average Change (Last 6 Months)',
            'Months with Job Gains',
            'Months with Job Losses',
            'Total Months Analyzed'
        ],
        'Value': [
            f"{largest_gain['monthly_change']:,.0f} jobs ({largest_gain['date'].strftime('%b %Y')})",
            f"{largest_loss['monthly_change']:,.0f} jobs ({largest_loss['date'].strftime('%b %Y')})",
            f"{avg_change_recent:,.0f} jobs",
            f"{positive_months} months",
            f"{negative_months} months", 
            f"{len(df)} months"
        ]
    })
    
    st.dataframe(summary_stats, use_container_width=True, hide_index=True)


def show_bay_area_monthly_job_change(df_bay):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Monthly Change

    Displays a monthly job change bar chart for the Bay Area region (aggregated across all subregions).

    Calculates monthly changes in total employment from February 2020 onward, and visualizes the data 
    as a color-coded bar chart (teal for job gains, red for job losses). April 2020 is excluded from 
    y-axis range calculations to avoid distortion due to extreme outliers.

    Also displays a summary statistics table showing:
        - Largest monthly gain and loss
        - Average change over the last 6 months
        - Number of months with gains and losses
        - Total months analyzed

    Args:
        df_bay (pd.DataFrame): A DataFrame containing total Bay Area employment data with columns 
                            ['date', 'value'] where 'value' is the total employment count.
    """
    df_bay_monthly = df_bay.copy().sort_values("date").reset_index(drop=True)
    df_bay_monthly["date"] = pd.to_datetime(df_bay_monthly["date"]).dt.to_period("M").dt.to_timestamp()
    df_bay_monthly["monthly_change"] = df_bay_monthly["value"].diff()

    # --- Manually override Jan 2024 & Feb 2024 ---
    df_bay_monthly.loc[df_bay_monthly["date"] == pd.to_datetime("2024-01-01"), "monthly_change"] = 1250
    df_bay_monthly.loc[df_bay_monthly["date"] == pd.to_datetime("2024-02-01"), "monthly_change"] = 1250

    # --- Time-frame selector ---
    with st.container():
        tf_choice = st.radio(
            label="Select Time Frame:",
            options=["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"],
            index=5,
            horizontal=True,
            key="timeframe_bay_area"
        )

    data_last = pd.to_datetime(df_bay_monthly["date"].max()).to_period("M").to_timestamp()

    months_map = {"6 Months": 6, "12 Months": 12, "18 Months": 18, "24 Months": 24, "36 Months": 36}
    if tf_choice == "Since COVID-19":
        start_date = pd.to_datetime("2020-02-01")
    else:
        n_months = months_map[tf_choice]
        start_date = (data_last - pd.DateOffset(months=n_months - 1)).to_period("M").to_timestamp()

    # --- Filter window (after diff) ---
    window = (
        df_bay_monthly[(df_bay_monthly["date"] >= start_date) & (df_bay_monthly["date"] <= data_last)]
        .dropna(subset=["monthly_change"])
        .reset_index(drop=True)
    )

    # Labels & colors
    def _fmt_label(x):
        try:
            xi = int(round(x))
        except Exception:
            return ""
        return f"{xi/1000:.0f}K" if abs(xi) >= 1000 else f"{xi}"
    
    window["label"] = window["monthly_change"].apply(_fmt_label)
    window["color"] = window["monthly_change"].apply(lambda x: "#00aca2" if x >= 0 else "#e63946")

    # --- Chart ---
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=window["date"],
            y=window["monthly_change"],
            marker_color=window["color"],
            text=window["label"],
            textposition="outside",
            hovertemplate="%{x|%B %Y}<br>Change: %{y:,.0f} Jobs<extra></extra>",
            name="Monthly Job Change",
        )
    )

    # --- Dynamic label font size ---
    n_bars = len(window)

    # Choose font size dynamically based on bar count
    if n_bars <= 12:       
        label_size = 16
    elif n_bars <= 24:     
        label_size = 14
    elif n_bars <= 36:     
        label_size = 12
    else:                 
        label_size = 7

    fig.update_traces(
        textposition="outside",
        outsidetextfont=dict(family="Avenir", size=label_size, color="black"),
        cliponaxis=False
    )

    fig.update_layout(
        uniformtext_minsize=label_size,
        uniformtext_mode="show"
    )

    # Quarterly ticks
    quarterly_ticks = list(
        window["date"][window["date"].dt.month.isin([1, 4, 7, 10])].drop_duplicates()
    )
    ticktext = [
        ts.strftime("%b<br>%Y") if ts.month == 1 else ts.strftime("%b")
        for ts in quarterly_ticks
    ]

    # Symmetric y-axis (ignore Apr 2020)
    apr_2020 = pd.Timestamp("2020-04-01")
    y_series = window.loc[~(window["date"] == apr_2020), "monthly_change"]
    if y_series.empty:
        y_series = window["monthly_change"]

    vmax = y_series.max() if len(y_series) else 0
    vmin = y_series.min() if len(y_series) else 0
    v = max(abs(vmax), abs(vmin))
    pad = 0.1 * v if v > 0 else 1000
    y_range = [-v - pad, v + pad] if v > 0 else [-2000, 2000]

    subtitle = (
        f"{start_date.strftime('%B %Y')} to {data_last.strftime('%B %Y')}"
    )

    fig.update_layout(
        title=dict(
                text=(
                    f"<span style='font-size:24px; font-family:Avenir Black'>Monthly Job Changes in the Bay Area</span><br>"
                    f"<span style='font-size:17px; color:#666; font-family:Avenir Medium'>{subtitle}</span>"
                ),
                x=0.5,
                xanchor='center'
        ),
        xaxis=dict(
            title="Month",
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            tickmode="array",
            tickvals=quarterly_ticks,
            tickformat="%b\n%Y",
            ticktext=ticktext,
            tickangle=0,
            showgrid=False,
        ),
        yaxis=dict(
            title="Monthly Change in Jobs",
            title_font=dict(family="Avenir Medium", size=18, color="black"),
            tickfont=dict(family="Avenir", size=14, color="black"),
            showgrid=True,
            range=y_range
        ),
        bargap=0.15,
        margin=dict(l=60, r=20, t=80, b=60),
        showlegend=False,
        height=420,
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "toImageButtonOptions": {
                "format": "svg",
                "filename": "bay_area_monthly_job_change",
                "scale": 10,
            }
        },
    )

    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong> Bureau of Labor Statistics (BLS).
    <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong> Data are seasonally adjusted.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis: </strong> Bay Area Council Economic Institute.<br>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Summary Table
    st.subheader("Summary")
    
    # Get key statistics
    largest_gain = df_bay_monthly.loc[df_bay_monthly["monthly_change"].idxmax()]
    largest_loss = df_bay_monthly.loc[df_bay_monthly["monthly_change"].idxmin()]
    recent_months = df_bay_monthly.tail(6)  # Last 6 months
    avg_change_recent = recent_months["monthly_change"].mean()
    
    # Count positive vs negative months
    positive_months = len(df_bay_monthly[df_bay_monthly["monthly_change"] > 0])
    negative_months = len(df_bay_monthly[df_bay_monthly["monthly_change"] < 0])
    
    summary_stats = pd.DataFrame({
        'Metric': [
            'Largest Monthly Gain',
            'Largest Monthly Loss', 
            'Average Change (Last 6 Months)',
            'Months with Job Gains',
            'Months with Job Losses',
            'Total Months Analyzed'
        ],
        'Value': [
            f"{largest_gain['monthly_change']:,.0f} jobs ({largest_gain['date'].strftime('%b %Y')})",
            f"{largest_loss['monthly_change']:,.0f} jobs ({largest_loss['date'].strftime('%b %Y')})",
            f"{avg_change_recent:,.0f} jobs",
            f"{positive_months} months",
            f"{negative_months} months", 
            f"{len(df_bay_monthly)} months"
        ]
    })
    
    st.dataframe(summary_stats, use_container_width=True, hide_index=True)

def show_combined_industry_job_recovery_chart(bay_area_series_mapping, us_series_mapping, BLS_API_KEY):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Industry

    Horizontal bar chart of job recovery by industry with region + time frame + metric selectors.
    Matches the time-frame behavior of show_office_tech_recovery_chart.
    """

    # --- Controls ---
    region_choice = st.selectbox(
        "Select Region:",
        ["Bay Area", "United States"],
        index=0,
        key="industry_region_select"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        tf_choice = st.radio(
            label="Select Time Frame:",
            options=["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"],
            index=5,
            horizontal=True,
            key="industry_timeframe_select"
        )
    with col2:
        metric_choice = st.radio(
            "Metric:",
            ["Percent Change", "Net Change"],
            horizontal=True,
            key="industry_metric_select"
        )

    # Pick mapping based on region
    selected_mapping = bay_area_series_mapping if region_choice == "Bay Area" else us_series_mapping
    title_region = "Bay Area" if region_choice == "Bay Area" else "United States"

    # --- BLS fetch ---
    series_ids = list(selected_mapping.keys())
    all_data = []
    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i:i+25]
        payload = {
            "seriesid": chunk,
            "startyear": "2020",
            "endyear": str(datetime.now().year),
            "registrationKey": BLS_API_KEY
        }
        try:
            response = requests.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json=payload, timeout=30
            )
            data = response.json()
            if "Results" in data and "series" in data["Results"]:
                all_data.extend(data["Results"]["series"])
            else:
                st.warning(f"No data returned for chunk {i//25 + 1}")
        except Exception as e:
            st.error(f"Error fetching chunk {i//25 + 1}: {e}")

    if not all_data:
        st.error("No data could be fetched from BLS API")
        return

    # --- Parse ---
    records = []
    for series in all_data:
        sid = series["seriesID"]
        if sid not in selected_mapping:
            continue
        region, industry = selected_mapping[sid]
        for entry in series["data"]:
            if entry.get("period") == "M13":
                continue
            try:
                date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                if pd.isna(date):
                    continue
                value = float(entry["value"].replace(",", "")) * 1000
                records.append({
                    "series_id": sid,
                    "region": region,
                    "industry": industry,
                    "date": date,
                    "value": value
                })
            except Exception:
                continue

    df = pd.DataFrame(records)
    if df.empty:
        st.error("No valid data records could be processed.")
        return

    # --- Time-frame baseline selection (mirrors office/tech chart) ---
    data_last = pd.to_datetime(df["date"].max()).to_period("M").to_timestamp()
    months_map = {"6 Months": 6, "12 Months": 12, "18 Months": 18, "24 Months": 24, "36 Months": 36}
    if tf_choice == "Since COVID-19":
        baseline_target = pd.to_datetime("2020-02-01")
    else:
        n_months = months_map[tf_choice]
        # Inclusive window: if last is Aug, 12 months spans Sep last year .. Aug this year
        baseline_target = (data_last - pd.DateOffset(months=n_months - 1)).to_period("M").to_timestamp()

    available_dates = df["date"].unique()
    baseline_date = min(available_dates, key=lambda x: abs(x - baseline_target))
    latest_date   = data_last

    baseline_label = pd.to_datetime(baseline_date).strftime("%B %Y")
    title_period   = tf_choice if tf_choice != "Since COVID-19" else "Post-Covid"
    subtitle_text  = f"{baseline_label} to {latest_date.strftime('%B %Y')}"

    # --- Slice baseline/latest ---
    baseline_df = df[df["date"] == baseline_date]
    latest_df   = df[df["date"] == latest_date]

    if baseline_df.empty:
        st.error(f"No data available for baseline period ({baseline_label})")
        return
    if latest_df.empty:
        st.error(f"No data available for latest period ({latest_date.strftime('%b %Y')})")
        return

    # --- Aggregate by industry ---
    baseline_totals = baseline_df.groupby("industry")["value"].sum()
    latest_totals   = latest_df.groupby("industry")["value"].sum()

    # Derived category: Wholesale, Transportation, and Utilities = TTU - Retail
    if "Trade, Transportation, and Utilities" in baseline_totals and "Retail Trade" in baseline_totals:
        baseline_totals["Wholesale, Transportation, and Utilities"] = (
            baseline_totals["Trade, Transportation, and Utilities"] - baseline_totals["Retail Trade"]
        )
    if "Trade, Transportation, and Utilities" in latest_totals and "Retail Trade" in latest_totals:
        latest_totals["Wholesale, Transportation, and Utilities"] = (
            latest_totals["Trade, Transportation, and Utilities"] - latest_totals["Retail Trade"]
        )

    # Keep only industries present in both periods
    industries_with_both = set(baseline_totals.index) & set(latest_totals.index)

    # Percent change
    pct_change = pd.Series(dtype=float)
    for industry in industries_with_both:
        base = baseline_totals[industry]
        if base > 0:
            pct_change[industry] = (latest_totals[industry] - base) / base * 100

    # Net change
    net_change = pd.Series(dtype=float)
    for industry in industries_with_both:
        net_change[industry] = latest_totals[industry] - baseline_totals[industry]

    # Drop aggregate TTU
    pct_change = pct_change.sort_values().drop("Trade, Transportation, and Utilities", errors="ignore")
    net_change = net_change.sort_values().drop("Trade, Transportation, and Utilities", errors="ignore")

    if pct_change.empty and metric_choice == "Percent Change":
        st.error("No industries have sufficient data for percent change comparison")
        return
    if net_change.empty and metric_choice == "Net Change":
        st.error("No industries have sufficient data for net change comparison")
        return

    def nice_step(data_range, target_ticks=8):
        if data_range <= 0:
            return 1
        ideal = data_range / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for m in (1, 2, 2.5, 5, 10):
            step = m * power
            if step >= ideal:
                return step
        return 10 * power

    # --- Choose metric for plotting ---
    if metric_choice == "Net Change":
        selected = net_change
        xaxis_title = f"Net Change in Jobs Since {baseline_label}"
        label_formatter = lambda v: f"{v:+,.0f}"
        tick_value_formatter = lambda x: f"{x:,}"
        is_percent_axis = False
        hover_value_fmt = ":,.0f"
    else:
        selected = pct_change
        xaxis_title = f"Percent Change in Jobs Since {baseline_label}"
        label_formatter = lambda v: f"{v:+.1f}%"
        tick_value_formatter = lambda x: f"{x:.0f}%"
        is_percent_axis = True
        hover_value_fmt = ":.1f"

    vmin = float(selected.min())
    vmax = float(selected.max())
    rng  = vmax - vmin
    if rng <= 0:
        rng = 1.0 if is_percent_axis else 1000.0
    max_abs = max(abs(vmin), abs(vmax))

    # Base padding
    pad_pct = 0.18 if not is_percent_axis else 0.12
    if title_region == "Bay Area" and not is_percent_axis:
        pad_pct = 0.12

    if is_percent_axis:
        min_pad = 2  # percentage points
    else:
        # Scale-aware floor: ~4% of magnitude with a small floor and a sane cap
        min_pad = max(0.04 * max_abs, 1500)
        min_pad = min(min_pad, 75000)

    left_pad  = max(pad_pct * rng, min_pad)
    right_pad = max(pad_pct * rng, min_pad)

    x_min = vmin - left_pad
    x_max = vmax + right_pad

    # Nice tick step & rounded bounds
    step = nice_step(x_max - x_min, target_ticks=6 if is_percent_axis else 7)
    x_min_rounded = np.floor(x_min / step) * step
    x_max_rounded = np.ceil(x_max / step) * step

    tick_positions = np.arange(x_min_rounded, x_max_rounded + 0.5 * step, step)
    tick_labels = (
        [f"{int(round(x)):,}" for x in tick_positions]
        if not is_percent_axis else
        [f"{x:.0f}%" for x in tick_positions]
    )

    # Colors by sign of the plotted metric
    colors = ["#d1493f" if val < 0 else "#00aca2" for val in selected.values]

    # --- Chart ---
    fig = go.Figure()
    order = selected.index  # preserve sorted order

    fig.add_trace(go.Bar(
        y=order,
        x=selected.loc[order].values,
        orientation='h',
        marker_color=colors,
        text=[label_formatter(v) for v in selected.loc[order].values],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate=(
            f"%{{y}}<br>{metric_choice}: %{{x{hover_value_fmt}}}"
            f"<br>{baseline_label}: %{{customdata[0]:,.0f}}"
            f"<br>{latest_date.strftime('%B %Y')}: %{{customdata[1]:,.0f}}<extra></extra>"
        ),
        customdata=[[baseline_totals[ind], latest_totals[ind]] for ind in order]
    ))

    # Vertical dashed grid lines at tick marks
    for tx in tick_positions:
        fig.add_shape(
            type="line",
            x0=tx, y0=-0.5, x1=tx, y1=len(selected) - 0.5,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        xaxis_title=xaxis_title,
        title=dict(
            text=(
                f"{title_region} Job Recovery by Industry<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>{subtitle_text}</span>"
            ),
            x=0.5,
            xanchor='center',
            font=dict(family="Avenir Black", size=26)
        ),
        margin=dict(l=100, r=200, t=80, b=70),
        xaxis=dict(
            tickmode="array",
            tickvals=tick_positions,
            ticktext=tick_labels,
            range=[x_min_rounded, x_max_rounded],
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
        ),
        yaxis=dict(
            tickfont=dict(family="Avenir", size=20, color="black"),
        ),
        showlegend=False,
        height=600
    )

    fig.update_traces(textposition="outside", cliponaxis=False)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "toImageButtonOptions": {
                "format": "svg",
                "filename": "industry_recovery",
                "scale": 10
            }
        }
    )

    st.markdown(f"""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong>Source:</strong> Bureau of Labor Statistics (BLS).<br>
    <strong>Note:</strong> "Education" refers to private education, while public education is included under Government. Total Non-Farm Employment data are seasonally adjusted; other industry data are not.<br>
    <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # --- Summary table ---
    st.subheader("Summary")
    summary_df = pd.DataFrame({
        'Industry': order,
        f'{baseline_label} Jobs': [f"{baseline_totals[ind]:,.0f}" for ind in order],
        f'{latest_date.strftime("%B %Y")} Jobs': [f"{latest_totals[ind]:,.0f}" for ind in order],
        'Net Change': [f"{(latest_totals[ind] - baseline_totals[ind]):+,.0f}" for ind in order],
        'Percent Change': [f"{(pct_change.get(ind, np.nan)):+.1f}%" for ind in order],
    })

    def color_percent(val):
        if isinstance(val, str) and '-' in val:
            return 'color: red'
        else:
            return 'color: green'

    styled_summary = summary_df.style.map(color_percent, subset=['Percent Change'])
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)


def show_sonoma_combined_industry_job_recovery_chart(sonoma_mapping, us_series_mapping, BLS_API_KEY):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Industry

    Horizontal bar chart of job recovery by industry with region + time frame + metric selectors.
    Matches the time-frame behavior of show_office_tech_recovery_chart.
    """

    # --- Controls ---
    region_choice = st.selectbox(
        "Select Region:",
        ["Bay Area", "United States"],
        index=0,
        key="industry_region_select"
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        tf_choice = st.radio(
            label="Select Time Frame:",
            options=["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"],
            index=5,
            horizontal=True,
            key="industry_timeframe_select"
        )
    with col2:
        metric_choice = st.radio(
            "Metric:",
            ["Percent Change", "Net Change"],
            horizontal=True,
            key="industry_metric_select"
        )

    # Pick mapping based on region
    selected_mapping = sonoma_mapping if region_choice == "Sonoma County" else us_series_mapping
    title_region = "Sonoma County" if region_choice == "Sonoma County" else "United States"

    # --- BLS fetch ---
    series_ids = list(selected_mapping.keys())
    all_data = []
    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i:i+25]
        payload = {
            "seriesid": chunk,
            "startyear": "2020",
            "endyear": str(datetime.now().year),
            "registrationKey": BLS_API_KEY
        }
        try:
            response = requests.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json=payload, timeout=30
            )
            data = response.json()
            if "Results" in data and "series" in data["Results"]:
                all_data.extend(data["Results"]["series"])
            else:
                st.warning(f"No data returned for chunk {i//25 + 1}")
        except Exception as e:
            st.error(f"Error fetching chunk {i//25 + 1}: {e}")

    if not all_data:
        st.error("No data could be fetched from BLS API")
        return

    # --- Parse ---
    records = []
    for series in all_data:
        sid = series["seriesID"]
        if sid not in selected_mapping:
            continue
        region, industry = selected_mapping[sid]
        for entry in series["data"]:
            if entry.get("period") == "M13":
                continue
            try:
                date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                if pd.isna(date):
                    continue
                value = float(entry["value"].replace(",", "")) * 1000
                records.append({
                    "series_id": sid,
                    "region": region,
                    "industry": industry,
                    "date": date,
                    "value": value
                })
            except Exception:
                continue

    df = pd.DataFrame(records)
    if df.empty:
        st.error("No valid data records could be processed.")
        return

    # --- Time-frame baseline selection (mirrors office/tech chart) ---
    data_last = pd.to_datetime(df["date"].max()).to_period("M").to_timestamp()
    months_map = {"6 Months": 6, "12 Months": 12, "18 Months": 18, "24 Months": 24, "36 Months": 36}
    if tf_choice == "Since COVID-19":
        baseline_target = pd.to_datetime("2020-02-01")
    else:
        n_months = months_map[tf_choice]
        # Inclusive window: if last is Aug, 12 months spans Sep last year .. Aug this year
        baseline_target = (data_last - pd.DateOffset(months=n_months - 1)).to_period("M").to_timestamp()

    available_dates = df["date"].unique()
    baseline_date = min(available_dates, key=lambda x: abs(x - baseline_target))
    latest_date   = data_last

    baseline_label = pd.to_datetime(baseline_date).strftime("%B %Y")
    title_period   = tf_choice if tf_choice != "Since COVID-19" else "Post-Covid"
    subtitle_text  = f"{baseline_label} to {latest_date.strftime('%B %Y')}"

    # --- Slice baseline/latest ---
    baseline_df = df[df["date"] == baseline_date]
    latest_df   = df[df["date"] == latest_date]

    if baseline_df.empty:
        st.error(f"No data available for baseline period ({baseline_label})")
        return
    if latest_df.empty:
        st.error(f"No data available for latest period ({latest_date.strftime('%b %Y')})")
        return

    # --- Aggregate by industry ---
    baseline_totals = baseline_df.groupby("industry")["value"].sum()
    latest_totals   = latest_df.groupby("industry")["value"].sum()

    # Derived category: Wholesale, Transportation, and Utilities = TTU - Retail
    if "Trade, Transportation, and Utilities" in baseline_totals and "Retail Trade" in baseline_totals:
        baseline_totals["Wholesale, Transportation, and Utilities"] = (
            baseline_totals["Trade, Transportation, and Utilities"] - baseline_totals["Retail Trade"]
        )
    if "Trade, Transportation, and Utilities" in latest_totals and "Retail Trade" in latest_totals:
        latest_totals["Wholesale, Transportation, and Utilities"] = (
            latest_totals["Trade, Transportation, and Utilities"] - latest_totals["Retail Trade"]
        )

    # Keep only industries present in both periods
    industries_with_both = set(baseline_totals.index) & set(latest_totals.index)

    # Percent change
    pct_change = pd.Series(dtype=float)
    for industry in industries_with_both:
        base = baseline_totals[industry]
        if base > 0:
            pct_change[industry] = (latest_totals[industry] - base) / base * 100

    # Net change
    net_change = pd.Series(dtype=float)
    for industry in industries_with_both:
        net_change[industry] = latest_totals[industry] - baseline_totals[industry]

    # Drop aggregate TTU
    pct_change = pct_change.sort_values().drop("Trade, Transportation, and Utilities", errors="ignore")
    net_change = net_change.sort_values().drop("Trade, Transportation, and Utilities", errors="ignore")

    if pct_change.empty and metric_choice == "Percent Change":
        st.error("No industries have sufficient data for percent change comparison")
        return
    if net_change.empty and metric_choice == "Net Change":
        st.error("No industries have sufficient data for net change comparison")
        return

    def nice_step(data_range, target_ticks=8):
        if data_range <= 0:
            return 1
        ideal = data_range / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for m in (1, 2, 2.5, 5, 10):
            step = m * power
            if step >= ideal:
                return step
        return 10 * power

    # --- Choose metric for plotting ---
    if metric_choice == "Net Change":
        selected = net_change
        xaxis_title = f"Net Change in Jobs Since {baseline_label}"
        label_formatter = lambda v: f"{v:+,.0f}"
        tick_value_formatter = lambda x: f"{x:,}"
        is_percent_axis = False
        hover_value_fmt = ":,.0f"
    else:
        selected = pct_change
        xaxis_title = f"Percent Change in Jobs Since {baseline_label}"
        label_formatter = lambda v: f"{v:+.1f}%"
        tick_value_formatter = lambda x: f"{x:.0f}%"
        is_percent_axis = True
        hover_value_fmt = ":.1f"

    vmin = float(selected.min())
    vmax = float(selected.max())
    rng  = vmax - vmin
    if rng <= 0:
        rng = 1.0 if is_percent_axis else 1000.0
    max_abs = max(abs(vmin), abs(vmax))

    # Base padding
    pad_pct = 0.18 if not is_percent_axis else 0.12
    if title_region == "Sonoma County" and not is_percent_axis:
        pad_pct = 0.12

    if is_percent_axis:
        min_pad = 2  # percentage points
    else:
        # Scale-aware floor: ~4% of magnitude with a small floor and a sane cap
        min_pad = max(0.04 * max_abs, 1500)
        min_pad = min(min_pad, 75000)

    left_pad  = max(pad_pct * rng, min_pad)
    right_pad = max(pad_pct * rng, min_pad)

    x_min = vmin - left_pad
    x_max = vmax + right_pad

    # Nice tick step & rounded bounds
    step = nice_step(x_max - x_min, target_ticks=6 if is_percent_axis else 7)
    x_min_rounded = np.floor(x_min / step) * step
    x_max_rounded = np.ceil(x_max / step) * step

    tick_positions = np.arange(x_min_rounded, x_max_rounded + 0.5 * step, step)
    tick_labels = (
        [f"{int(round(x)):,}" for x in tick_positions]
        if not is_percent_axis else
        [f"{x:.0f}%" for x in tick_positions]
    )

    # Colors by sign of the plotted metric
    colors = ["#d1493f" if val < 0 else "#00aca2" for val in selected.values]

    # --- Chart ---
    fig = go.Figure()
    order = selected.index  # preserve sorted order

    fig.add_trace(go.Bar(
        y=order,
        x=selected.loc[order].values,
        orientation='h',
        marker_color=colors,
        text=[label_formatter(v) for v in selected.loc[order].values],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate=(
            f"%{{y}}<br>{metric_choice}: %{{x{hover_value_fmt}}}"
            f"<br>{baseline_label}: %{{customdata[0]:,.0f}}"
            f"<br>{latest_date.strftime('%B %Y')}: %{{customdata[1]:,.0f}}<extra></extra>"
        ),
        customdata=[[baseline_totals[ind], latest_totals[ind]] for ind in order]
    ))

    # Vertical dashed grid lines at tick marks
    for tx in tick_positions:
        fig.add_shape(
            type="line",
            x0=tx, y0=-0.5, x1=tx, y1=len(selected) - 0.5,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        xaxis_title=xaxis_title,
        title=dict(
            text=(
                f"{title_region} Job Recovery by Industry<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>{subtitle_text}</span>"
            ),
            x=0.5,
            xanchor='center',
            font=dict(family="Avenir Black", size=26)
        ),
        margin=dict(l=100, r=200, t=80, b=70),
        xaxis=dict(
            tickmode="array",
            tickvals=tick_positions,
            ticktext=tick_labels,
            range=[x_min_rounded, x_max_rounded],
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
        ),
        yaxis=dict(
            tickfont=dict(family="Avenir", size=20, color="black"),
        ),
        showlegend=False,
        height=600
    )

    fig.update_traces(textposition="outside", cliponaxis=False)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "toImageButtonOptions": {
                "format": "svg",
                "filename": "industry_recovery",
                "scale": 10
            }
        }
    )

    st.markdown(f"""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong>Source:</strong> Bureau of Labor Statistics (BLS).<br>
    <strong>Note:</strong> "Education" refers to private education, while public education is included under Government. Total Non-Farm Employment data are seasonally adjusted; other industry data are not.<br>
    <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # --- Summary table ---
    st.subheader("Summary")
    summary_df = pd.DataFrame({
        'Industry': order,
        f'{baseline_label} Jobs': [f"{baseline_totals[ind]:,.0f}" for ind in order],
        f'{latest_date.strftime("%B %Y")} Jobs': [f"{latest_totals[ind]:,.0f}" for ind in order],
        'Net Change': [f"{(latest_totals[ind] - baseline_totals[ind]):+,.0f}" for ind in order],
        'Percent Change': [f"{(pct_change.get(ind, np.nan)):+.1f}%" for ind in order],
    })

    def color_percent(val):
        if isinstance(val, str) and '-' in val:
            return 'color: red'
        else:
            return 'color: green'

    styled_summary = summary_df.style.map(color_percent, subset=['Percent Change'])
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)



def show_office_tech_recovery_chart(office_metros_mapping, BLS_API_KEY):
    """
    Dashboard Section: Employment
    Dashboard Subtab: Office Sector

    Displays a horizontal bar chart showing percent change in Office/Tech sector jobs 
    for selected metro areas, with a toggle between:
    - Since Feb 2020
    - Last 12 Months

    Office/Tech jobs include: Information, Financial Activities, and Professional & Business Services.

    Args:
        office_metros_mapping (dict): Mapping of BLS series IDs to (region, sector).
        BLS_API_KEY (str): User's BLS API key.

    Returns:
        None. Displays chart and summary in Streamlit.
    """

    with st.container():
        c1, c2 = st.columns([1, 1])
        with c1:
            tf_choice = st.radio(
                label="Select Time Frame:",
                options=["6 Months", "12 Months", "18 Months", "24 Months", "36 Months", "Since COVID-19"],
                index=5,
                horizontal=True,
                key="office_timeframe_select"
            )
        with c2:
            metric_choice = st.radio(
                "Metric:",
                ["Percent Change", "Net Change"],
                index=0,
                horizontal=True,
                key="office_metric_select"
            )

    # --- Step 1: Fetch BLS data ---
    series_ids = list(office_metros_mapping.keys())
    all_data = []
    for i in range(0, len(series_ids), 25):
        chunk = series_ids[i:i+25]
        payload = {
            "seriesid": chunk,
            "startyear": "2020",
            "endyear": str(datetime.now().year),
            "registrationKey": BLS_API_KEY
        }
        try:
            response = requests.post(
                "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                json=payload, timeout=30
            )
            data = response.json()
            if "Results" in data and "series" in data["Results"]:
                all_data.extend(data["Results"]["series"])
            else:
                st.warning(f"No data returned for chunk {i//25 + 1}")
        except Exception as e:
            st.error(f"Error fetching chunk {i//25 + 1}: {e}")

    # --- Step 2: Parse ---
    records = []
    for series in all_data:
        sid = series["seriesID"]
        if sid not in office_metros_mapping:
            continue
        metro, sector = office_metros_mapping[sid]
        for entry in series["data"]:
            if entry["period"] == "M13":
                continue
            try:
                date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                value = float(entry["value"].replace(",", "")) * 1000
                records.append({"metro": metro, "sector": sector, "date": date, "value": value})
            except Exception:
                continue

    df = pd.DataFrame(records)
    if df.empty:
        st.error("No valid data records could be processed.")
        return

    # --- Step 3: Define baseline and latest dates (same logic as monthly chart) ---
    data_last = pd.to_datetime(df["date"].max()).to_period("M").to_timestamp()
    months_map = {"6 Months": 6, "12 Months": 12, "18 Months": 18, "24 Months": 24, "36 Months": 36}
    if tf_choice == "Since COVID-19":
        baseline_target = pd.to_datetime("2020-02-01")
    else:
        n_months = months_map[tf_choice]
        baseline_target = (data_last - pd.DateOffset(months=n_months - 1)).to_period("M").to_timestamp()

    available_dates = df["date"].unique()
    baseline_date = min(available_dates, key=lambda x: abs(x - baseline_target))
    latest_date = data_last
    baseline_label = pd.to_datetime(baseline_date).strftime("%B %Y")
    title_suffix = f"{baseline_label} to {latest_date.strftime('%B %Y')}"

    # --- Step 4: Aggregate Office/Tech totals per metro ---
    office_sectors = ["Information", "Financial Activities", "Professional and Business Services"]
    baseline_df = df[(df["date"] == baseline_date) & (df["sector"].isin(office_sectors))]
    latest_df   = df[(df["date"] == latest_date) & (df["sector"].isin(office_sectors))]

    baseline_totals = baseline_df.groupby("metro")["value"].sum()
    latest_totals   = latest_df.groupby("metro")["value"].sum()

    # Common metros in both periods
    common_metros = list(set(baseline_totals.index) & set(latest_totals.index))
    if not common_metros:
        st.error("No metros have data for both selected periods.")
        return

    # Build both metrics
    pct_change = pd.Series(
        {m: ((latest_totals[m] - baseline_totals[m]) / baseline_totals[m] * 100.0)
        for m in common_metros if baseline_totals[m] > 0},
        dtype=float
    ).sort_values(ascending=True)

    net_change = pd.Series(
        {m: (latest_totals[m] - baseline_totals[m]) for m in common_metros},
        dtype=float
    ).sort_values(ascending=True)

    # Short names for y-axis labels (stable regardless of metric order)
    short_name_map = {m: rename_mapping.get(m, m) for m in common_metros}

    # --- Choose metric for plotting ---
    if metric_choice == "Net Change":
        selected = net_change
        xaxis_title = "Net Change in Jobs"
        label_formatter = lambda v: f"{v:+,.0f}"
        is_percent_axis = False
        hover_value_fmt = ":,.0f"
    else:
        selected = pct_change
        xaxis_title = "Percent Change"
        label_formatter = lambda v: f"{v:+.1f}%"
        is_percent_axis = True
        hover_value_fmt = ":.1f"

    if selected.empty:
        st.warning(f"No data available for {metric_choice.lower()} with the selected time frame.")
        return

    # Preserve sorted order
    order = selected.index.tolist()

    # Colors: highlight Bay Area metros in gold; otherwise teal
    highlight = {
        "San Jose-Sunnyvale-Santa Clara, CA",
        "San Francisco-Oakland-Fremont, CA"
    }
    colors = ["#eeaf30" if m in highlight else "#00aca2" for m in order]

    # Y labels (optionally color Sonoma if present in short name)
    colored_labels = []
    for m in order:
        name = short_name_map[m]
        if "Sonoma" in name:
            colored_labels.append(f'<span style="color:#d84f19">{name}</span>')
        else:
            colored_labels.append(name)

    # --- Axis: dynamic ticks and padding (scale-aware) ---
    def nice_step(data_range, target_ticks=8):
        if data_range <= 0:
            return 1
        ideal = data_range / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for mult in (1, 2, 2.5, 5, 10):
            step = mult * power
            if step >= ideal:
                return step
        return 10 * power

    vmin, vmax = float(selected.min()), float(selected.max())
    rng = vmax - vmin
    if rng <= 0:
        rng = 1.0 if is_percent_axis else 1000.0
    max_abs = max(abs(vmin), abs(vmax))

    pad_pct = 0.12 if is_percent_axis else 0.18
    if not is_percent_axis:
        # Scale-aware floor for net change
        min_pad = max(0.04 * max_abs, 1500)
        min_pad = min(min_pad, 75000)
    else:
        min_pad = 2  # percentage points

    left_pad  = max(pad_pct * rng, min_pad)
    right_pad = max(pad_pct * rng, min_pad)

    x_min = vmin - left_pad
    x_max = vmax + right_pad

    step = nice_step(x_max - x_min, target_ticks=6 if is_percent_axis else 7)
    x_min_rounded = np.floor(x_min / step) * step
    x_max_rounded = np.ceil(x_max / step) * step

    tick_positions = np.arange(x_min_rounded, x_max_rounded + 0.5 * step, step)
    tick_labels = (
        [f"{x:.0f}%" for x in tick_positions] if is_percent_axis
        else [f"{int(round(x)):,}" for x in tick_positions]
    )

    # --- Chart ---
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=colored_labels,
        x=[selected[m] for m in order],
        orientation='h',
        marker_color=colors,
        text=[label_formatter(selected[m]) for m in order],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate=(
            f"%{{y}}<br>{metric_choice}: %{{x{hover_value_fmt}}}"
            f"<br>{baseline_label}: %{{customdata[0]:,.0f}}"
            f"<br>{latest_date.strftime('%B %Y')}: %{{customdata[1]:,.0f}}<extra></extra>"
        ),
        customdata=[[baseline_totals[m], latest_totals[m]] for m in order]
    ))

    # Dashed grid lines at ticks
    for x in tick_positions:
        fig.add_shape(
            type="line",
            x0=x, y0=-0.5, x1=x, y1=len(order) - 0.5,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        title=dict(
            text=(
                "Employment in Key Office Sectors by Metro Area<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>{title_suffix}</span>"
            ),
            x=0.5, xanchor='center',
            font=dict(family="Avenir Black", size=26)
        ),
        margin=dict(l=200, r=110, t=80, b=50),
        xaxis=dict(
            title=xaxis_title,
            tickmode="array",
            tickvals=tick_positions,
            ticktext=tick_labels,
            range=[x_min_rounded, x_max_rounded],
            tickformat=".1f" if is_percent_axis else ",.0f",
            ticksuffix="%" if is_percent_axis else "",
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=18, color="black"),
        ),
        yaxis=dict(
            tickfont=dict(family="Avenir Medium", size=20, color="black")
        ),
        showlegend=False,
        height=700
    )

    fig.update_traces(textposition="outside", cliponaxis=False)

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "toImageButtonOptions": {
                "format": "svg",
                "filename": "office_sector_recovery",
                "scale": 10
            }
        }
    )

    st.markdown("""
        <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS).
        <strong>Note:</strong> Data are not seasonally adjusted. Sectors include Information, Financial Activities, and Professional &amp; Business Services.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute.
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("---")

    # --- Summary table ---
    st.subheader("Summary")
    pct_for_summary = [f"{(pct_change.get(m, np.nan)):+.1f}%" for m in order]
    net_for_summary = [f"{(latest_totals[m] - baseline_totals[m]):+,.0f}" for m in order]
    summary_df = pd.DataFrame({
        'Metro': [short_name_map[m] for m in order],
        f'{baseline_label} Jobs': [f"{baseline_totals[m]:,.0f}" for m in order],
        f'{latest_date.strftime("%B %Y")} Jobs': [f"{latest_totals[m]:,.0f}" for m in order],
        'Net Change': net_for_summary,
        'Percent Change': pct_for_summary,
    })

    def color_percent(val):
        if isinstance(val, str) and '-' in val:
            return 'color: red'
        else:
            return 'color: green'

    styled_summary = summary_df.style.map(color_percent, subset=['Percent Change'])
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)



@st.cache_data(ttl=86400)
def fetch_bls_employment_for_ratios():
    """
    Fetches BLS employment data for the specific metro areas needed for jobs ratio analysis.
    Now includes all Bay Area regions for total calculation and extends to 2015 for Sonoma County.
    """
    # Mapping of area names to BLS series IDs - expanded to include all Bay Area regions
    area_to_series = {
        "San Francisco-San Mateo-Redwood City MD": "SMS06418840000000001",
        "San Jose-Sunnyvale-Santa Clara MSA": "SMS06419400000000001", 
        "Oakland-Fremont-Berkeley MD": "SMS06360840000000001",
        "Napa MSA": "SMS06349000000000001",
        "Santa Rosa-Petaluma MSA": "SMS06422200000000001",
        "San Rafael MD": "SMS06420340000000001",
        "Vallejo MSA": "SMS06467000000000001"
    }
    
    series_ids = list(area_to_series.values())
    
    payload = {
        "seriesid": series_ids,
        "startyear": "2015",  # Extended to include 2015 for Sonoma County
        "endyear": str(datetime.now().year),
        "registrationKey": BLS_API_KEY
    }
    
    try:
        response = requests.post(
            "https://api.bls.gov/publicAPI/v2/timeseries/data/",
            json=payload, timeout=30
        )
        data = response.json()
        
        if "Results" not in data or "series" not in data["Results"]:
            st.error("BLS API error: No results returned for jobs ratio data.")
            return None
        
        all_records = []
        
        for series in data["Results"]["series"]:
            series_id = series["seriesID"]
            area_name = next((area for area, sid in area_to_series.items() if sid == series_id), series_id)
            
            for entry in series["data"]:
                if entry["period"] != "M13":  # Skip annual averages
                    try:
                        date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                        value = float(entry["value"].replace(",", "")) * 1000  # Convert to actual counts
                        
                        all_records.append({
                            "Area Name": area_name,
                            "Date": date,
                            "Year": int(entry["year"]),
                            "Month": entry["periodName"],
                            "Employment": value
                        })
                    except (ValueError, TypeError):
                        continue
        
        if not all_records:
            st.error("No valid BLS data records could be processed for jobs ratio")
            return None
            
        df = pd.DataFrame(all_records)
        return df
        
    except Exception as e:
        st.error(f"Failed to fetch BLS data for jobs ratio: {e}")
        return None


@st.cache_data(ttl=86400)
def fetch_laus_employment_data():
    """
    Fetches LAUS employment data for specific Bay Area metro areas from CA Open Data Portal.
    Returns data for 2015, 2019, and the latest available year.
    Now includes all Bay Area regions for total calculation and 2015 for Sonoma County.
    """
    API_ENDPOINT = "https://data.ca.gov/api/3/action/datastore_search"
    RESOURCE_ID = "b4bc4656-7866-420f-8d87-4eda4c9996ed"
    
    # Expanded target areas to include all Bay Area regions
    target_areas = [
        "San Francisco-San Mateo-Redwood City MD",
        "San Jose-Sunnyvale-Santa Clara MSA", 
        "Oakland-Fremont-Berkeley MD",
        "Napa MSA",
        "Santa Rosa-Petaluma MSA",
        "San Rafael MD",
        "Vallejo MSA"
    ]
    
    try:
        # Get a sample to determine the latest year available
        response = requests.get(API_ENDPOINT, params={
            "resource_id": RESOURCE_ID,
            "limit": 5000,
            "sort": "Year desc"
        }, timeout=30)
        
        if response.status_code != 200:
            st.error(f"Failed to connect to CA Open Data API. Status code: {response.status_code}")
            return None
            
        sample_data = response.json()["result"]["records"]
        sample_df = pd.DataFrame(sample_data)
        
        # Find the latest year in the dataset
        sample_df["Year"] = pd.to_numeric(sample_df["Year"], errors="coerce")
        latest_year = int(sample_df["Year"].max())

        # Fetch all data for our target areas and years (including 2015)
        all_records = []
        
        # Fetch data in chunks
        response = requests.get(API_ENDPOINT, params={"resource_id": RESOURCE_ID, "limit": 1}, timeout=30)
        total_records = response.json()["result"]["total"]
        chunk_size = 10000
        
        for offset in range(0, total_records, chunk_size):
            response = requests.get(API_ENDPOINT, params={
                "resource_id": RESOURCE_ID,
                "limit": min(chunk_size, total_records - offset),
                "offset": offset
            }, timeout=30)
            
            if response.status_code == 200:
                chunk_data = response.json()["result"]["records"]
                # Filter for our target areas and years during fetch to reduce memory
                for record in chunk_data:
                    if (record.get("Area Name") in target_areas and 
                        record.get("Year") in ["2015", "2019", str(latest_year)]):
                        all_records.append(record)
            else:
                st.warning(f"Failed to fetch chunk at offset {offset}")
        
        if not all_records:
            st.error("No LAUS data found for target areas and years")
            return None
            
        df = pd.DataFrame(all_records)
        
        # Clean and filter the data
        df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
        df["Employment"] = pd.to_numeric(df["Employment"], errors="coerce")
        df = df.dropna(subset=["Year", "Employment"])
        
        # Filter for target years (2015, 2019 and latest year)
        df = df[df["Year"].isin([2015, 2019, latest_year])]
        return df
        
    except Exception as e:
        st.error(f"Error fetching LAUS data: {str(e)}")
        return None


def show_jobs_ratio_chart():
    """
    Dashboard Section: Employment
    Dashboard Subtab: Jobs Ratio

    Creates a jobs ratio chart comparing BLS/LAUS employment ratios between 2019 and latest year.
    Now includes Bay Area Total as an additional region and Sonoma County 2015 data.
    """
    # Fetch data from both sources
    laus_df = fetch_laus_employment_data()
    bls_df = fetch_bls_employment_for_ratios()
    
    if laus_df is None or bls_df is None:
        st.error("Unable to fetch required data for jobs ratio analysis")
        return
    
    # Find the latest available month in BLS data
    latest_bls_date = bls_df["Date"].max()
    latest_month = latest_bls_date.strftime("%B")
    latest_year = latest_bls_date.year
    
    # Filter BLS data for the specific months we need
    bls_2015 = bls_df[(bls_df["Year"] == 2015) & (bls_df["Month"] == latest_month)]
    bls_2019 = bls_df[(bls_df["Year"] == 2019) & (bls_df["Month"] == latest_month)]
    bls_latest = bls_df[(bls_df["Year"] == latest_year) & (bls_df["Month"] == latest_month)]
    
    # Filter LAUS data for all years
    laus_2015 = laus_df[laus_df["Year"] == 2015]
    laus_2019 = laus_df[laus_df["Year"] == 2019]
    laus_latest = laus_df[laus_df["Year"] == latest_year]
    
    # Find the matching month in LAUS data for all years
    if "Month" in laus_2015.columns:
        laus_2015_month = laus_2015[laus_2015["Month"] == latest_month]
    else:
        st.warning("Month-specific LAUS data not available for 2015, using available 2015 data")
        laus_2015_month = laus_2015

    if "Month" in laus_2019.columns:
        laus_2019_month = laus_2019[laus_2019["Month"] == latest_month]
    else:
        st.warning("Month-specific LAUS data not available for 2019, using available 2019 data")
        laus_2019_month = laus_2019

    if "Month" in laus_latest.columns:
        laus_latest_month = laus_latest[laus_latest["Month"] == latest_month]
    else:
        st.warning(f"Month-specific LAUS data not available for {latest_year}, using available {latest_year} data")
        laus_latest_month = laus_latest
    
    # Create results for visualization
    results = []
    
    # Individual target areas (original 5)
    individual_areas = [
        "San Francisco-San Mateo-Redwood City MD",
        "San Jose-Sunnyvale-Santa Clara MSA", 
        "Oakland-Fremont-Berkeley MD"
        # "Napa MSA",
        # "Santa Rosa-Petaluma MSA"
    ]
    
    # All Bay Area regions for total calculation
    all_bay_area_regions = [
        "San Francisco-San Mateo-Redwood City MD",
        "San Jose-Sunnyvale-Santa Clara MSA", 
        "Oakland-Fremont-Berkeley MD",
        "Napa MSA",
        "Santa Rosa-Petaluma MSA",
        "San Rafael MD",
        "Vallejo MSA"
    ]
    
    # Display name mapping
    display_name_mapping = {
        "San Francisco-San Mateo-Redwood City MD": "SF/San Mateo",
        "San Jose-Sunnyvale-Santa Clara MSA": "South Bay",
        "Oakland-Fremont-Berkeley MD": "East Bay", 
        "Napa MSA": "Napa County",
        "Santa Rosa-Petaluma MSA": "Sonoma County"
    }
    
    # Process individual areas (2019 and latest year)
    for area in individual_areas:
        # Get LAUS employment for both years
        laus_2019_emp = laus_2019_month[laus_2019_month["Area Name"] == area]["Employment"]
        laus_latest_emp = laus_latest_month[laus_latest_month["Area Name"] == area]["Employment"]
        
        if laus_2019_emp.empty:
            st.warning(f"No LAUS 2019 data found for {area}")
            continue
        
        if laus_latest_emp.empty:
            st.warning(f"No LAUS {latest_year} data found for {area}")
            continue
            
        laus_2019_value = laus_2019_emp.iloc[0]
        laus_latest_value = laus_latest_emp.iloc[0]
        
        # Get BLS employment for both years
        bls_2019_emp = bls_2019[bls_2019["Area Name"] == area]["Employment"]
        bls_latest_emp = bls_latest[bls_latest["Area Name"] == area]["Employment"]
        
        if not bls_2019_emp.empty and not bls_latest_emp.empty and laus_2019_value > 0 and laus_latest_value > 0:
            # Calculate ratios using respective year LAUS data
            ratio_2019 = bls_2019_emp.iloc[0] / laus_2019_value
            ratio_latest = bls_latest_emp.iloc[0] / laus_latest_value
            
            display_name = display_name_mapping.get(area, area)
            
            results.append({
                "Region": display_name,
                "Period": f"2019",
                "Ratio": ratio_2019,
                "BLS_Employment": bls_2019_emp.iloc[0],
                "LAUS_Employment": laus_2019_value
            })
            
            results.append({
                "Region": display_name, 
                "Period": f"{latest_year}",
                "Ratio": ratio_latest,
                "BLS_Employment": bls_latest_emp.iloc[0],
                "LAUS_Employment": laus_latest_value
            })
        else:
            st.warning(f"Missing data for {area}")
    
    # # Special handling for Sonoma County 2015 data
    # sonoma_area = "Santa Rosa-Petaluma MSA"
    # laus_2015_emp = laus_2015_month[laus_2015_month["Area Name"] == sonoma_area]["Employment"]
    # bls_2015_emp = bls_2015[bls_2015["Area Name"] == sonoma_area]["Employment"]
    
    # if not laus_2015_emp.empty and not bls_2015_emp.empty:
    #     laus_2015_value = laus_2015_emp.iloc[0]
    #     if laus_2015_value > 0:
    #         ratio_2015 = bls_2015_emp.iloc[0] / laus_2015_value
            
    #         results.append({
    #             "Region": "Sonoma County",
    #             "Period": "2015",
    #             "Ratio": ratio_2015,
    #             "BLS_Employment": bls_2015_emp.iloc[0],
    #             "LAUS_Employment": laus_2015_value
    #         })
    # else:
    #     st.warning("No 2015 data available for Sonoma County")
    


    # Calculate Bay Area Total (2019 and latest year only)
    # Sum BLS employment for all Bay Area regions
    bls_2019_total = bls_2019[bls_2019["Area Name"].isin(all_bay_area_regions)]["Employment"].sum()
    bls_latest_total = bls_latest[bls_latest["Area Name"].isin(all_bay_area_regions)]["Employment"].sum()
    
    # Sum LAUS employment for all Bay Area regions
    laus_2019_total = laus_2019_month[laus_2019_month["Area Name"].isin(all_bay_area_regions)]["Employment"].sum()
    laus_latest_total = laus_latest_month[laus_latest_month["Area Name"].isin(all_bay_area_regions)]["Employment"].sum()
    
    # Calculate Bay Area total ratios if we have valid data
    if bls_2019_total > 0 and bls_latest_total > 0 and laus_2019_total > 0 and laus_latest_total > 0:
        bay_area_ratio_2019 = bls_2019_total / laus_2019_total
        bay_area_ratio_latest = bls_latest_total / laus_latest_total
        
        results.append({
            "Region": "Bay Area",
            "Period": f"2019",
            "Ratio": bay_area_ratio_2019,
            "BLS_Employment": bls_2019_total,
            "LAUS_Employment": laus_2019_total
        })
        
        results.append({
            "Region": "Bay Area", 
            "Period": f"{latest_year}",
            "Ratio": bay_area_ratio_latest,
            "BLS_Employment": bls_latest_total,
            "LAUS_Employment": laus_latest_total
        })
    else:
        st.warning("Could not calculate Bay Area Total due to missing data")
    
    if not results:
        st.error("No valid data available to create jobs ratio chart")
        return
    
    # Create DataFrame and plot
    ratio_df = pd.DataFrame(results)
    
    # Create the grouped bar chart
    fig = go.Figure()
    
    periods = sorted(ratio_df["Period"].unique())
    regions = list(ratio_df["Region"].unique())
    
    # Updated colors for three periods
    colors =  ["#00aca2", "#eeaf30", "#203864"]
    
    # Calculate bar width and offsets for better centering
    bar_width = 0.25
    total_periods = len(periods)
    
    for i, period in enumerate(periods):
        period_data = ratio_df[ratio_df["Period"] == period]
        
        # Create x positions and y values for each region
        x_positions = []
        y_values = []
        custom_data = []
        region_names = []  # Track the actual region names
        
        for region in regions:
            region_data = period_data[period_data["Region"] == region]
            if not region_data.empty:
                # Calculate offset based on how many bars this region has
                region_periods = ratio_df[ratio_df["Region"] == region]["Period"].unique()
                n_bars_for_region = len(region_periods)
                
                if region == "Sonoma County" and n_bars_for_region == 3:
                    # For Sonoma County with 3 bars, use standard offset
                    offset = (i - 1) * bar_width
                else:
                    # For regions with 2 bars, adjust offset to center them
                    if period == "2015":
                        continue  # Skip 2015 for non-Sonoma regions
                    period_idx = 0 if period == "2019" else 1
                    offset = (period_idx - 0.5) * bar_width
                
                x_positions.append(regions.index(region) + offset)
                y_values.append(region_data["Ratio"].iloc[0])
                custom_data.append([region_data["BLS_Employment"].iloc[0], 
                                region_data["LAUS_Employment"].iloc[0]])
                region_names.append(region)  # Store the actual region name
        
        if x_positions:  # Only add trace if there are data points
            # Create custom legend names
            legend_names = {
                "2015": "2015",
                "2019": "2019", 
                str(latest_year): f"{latest_year}"
            }
            
            fig.add_trace(go.Bar(
                name=legend_names.get(period, period),  # Use custom legend name
                x=x_positions,
                y=y_values,
                width=bar_width,
                marker_color=colors[i % len(colors)],
                text=[f"{val:.2f}" for val in y_values],
                textposition="outside",
                textfont=dict(size=25, family="Avenir", color="black"),
                hovertemplate=f"<b>%{{customdata[2]}}</b><br>{period}: %{{y:.3f}}<br>" +
                            "CES Employment: %{customdata[0]:,.0f}<br>" +
                            "LAUS Employment: %{customdata[1]:,.0f}<extra></extra>",
                customdata=[[cd[0], cd[1], region_names[j]] 
                        for j, cd in enumerate(custom_data)]
            ))
    
    fig.update_layout(
        title=dict(
            text=f"Ratio of Jobs to Employed Residents<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>"
                f"{latest_month} 2019 vs {latest_month} {latest_year}",
            x=0.5,
            xanchor='center',
            font=dict(family="Avenir Black", size=24)
        ),
        xaxis=dict(
            title="Metro Area",
            title_font=dict(family="Avenir Medium", size=20, color="black"),
            tickfont=dict(family="Avenir", size=20, color="black"),
            tickangle=0,
            tickmode='array',
            tickvals=list(range(len(regions))),
            ticktext=regions
        ),
        yaxis=dict(
            title="Employment Ratio",
            title_font=dict(family="Avenir Medium", size=20, color="black"),
            tickfont=dict(family="Avenir", size=20, color="black"),
            showgrid=True,
            gridcolor="#CCCCCC",
            gridwidth=1,
            griddash="dash",
            range=[0, ratio_df["Ratio"].max() * 1.15]
        ),
        barmode='overlay',
        legend=dict(
            font=dict(family="Avenir", size=25, color="black"),
            orientation="v",
            x=1.01,
            y=1
        ),
        height=700,
        showlegend=True,
        margin=dict(b=120)
    )

    # Add horizontal line at y=1.00
    fig.add_hline(
        y=1.00,
        line_dash="dash",
        line_color="black",
        line_width=2,
    )

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "job_ratio",
                    "scale": 10        
                }
            }
        )

    # Add explanation and sources
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong> Bureau of Labor Statistics (BLS) and Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong> Ratio greater than 1 means more jobs than employed residents in a region.<br>BLS data are seasonally adjusted nonfarm payroll jobs. LAUS data are total employment including farm jobs and self-employed. <br> Each ratio uses the respective year's LAUS data as denominator. Bay Area Total includes all 7 metro divisions/MSAs.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    
    # Summary table
    st.subheader("Summary Table")
    
    # Reshape data for better table display
    summary_data = []
    for region in regions:
        region_data = ratio_df[ratio_df["Region"] == region]
        
        # Handle different regions with different years available
        if region == "Sonoma County":
            # For Sonoma County, show all three years if available
            ratios = {}
            for _, row in region_data.iterrows():
                ratios[row["Period"]] = row["Ratio"]
            
            row_data = {"Metro Area": region}
            if "2015" in ratios:
                row_data["2015 Ratio"] = f"{ratios['2015']:.3f}"
            if "2019" in ratios:
                row_data["2019 Ratio"] = f"{ratios['2019']:.3f}"
            if str(latest_year) in ratios:
                row_data[f"{latest_year} Ratio"] = f"{ratios[str(latest_year)]:.3f}"
            
            # Calculate changes if we have both 2019 and latest year
            if "2019" in ratios and str(latest_year) in ratios:
                change = ratios[str(latest_year)] - ratios["2019"]
                pct_change = (change / ratios["2019"]) * 100
                row_data["Change (2019 to Latest)"] = f"{change:+.3f}"
                row_data["% Change (2019 to Latest)"] = f"{pct_change:+.1f}%"
            
            summary_data.append(row_data)
        else:
            # For other regions, show 2019 and latest year comparison
            if len(region_data) == 2:
                ratio_2019 = region_data[region_data["Period"].str.contains("2019")]["Ratio"].iloc[0]
                ratio_latest = region_data[region_data["Period"].str.contains(str(latest_year))]["Ratio"].iloc[0]
                
                summary_data.append({
                    "Metro Area": region,
                    f"2019 Ratio": f"{ratio_2019:.3f}",
                    f"{latest_year} Ratio": f"{ratio_latest:.3f}",
                    "Change (2019 to Latest)": f"{ratio_latest - ratio_2019:+.3f}",
                    "% Change (2019 to Latest)": f"{((ratio_latest - ratio_2019) / ratio_2019) * 100:+.1f}%"
                })
    
    summary_df = pd.DataFrame(summary_data)
    
    # Style the table
    def color_change(val):
        if '+' in str(val):
            return 'color: green'
        elif '-' in str(val):
            return 'color: red'
        return ''
    
    # Apply styling to change columns
    change_columns = [col for col in summary_df.columns if 'Change' in col]
    styled_summary = summary_df.style.map(color_change, subset=change_columns)
    st.dataframe(styled_summary, use_container_width=True, hide_index=True)


def show_metro_population_change_chart(
    csv_path: str = "docs/data_build/Metro_Population.csv",
    rename_mapping: dict[str, str] | None = None,
):
    """
    Reads a wide CSV with columns:
      Year, United States, Atlanta, Austin, ..., Washington D.C.
    and renders a horizontal bar chart of PERCENT change in population for a chosen timeframe:
      - Last Year, Last 5 Years, Last 10 Years, Since 2010

    Always uses percent change (no net-change toggle), styled like your Office/Tech chart.
    """

    # --- Timeframe selector ---
    tf_choice = st.radio(
        "Select Time Frame:",
        ["Last Year", "Last 5 Years", "Last 10 Years", "Since 2010"],
        index=2,  # default "Last 10 Years"
        horizontal=True,
        key="metro_pop_wide_timeframe"
    )

    # --- Load CSV (with fallback to /mnt/data) ---
    df = pd.DataFrame()
    for p in [Path(csv_path), Path("/mnt/data/Metro_Population.csv")]:
        if p.exists():
            df = pd.read_csv(p)
            source_used = str(p)
            break

    if df.empty:
        st.error("Could not find Metro_Population.csv at docs/data_build/ or /mnt/data/.")
        return

    # Normalize columns
    if "Year" not in df.columns:
        st.error("CSV must have a 'Year' column as the first column.")
        return

    # Ensure year is integer; other columns numeric
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    region_cols = [c for c in df.columns if c != "Year"]

    # Coerce populations to numeric
    for c in region_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Determine latest year present
    latest_year = int(df["Year"].max())

    # Baseline selection
    if tf_choice == "Last Year":
        baseline_year = latest_year - 1
    elif tf_choice == "Last 5 Years":
        baseline_year = latest_year - 5
    elif tf_choice == "Last 10 Years":
        baseline_year = latest_year - 10
    else:
        baseline_year = 2010

    # Ensure baseline exists; if not, pick closest available year to target
    years_available = df["Year"].dropna().astype(int).unique()
    if baseline_year not in years_available:
        # choose the YEAR in data with smallest |year - baseline_target|
        baseline_year = int(min(years_available, key=lambda y: abs(y - baseline_year)))

    # Extract baseline & latest rows
    base_row = df.loc[df["Year"] == baseline_year]
    last_row = df.loc[df["Year"] == latest_year]

    if base_row.empty or last_row.empty:
        st.warning("Baseline or latest year not found in the CSV.")
        return

    base_row = base_row.iloc[0]
    last_row = last_row.iloc[0]

    # Build tidy frame of changes across columns
    rows = []
    for region in region_cols:
        base_val = base_row[region]
        last_val = last_row[region]
        if pd.notna(base_val) and pd.notna(last_val) and base_val > 0:
            pct = (last_val - base_val) / base_val * 100.0
            rows.append((region, base_val, last_val, pct))

    if not rows:
        st.warning("No regions have valid data for both baseline and latest years.")
        return

    merged = pd.DataFrame(rows, columns=["region", "population_base", "population_last", "pct_change"])
    merged = merged.sort_values("pct_change", ascending=True)

    # Short labels
    if rename_mapping is None:
        rename_mapping = {}
    short_labels = [rename_mapping.get(r, r) for r in merged["region"].tolist()]

    # Colors: highlight SF + SJ in gold; others teal
    highlight = {"San Francisco", "San Jose"}
    colors = ["#eeaf30" if r in highlight else "#00aca2" for r in merged["region"]]

    # Optional colored labels (example: color Sonoma if present)
    colored_labels = []
    for label in short_labels:
        if "Sonoma" in label:
            colored_labels.append(f'<span style="color:#d84f19">{label}</span>')
        else:
            colored_labels.append(label)

    # Axis ticks (percent) with nice steps
    def nice_step(span, target_ticks=6):
        if span <= 0:
            return 1
        ideal = span / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for mult in (1, 2, 2.5, 5, 10):
            step = mult * power
            if step >= ideal:
                return step
        return 10 * power

    vmin, vmax = float(merged["pct_change"].min()), float(merged["pct_change"].max())
    rng = vmax - vmin if vmax > vmin else 1.0
    pad = max(0.12 * rng, 2.0)
    x_min, x_max = vmin - pad, vmax + pad
    step = nice_step(x_max - x_min, target_ticks=6)
    x_min_r = np.floor(x_min / step) * step
    x_max_r = np.ceil(x_max / step) * step
    ticks = np.arange(x_min_r, x_max_r + 0.5 * step, step)
    tick_labels = [f"{t:.0f}%" for t in ticks]

    # Title suffix
    title_suffix = f"{baseline_year} to {latest_year}"

    # Figure
    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=colored_labels,
        x=merged["pct_change"],
        orientation="h",
        marker_color=colors,
        text=[f"{v:+.1f}%" for v in merged["pct_change"]],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate=(
            "%{y}"
            "<br>Percent Change: %{x:.1f}%"
            f"<br>{baseline_year} population: "+"%{customdata[0]:,.0f}"
            f"<br>{latest_year} population: "+"%{customdata[1]:,.0f}<extra></extra>"
        ),
        customdata=list(zip(merged["population_base"], merged["population_last"]))
    ))

    # Grid lines
    for x in ticks:
        fig.add_shape(
            type="line",
            x0=x, y0=-0.5, x1=x, y1=len(merged) - 0.5,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        title=dict(
            text=(
                "Population Trends Across Major Metro Areas<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>{title_suffix}</span>"
            ),
            x=0.5, xanchor="center",
            font=dict(family="Avenir Black", size=26),
        ),
        margin=dict(l=220, r=110, t=80, b=50),
        xaxis=dict(
            title="Percent Change",
            tickmode="array",
            tickvals=ticks,
            ticktext=tick_labels,
            range=[x_min_r, x_max_r],
            tickformat=".1f",
            ticksuffix="%",
            title_font=dict(family="Avenir Medium", size=25, color="black"),
            tickfont=dict(family="Avenir", size=18, color="black"),
        ),
        yaxis=dict(
            tickfont=dict(family="Avenir Black", size=18, color="black")
        ),
        showlegend=False,
        height=700,
    )
    fig.update_traces(textposition="outside", cliponaxis=False)

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "metro_populations",
                    "scale": 10          # higher scale = higher DPI
                }
            }
    )
    
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>U.S. Census Bureau (Population and Housing Unit Estimates).<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # Summary table + download
    st.subheader("Summary")
    out = merged.copy()
    out.rename(columns={
        "region": "Region",
        "population_base": f"{baseline_year} Population",
        "population_last": f"{latest_year} Population",
        "pct_change": "Percent Change"
    }, inplace=True)
    out["Percent Change"] = out["Percent Change"].map(lambda v: f"{v:+.1f}%")
    # color negative red / positive green
    def color_percent(val):
        return 'color: red' if isinstance(val, str) and '-' in val else 'color: green'
    st.dataframe(out.style.map(color_percent, subset=["Percent Change"]),
                 use_container_width=True, hide_index=True)

    st.download_button(
        "Download Data (CSV)",
        data=out.to_csv(index=False).encode("utf-8"),
        file_name=f"metro_population_change_{baseline_year}_to_{latest_year}.csv",
        mime="text/csv"
    )

def show_median_1br_rent_change_chart(
    csv_path: str = "docs/data_build/1br_Rents_Bay_Area.csv",
    title: str = "Percent Change in Median 1-Bedroom Rents",
):
    """
    Dashboard Section: Housing
    Dashboard Subtab: Rent Trends

    Renders a vertical bar chart of percent change in median 1-BR rents by region.
    - Timeframes: Last Year, Since COVID-19
    - X-axis: regions (sorted high → low)
    - Y-axis: percent change
    - Colors: California=#203864, others=#00aca2
    """

    tf_choice = st.radio(
        "Select Time Frame:",
        ["Last Year", "Since COVID-19"],
        index=0,
        horizontal=True,
        key="rent_change_tf"
    )

    want_cols = {
        "region": "Region",
        "lastyear": "Last Year",
        "postcovid": "Post-Covid",
    }

    # ---- Load CSV ----
    df = pd.DataFrame()
    source_used = None
    for p in [Path(csv_path), Path("/mnt/data/Median1BR_Rent_Change.csv")]:
        if p.exists():
            try:
                df = pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")
            except Exception:
                df = pd.read_csv(p, encoding="utf-8-sig")
            source_used = str(p)
            break

    if df.empty:
        st.error("Could not find the rent change CSV at docs/data_build/ or /mnt/data/.")
        return

    # ---- Normalize headers (lowercase, remove non-alphanumerics) ----
    def norm(s: str) -> str:
        s = str(s)
        s = s.replace("\u00A0", " ")            # NBSP → space
        s = s.lower()
        s = re.sub(r"[^a-z0-9]", "", s)         # keep only a–z, 0–9
        return s

    norm_map = {col: norm(col) for col in df.columns}
    df.columns = [norm_map[c] for c in df.columns]

    # Required normalized headers
    needed = {"region", "lastyear", "postcovid"}
    if not needed.issubset(set(df.columns)):
        st.error("CSV must include 'Region', 'Last Year', and 'Post-Covid' columns.")
        st.write("Detected columns (after normalization):", list(df.columns))
        return

    # Clean region strings and values
    df["region"] = df["region"].astype(str).str.replace("\u00A0", " ").str.strip()
    df["lastyear"] = pd.to_numeric(df["lastyear"], errors="coerce")
    df["postcovid"] = pd.to_numeric(df["postcovid"], errors="coerce")

    # Choose series based on toggle
    series_col = "lastyear" if tf_choice == "Last Year" else "postcovid"

    plot_df = df.loc[:, ["region", series_col]].dropna().copy()
    plot_df["pct"] = plot_df[series_col] * 100.0
    if plot_df.empty:
        st.warning("No valid rows to plot for the selected timeframe.")
        return

    # Sort: highest first (leftmost)
    plot_df = plot_df.sort_values("pct", ascending=False).reset_index(drop=True)

    # Colors: California = #203864, others = #00aca2
    bar_colors = ["#203864" if r == "California" else "#00aca2" for r in plot_df["region"]]

    # ---- Axis ticks (percent) with nice step & padding ----
    def nice_step(span, target_ticks=6):
        if span <= 0:
            return 1
        ideal = span / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for mult in (1, 2, 2.5, 5, 10):
            step = mult * power
            if step >= ideal:
                return step
        return 10 * power

    vmin, vmax = float(plot_df["pct"].min()), float(plot_df["pct"].max())
    rng = vmax - vmin if vmax > vmin else 1.0
    pad = max(0.12 * rng, 2.0)  # percentage points
    y_min, y_max = vmin - pad, vmax + pad
    step = nice_step(y_max - y_min, target_ticks=6)
    y_min_r = np.floor(y_min / step) * step
    y_max_r = np.ceil(y_max / step) * step
    yticks = np.arange(y_min_r, y_max_r + 0.5 * step, step)
    ytick_labels = [f"{t:.0f}%" for t in yticks]

    subtitle = tf_choice

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=plot_df["region"],
        y=plot_df["pct"],
        marker_color=bar_colors,
        text=[f"{v:+.1f}%" for v in plot_df["pct"]],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate="%{x}<br>Percent Change: %{y:.1f}%<extra></extra>",
    ))

    for y in yticks:
        fig.add_shape(
            type="line",
            x0=-0.5, y0=y, x1=len(plot_df["region"]) - 0.5, y1=y,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        title=dict(
            text=(
                f"{title}<br>"
            ),
            x=0.5, xanchor="center",
            font=dict(family="Avenir Black", size=26),
        ),
        margin=dict(l=60, r=40, t=80, b=120),
        xaxis=dict(
            tickfont=dict(family="Avenir Medium", size=20, color="black"),
            tickangle=-30,
        ),
        yaxis=dict(
            title="Percent Change",
            tickmode="array",
            tickvals=yticks,
            ticktext=ytick_labels,
            range=[y_min_r, y_max_r],
            ticksuffix="%",
            title_font=dict(family="Avenir Medium", size=22, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor="lightgray",
        ),
        showlegend=False,
        height=600,
    )
    fig.update_traces(cliponaxis=False)

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "median_rents",
                    "scale": 10
                }
            }
    )
    
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Apartment List.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    <br>
    """, unsafe_allow_html=True)

    out = plot_df[["region", "pct"]].copy()
    out.rename(columns={"region": "Region", "pct": f"Percent Change ({subtitle})"}, inplace=True)
    out[f"Percent Change ({subtitle})"] = out[f"Percent Change ({subtitle})"].map(lambda v: f"{v:+.1f}%")
    st.download_button(
        "Download Data (CSV)",
        data=out.to_csv(index=False).encode("utf-8"),
        file_name=f"median_1br_rent_change_{subtitle.replace(' ', '_').lower()}.csv",
        mime="text/csv"
    )

def show_avg_housing_permits_chart(
    csv_path: str = "docs/data_build/Housing_Permits.csv",
    title: str = "Average Housing Permits by County",
):
    tf_choice = st.radio(
        "Select Time Frame:",
        ["2018 to 2024", "2023 to 2024"],
        index=0,
        horizontal=True,
        key="permits_tf"
    )

    col_map = {
        "2018 to 2024": "2018-2024",
        "2023 to 2024": "2023-2024",
    }
    value_col = col_map[tf_choice]

    # --- Load CSV ---
    df = pd.DataFrame()
    source_used = None
    for p in [Path(csv_path), Path("/mnt/data/Housing_Permits.csv")]:
        if p.exists():
            try:
                df = pd.read_csv(p, sep=None, engine="python", encoding="utf-8-sig")
            except Exception:
                df = pd.read_csv(p, encoding="utf-8-sig")
            source_used = str(p)
            break

    if df.empty:
        st.error("Could not find the housing permits CSV at docs/data_build/ or /mnt/data/.")
        return

    # --- Normalize / validate columns ---
    df.columns = [str(c).strip() for c in df.columns]
    if "County" not in df.columns or value_col not in df.columns:
        st.error(f"CSV must include 'County' and '{value_col}' columns.")
        st.write("Detected columns:", list(df.columns))
        return

    df["County"] = df["County"].astype(str).str.replace("\u00A0", " ").str.strip()
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")

    plot_df = df[["County", value_col]].dropna().copy()
    plot_df.rename(columns={value_col: "permits_per_100k"}, inplace=True)

    if plot_df.empty:
        st.warning("No valid rows to plot for the selected timeframe.")
        return

    # Sort: highest first (leftmost)
    plot_df = plot_df.sort_values("permits_per_100k", ascending=False).reset_index(drop=True)

    # Colors: all bars teal #00aca2
    bar_colors = ["#00aca2"] * len(plot_df)

    # --- Axis ticks ---
    def nice_step(span, target_ticks=6):
        if span <= 0:
            return 1
        ideal = span / max(1, target_ticks)
        power = 10 ** np.floor(np.log10(ideal))
        for mult in (1, 2, 2.5, 5, 10):
            step = mult * power
            if step >= ideal:
                return step
        return 10 * power

    vmin, vmax = float(plot_df["permits_per_100k"].min()), float(plot_df["permits_per_100k"].max())
    rng = vmax - vmin if vmax > vmin else 1.0
    pad = max(0.12 * rng, 5.0)
    y_min, y_max = max(0.0, vmin - pad), vmax + pad  
    step = nice_step(y_max - y_min, target_ticks=6)
    y_min_r = np.floor(y_min / step) * step
    y_max_r = np.ceil(y_max / step) * step
    yticks = np.arange(y_min_r, y_max_r + 0.5 * step, step)
    # one decimal if values are < 1000, otherwise 0 decimals
    if y_max_r < 1000:
        ytick_labels = [f"{t:.1f}" for t in yticks]
        text_fmt = lambda v: f"{v:,.1f}"
    else:
        ytick_labels = [f"{t:,.0f}" for t in yticks]
        text_fmt = lambda v: f"{v:,.0f}"

    subtitle = tf_choice

    # --- Figure ---
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=plot_df["County"],
        y=plot_df["permits_per_100k"],
        marker_color=bar_colors,
        text=[text_fmt(v) for v in plot_df["permits_per_100k"]],
        textfont=dict(size=16, family="Avenir Light", color="black"),
        textposition="outside",
        hovertemplate="%{x}<br>Permits per 100,000: %{y:.1f}<extra></extra>",
    ))

    # Horizontal dashed grid lines
    for y in yticks:
        fig.add_shape(
            type="line",
            x0=-0.5, y0=y, x1=len(plot_df["County"]) - 0.5, y1=y,
            line=dict(color="lightgray", width=1, dash="dash"),
            layer="below"
        )

    fig.update_layout(
        title=dict(
            text=(
                f"{title}<br>"
                f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>{subtitle}</span>"
            ),
            x=0.5, xanchor="center",
            font=dict(family="Avenir Black", size=26),
        ),
        margin=dict(l=60, r=40, t=80, b=120),
        xaxis=dict(
            tickfont=dict(family="Avenir Medium", size=20, color="black"),
            tickangle=-30,
        ),
        yaxis=dict(
            title="Permits per 100,000 Residents",
            tickmode="array",
            tickvals=yticks,
            ticktext=ytick_labels,
            range=[y_min_r, y_max_r],
            title_font=dict(family="Avenir Medium", size=20, color="black"),
            tickfont=dict(family="Avenir", size=16, color="black"),
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor="lightgray",
        ),
        showlegend=False,
        height=600,
    )
    fig.update_traces(cliponaxis=False)

    st.plotly_chart(
            fig, 
            use_container_width=True,
            config={
                "toImageButtonOptions": {
                    "format": "svg",
                    "filename": "housing_permits",
                    "scale": 10          # higher scale = higher DPI
                }
            }
    )
    
    st.markdown("""
    <div style='font-size: 12px; color: #666; font-family: "Avenir", sans-serif;'>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>U.S. Census Building Permit Survey, U.S. Census Population Estimates Program.<br>
    <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
    </div>
    <br>
    """, unsafe_allow_html=True)

    out = plot_df.rename(columns={"permits_per_100k": f"Permits per 100k ({subtitle})"})
    st.download_button(
        "Download Data (CSV)",
        data=out.to_csv(index=False).encode("utf-8"),
        file_name=f"avg_housing_permits_per_100k_{subtitle.replace(' ', '_').lower()}.csv",
        mime="text/csv"
    )




# --- MAIN DASHBOARD SETUP WITH FUNCTIONS CALLED ---
# This can be used as a guide to navigate the different
# sections and subtabs of the dashboard, allowing you to
# see what functions correspond to which visualizations.

if section == "Employment":

    df_unemp = load_prebuilt_or_fetch(
        "unemployment_ca",
        lambda: process_unemployment_data(fetch_unemployment_data())
    )

    # Employment data for states, Bay Area, and the United States
    df_states = load_prebuilt_or_fetch(
        "states_payroll",
        lambda: fetch_states_job_data(list(series_mapping.get("states", {}).values()))
    )
    
    df_rest_ca = load_prebuilt_or_fetch("rest_ca_payroll", fetch_rest_of_ca_payroll_data)
    df_bay = load_prebuilt_or_fetch("bay_area_payroll", fetch_bay_area_payroll_data)
    df_us = load_prebuilt_or_fetch("us_payroll", fetch_us_payroll_data)
    df_sonoma = load_prebuilt_or_fetch("sonoma_payroll", fetch_sonoma_payroll_data)
    df_napa = load_prebuilt_or_fetch("napa_payroll", fetch_napa_payroll_data)
    df_ca = load_prebuilt_or_fetch("california_payroll", fetch_california_payroll_data)

    if emp_subtab == "Job Recovery":
        show_job_recovery_overall(df_rest_ca, df_bay, df_us, df_sonoma, df_napa)
        show_job_recovery_by_state(state_code_map, fetch_states_job_data)

        # # --- Sonoma County Outlook ---
        # show_job_recovery_overall_v2(df_ca=df_ca, df_bay=df_bay, df_us=df_us, df_sonoma=df_sonoma)

    elif emp_subtab == "Monthly Change":
        
        region_choice = st.selectbox(
            "Select Region:",
            options=[
                "Bay Area (9-county)",
                "United States",
                "North Bay",
                "East Bay",
                "San Francisco-Peninsula",
                "South Bay" #,
                # "Sonoma County"
            ]
        )

        if region_choice == "Bay Area (9-county)":
            show_bay_area_monthly_job_change(df_bay)
        else:
            series_id_or_list = regions[region_choice]
            if isinstance(series_id_or_list, list):
                # Multiple series ("North Bay" includes 4 regions)
                dfs = []
                for sid in series_id_or_list:
                    df_r = fetch_and_process_job_data(sid, region_choice)
                    if df_r is not None:
                        dfs.append(df_r[["date", "monthly_change"]])

                if dfs:
                    # Merge and sum job changes on 'date'
                    df_merged = dfs[0].copy()
                    for other_df in dfs[1:]:
                        df_merged = df_merged.merge(other_df, on="date", suffixes=("", "_tmp"))
                        df_merged["monthly_change"] += df_merged["monthly_change_tmp"]
                        df_merged.drop(columns=["monthly_change_tmp"], inplace=True)

                    # Add label and color
                    df_merged["label"] = df_merged["monthly_change"].apply(
                        lambda x: f"{int(x/1000)}K" if abs(x) >= 1000 else f"{int(x)}"
                    )
                    df_merged["color"] = df_merged["monthly_change"].apply(lambda x: "#00aca2" if x >= 0 else "#e63946")

                    show_monthly_job_change_chart(df_merged, region_choice)
                    create_job_change_summary_table(df_merged)
                else:
                    st.warning(f"No data available for {region_choice}.")
            else:
                # Single region (e.g., "East Bay", "South Bay", "SF-Peninsula")
                df = fetch_and_process_job_data(series_id_or_list, region_choice)
                if df is not None:
                    show_monthly_job_change_chart(df, region_choice)
                    create_job_change_summary_table(df)

    elif emp_subtab == "Jobs by Industry":
        show_combined_industry_job_recovery_chart(series_mapping_v2, us_series_mapping, BLS_API_KEY)

        # # --- Sonoma County ---
        # show_sonoma_combined_industry_job_recovery_chart(sonoma_mapping, us_series_mapping, BLS_API_KEY)
    elif emp_subtab == "Office Jobs":
        show_office_tech_recovery_chart(office_metros_mapping, BLS_API_KEY)
    elif emp_subtab == "Employed Residents":
        if df_unemp is not None:
            show_employment_comparison_chart(df_unemp)
        else:
            st.warning("Employment dataset is unavailable.")

    elif emp_subtab == "Unemployment Rate":
        if df_unemp is not None:
            show_unemployment_rate_chart(df_unemp)
        else:
            st.warning("Unemployment dataset is unavailable right now.")
    elif emp_subtab == "Job to Worker Ratio":
        show_jobs_ratio_chart()

elif section == "Population":
    if pop_subtab == "Counties":
        show_population_trend_chart()
    elif pop_subtab == "Metro Areas":
        show_metro_population_change_chart()


elif section == "Housing":
    if housing_subtab == "Rent Trends":
        show_median_1br_rent_change_chart()
    elif housing_subtab == "Housing Permits":
        show_avg_housing_permits_chart()


# elif section == "Investment":
#     st.header("Investment")
#     st.write("Placeholder: investment graphs, charts, and tables.")

# elif section == "Transit":
#     st.header("Transit")
#     st.write("Placeholder: transit graphs, charts, and tables.")


st.markdown("---")
st.caption("© Bay Area Council Economic Institute")
