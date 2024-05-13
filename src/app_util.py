import math
import os
import json
import pandas as pd
from pathlib import Path
from enum import Enum


class Env(Enum):
    DEV = 1
    PROD = 2
env = Env.DEV if os.getenv('ENVIRONMENT') == "DEV" else Env.PROD

# Get the directory of the current file.
current_directory = Path(__file__).resolve().parent

# Construct the path to the data directory.
data_directory = current_directory.parent / 'backend_data'

# Construct the paths to the data files.
PROPERTY_DF_PATH = data_directory / 'property_df.parquet'
REGION_DATA_PATH = data_directory / 'regions.json'

# Load data from files.
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Load the property dataframe.
BACKEND_PROPERTIES_DF = pd.read_parquet(PROPERTY_DF_PATH).round(2)

# Load region data.
REGION_TO_ZIP_CODE = {region: set(zip_codes) for region, zip_codes in load_json(REGION_DATA_PATH).items()}

TARGET_COLUMNS = ['Image', 'Save', 'City', 'Rental Income (5% Down)', 'Rent Estimate', 'Price', 'Breakeven Price (5% Down)', 'Competative Price (5% Down)', 'Is Breakeven Price Offending', 'Adjusted CoC (5% Down)', 'Year Built', 'Home Type', 'Bedrooms', 'Bathrooms']
BACKEND_COL_NAME_TO_FRONTEND_COL_NAME = {
    "image_url": {
        "name": "Image"},
    "city": {
        "name": "City"},
    "street_address": {
        "name": "Property Address"},
    "purchase_price": {
        "name": "Price"},
    "restimate": {
        "name": "Rent Estimate",
        "description": "Estimated monthly rent."},
    "year_built": {
        "name": "Year Built"},
    "home_type": {
        "name": "Home Type",
        "description": "Type of housing (e.g., Single Family, Townhouse)."},
    "bedrooms": {
        "name": "Bedrooms"},
    "bathrooms": {
        "name": "Bathrooms"},
    "zip_code": {
        "name": "Zip Code"},
    "gross_rent_multiplier": {
        "name": "Gross Rent Multiplier",
        "description": "The ratio of purchase price to annual rental income. A lower ratio indicates a potentially more profitable investment."},
    "page_view_count": {
        "name": "Times Viewed"},
    "favorite_count": {
        "name": "Favorite Count"},
    "days_on_zillow": {
        "name": "Days on Zillow"},
    "property_tax_rate": {
        "name": "Tax Rate (%)",
        "description": "Annual property tax rate."},
    "living_area": {
        "name": "Living Area (sq ft)",
        "description": "Interior space of the property."},
    "lot_size": {
        "name": "Lot Size (sq ft)",
        "description": "Total area of the property's lot."},
    "mortgage_rate": {
        "name": "Mortgage Rate",
        "description": "Interest rate on the mortgage."},
    "homeowners_insurance": {
        "name": "Home Insurance",
        "description": "Monthly cost of homeowners insurance."},
    "monthly_hoa": {
        "name": "HOA Fee",
        "description": "Monthly fee charged by the Homeowners Association."},
    "home_features_score": {
        "name": "Home Features Score",
        "description": "Score representing the quality and number of features."},
    "is_waterfront": {
        "name": "Waterfront",
        "description": "Indicates if the property is located next to a body of water."},
}

coc_description = 'The (annualized) rate of return on a real estate investment property based on the income that the property is expected to generate'
BACKEND_COL_NAME_TO_DYNAMIC_FRONTEND_COL_NAME = {
    # Down payment based keys.
    "rental_income": {
        "name": "Rental Income",
        "description": "The monthly income expected from renting the property, after deducting expenses like mortgage, HOA fees, and insurance."},
    "Beta": {
        "name": "Beta",
        "description": "This represents the purchase price at which the annualized rental income would yield a return comparable to half of the historical average returns of the S&P 500. This benchmark is used to assess the attractiveness of real estate investments relative to traditional stock market investments."},
    "Alpha": {
        "name": "Alpha",
        "description": "Alpha represents the active return of a property compared to the broader real estate market. It measures how much a property's value has deviated from the market average, adjusted for risk. A positive Alpha indicates that the property has appreciated more than the market average, likely due to favorable factors such as location, improvements, or unique market conditions. Conversely, a negative Alpha indicates that the property has underperformed relative to the market benchmark."},
    "breakeven_price": {
        "name": "Breakeven Price",
        "description": "This is the price at which owning the property becomes financially neutral each month, meaning the rental income exactly covers all expenses. It includes factors such as maintenance, HOA fees, mortgage costs, property taxes, and insurance, adjusted for typical vacancy rates. A breakeven price above the asking price suggests the property could generate positive cash flow at the listed price."},
    "is_breakeven_price_offending": {
        "name": "Is Breakeven Price Offending",
        "description": "Indicates whether the breakeven price is significantly lower than the listing price, specifically if it is less than 80% of the listed amount. This metric can be used to assess whether the price at which the property breaks even financially might be considered too low or 'offensive' in a standard real estate negotiation, suggesting a lower than expected value or profitability from the property."},
    "snp_equivalent_price": {
        "name": "Competative Price",
        "description": "The purchase price at which the annualized rental income is comporable to half the historical SnP 500 returns."},
    "CoC": {
        "name": "CoC",
        "description": f"{coc_description}."},
    "adj_CoC": {
        "name": "Adjusted CoC",
        "description": f"{coc_description}, adjusted for maintenance and vacancy rates."},
    "CoC_no_prepaids": {
        "name": "CoC w/o Prepaids",
        "description": f"{coc_description}, without prepaids."},
    "adj_CoC_no_prepaids": {
        "name": "Adjusted CoC w/o Prepaids",
        "description": f"{coc_description}, adjusted for maintenance and vacancy rates, and without prepaids."},
    "cap_rate": {
        "name": "Cap Rate",
        "description": "This is a key real estate valuation measure used to compare different real estate investments. It is calculated as the ratio of the annual rental income generated by the property to the purchase price or current market value, expressed as a percentage. It provides an indication of the potential return on investment."},
    "adj_cap_rate":  {
        "name": "Adjusted Cap Rate",
        "description": "Similar to the Cap Rate, but adjusted for factors like vacancy rates and ongoing maintenance costs, providing a more realistic measure of the property's potential return on investment after accounting for common expenses that reduce net income."},
}

