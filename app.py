import streamlit as st
import pandas as pd
import requests
import numpy as np
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Bay Area Dashboard", layout="wide")
st.title("Bay Area Economic Dashboard")

# Sidebar dropdown
section = st.sidebar.selectbox(
    "Select Indicator:",
    ["Employment", "Population", "Housing", "Investment", "Transit"]
)

# Main content
if section == "Employment":
    st.header("Employment")

    bay_area_counties = [
        "Alameda County", "Contra Costa County", "Marin County",
        "Napa County", "San Francisco County", "San Mateo County",
        "Santa Clara County", "Solano County", "Sonoma County"
    ]

    @st.cache_data(ttl=3600)  # Cache for 1 hour
    def fetch_unemployment_data():
        """Fetch unemployment data from CA Open Data Portal"""
        
        API_ENDPOINT = "https://data.ca.gov/api/3/action/datastore_search"
        RESOURCE_ID = "b4bc4656-7866-420f-8d87-4eda4c9996ed"
        
        try:
            # Get total record count first
            response = requests.get(API_ENDPOINT, params={
                "resource_id": RESOURCE_ID,
                "limit": 1
            }, timeout=30)
            
            if response.status_code != 200:
                st.error(f"Failed to connect to API. Status code: {response.status_code}")
                return None
                
            total_records = response.json()["result"]["total"]
            
            # Fetch the most recent data
            all_data = []
            chunk_size = 10000
            
            # Fetch from most recent records first
            for offset in range(0, total_records, chunk_size):
                try:
                    response = requests.get(API_ENDPOINT, params={
                        "resource_id": RESOURCE_ID,
                        "limit": min(chunk_size, total_records - offset),
                        "offset": offset
                    }, timeout=30)
                    
                    if response.status_code == 200:
                        chunk_data = response.json()["result"]["records"]
                        all_data.extend(chunk_data)
                    else:
                        st.warning(f"Failed to fetch chunk at offset {offset}")
                        
                except requests.exceptions.Timeout:
                    st.warning(f"Timeout for chunk at offset {offset}")
                    continue
                    
            return all_data
            
        except Exception as e:
            st.error(f"Error fetching data: {str(e)}")
            return None


    def process_unemployment_data(data):
        """Process and filter unemployment data"""
        if not data:
            return None
            
        df = pd.DataFrame(data)
        
        # Filter for Bay Area counties
        df = df[(df["Area Type"] == "County") & (df["Area Name"].isin(bay_area_counties))]
        
        # Handle different possible date formats
        date_column = None
        for col in ["Date_Numeric", "Date", "Period", "Month", "Year"]:
            if col in df.columns:
                date_column = col
                break
                
        if not date_column:
            st.error("No date column found")
            return None
            
        
        # Try date parsing method
        df["date"] = None
        
        # Date MM/YYYY format
        try:
            df["date"] = pd.to_datetime(df[date_column], format="%m/%Y", errors="coerce")
        except:
            pass
            
        # Remove rows with invalid dates
        df = df.dropna(subset=["date"])
        
        if df.empty:
            st.error("No valid dates found")
            return None
        
        # Parse unemployment rate
        if "Unemployment Rate" not in df.columns:
            st.error("Unemployment Rate column not found")
            return None
            
        df["Unemployment Rate"] = pd.to_numeric(df["Unemployment Rate"], errors="coerce")
        df = df.dropna(subset=["Unemployment Rate"])
        
        # Keep only the last 10 years of data (continuously updating)
        latest_date = df["date"].max()
        ten_years_ago = latest_date - pd.DateOffset(years=10)
        df = df[df["date"] >= ten_years_ago]
        
        # Sort by date
        df = df.sort_values("date")
        
        return df

    # Fetch and process data
    with st.spinner("Fetching unemployment data..."):
        raw_data = fetch_unemployment_data()
        
        
    if raw_data:
        df = process_unemployment_data(raw_data)
        
        if df is not None and not df.empty:
            # Create the plot with 10-year focus
            fig = px.line(
                df,
                x="date",
                y="Unemployment Rate",
                color="Area Name",
                title="Bay Area Unemployment Rate",
                labels={"date": "Date", "Unemployment Rate": "Unemployment Rate (%)"},
                line_shape="linear"
            )
            
            # Customize the plot for 10-year view
            fig.update_layout(
                legend_title_text='County',
                hovermode='closest',
                xaxis_title="Date",
                yaxis_title="Unemployment Rate (%)",
                height=600,
                showlegend=True
            )

            fig.update_traces(
                hovertemplate="<b>%{fullData.name}</b><br>" +
                             "Date: %{x|%b %Y}<br>" +
                             "Unemployment Rate: %{y:.1f}%<br>" +
                             "<extra></extra>"  # Removes the default box around hover
            )
            
            st.plotly_chart(fig, use_container_width=True)
                        
            # Show current vs 10-year analysis
            st.subheader("Current vs. 10-Year Analysis")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                st.write("**Current Rates (Latest Month):**")
                # Get most recent data for each county
                latest_data = df.groupby("Area Name")["date"].max().reset_index()
                latest_data = latest_data.merge(df, on=["Area Name", "date"])
                latest_data = latest_data.sort_values("Unemployment Rate")
                
                st.dataframe(
                    latest_data[["Area Name", "Unemployment Rate"]].rename(columns={
                        "Area Name": "County", 
                        "Unemployment Rate": "Current (%)"
                    }),
                    hide_index=True
                )
            
            with col2:
                st.write("**10-Year Peaks:**")
                # Find 10-year peaks for each county
                peak_data = df.groupby("Area Name")["Unemployment Rate"].max().reset_index()
                peak_data = peak_data.sort_values("Unemployment Rate", ascending=False)
                
                st.dataframe(
                    peak_data.rename(columns={
                        "Area Name": "County", 
                        "Unemployment Rate": "Peak (%)"
                    }),
                    hide_index=True
                )
            
            with col3:
                st.write("**10-Year Lows:**")
                # Find 10-year lows for each county
                low_data = df.groupby("Area Name")["Unemployment Rate"].min().reset_index()
                low_data = low_data.sort_values("Unemployment Rate")
                
                st.dataframe(
                    low_data.rename(columns={
                        "Area Name": "County", 
                        "Unemployment Rate": "Low (%)"
                    }),
                    hide_index=True
                )
        else:
            st.error("Unable to process unemployment data. Please check the API or data format.")
    else:
        st.error("Failed to fetch data from CA Open Data Portal.")

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