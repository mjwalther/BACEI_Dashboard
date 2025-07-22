import streamlit as st
import pandas as pd
import requests
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os
from datetime import datetime, timedelta
from data_mappings import state_code_map, series_mapping, bay_area_counties, regions, office_metros_mapping, rename_mapping, color_map, sonoma_mapping
from dotenv import load_dotenv
load_dotenv()

# BLS_API_KEY = os.getenv("BLS_API_KEY")
BLS_API_KEY= "15060bc07890456a95aa5d0076966247"

# --- Title ----
st.set_page_config(page_title="Bay Area Dashboard", layout="wide")

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
    ["Employment", "Population", "Housing", "Investment", "Transit"]
)

# --- Sidebar Subtabs ---
subtab = None
if section == "Employment":
    subtab = st.sidebar.radio(
        "Employment Views:",
        ["Employment", "Unemployment", "Job Recovery", "Monthly Change", "Industry", "Office Sectors"],
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
        """
        Displays an interactive line chart of unemployment rate trends for Bay Area counties.

        Provides a checkbox to select all counties by default, and a multiselect option 
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
        bay_area_agg['County'] = '9-county Bay Area'
        
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
            if trace.name == '9-county Bay Area':
                trace.update(
                    line=dict(width=2, dash='dash'),
                    marker=dict(size=8)
                )

        quarterly_ticks = combined_df["date"][combined_df["date"].dt.month.isin([1, 4, 7, 10])].dt.strftime("%Y-%m-01").unique().tolist()

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
                title_font=dict(family="Avenir Medium", size=18, color="black"),
                tickvals=quarterly_ticks,
                tickformat="%b\n%Y",
                dtick="M1",
                tickangle=0,
                tickfont=dict(family="Avenir", size=12, color="black"),
            ),
            yaxis=dict(
                title="Unemployment Rate",
                ticksuffix="%",
                title_font=dict(family="Avenir Medium", size=18, color="black"),
                tickfont=dict(family="Avenir", size=12, color="black")
            ),
            legend=dict(
                title=dict(
                    text="Region",  # Or any title you prefer
                    font=dict(
                        family="Avenir Black",  # Bold/dark font
                        size=14,
                        color="black"
                    )
                ),
                font=dict(
                    family="Avenir",
                    size=15,
                    color="black"
                ),
                orientation="v",
                x=1.01,
                y=1
            ),
            title_font = dict(family="Avenir Black", size=20)

        )

        for trace in fig.data:
            trace.hovertemplate = f"{trace.name}: " + "%{y:.1f}%<extra></extra>"

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666; font-family: "Avenir Light", sans-serif;'>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
        </div>
        """, unsafe_allow_html=True)

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
                'Minimum Rate': f"{min_rate:.1f}% ({min_date.strftime('%b %Y')})",
                'Maximum Rate': f"{max_rate:.1f}% ({max_date.strftime('%b %Y')})"
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


    def show_employment_comparison_chart(df):
        """
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
        
        # Add February 2020 bars
        fig.add_trace(go.Bar(
            name='February 2020',
            x=comparison_df['County'],
            y=comparison_df['Feb 2020'],
            marker_color='#00aca2',
            text=comparison_df['Feb 2020'],
            texttemplate='%{text:,.0f}',
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>%{y:,.0f} residents employed<extra></extra>',
            textfont=dict(family="Avenir", size=13, color="black")
        ))
        
        # Add latest month bars
        fig.add_trace(go.Bar(
            name=f'{comparison_df["Latest Date"].iloc[0].strftime("%b %Y")}',
            x=comparison_df['County'],
            y=comparison_df['Latest'],
            marker_color='#eeaf30',
            text=comparison_df['Latest'],
            texttemplate='%{text:,.0f}',
            textposition='outside',
            hovertemplate='<b>%{x}</b><br>%{y:,.0f} residents employed<extra></extra>',
            textfont=dict(family="Avenir Black", size=15, color="black")
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
                tickfont=dict(family="Avenir", size=16, color="black"),
            ),
            yaxis=dict(
                title='Number of Employed Residents',
                title_font=dict(family="Avenir Medium", size=22, color="black"),
                tickfont=dict(family="Avenir", size=16, color="black"),
                showgrid=True,
                gridcolor="#CCCCCC",
                gridwidth=1,
                griddash="dash"
            ),
            legend=dict(
                font=dict(family="Avenir", size=18)
            ),
            barmode='group',
            height=600,
            showlegend=True,
            xaxis_tickangle=0,
            title_font = dict(family="Avenir Black", size=20)
        )
        
        # Format y-axis to show numbers in thousands/millions
        fig.update_yaxes(tickformat='.0s')
        
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666; font-family: "Avenir Light", sans-serif;'>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Local Area Unemployment Statistics (LAUS), California Open Data Portal.<br>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
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
                return 'color: green'
            else:
                return 'color: red'

        styled_df = display_df.style.map(color_pct_change, subset=['Percent Change'])

        st.dataframe(styled_df, use_container_width=True, hide_index=True)


    def show_job_recovery_overall(df_state, df_bay, df_us, df_sonoma, df_napa):
        """
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
                    textfont=dict(size=18, family="Avenir", color="black"),
                    name="United States",
                    hoverinfo="skip",
                    showlegend=False
                )
            )

            # # Rest of California (teal)
            # fig.add_trace(
            #     go.Scatter(
            #         x=df_state["date"],
            #         y=df_state["pct_change"],
            #         mode="lines",
            #         name="Rest of California",
            #         line=dict(color="#00aca2"),
            #         hovertemplate="Rest of California: %{y:.2f}%<extra></extra>"
            #     )
            # )

            # latest_row = df_state.iloc[-1]
            # fig.add_trace(
            #     go.Scatter(
            #         x=[latest_row["date"]],
            #         y=[latest_row["pct_change"]],
            #         mode="markers+text",
            #         marker=dict(color="#00aca2", size=10),
            #         text=[f"{latest_row['pct_change']:.2f}%"],
            #         textposition="top center",
            #         name="California",
            #         hoverinfo="skip",
            #         showlegend=False
            #     )
            # )

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
                    textfont=dict(size=18, family="Avenir", color="black"),
                    name="Bay Area",
                    hoverinfo="skip",
                    showlegend=False
                )
            )


            # SONOMA (will delete later)
            fig.add_trace(
                go.Scatter(
                    x=df_sonoma["date"],
                    y=df_sonoma["pct_change"],
                    mode="lines",
                    name="Sonoma County",
                    line=dict(color="#d84f19"),
                    hovertemplate="Sonoma: %{y:.2f}%<extra></extra>"
                )
            )

            latest_son = df_sonoma.iloc[-1]
            fig.add_trace(
                go.Scatter(
                    x=[latest_son["date"]],
                    y=[latest_son["pct_change"]],
                    mode="markers+text",
                    marker=dict(color="#d84f19", size=10),
                    text=[f"{latest_son['pct_change']:.2f}%"],
                    textposition="bottom center",
                    textfont=dict(size=18, family="Avenir", color="black"),
                    name="Sonoma",
                    hoverinfo="skip",
                    showlegend=False
                )
            )

            # NAPA (will delete later)
            fig.add_trace(
                go.Scatter(
                    x=df_napa["date"],
                    y=df_napa["pct_change"],
                    mode="lines",
                    name="Napa County",
                    line=dict(color="#00aca2"),
                    hovertemplate="Napa: %{y:.2f}%<extra></extra>"
                )
            )

            latest_napa = df_napa.iloc[-1]
            fig.add_trace(
                go.Scatter(
                    x=[latest_napa["date"]],
                    y=[latest_napa["pct_change"]],
                    mode="markers+text",
                    marker=dict(color="#00aca2", size=10),
                    text=[f"{latest_napa['pct_change']:.2f}%"],
                    textposition="bottom center",
                    textfont=dict(size=18, family="Avenir", color="black"),
                    name="Napa",
                    hoverinfo="skip",
                    showlegend=False
                )
            )


            latest_date = max(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max(), df_napa["date"].max())
            buffered_latest = latest_date + timedelta(days=50)

            # Generate quarterly ticks (Jan, Apr, Jul, Oct) across all dates
            all_dates = pd.concat([df_state["date"], df_bay["date"], df_us["date"], df_napa["date"], df_sonoma["date"]])
            quarterly_ticks = sorted(all_dates[all_dates.dt.month.isin([1, 4, 7, 10])].unique())
            ticktext=[
                date.strftime("%b<br> %Y") if date.month == 1 else date.strftime("%b")
                for date in quarterly_ticks
            ]

            fig.update_layout(
                title=dict(
                    text="<span style='font-size:26px; font-family:Avenir Black'>Sonoma County Job Recovery Lags Behind</span><br><br><span style='font-size:20px; color:#666; font-family:Avenir Medium'>Percent Change in Nonfarm Payroll Jobs from February 2020 to " + latest_date.strftime('%B %Y') + "</span>",
                    x=0.5,
                    xanchor='center'
                ),
                xaxis=dict(
                    title='Date',
                    title_font=dict(family="Avenir Medium", size=24, color="black"),
                    tickfont=dict(family="Avenir", size=18, color="black"),
                    tickvals=quarterly_ticks,
                    ticktext=ticktext,
                    dtick="M1",
                    tickangle=0,
                    range=["2020-02-01", buffered_latest.strftime("%Y-%m-%d")]
                ),
                yaxis=dict(
                    title='Employment Change Since Feb 2020',
                    ticksuffix="%",
                    title_font=dict(family="Avenir Medium", size=21, color="black"),
                    tickfont=dict(family="Avenir", size=18, color="black"),
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
                            family="Avenir Black",  # Bold/dark font
                            size=20,
                            color="black"
                        )
                    ),
                    font=dict(
                        family="Avenir",
                        size=21,
                        color="black"
                    ),
                    orientation="v",
                    x=1.01,
                    y=1
                ),
            )

            st.plotly_chart(fig, use_container_width=True)
            st.markdown("""
            <div style='font-size: 12px; color: #666; font-family: "Avenir Light", sans-serif;'>
            <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong>Bureau of Labor Statistics (BLS).<br>
            <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong>Data are seasonally adjusted.<br>
            <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis:</strong> Bay Area Council Economic Institute.<br>
            </div>
            """, unsafe_allow_html=True)
        


    def show_job_recovery_by_state(state_code_map, fetch_states_job_data):
        """
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

            max_date = df_states["date"].max() + timedelta(days=40)
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
            <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
            </div>
            """, unsafe_allow_html=True)


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
                df = df[df["date"] >= "2020-02-01"]     # Start date of employment job data
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


    def create_monthly_job_change_chart(df, region_name):
        """
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
            textfont=dict(
                family="Avenir",
                size=20
            ),
            name=region_name,
            hovertemplate="%{x|%B %Y}<br>Change: %{y:,.0f} Jobs<extra></extra>"
        ))

        quarterly_ticks = df["date"][df["date"].dt.month.isin([1, 4, 7, 10])].unique()
        latest_month = df["date"].max().strftime('%B %Y')

        
        fig.update_layout(
            title=dict(
                text=f"Monthly Job Change in {region_name} <br>"
                    f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>"
                    f"February 2020 to {latest_month}</span>",
                x=0.5,
                xanchor='center',
                font=dict(family="Avenir Black", size=26)
            ),
            margin=dict(t=80, b=50),
            xaxis=dict(
                title='Month',
                title_font=dict(family="Avenir Medium", size=24, color="black"),
                tickfont=dict(family="Avenir", size=18, color="black"),
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
                title_font=dict(family="Avenir Medium", size=24, color="black"),
                tickfont=dict(family="Avenir", size=18, color="black"),
                showgrid=True,
                range=[y_axis_min, y_axis_max]
            ),
        )

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666; font-family: "Avenir Light", sans-serif;'>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Source: </strong> Bureau of Labor Statistics (BLS).<br>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Note: </strong> Data are seasonally adjusted.<br>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Analysis: </strong> Bay Area Council Economic Institute.<br>
        <strong style='font-family: "Avenir Medium", sans-serif;'>Regions:</strong> North Bay: Napa MSA, San Rafael MD, Santa Rosa-Petaluma, Vallejo.
                    East Bay: Oakland-Fremont-Berkeley MD. South Bay: San Jose-Sunnyvale-Santa Clara, San Francisco-Peninsula: San Francisco-San Mateo-Redwood City MD<br>
        </div>
        """, unsafe_allow_html=True)


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

        quarterly_ticks = df_bay_monthly["date"][df_bay_monthly["date"].dt.month.isin([1, 4, 7, 10])].unique()

        fig_monthly.update_layout(
            title=f"February 2020 to {df_bay_monthly['date'].max().strftime('%B %Y')}",
            xaxis_title="Month",
            yaxis_title="Job Change",
            showlegend=False,
            xaxis=dict(
                tickvals=quarterly_ticks,
                tickformat="%b\n%Y",
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
        <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
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
        """
        Displays a horizontal bar chart of job recovery by industry for the Bay Area, 
        allowing the user to toggle between Post-Covid Recovery (Feb 2020 to latest month)
        and Past-Year Recovery (latest 12-month period).

        The function aggregates employment data across all Bay Area regions for each industry, 
        calculates the percent change in employment from the selected baseline to the latest available month, 
        and visualizes the results as a bar chart.

        A derived category called 'Wholesale, Transportation, and Utilities' is calculated by subtracting
        'Retail Trade' from 'Trade, Transportation, and Utilities'. The original 'Trade, Transportation, 
        and Utilities' category is excluded from the final chart.

        A summary table with employment levels, changes in job counts, and percentage changes is also displayed.

        Args:
            series_mapping (dict): Dictionary mapping BLS series IDs to tuples of (region, industry).
            BLS_API_KEY (str): User's BLS API key for data access.

        Returns:
            None. Displays charts and tables directly in the Streamlit app.
        """
        
        st.subheader("Job Recovery by Industry")
        
        # Add toggle for time period selection
        recovery_period = st.radio(
            "Select Recovery Period:",
            ["Since Feb 2020", "Last 12 Months"],
            horizontal=True
        )

        # Step 1: Fetch data in chunks (BLS API has limits)
        series_ids = list(series_mapping.keys())
        # series_ids = list(sonoma_mapping.keys())
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
            # if sid not in sonoma_mapping:
            if sid not in series_mapping:
                continue
            
            # region, industry = sonoma_mapping[sid]
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
        
        # Step 3: Set baseline and latest dates based on selected period
        if recovery_period == "Since Feb 2020":
            baseline_date = pd.to_datetime("2020-02-01")
            baseline_label = "Feb 2020"
            title_period = "Post-Covid"
        else:  # Past-Year Recovery
            # Get the latest available date and calculate 12 months prior
            latest_date = df["date"].max()
            baseline_date = latest_date - pd.DateOffset(months=12)
            
            # Find the closest actual date in the data to our calculated baseline
            available_dates = df["date"].unique()
            closest_baseline = min(available_dates, key=lambda x: abs(x - baseline_date))
            baseline_date = closest_baseline
            baseline_label = baseline_date.strftime("%b %Y")
            title_period = "Last 12 Months"
        
        # Get the latest available date
        latest_date = df["date"].max()
        
        # Filter for baseline data
        baseline_df = df[df["date"] == baseline_date]
        
        # Filter for latest data
        latest_df = df[df["date"] == latest_date]
        
        # Check if we have data for both periods
        if baseline_df.empty:
            st.error(f"No data available for baseline period ({baseline_label})")
            return
        
        if latest_df.empty:
            st.error(f"No data available for latest period ({latest_date.strftime('%b %Y')})")
            return
        
        # Step 4: Aggregate by industry for both periods
        # Sum across all regions for each industry
        baseline_totals = baseline_df.groupby("industry")["value"].sum()
        latest_totals = latest_df.groupby("industry")["value"].sum()

        # Calculate 'Wholesale, Transportation, and Utilities' if applicable
        if "Trade, Transportation, and Utilities" in baseline_totals and "Retail Trade" in baseline_totals:
            baseline_totals["Wholesale, Transportation, and Utilities"] = (
                baseline_totals["Trade, Transportation, and Utilities"] - baseline_totals["Retail Trade"]
            )
        if "Trade, Transportation, and Utilities" in latest_totals and "Retail Trade" in latest_totals:
            latest_totals["Wholesale, Transportation, and Utilities"] = (
                latest_totals["Trade, Transportation, and Utilities"] - latest_totals["Retail Trade"]
            )

        # Step 5: Calculate percent change only for industries with both data points
        industries_with_both = set(baseline_totals.index) & set(latest_totals.index)
        pct_change = pd.Series(dtype=float)
        
        for industry in industries_with_both:
            if baseline_totals[industry] > 0:  # Avoid division by zero
                change = ((latest_totals[industry] - baseline_totals[industry]) / baseline_totals[industry]) * 100
                pct_change[industry] = change

        # Step 5a: Net Change
        net_change = pd.Series(dtype=float)
        for industry in industries_with_both:
            net_change[industry] = latest_totals[industry] - baseline_totals[industry]
        
        if pct_change.empty:
            st.error("No industries have sufficient data for comparison")
            return
        
        # Sort by percent change
        pct_change = pct_change.sort_values()
        pct_change = pct_change.drop("Trade, Transportation, and Utilities", errors="ignore")

        # Sort by net change
        net_change = net_change.sort_values()
        net_change = net_change.drop("Trade, Transportation, and Utilities", errors="ignore")
        
        # Step 6: Create colors (red for negative, teal for positive)
        # colors = ["#d1493f" if val < 0 else "#00aca2" for val in pct_change.values]

        # # Step 6: Create colors (red for negative, teal for positive)
        colors = ["#d1493f" if val < 0 else "#00aca2" for val in net_change.values]
        
        # Step 7: Create the horizontal bar chart
        fig = go.Figure()
        fig.add_trace(go.Bar(
            y=net_change.index,
            x=net_change.values,
            orientation='h',
            marker_color=colors,
            # text=[f"{val:+,.1f}%" for val in pct_change.values],
            text=[f"{val:+,.0f}" for val in net_change.values],
            textfont=dict(size=17, family="Avenir Light", color="black"),
            textposition="outside",
            # hovertemplate=f"%{{y}}<br>% Change: %{{x:.1f}}%<br>{baseline_label}: %{{customdata[0]:,.0f}}<br>{latest_date.strftime('%b %Y')}: %{{customdata[1]:,.0f}}<extra></extra>",
            hovertemplate=f"%{{y}}<br>Net Change: %{{x:.0f}}<br>{baseline_label}: %{{customdata[0]:,.0f}}<br>{latest_date.strftime('%b %Y')}: %{{customdata[1]:,.0f}}<extra></extra>",
            customdata=[[baseline_totals[industry], latest_totals[industry]] for industry in pct_change.index]
        ))

        # --- NET CHANGE ---
        # Add vertical dashed lines at specified x-axis values
        # Determine dynamic x-axis range
        buffer = 0.05 * (net_change.max() - net_change.min())  # 5% padding
        x_min = net_change.min() - buffer
        x_max = net_change.max() + max(500, buffer)

        # Dynamically determine tick spacing
        data_range = x_max - x_min
        if data_range < 5000:
            tick_spacing = 500
        elif data_range < 20000:
            tick_spacing = 1000
        elif data_range < 50000:
            tick_spacing = 2500
        else:
            tick_spacing = 5000

        # Round min and max to nearest multiple of spacing
        x_min_rounded = int(np.floor(x_min / tick_spacing) * tick_spacing)
        x_max_rounded = int(np.ceil(x_max / tick_spacing) * tick_spacing)

        tick_positions = list(range(x_min_rounded, x_max_rounded + 1, tick_spacing))

        for x in tick_positions:
            fig.add_shape(
                type="line",
                x0=x,
                y0=-0.5,
                x1=x,
                y1=len(net_change) - 0.5,
                line=dict(
                    color="lightgray",
                    width=1,
                    dash="dash"
                ),
                layer="below"
            )


        # --- PERCENT CHANGE ---
        # x_min = min(pct_change.min() - 5, -10)
        # x_max = max(pct_change.max() + 5, 10)

        # # Define tick spacing
        # tick_spacing = 5

        # # Round min and max to nearest multiple of 5
        # x_min_rounded = int(np.floor(x_min / tick_spacing) * tick_spacing)
        # x_max_rounded = int(np.ceil(x_max / tick_spacing) * tick_spacing)

        # tick_positions = list(range(x_min_rounded, x_max_rounded + 1, tick_spacing))
        # tick_labels = [f"{x}%" for x in tick_positions]

        # for x in tick_positions:
        #     fig.add_shape(
        #         type="line",
        #         x0=x,
        #         y0=-0.5,
        #         x1=x,
        #         y1=len(pct_change) - 0.5,
        #         line=dict(color="lightgray", width=1, dash="dash"),
        #         layer="below"
        #     )


        fig.update_layout(
            xaxis_title=f"Net Change in Jobs Since {baseline_label}",
            title=dict(
                text=f"Bay Area Job Recovery by Industry<br>"
                    f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>"
                    f"{title_period}: {baseline_label} to {latest_date.strftime('%b %Y')}</span>",
                x=0.5,
                xanchor='center',
                font=dict(family="Avenir Black", size=26)
            ),
            margin=dict(l=100, r=200, t=80, b=70),
            xaxis=dict(
                tickformat=",.0f",
                ticksuffix="%",
                title_font=dict(family="Avenir Medium", size=21, color="black"),
                tickfont=dict(family="Avenir", size=18, color="black"),
                tickvals=tick_positions,
                # ticktext=tick_labels,
                range=[x_min_rounded, x_max_rounded],
                #title_standoff=25
            ),
            yaxis=dict(
                tickfont=dict(family="Avenir", size=20, color="black"),
                # showticklabels=False
            ),
            showlegend=False,
            height=600
        )

        # --- Moving y-axis labels next to the horizontal bars ---
        # for i, (industry, value) in enumerate(pct_change.items()):
        #     fig.add_annotation(
        #         x=-1 if value >= 0 else 1,  # Slight offset from 0 line
        #         y=i,
        #         text=industry,
        #         showarrow=False,
        #         xanchor="right" if value >= 0 else "left",  # Align text depending on side
        #         font=dict(family="Avenir", size=18, color="black")
        #     )

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
        <div style='font-size: 12px; color: #666;'>
        <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Total Non-Farm Employment data is seasonally adjusted, while other industries are not seasonally adjusted.<br>
        <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
        </div>
        """, unsafe_allow_html=True)

        # Step 8: Show summary table
        st.subheader("Summary")
        summary_df = pd.DataFrame({
            'Industry': pct_change.index,
            f'{baseline_label} Jobs': [f"{baseline_totals[industry]:,.0f}" for industry in pct_change.index],
            f'{latest_date.strftime("%b %Y")} Jobs': [f"{latest_totals[industry]:,.0f}" for industry in pct_change.index],
            'Net Change': [f"{latest_totals[industry] - baseline_totals[industry]:+,.0f}" for industry in pct_change.index],
            'Percent Change': [f"{val:+.1f}%" for val in pct_change.values]
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

        st.subheader("Office Sector Job Recovery by Metro Area")

        recovery_period = st.radio(
            "Select Recovery Period:",
            ["Since Feb 2020", "Last 12 Months"],
            horizontal=True
        )

        # Step 1: Fetch Data
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
            response = requests.post("https://api.bls.gov/publicAPI/v2/timeseries/data/", json=payload, timeout=30)
            data = response.json()

            if "Results" in data and "series" in data["Results"]:
                all_data.extend(data["Results"]["series"])
            else:
                st.warning(f"No data returned for chunk {i//25 + 1}")

        # Step 2: Parse Data
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
                    records.append({
                        "metro": metro,
                        "sector": sector,
                        "date": date,
                        "value": value
                    })
                except:
                    continue

        df = pd.DataFrame(records)

        # Step 3: Define baseline and latest dates
        latest_date = df["date"].max()

        if recovery_period == "Since Feb 2020":
            baseline_date = pd.to_datetime("2020-02-01")
            baseline_label = "Feb 2020"
            title_suffix = f"Feb 2020 to {latest_date.strftime('%b %Y')}"
        else:
            baseline_date = latest_date - pd.DateOffset(months=12)
            available_dates = df["date"].unique()
            baseline_date = min(available_dates, key=lambda x: abs(x - baseline_date))
            baseline_label = baseline_date.strftime("%b %Y")
            title_suffix = f"{baseline_label} to {latest_date.strftime('%b %Y')}"

        # Step 4: Aggregate Office/Tech sectors per metro
        office_sectors = ["Information", "Financial Activities", "Professional and Business Services"]

        baseline_df = df[(df["date"] == baseline_date) & (df["sector"].isin(office_sectors))]
        latest_df = df[(df["date"] == latest_date) & (df["sector"].isin(office_sectors))]

        baseline_totals = baseline_df.groupby("metro")["value"].sum()
        latest_totals = latest_df.groupby("metro")["value"].sum()

        # Step 5: Calculate Percent Change
        common_metros = set(baseline_totals.index) & set(latest_totals.index)
        pct_change = pd.Series({
            metro: round(((latest_totals[metro] - baseline_totals[metro]) / baseline_totals[metro]) * 100, 1)
            for metro in common_metros if baseline_totals[metro] > 0
        }).sort_values(ascending=True)

        short_names = [rename_mapping.get(metro, metro) for metro in pct_change.index]

        # Step 6: Red for negative, Green for positive
        colors = ["#d1493f" if val < 0 else "#00aca2" for val in pct_change.values]

        # Step 7: Create Chart
        fig = go.Figure()

        # Create custom y-axis labels with specific color for Sonoma County
        colored_labels = []
        for name in short_names:
            if "Sonoma" in name:  # Adjust this condition based on your exact label
                colored_labels.append(f'<span style="color:#d84f19">{name}</span>')
            else:
                colored_labels.append(name)


        fig.add_trace(go.Bar(
            y=colored_labels,
            x=pct_change.values,
            orientation='h',
            marker_color=colors,
            text=[f"{val:.1f}%" for val in pct_change.values],
            textfont=dict(size=16, family="Avenir Light", color="black"),
            textposition="outside",
            hovertemplate="%{y}<br>% Change: %{x:.1f}%<br>" +
                        f"{baseline_label}: " + "%{customdata[0]:,.0f}" +
                        f"<br>{latest_date.strftime('%b %Y')}: " + "%{customdata[1]:,.0f}<extra></extra>",
            customdata=[[baseline_totals[metro], latest_totals[metro]] for metro in pct_change.index]
        ))


        # Determine automatic tick positions by creating a temporary figure
        temp_fig = go.Figure()
        temp_fig.add_trace(go.Bar(y=short_names, x=pct_change.values, orientation='h'))
        temp_fig.update_layout(xaxis=dict(tickformat=".1f", ticksuffix="%"))
        
        # Extract the automatic tick positions
        tick_positions = temp_fig.layout.xaxis.tickvals
        
        if tick_positions is None:
            data_range = pct_change.max() - pct_change.min()
            if data_range <= 2:
                tick_step = 0.5
            elif data_range <= 5:
                tick_step = 1
            elif data_range <= 10:
                tick_step = 2
            else:
                tick_step = 5
            
            x_min = pct_change.min()
            x_max = pct_change.max()
            start_tick = (x_min // tick_step) * tick_step
            end_tick = ((x_max // tick_step) + 1) * tick_step
            
            tick_positions = []
            current = start_tick
            while current <= end_tick:
                tick_positions.append(current)
                current += tick_step

        # Add vertical dashed lines at tick positions
        for x in tick_positions:
            fig.add_shape(
                type="line",
                x0=x,
                y0=-0.5,
                x1=x,
                y1=len(pct_change) - 0.5,
                line=dict(
                    color="lightgray",
                    width=1,
                    dash="dash"
                ),
                layer="below"
            )


        fig.update_layout(
            title=dict(
                text=f"Employment in Key Office Sectors by Metro Area<br>"
                    f"<span style='font-size:20px; color:#666; font-family:Avenir Medium'>"
                    f"{title_suffix}</span>",
                x=0.5,
                xanchor='center',
                font=dict(family="Avenir Black", size=26)
            ),
            margin=dict(l=200, r=100, t=80, b=50),
            xaxis=dict(
                title=f"Percent Change Since {baseline_label}",
                tickformat=".1f",
                ticksuffix="%",
                title_font=dict(family="Avenir Medium", size=24, color="black"),
                tickfont=dict(family="Avenir", size=18, color="black"),
            ),
            yaxis=dict(
                tickfont=dict(family="Avenir Black", size=18, color="black")
            ),
            showlegend=False,
            height=700
        )

        st.plotly_chart(fig, use_container_width=True)
        st.markdown("""
            <div style='font-size: 12px; color: #666;'>
            <strong>Source:</strong> Bureau of Labor Statistics (BLS). <strong>Note:</strong> Data are not seasonally adjusted. Knowledge industries include: Information, Financial Activities, and Professional and Business Services.<br>
            <strong>Analysis:</strong> Bay Area Council Economic Institute.<br>
            </div>
            """, unsafe_allow_html=True)

        # Step 8: Summary Table
        st.subheader("Summary")
        summary_df = pd.DataFrame({
            'Metro': short_names,
            f'{baseline_label} Jobs': [f"{baseline_totals[metro]:,.0f}" for metro in pct_change.index],
            f'{latest_date.strftime("%b %Y")} Jobs': [f"{latest_totals[metro]:,.0f}" for metro in pct_change.index],
            'Net Change': [f"{latest_totals[metro] - baseline_totals[metro]:+,.0f}" for metro in pct_change.index],
            'Percent Change': [f"{val:+.1f}%" for val in pct_change.values]
        })

        def color_percent(val):
            if isinstance(val, str) and '-' in val:
                return 'color: red'
            else:
                return 'color: green'
        
        styled_summary = summary_df.style.map(color_percent, subset=['Percent Change'])
        st.dataframe(styled_summary, use_container_width=True, hide_index=True)


    # --- Main Dashboard Block ---

    if section == "Employment":
        # Process employment / unemployment data
        raw_data = fetch_unemployment_data()
        processed_df = process_unemployment_data(raw_data)

        # Employment data for states, Bay Area, and the United States
        df_state = fetch_rest_of_ca_payroll_data()
        df_bay = fetch_bay_area_payroll_data()
        df_us = fetch_us_payroll_data()
        df_sonoma = fetch_sonoma_payroll_data()
        df_napa = fetch_napa_payroll_data()


        if processed_df is not None:
            if subtab == "Employment":
                # show_employment_chart(processed_df)
                show_employment_comparison_chart(processed_df)

            elif subtab == "Unemployment":
                show_unemployment_rate_chart(processed_df)

            elif subtab == "Job Recovery":
                show_job_recovery_overall(df_state, df_bay, df_us, df_sonoma, df_napa)
                show_job_recovery_by_state(state_code_map, fetch_states_job_data)

            elif subtab == "Monthly Change":
                
                region_choice = st.selectbox(
                    "Select Region:",
                    options=[
                        "9-county Bay Area",
                        "North Bay",
                        "East Bay",
                        "San Francisco-Peninsula",
                        "South Bay",
                        "Sonoma County"
                    ]
                )

                if region_choice == "9-county Bay Area":
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

                            create_monthly_job_change_chart(df_merged, region_choice)
                            create_job_change_summary_table(df_merged)
                        else:
                            st.warning(f"No data available for {region_choice}.")
                    else:
                        # Single region (e.g., "East Bay", "South Bay", "SF-Peninsula")
                        df = fetch_and_process_job_data(series_id_or_list, region_choice)
                        if df is not None:
                            create_monthly_job_change_chart(df, region_choice)
                            create_job_change_summary_table(df)

            elif subtab == "Industry":
                show_combined_industry_job_recovery_chart(series_mapping, BLS_API_KEY)

            elif subtab == "Office Sectors":
                show_office_tech_recovery_chart(office_metros_mapping, BLS_API_KEY)


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