# Function to construct a dictionary to map from the input names ot the descriptive ones.
def create_rename_dict():
    rename_dict = {}
    for old_name, props in BACKEND_COL_NAME_TO_FRONTEND_COL_NAME.items():
        rename_dict[old_name] = props['name']
    
    for old_name, props in BACKEND_COL_NAME_TO_DYNAMIC_FRONTEND_COL_NAME.items():
        rename_dict[old_name] = props['name']
        rename_dict[f"{old_name}_5%_down"] = f"{props['name']} (5% Down)"
    
    return rename_dict

def create_description_dict():
    description_dict = {}
    for props in BACKEND_COL_NAME_TO_FRONTEND_COL_NAME.values():
        if 'description' in props:
            description_dict[props['name']] = props['description']
    
    for props in BACKEND_COL_NAME_TO_DYNAMIC_FRONTEND_COL_NAME.values():
        if 'description' in props:
            description_dict[props['name']] = props['description']
            description_dict[f"{props['name']} (5% Down)"] = f"Given a 5% down payment... {props['description']}"
    
    return description_dict


def properties_df_from_search_request_data(request_data):
    region = request_data.get('region')
    home_type = request_data.get('home_type')
    year_built = int(request_data.get('year_built'))
    max_price = float(request_data.get('max_price'))
    city = request_data.get('city')
    is_waterfront = request_data.get('is_waterfront')
    is_cashflowing = bool(request_data.get('is_cashflowing'))

    properties_df = BACKEND_PROPERTIES_DF.copy()
    if region != "ANY_AREA":
        properties_df = properties_df[properties_df['zip_code'].isin(REGION_TO_ZIP_CODE[region])]
    if home_type != "ANY":
        properties_df = properties_df[properties_df['home_type'] == home_type]
    if year_built:
        properties_df = properties_df[properties_df['year_built'] >= year_built]
    if max_price:
        properties_df = properties_df[properties_df['purchase_price'] <= max_price]
    if is_waterfront:
        properties_df = properties_df[properties_df['is_waterfront'] == 'True']
    if is_cashflowing:
        properties_df = properties_df[properties_df['adj_CoC_5%_down'] >= 0.0]
    if city:
        properties_df = properties_df[properties_df['city'] == city.title()]

    return properties_df

def properties_response_from_properties_df(properties_df, num_properties_per_page=1, page=1, saved_zpids={}):
    num_properties_found = properties_df.shape[0]
    properties_df = properties_df.sort_values(by='adj_CoC_5%_down', ascending=False)
    # Calculate the total number of pages of listings in the backend to send to the frontend for the back/next buttons.
    total_pages = math.ceil(num_properties_found / num_properties_per_page)
    # We sort by CoC before filtering.
    start_property_index, stop_property_index = (page-1)*num_properties_per_page, page*num_properties_per_page
    properties_df = properties_df[start_property_index:stop_property_index]

    for zpid, _ in properties_df.iterrows():
        properties_df.loc[zpid, 'Save'] = zpid in saved_zpids
        properties_df.loc[zpid, 'zpid'] = zpid

    # Add the zpid as a column.
    properties_df.rename(columns=create_rename_dict(), inplace=True)

    if num_properties_found:
        ordered_cols = TARGET_COLUMNS + [col for col in properties_df.columns if col not in set(TARGET_COLUMNS)]
        ordered_properties_data = properties_df[ordered_cols].to_json(orient="records")
    else:
        ordered_properties_data = '{}'
    return {
        "properties": json.loads(ordered_properties_data),
        "descriptions": create_description_dict(),
        "total_properties": num_properties_found,
        "total_pages": total_pages,
    }
