import streamlit as st
import pandas as pd
import requests
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()

# BLS_API_KEY = os.getenv("BLS_API_KEY")
BLS_API_KEY= "15060bc07890456a95aa5d0076966247"

# Mapping of U.S. states to BLS nonfarm payroll series IDs (seasonally adjusted)
state_code_map = {
    "Alabama": "SMS01000000000000001",
    "Alaska": "SMS02000000000000001",
    "Arizona": "SMS04000000000000001",
    "Arkansas": "SMS05000000000000001",
    "California": "SMS06000000000000001",
    "Colorado": "SMS08000000000000001",
    "Connecticut": "SMS09000000000000001",
    "Delaware": "SMS10000000000000001",
    "District of Columbia": "SMS11000000000000001",
    "Florida": "SMS12000000000000001",
    "Georgia": "SMS13000000000000001",
    "Hawaii": "SMS15000000000000001",
    "Idaho": "SMS16000000000000001",
    "Illinois": "SMS17000000000000001",
    "Indiana": "SMS18000000000000001",
    "Iowa": "SMS19000000000000001",
    "Kansas": "SMS20000000000000001",
    "Kentucky": "SMS21000000000000001",
    "Louisiana": "SMS22000000000000001",
    "Maine": "SMS23000000000000001",
    "Maryland": "SMS24000000000000001",
    "Massachusetts": "SMS25000000000000001",
    "Michigan": "SMS26000000000000001",
    "Minnesota": "SMS27000000000000001",
    "Mississippi": "SMS28000000000000001",
    "Missouri": "SMS29000000000000001",
    "Montana": "SMS30000000000000001",
    "Nebraska": "SMS31000000000000001",
    "Nevada": "SMS32000000000000001",
    "New Hampshire": "SMS33000000000000001",
    "New Jersey": "SMS34000000000000001",
    "New Mexico": "SMS35000000000000001",
    "New York": "SMS36000000000000001",
    "North Carolina": "SMS37000000000000001",
    "North Dakota": "SMS38000000000000001",
    "Ohio": "SMS39000000000000001",
    "Oklahoma": "SMS40000000000000001",
    "Oregon": "SMS41000000000000001",
    "Pennsylvania": "SMS42000000000000001",
    "Rhode Island": "SMS44000000000000001",
    "South Carolina": "SMS45000000000000001",
    "South Dakota": "SMS46000000000000001",
    "Tennessee": "SMS47000000000000001",
    "Texas": "SMS48000000000000001",
    "Utah": "SMS49000000000000001",
    "Vermont": "SMS50000000000000001",
    "Virginia": "SMS51000000000000001",
    "Washington": "SMS53000000000000001",
    "West Virginia": "SMS54000000000000001",
    "Wisconsin": "SMS55000000000000001",
    "Wyoming": "SMS56000000000000001"
    # "Puerto Rico": "SMS72000000000000001",
    # "Virign Islands": "SMS78000000000000001"
}

bay_area_counties = [
    "Alameda County", "Contra Costa County", "Marin County",
    "Napa County", "San Francisco County", "San Mateo County",
    "Santa Clara County", "Solano County", "Sonoma County"
]

