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


# Title
st.set_page_config(page_title="Bay Area Dashboard", layout="wide")
st.title("Bay Area Economic Dashboard")

# Sidebar dropdown
section = st.sidebar.selectbox(
    "Select Indicator:",
    ["Employment", "Population", "Housing", "Investment", "Transit"]
)

# Main content - selecting an indicator
if section == "Employment":

    bay_area_counties = [
    "Alameda County", "Contra Costa County", "Marin County",
    "Napa County", "San Francisco County", "San Mateo County",
    "Santa Clara County", "Solano County", "Sonoma County"
    ]

    # --- Data Fetching ---

    # Cache data with streamlit for 24 hours (data will be updated once a day)
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
        from math import ceil

        def chunk_list(lst, size):
            return [lst[i:i+size] for i in range(0, len(lst), size)]

        chunks = chunk_list(series_ids, 25)  # Safe limit per API docs
        all_dfs = []
        received_ids = set()

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
        st.plotly_chart(fig, use_container_width=True)

    def show_employment_chart(df):
        st.subheader("Employment Trend")
        fig = px.line(df, x="date", y="Employment", color="County", title="Employment Over Time")
        st.plotly_chart(fig, use_container_width=True


    # --- Main Dashboard Block ---


    if section == "Employment":
        st.header("Employment")

        selected_tab = st.radio("Choose Employment View:", ["Employment", "Unemployment", "Job Recovery"], horizontal=True)

        raw_data = fetch_unemployment_data()
        processed_df = process_unemployment_data(raw_data)
        

        if processed_df is not None:
            if selected_tab == "Employment":
                show_employment_chart(processed_df)
            elif selected_tab == "Unemployment":
                show_unemployment_rate_chart(processed_df)
            elif selected_tab == "Job Recovery":
                st.subheader("Job Recovery Since February 2020")

                df_state = fetch_rest_of_ca_payroll_data()
                df_bay = fetch_bay_area_payroll_data()
                df_us = fetch_us_payroll_data()


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
                            hovertemplate="% Change: %{y:.2f}<extra></extra>"
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
                            hovertemplate="% Change: %{y:.2f}<extra></extra>"
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
                            hovertemplate="% Change: %{y:.2f}<extra></extra>"
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

                    # Layout design
                    latest_date = max(df_state["date"].max(), df_bay["date"].max(), df_us["date"].max())
                    buffered_latest = latest_date + timedelta(days=30)
                    fig.update_layout(
                        title="Percent Change in Nonfarm Payroll Jobs Since Feb 2020",
                        xaxis_title="Date",
                        yaxis_title="% Change Since Feb 2020",
                        xaxis=dict(
                            tickformat="%b\n%Y",        # Format as "Jan\n2024"
                            dtick="M1",                 # One tick per month
                            tickangle=0,                # Keep labels horizontal (adjust for a slant)
                            title_font=dict(size=20),   # X-axis title
                            tickfont=dict(size=10),     # X-axis tick labels
                            range=["2020-02-01", buffered_latest.strftime("%Y-%m-%d")]
                        ),
                        yaxis=dict(
                            title_font=dict(size=20),   # Y-axis title
                            tickfont=dict(size=12)      # Y-axis tick labels
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


                # US States Job Recovery Chart
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
                        default=["California"],  # Default starting state
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

                    # Extract color mapping from base figure
                    color_map = {trace.name: trace.line.color for trace in fig_states.data}

                    # Add markers for latest data points, with matching color
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
                                    showlegend=False
                                )
                            )
                        else:
                            st.warning(f"No data available for {state}.")

                    # Extend x-axis just a bit
                    max_date = df_states["date"].max() + timedelta(days=25)
                    fig_states.update_layout(
                        xaxis_title="Date",
                        yaxis_title="% Change Since Feb 2020",
                        xaxis=dict(
                            tickformat="%b\n%Y",
                            dtick="M1",
                            title_font=dict(size=20),   # X-axis title
                            tickfont=dict(size=10),     # X-axis tick labels
                            tickangle=0,
                            range=["2020-02-01", max_date.strftime("%Y-%m-%d")]
                        ),
                        yaxis=dict(
                            title_font=dict(size=20),
                            tickfont=dict(size=12)
                        ),
                        # hovermode="x unified",
                        # legend=dict(
                        #     font=dict(size=14),
                        #     title=None
                        # )
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
                    st.plotly_chart(fig_states, use_container_width=True)
            


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
st.caption("Created by Matthias Jiro Walther")