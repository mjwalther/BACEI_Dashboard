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



# TO-DO
# 1. Remove Bay Area counties from the count of California in Jobs Recovery to make it "Rest of California"
# 2. Add United States metric to Jobs Recovery
# 3. Fix x-axis to include only months up to present, not future months
# 4. Make drop-down for selecting different counties / regions


# BLS_API_KEY = os.getenv("BLS_API_KEY")
BLS_API_KEY= "15060bc07890456a95aa5d0076966247"

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
    def fetch_nonfarm_payroll_data():
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
        SERIES_ID = "SMS06000000000000001"
        payload = {
            "seriesid": [SERIES_ID],
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
            if "Results" not in data:
                st.error("BLS API error: No results returned.")
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
            st.error(f"BLS data fetch failed: {e}")
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
        st.plotly_chart(fig, use_container_width=True)



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
                st.subheader("Job Recovery from February 2020 to Now")

                df_state = fetch_nonfarm_payroll_data()
                df_bay = fetch_bay_area_payroll_data()

                if df_state is not None and df_bay is not None:
                    fig = go.Figure()

                    # California (teal)
                    fig.add_trace(
                        go.Scatter(
                            x=df_state["date"],
                            y=df_state["pct_change"],
                            mode="lines",
                            name="California",
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
                    fig.update_layout(
                        title="Percent Change in Nonfarm Payroll Jobs Since Feb 2020",
                        xaxis_title="Date",
                        yaxis_title="% Change Since Feb 2020",
                        yaxis=dict(
                            title_font=dict(size=20),   # Y-axis title
                            tickfont=dict(size=12)      # Y-axis tick labels
                        ),
                        xaxis=dict(
                            tickformat="%b\n%Y",        # Format as "Jan\n2024"
                            dtick="M1",                 # One tick per month
                            tickangle=315,              # Keep labels horizontal (adjust for a slant)
                            title_font=dict(size=20),   # X-axis title
                            tickfont=dict(size=10)      # X-axis tick labels
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