# Mapping for jobs by industry and by region
series_mapping = {
    'SMU06360842000000001': ('Oakland-Fremont-Berkeley, CA', 'Construction'),
    'SMU06418842000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Construction'),
    'SMU06419402000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Construction'),
    'SMU06420342000000001': ('San Rafael, CA', 'Construction'),
    'SMU06422202000000001': ('Santa Rosa-Petaluma, CA', 'Construction'),
    'SMU06467002000000001': ('Vallejo, CA', 'Construction'),
    'SMU06349003000000001': ('Napa, CA', 'Manufacturing'),
    'SMU06360843000000001': ('Oakland-Fremont-Berkeley, CA', 'Manufacturing'),
    'SMU06418843000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Manufacturing'),
    'SMU06419403000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Manufacturing'),
    'SMU06420343000000001': ('San Rafael, CA', 'Manufacturing'),
    'SMU06422203000000001': ('Santa Rosa-Petaluma, CA', 'Manufacturing'),
    'SMU06467003000000001': ('Vallejo, CA', 'Manufacturing'),
    # 'SMU06349004100000001': ('Napa, CA', 'Wholesale Trade'),
    # 'SMU06360844100000001': ('Oakland-Fremont-Berkeley, CA', 'Wholesale Trade'),
    # 'SMU06418844100000001': ('San Francisco-San Mateo-Redwood City, CA', 'Wholesale Trade'),
    # 'SMU06419404100000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Wholesale Trade'),
    # 'SMU06420344100000001': ('San Rafael, CA', 'Wholesale Trade'),
    # 'SMU06422204100000001': ('Santa Rosa-Petaluma, CA', 'Wholesale Trade'),
    # 'SMU06467004100000001': ('Vallejo, CA', 'Wholesale Trade'),
    'SMU06349004200000001': ('Napa, CA', 'Retail Trade'),
    'SMU06360844200000001': ('Oakland-Fremont-Berkeley, CA', 'Retail Trade'),
    'SMU06418844200000001': ('San Francisco-San Mateo-Redwood City, CA', 'Retail Trade'),
    'SMU06419404200000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Retail Trade'),
    'SMU06420344200000001': ('San Rafael, CA', 'Retail Trade'),
    'SMU06422204200000001': ('Santa Rosa-Petaluma, CA', 'Retail Trade'),
    'SMU06467004200000001': ('Vallejo, CA', 'Retail Trade'),
    # 'SMU06360844340008901': ('Oakland-Fremont-Berkeley, CA', 'Transportation and Warehousing'),
    # 'SMU06418844340008901': ('San Francisco-San Mateo-Redwood City, CA', 'Transportation and Warehousing'),
    # 'SMU06419404340008901': ('San Jose-Sunnyvale-Santa Clara, CA', 'Transportation and Warehousing'),
    'SMU06349005000000001': ('Napa, CA', 'Information'),
    'SMU06360845000000001': ('Oakland-Fremont-Berkeley, CA', 'Information'),
    'SMU06418845000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Information'),
    'SMU06419405000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Information'),
    'SMU06420345000000001': ('San Rafael, CA', 'Information'),
    'SMU06422205000000001': ('Santa Rosa-Petaluma, CA', 'Information'),
    'SMU06467005000000001': ('Vallejo, CA', 'Information'),
    # 'SMU06360845552000001': ('Oakland-Fremont-Berkeley, CA', 'Finance and Insurance'),
    # 'SMU06418845552000001': ('San Francisco-San Mateo-Redwood City, CA', 'Finance and Insurance'),
    # 'SMU06419405552000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Finance and Insurance'),
    # 'SMU06422205552000001': ('Santa Rosa-Petaluma, CA', 'Finance and Insurance'),
    # 'SMU06467005552000001': ('Vallejo, CA', 'Finance and Insurance'),
    # 'SMU06360845553000001': ('Oakland-Fremont-Berkeley, CA', 'Real Estate and Rental and Leasing'),
    # 'SMU06418845553000001': ('San Francisco-San Mateo-Redwood City, CA', 'Real Estate and Rental and Leasing'),
    # 'SMU06419405553000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Real Estate and Rental and Leasing'),
    'SMU06349006000000001': ('Napa, CA', 'Professional and Business Services'),
    'SMU06360846000000001': ('Oakland-Fremont-Berkeley, CA', 'Professional and Business Services'),
    'SMU06418846000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Professional and Business Services'),
    'SMU06419406000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Professional and Business Services'),
    'SMU06420346000000001': ('San Rafael, CA', 'Professional and Business Services'),
    'SMU06422206000000001': ('Santa Rosa-Petaluma, CA', 'Professional and Business Services'),
    'SMU06467006000000001': ('Vallejo, CA', 'Professional and Business Services'),
    # 'SMU06360846054000001': ('Oakland-Fremont-Berkeley, CA', 'Professional, Scientific, and Technical Services'),
    # 'SMU06418846054000001': ('San Francisco-San Mateo-Redwood City, CA', 'Professional, Scientific, and Technical Services'),
    # 'SMU06419406054000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Professional, Scientific, and Technical Services'),
    # 'SMU06422206054000001': ('Santa Rosa-Petaluma, CA', 'Professional, Scientific, and Technical Services'),
    # 'SMU06360846055000001': ('Oakland-Fremont-Berkeley, CA', 'Management of Companies and Enterprises'),
    # 'SMU06418846055000001': ('San Francisco-San Mateo-Redwood City, CA', 'Management of Companies and Enterprises'),
    # 'SMU06419406055000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Management of Companies and Enterprises'),
    # 'SMU06422206055000001': ('Santa Rosa-Petaluma, CA', 'Management of Companies and Enterprises'),
    # 'SMU06349006056000001': ('Napa, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06360846056000001': ('Oakland-Fremont-Berkeley, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06418846056000001': ('San Francisco-San Mateo-Redwood City, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06419406056000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06422206056000001': ('Santa Rosa-Petaluma, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06467006056000001': ('Vallejo, CA', 'Administrative and Support and Waste Management and Remediation Services'),
    # 'SMU06360846561000001': ('Oakland-Fremont-Berkeley, CA', 'Private Educational Services'),
    # 'SMU06418846561000001': ('San Francisco-San Mateo-Redwood City, CA', 'Private Educational Services'),
    # 'SMU06419406561000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Private Educational Services'),
    # 'SMU06349006562000001': ('Napa, CA', 'Health Care and Social Assistance'),
    # 'SMU06360846562000001': ('Oakland-Fremont-Berkeley, CA', 'Health Care and Social Assistance'),
    # 'SMU06418846562000001': ('San Francisco-San Mateo-Redwood City, CA', 'Health Care and Social Assistance'),
    # 'SMU06419406562000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Health Care and Social Assistance'),
    # 'SMU06422206562000001': ('Santa Rosa-Petaluma, CA', 'Health Care and Social Assistance'),
    # 'SMU06467006562000001': ('Vallejo, CA', 'Health Care and Social Assistance'),
    # 'SMU06360847071000001': ('Oakland-Fremont-Berkeley, CA', 'Arts, Entertainment, and Recreation'),
    # 'SMU06418847071000001': ('San Francisco-San Mateo-Redwood City, CA', 'Arts, Entertainment, and Recreation'),
    # 'SMU06349007072000001': ('Napa, CA', 'Accommodation and Food Services'),
    # 'SMU06360847072000001': ('Oakland-Fremont-Berkeley, CA', 'Accommodation and Food Services'),
    # 'SMU06418847072000001': ('San Francisco-San Mateo-Redwood City, CA', 'Accommodation and Food Services'),
    # 'SMU06419407072000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Accommodation and Food Services'),
    # 'SMU06422207072000001': ('Santa Rosa-Petaluma, CA', 'Accommodation and Food Services'),
    # 'SMU06467007072000001': ('Vallejo, CA', 'Accommodation and Food Services'),
    'SMU06349009000000001': ('Napa, CA', 'Government'),
    'SMU06360849000000001': ('Oakland-Fremont-Berkeley, CA', 'Government'),
    'SMU06418849000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Government'),
    'SMU06419409000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Government'),
    'SMU06420349000000001': ('San Rafael, CA', 'Government'),
    'SMU06422209000000001': ('Santa Rosa-Petaluma, CA', 'Government'),
    'SMU06467009000000001': ('Vallejo, CA', 'Government'),
    'SMU06349007000000001': ('Napa, CA', 'Leisure and Hospitality'),
    'SMU06360847000000001': ('Oakland-Fremont-Berkeley, CA', 'Leisure and Hospitality'),
    'SMU06418847000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Leisure and Hospitality'),
    'SMU06419407000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Leisure and Hospitality'),
    'SMU06420347000000001': ('San Rafael, CA', 'Leisure and Hospitality'),
    'SMU06422207000000001': ('Santa Rosa-Petaluma, CA', 'Leisure and Hospitality'),
    'SMU06467007000000001': ('Vallejo, CA', 'Leisure and Hospitality'),
    'SMU06349005500000001': ('Napa, CA', 'Financial Activities'),
    'SMU06360845500000001': ('Oakland-Fremont-Berkeley, CA', 'Financial Activities'),
    'SMU06418845500000001': ('San Francisco-San Mateo-Redwood City, CA', 'Financial Activities'),
    'SMU06419405500000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Financial Activities'),
    'SMU06420345500000001': ('San Rafael, CA', 'Financial Activities'),
    'SMU06422205500000001': ('Santa Rosa-Petaluma, CA', 'Financial Activities'),
    'SMU06467005500000001': ('Vallejo, CA', 'Financial Activities'),
    'SMU06349006500000001': ('Napa, CA', 'Education and Health Services'),
    'SMU06360846500000001': ('Oakland-Fremont-Berkeley, CA', 'Education and Health Services'),
    'SMU06418846500000001': ('San Francisco-San Mateo-Redwood City, CA', 'Education and Health Services'),
    'SMU06419406500000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Education and Health Services'),
    'SMU06420346500000001': ('San Rafael, CA', 'Education and Health Services'),
    'SMU06422206500000001': ('Santa Rosa-Petaluma, CA', 'Education and Health Services'),
    'SMU06467006500000001': ('Vallejo, CA', 'Education and Health Services'),
    'SMU06349004000000001': ('Napa, CA', 'Trade, Transportation, and Utilities'),
    'SMU06360844000000001': ('Oakland-Fremont-Berkeley, CA', 'Trade, Transportation, and Utilities'),
    'SMU06418844000000001': ('San Francisco-San Mateo-Redwood City, CA', 'Trade, Transportation, and Utilities'),
    'SMU06419404000000001': ('San Jose-Sunnyvale-Santa Clara, CA', 'Trade, Transportation, and Utilities'),
    'SMU06420344000000001': ('San Rafael, CA', 'Trade, Transportation, and Utilities'),
    'SMU06422204000000001': ('Santa Rosa-Petaluma, CA', 'Trade, Transportation, and Utilities'),
    'SMU06467004000000001': ('Vallejo, CA', 'Trade, Transportation, and Utilities')
}


