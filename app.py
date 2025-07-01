import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import os


# TO DO: Hide API key through .env file
BLS_API_KEY = "15060bc07890456a95aa5d0076966247"

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


    # --- Data Processing ---


    def process_unemployment_data(data):
        if not data:
            return None

        df = pd.DataFrame(data)
        df = df[(df["Area Type"] == "County") & (df["Area Name"].isin(bay_area_counties))]

        if "Seasonally Adjusted" in df.columns:
            df = df[df["Seasonally Adjusted"] == "Y"]

        # Parse date column
        for col in ["Date_Numeric", "Date", "Period", "Month", "Year"]:
            if col in df.columns:
                df["date"] = pd.to_datetime(df[col], errors='coerce')
                break
        else:
            st.error("No valid date column found.")
            return None
        
        df = df.rename(columns={
            "Area Name": "County",
            "Labor Force": "LaborForce",
            "Employment": "Employment",
            "Unemployment Rate": "UnemploymentRate"
        })


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

        # Customize which counties to view
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
                st.subheader("Non-Farm Payroll Jobs Recovery from February 2020 to Now")
                df_nfp = fetch_nonfarm_payroll_data()
                if df_nfp is not None:
                    fig = px.line(
                        df_nfp,
                        x="date", y="pct_change",
                        title="Percent Change in Nonfarm Payroll Jobs Since Feb 2020",
                        labels={"pct_change": "% Change"}
                    )

                    # Highlight most recent point
                    latest_row = df_nfp.iloc[-1]
                    fig.add_scatter(
                        x=[latest_row["date"]],
                        y=[latest_row["pct_change"]],
                        mode="markers+text",
                        marker=dict(color="red", size=10),
                        text=[f"{latest_row['pct_change']:.2f}%"],
                        textposition="top center",
                        name="California"
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