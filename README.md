# Economic Data Dashboard
Data Dashboard on Bay Area's Economy


## How to Run Dashboard

1. **Clone the repository**  
   Open your terminal or shell (e.g., in VS Code) and run:

   ```bash
   git clone https://github.com/your-username/BACEI_Dashboard.git
   cd BACEI_Dashboard
   ```

2. **Install the required libraries**  
   Make sure you have Python installed, then run:
   ```bash
   pip install streamlit pandas numpy matplotlib requests plotly 
   ```
   or try...
   
   ```bash
   pip3 install streamlit pandas numpy matplotlib requests plotly
   ```

4. **Run the dashboard**  
   From the terminal, launch the app by running this command:

   ```bash
   streamlit run app.py
   ```

---

## Data Sources

### Employment

- **Local Area Unemployment Statistics (LAUS)**
  
  Source: [California Open Data Portal](https://data.ca.gov/dataset/local-area-unemployment-statistics-laus/resource/b4bc4656-7866-420f-8d87-4eda4c9996ed)
  
  Data: Unemployment Rates, Employment, Labor Force, Counties

- **State and Metro Area Employment, Hours, & Earnings**
  
  Source: [U.S. Bureau of Labor Statistics (BLS)](https://www.bls.gov/sae/)

  Data: Seasonally adjusted nonfarm payroll employment data