# --- Title ----
st.set_page_config(page_title="Bay Area Dashboard", layout="wide")
st.title("Bay Area Economic Dashboard")

# --- BACEI Logo ---
st.sidebar.image("BACEI Logo.png", use_container_width=True)

# --- Sidebar dropdown ---
section = st.sidebar.selectbox(
    "Select Indicator:",
    ["Employment", "Population", "Housing", "Investment", "Transit"]
)

# --- Sidebar Subtabs ---
subtab = None
if section == "Employment":
    subtab = st.sidebar.radio(
        "Employment Views:",
        ["Employment", "Unemployment", "Regional Job Recovery", "Monthly Job Change", "Industry"],
        key="employment_subtab"
    )

# --- Main Content ---
if section == "Employment":

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
    def fetch_us_payroll_data():
        """
        Fetches national-level seasonally adjusted nonfarm payroll employment data for the U.S.
        Computes percent change in employment relative to February 2020.
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
        Fetches monthly employment data from BLS API for a list of U.S. state series IDs,
        and calculates percent change from February 2020 for each state.
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


    # --- Visualization ---


    def show_unemployment_rate_chart(df):
        st.subheader("Unemployment Rate Trend")

        counties = sorted(df["County"].unique().tolist())

        select_all = st.checkbox("Select all Bay Area Counties", value=True, key="select_all_checkbox")

        # Dropdown to select counties
        if select_all:
            selected_counties = counties
        else:
            selected_counties = st.multiselect(
                "Select counties to display:",
                options = counties,
                default = []
            )

        # User personalizes which counties to view
        if not selected_counties:
            st.info("Please select at least one county.")
            return

        filtered_df = df[df["County"].isin(selected_counties)]
        fig = px.line(
            filtered_df,
            x = "date",
            y = "UnemploymentRate",
            color = "County",
            title = "Unemployment Rate Over Time"
        )

        quarterly_ticks = filtered_df["date"][filtered_df["date"].dt.month.isin([1, 4, 7, 10])].dt.strftime("%Y-%m-01").unique().tolist()

        fig.update_layout(
            hovermode="x unified",
            xaxis=dict(
                title="Date",
                tickvals=quarterly_ticks,
                tickformat="%b\n%Y",
                dtick="M1",
                tickangle=0,
                title_font=dict(size=18),
                tickfont=dict(size=10)
            ),
            yaxis=dict(
                title="Unemployment Rate (%)",
                title_font=dict(size=18),
                tickfont=dict(size=12)
            ),
            title_font=dict(size=20)
        )

        for trace in fig.data:
            trace.hovertemplate = f"{trace.name}: " + "%{y:.1f}%<extra></extra>"

        st.plotly_chart(fig, use_container_width=True)

    def show_employment_comparison_chart(df):
        """
        Creates a bar chart comparing employment levels between February 2020 
        and the latest available month for each Bay Area county.
        
        Args:
            df (pd.DataFrame): Processed employment data with columns 
                            ['County', 'Employment', 'date', etc.]
        """
        latest_date = df["date"].max()
        st.subheader(f"Recovery from February 2020 to {latest_date.strftime('%B %Y')}")   

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
        
        # Add February 2020 bars
        fig.add_trace(go.Bar(
            name='February 2020',
            x=comparison_df['County'],
            y=comparison_df['Feb 2020'],
            marker_color='#00aca2',
            text=comparison_df['Feb 2020'],
            texttemplate='%{text:,.0f}',
            textposition='outside'
        ))
        
        # Add latest month bars
        fig.add_trace(go.Bar(
            name=f'{comparison_df["Latest Date"].iloc[0].strftime("%b %Y")}',
            x=comparison_df['County'],
            y=comparison_df['Latest'],
            marker_color='#203864',
            text=comparison_df['Latest'],
            texttemplate='%{text:,.0f}',
            textposition='outside'
        ))
        
        # Update layout
        fig.update_layout(
            title=f"February 2020 vs {df['date'].max().strftime('%B %Y')}",
            xaxis_title='County',
            yaxis_title='Number of Employed Persons',
            barmode='group',
            height=600,
            showlegend=True,
            xaxis_tickangle=0
        )
        
        # Format y-axis to show numbers in thousands/millions
        fig.update_yaxes(tickformat='.0s')
        
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666;'>
        <strong>Source: </strong>Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute
        </div>
        """, unsafe_allow_html=True)
        
        # Add summary statistics
        st.subheader("Recovery Summary")
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
        
        # Show detailed table
        st.subheader("Detailed Comparison")
        display_df = comparison_df[['County', 'Feb 2020', 'Latest', 'Change', 'Pct Change']].copy()
        display_df['Feb 2020'] = display_df['Feb 2020'].apply(lambda x: f"{x:,.0f}")
        display_df['Latest'] = display_df['Latest'].apply(lambda x: f"{x:,.0f}")
        display_df['Change'] = display_df['Change'].apply(lambda x: f"{x:+,.0f}")
        display_df['Pct Change'] = display_df['Pct Change'].apply(lambda x: f"{x:+.1f}%")
        
        # Color code the percentage change
        def color_pct_change(val):
            if '+' in val:
                return 'color: green'
            else:
                return 'color: red'
        
        styled_df = display_df.style.map(color_pct_change, subset=['Pct Change'])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)


    def show_job_recovery_overall(df_state, df_bay, df_us):
        st.subheader("Job Recovery Since February 2020")

        if df_state is not None and df_bay is not None and df_us is not None:
            # Find latest common month of data available for aesthetics
            latest_common_date = min(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max())
            df_state = df_state[df_state["date"] <= latest_common_date]
            df_bay = df_bay[df_bay["date"] <= latest_common_date]
            df_us = df_us[df_us["date"] <= latest_common_date]

            fig = go.Figure()

            # U.S. (gray)
            fig.add_trace(
                go.Scatter(
                    x=df_us["date"],
                    y=df_us["pct_change"],
                    mode="lines",
                    name="United States",
                    line=dict(color="#888888"),
                    hovertemplate="United States: %{y:.2f}%<extra></extra>"
                )
            )

            latest_us = df_us.iloc[-1]
            fig.add_trace(
                go.Scatter(
                    x=[latest_us["date"]],
                    y=[latest_us["pct_change"]],
                    mode="markers+text",
                    marker=dict(color="#888888", size=10),
                    text=[f"{latest_us['pct_change']:.2f}%"],
                    textposition="top center",
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
                    textposition="top center",
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
                    textposition="top center",
                    name="Bay Area",
                    hoverinfo="skip",
                    showlegend=False
                )
            )

            latest_date = max(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max())
            buffered_latest = latest_date + timedelta(days=30)

            # Generate quarterly ticks (Jan, Apr, Jul, Oct) across all dates
            all_dates = pd.concat([df_state["date"], df_bay["date"], df_us["date"]])
            quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())

            fig.update_layout(
                title="Percent Change in Nonfarm Payroll Jobs Since Feb 2020",
                xaxis_title="Date",
                yaxis_title="% Change Since Feb 2020",
                xaxis=dict(
                    tickvals=quarterly_ticks,
                    tickformat="%b\n%Y",
                    dtick="M1",
                    tickangle=0,
                    title_font=dict(size=20),
                    tickfont=dict(size=10),
                    range=["2020-02-01", buffered_latest.strftime("%Y-%m-%d")]
                ),
                yaxis=dict(
                    title_font=dict(size=20),
                    tickfont=dict(size=12)
                ),
                hovermode="x unified",
                legend=dict(
                    font=dict(size=20),
                    title=None,
                    orientation="v",
                    yanchor="top",
                    y=1,
                    xanchor="left",
                    x=1
                )
            )

            st.plotly_chart(fig, use_container_width=True)
            st.markdown("""
            <div style='font-size: 12px; color: #666;'>
            <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
            <strong>Analysis:</strong> Bay Area Council Economic Institute
            </div>
            """, unsafe_allow_html=True)

    def show_job_recovery_by_state(state_code_map, fetch_states_job_data):
        st.subheader("Job Recovery by State Since February 2020")

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
                            name=state,
                            hoverinfo="skip",
                            showlegend=False
                        )
                    )
                else:
                    st.warning(f"No data available for {state}.")

            max_date = df_states["date"].max() + timedelta(days=25)
            hover_mode = "x unified" if len(selected_states) <= 10 else "closest"
            all_dates = df_states["date"]
            quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())

            fig_states.update_layout(
                xaxis_title="Date",
                yaxis_title="% Change Since Feb 2020",
                xaxis=dict(
                    tickformat="%b\n%Y",
                    tickvals=quarterly_ticks,
                    dtick="M1",
                    title_font=dict(size=20),
                    tickfont=dict(size=10),
                    tickangle=0,
                    range=["2020-02-01", max_date.strftime("%Y-%m-%d")]
                ),
                yaxis=dict(
                    title_font=dict(size=20),
                    tickfont=dict(size=12)
                ),
                hovermode=hover_mode,
                legend=dict(
                    font=dict(size=20),
                    title=None,
                    orientation="v",
                    yanchor="top",
                    y=1,
                    xanchor="left",
                    x=1
                )
            )

            for trace in fig_states.data:
                if "lines" in trace.mode:
                    trace.hovertemplate = trace.name + ": %{y:.2f}%<extra></extra>"
                else:
                    trace.hovertemplate = ""

            st.plotly_chart(fig_states, use_container_width=True)
            st.markdown("""
            <div style='font-size: 12px; color: #666;'>
            <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
            <strong>Analysis:</strong> Bay Area Council Economic Institute
            </div>
            """, unsafe_allow_html=True)


    def show_sf_monthly_job_change():
        st.subheader("Monthly Job Change in SF/San Mateo Subregion")

        series_id = "SMS06418840000000001"
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
                df = df[df["period"] != "M13"]
                df["date"] = pd.to_datetime(df["year"] + df["periodName"], format="%Y%B", errors="coerce")
                df["value"] = pd.to_numeric(df["value"], errors="coerce") * 1000
                df = df.sort_values("date")
                df = df[df["date"] >= "2020-02-01"]
                df["monthly_change"] = df["value"].diff()
                df = df.dropna(subset=["monthly_change"])
                df["label"] = df["monthly_change"].apply(
                    lambda x: f"{int(x/1000)}K" if abs(x) >= 1000 else f"{int(x)}"
                )
                df["color"] = df["monthly_change"].apply(lambda x: "#00aca2" if x >= 0 else "#e63946")

                # Calculate dynamic y-axis range excluding April 2020
                df_for_range = df[df["date"] != pd.to_datetime("2020-04-01")]
                y_min = df_for_range["monthly_change"].min()
                y_max = df_for_range["monthly_change"].max()
                
                # Add padding (10% of the range)
                y_range = y_max - y_min
                padding = y_range * 0.1
                y_axis_min = y_min - padding
                y_axis_max = y_max + padding

                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=df["date"],
                    y=df["monthly_change"],
                    marker_color=df["color"],
                    text=df["label"],
                    textposition="outside",
                    name="SF/San Mateo MD",
                    hovertemplate="%{x|%B %Y}<br>Change: %{y:,.0f} Jobs<extra></extra>"
                ))

                fig.update_layout(
                    title=f"February 2020 to {df['date'].max().strftime('%B %Y')}",
                    xaxis_title="Month",
                    yaxis_title="Job Change",
                    showlegend=False,
                    xaxis=dict(
                        tickformat="%b\n%Y",
                        dtick="M1",
                        tickangle=0,
                        title_font=dict(size=20),
                        tickfont=dict(size=10)
                    ),
                    yaxis=dict(tickfont=dict(size=12),
                            range=[y_axis_min, y_axis_max]),
                    margin=dict(t=50, b=50),
                )

                st.plotly_chart(fig, use_container_width=True)
                st.markdown("""
                <div style='font-size: 12px; color: #666;'>
                <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
                <strong>Analysis:</strong> Bay Area Council Economic Institute
                </div>
                """, unsafe_allow_html=True)
            else:
                st.warning("No data returned from BLS for SF/San Mateo MD.")
        except Exception as e:
            st.error(f"Failed to fetch or render chart: {e}")

        # Summary Table
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
        st.subheader("Monthly Job Change in the Bay Area")

        df_bay_monthly = df_bay.copy().sort_values("date")
        df_bay_monthly["monthly_change"] = df_bay_monthly["value"].diff()
        df_bay_monthly = df_bay_monthly[df_bay_monthly["date"] >= pd.to_datetime("2020-03-01")]

        df_bay_monthly["label"] = df_bay_monthly["monthly_change"].apply(
            lambda x: f"{int(x/1000)}K" if abs(x) >= 1000 else f"{int(x)}"
        )
        df_bay_monthly["color"] = df_bay_monthly["monthly_change"].apply(
            lambda x: "#00aca2" if x >= 0 else "#e63946"
        )

        # Calculate dynamic y-axis range excluding April 2020
        df_for_range = df_bay_monthly[df_bay_monthly["date"] != pd.to_datetime("2020-04-01")]
        y_min = df_for_range["monthly_change"].min()
        y_max = df_for_range["monthly_change"].max()
        
        # Add padding (10% of the range)
        y_range = y_max - y_min
        padding = y_range * 0.1
        y_axis_min = y_min - padding
        y_axis_max = y_max + padding

        fig_monthly = go.Figure()
        fig_monthly.add_trace(go.Bar(
            x=df_bay_monthly["date"],
            y=df_bay_monthly["monthly_change"],
            marker_color=df_bay_monthly["color"],
            text=df_bay_monthly["label"],
            textposition="outside",
            name="Bay Area Monthly Job Change",
            hovertemplate="%{x|%B %Y}<br>Change: %{y:,.0f} Jobs<extra></extra>"
        ))

        fig_monthly.update_layout(
            title=f"February 2020 to {df_bay_monthly['date'].max().strftime('%B %Y')}",
            xaxis_title="Month",
            yaxis_title="Job Change",
            showlegend=False,
            xaxis=dict(
                tickformat="%b\n%Y",
                dtick="M1",
                tickangle=0,
                title_font=dict(size=20),
                tickfont=dict(size=10)
            ),
            yaxis=dict(
                tickfont=dict(size=12),
                range=[y_axis_min, y_axis_max]
            ),
        )

        st.plotly_chart(fig_monthly, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are seasonally adjusted.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute
        </div>
        """, unsafe_allow_html=True)

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


    def show_combined_industry_job_recovery_chart(series_mapping, BLS_API_KEY):
        st.subheader("Job Recovery by Industry Since February 2020")

        # Step 1: Fetch data in chunks (BLS API has limits)
        series_ids = list(series_mapping.keys())
        all_data = []
        
        # Process in chunks of 25 series (BLS API limit)
        for i in range(0, len(series_ids), 25):
            chunk = series_ids[i:i+25]
            payload = {
                "seriesid": chunk,
                "startyear": "2020",
                "endyear": str(datetime.now().year),
                "registrationKey": BLS_API_KEY
            }
            
            try:
                response = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", 
                                    json=payload, timeout=30)
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

        # Step 2: Parse response into DataFrame
        records = []
        for series in all_data:
            sid = series["seriesID"]
            if sid not in series_mapping:
                continue
                
            region, industry = series_mapping[sid]
            
            for entry in series["data"]:
                if entry["period"] == "M13":
                    continue  # Skip annual average
                
                try:
                    date = pd.to_datetime(entry["year"] + entry["periodName"], format="%Y%B", errors="coerce")
                    value = float(entry["value"].replace(",", "")) * 1000  # Convert to actual job counts
                    
                    records.append({
                        "series_id": sid,
                        "region": region,
                        "industry": industry,
                        "date": date,
                        "value": value
                    })
                except (ValueError, TypeError) as e:
                    continue  # Skip problematic entries

        if not records:
            st.error("No valid data records could be processed")
            return

        df = pd.DataFrame(records)
        if df.empty:
            st.error("No valid data records could be processed.")
            return
        
        # Debug: Show what industries we have data for
        # industries_with_data = df['industry'].unique()
        # st.write(f"Industries with data: {len(industries_with_data)}")
        
        # Step 3: Get February 2020 baseline and latest month data
        feb_2020_date = pd.to_datetime("2020-02-01")
        
        # Filter for Feb 2020 data
        feb_2020_df = df[df["date"] == feb_2020_date]
        
        # Get the latest available date
        latest_date = df["date"].max()
        latest_df = df[df["date"] == latest_date]
        
        # Debug: See dates for Feb 2020 data and latest data
        # st.write(f"Baseline date: {feb_2020_date.strftime('%B %Y')}")
        # st.write(f"Latest date: {latest_date.strftime('%B %Y')}")
        
        # Step 4: Aggregate by industry for both periods
        # Sum across all regions for each industry
        feb_totals = feb_2020_df.groupby("industry")["value"].sum()
        latest_totals = latest_df.groupby("industry")["value"].sum()

        # Calculate 'Wholesale, Transportation, and Utilities'
        if "Trade, Transportation, and Utilities" in feb_totals and "Retail Trade" in feb_totals:
            feb_totals["Wholesale, Transportation, and Utilities"] = (
                feb_totals["Trade, Transportation, and Utilities"] - feb_totals["Retail Trade"]
            )
        if "Trade, Transportation, and Utilities" in latest_totals and "Retail Trade" in latest_totals:
            latest_totals["Wholesale, Transportation, and Utilities"] = (
                latest_totals["Trade, Transportation, and Utilities"] - latest_totals["Retail Trade"]
            )

        # Debug: Show which industries have both baseline and latest data
        industries_with_both = set(feb_totals.index) & set(latest_totals.index)
        # st.write(f"Industries with both baseline and latest data: {len(industries_with_both)}")
        
        # Step 5: Calculate percent change only for industries with both data points
        pct_change = pd.Series(dtype=float)
        
        for industry in industries_with_both:
            if feb_totals[industry] > 0:  # Avoid division by zero
                change = ((latest_totals[industry] - feb_totals[industry]) / feb_totals[industry]) * 100
                pct_change[industry] = change
        
        if pct_change.empty:
            st.error("No industries have sufficient data for comparison")
            return
        
        # Sort by percent change
        pct_change = pct_change.sort_values()
        pct_change = pct_change.drop("Trade, Transportation, and Utilities", errors="ignore")           # No need to include this anymore
        
        # Step 6: Create colors (red for negative, teal for positive)
        colors = ["#d1493f" if val < 0 else "#00aca2" for val in pct_change.values]
        
        # Step 7: Create the horizontal bar chart
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=pct_change.index,
            x=pct_change.values,
            orientation='h',
            marker_color=colors,
            text=[f"{val:.1f}%" for val in pct_change.values],
            textposition="outside",
            hovertemplate="%{y}<br>% Change: %{x:.1f}%<br>Feb 2020: %{customdata[0]:,.0f}<br>Latest: %{customdata[1]:,.0f}<extra></extra>",
            customdata=[[feb_totals[industry], latest_totals[industry]] for industry in pct_change.index]
        ))

        fig.update_layout(
            title=f"{feb_2020_date.strftime('%b %Y')} to {latest_date.strftime('%b %Y')}",
            xaxis_title="% Change Since Feb 2020",
            margin=dict(l=200, r=100, t=80, b=50),  # Increased left margin for long industry names
            xaxis=dict(
                tickformat=".0f",
                range=[min(pct_change.min() - 5, -10), max(pct_change.max() + 5, 10)],
                tickfont=dict(size=14),
                title=dict(font=dict(size=20))
            ),
            yaxis=dict(tickfont=dict(size=20)),
            showlegend=False,
            height=600  # Make chart taller to accommodate all industries
        )

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Total Non-Farm Employment data is seasonally adjusted, while other industries are not seasonally adjusted.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute
        </div>
        """, unsafe_allow_html=True)

        # Step 8: Show summary table
        st.subheader("Summary")
        summary_df = pd.DataFrame({
            'Industry': pct_change.index,
            'Feb 2020 Jobs': [f"{feb_totals[industry]:,.0f}" for industry in pct_change.index],
            f'{latest_date.strftime("%b %Y")} Jobs': [f"{latest_totals[industry]:,.0f}" for industry in pct_change.index],
            'Change': [f"{latest_totals[industry] - feb_totals[industry]:,.0f}" for industry in pct_change.index],
            '% Change': [f"{val:.1f}%" for val in pct_change.values]
        })
        
        st.dataframe(summary_df, use_container_width=True, hide_index=True)


    # --- Main Dashboard Block ---

    if section == "Employment":
        st.header("Employment")

        # Process employment / unemployment data
        raw_data = fetch_unemployment_data()
        processed_df = process_unemployment_data(raw_data)

        # Employment data for states, Bay Area, and the United States
        df_state = fetch_rest_of_ca_payroll_data()
        df_bay = fetch_bay_area_payroll_data()
        df_us = fetch_us_payroll_data()


        if processed_df is not None:
            if subtab == "Employment":
                # show_employment_chart(processed_df)
                show_employment_comparison_chart(processed_df)

            elif subtab == "Unemployment":
                show_unemployment_rate_chart(processed_df)

            elif subtab == "Regional Job Recovery":
                show_job_recovery_overall(df_state, df_bay, df_us)
                show_job_recovery_by_state(state_code_map, fetch_states_job_data)

            elif subtab == "Monthly Job Change":
                region_choice = st.selectbox(
                    "Select Region:",
                    options=["Greater Bay Area", "SF/San Mateo Subregion"]
                )

                if region_choice == "SF/San Mateo Subregion":
                    show_sf_monthly_job_change()
                elif region_choice == "Greater Bay Area":
                    show_bay_area_monthly_job_change(df_bay)

            elif subtab == "Industry":
                show_combined_industry_job_recovery_chart(series_mapping, BLS_API_KEY)



    elif section == "Population":
        st.header("Population")
        st.write("Placeholder: population graphs, charts, and tables.")

    elif section == "Housing":
        st.header("Housing")
        st.write("Placeholder: housing graphs, charts, and tables.")

    elif section == "Investment":
        st.header("Investment")
        st.write("Placeholder: investment graphs, charts, and tables.")

    elif section == "Transit":
        st.header("Transit")
        st.write("Placeholder: transit graphs, charts, and tables.")


st.markdown("---")
st.caption("Created by Matthias Jiro Walther for the Bay Area Council Economic Institute")