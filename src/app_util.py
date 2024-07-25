import math
import os
import json
import pandas as pd
from pathlib import Path
from enum import Enum

from dynamic_re_metrics_processor import calculate_dynamic_metrics, calculate_series_metrics_df, calculate_monthly_costs, ZESTIMATE_HISTORY_DF, INDEX_DATA_DICT, RF_DATA


class Env(Enum):
    DEV = 1
    PROD = 2
env = Env.DEV if os.getenv('ENVIRONMENT') == "DEV" else Env.PROD

# Get the directory of the current file.
current_directory = Path(__file__).resolve().parent

# Construct the path to the data directory.
DATA_DIR = current_directory.parent / 'backend_data'

# Construct the paths to the data files.
PROPERTY_DF_PATH = DATA_DIR / 'property_static_df.parquet'
REGION_DATA_PATH = DATA_DIR / 'regions.json'


# Load data from files.
def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)

# Load static backend data.
BACKEND_PROPERTIES_DF = pd.read_parquet(PROPERTY_DF_PATH).round(2)
REGION_TO_ZIP_CODE = {region: set(zip_codes) for region, zip_codes in load_json(REGION_DATA_PATH).items()}

TARGET_COLUMNS = ['Image', 'Save', 'City', 'Rent Estimate', 'Price', 'Year Built', 'Home Type', 'Bedrooms', 'Bathrooms']
coc_description = 'The (annualized) rate of return on a real estate investment property based on the income that the property is expected to generate'
BACKEND_COL_NAME_TO_FRONTEND_COL_NAME = {
    "image_url": {"name": "Image"},
    "year_built": {"name": "Year Built"},
    "home_type": {"name": "Home Type", "description": "Type of housing (e.g., Single Family, Townhouse)."},
    "zip_code": {"name": "Zip Code"},
    "city": {"name": "City"},
    "street_address": {"name": "Property Address"},
    "living_area": {"name": "Living Area (sq ft)", "description": "Interior space of the property."},
    "lot_size": {"name": "Lot Size (sq ft)", "description": "Total area of the property's lot."},
    "bedrooms": {"name": "Bedrooms"},
    "bathrooms": {"name": "Bathrooms"},
    "purchase_price": {"name": "Price"},
    "monthly_restimate": {"name": "Rent Estimate", "description": "Estimated monthly rent."},
    "total_monthly_cost": {"name": "Total Monthly Cost", "description": "Sum of all monthly expenses, including mortgage payment, PMI, property tax, homeowners insurance, and HOA fees."},
    "gross_rent_multiplier": {"name": "Gross Rent Multiplier", "description": "The ratio of purchase price to annual rental income. A lower ratio indicates a potentially more profitable investment."},
    "annual_property_tax_rate": {"name": "Tax Rate (%)", "description": "Annual property tax rate."},
    "annual_mortgage_rate": {"name": "Mortgage Rate (%)", "description": "Annual interest rate on the mortgage."},
    "monthly_homeowners_insurance": {"name": "Home Insurance", "description": "Annual cost of homeowners insurance."},
    "monthly_hoa": {"name": "HOA Fee", "description": "Monthly fee charged by the Homeowners Association."},
    "home_features_score": {"name": "Home Features Score", "description": "Score representing the quality and number of features."},
    "is_waterfront": {"name": "Waterfront", "description": "Indicates if the property is located next to a body of water."},
    # Down payment dependent metrics.
    "breakeven_price": {"name": "Breakeven Price", "description": "This is the price at which owning the property becomes financially neutral each month, meaning the rental income exactly covers all expenses. It includes factors such as maintenance, HOA fees, mortgage costs, property taxes, and insurance, adjusted for typical vacancy rates. A breakeven price above the asking price suggests the property could generate positive cash flow at the listed price."},
    "is_breakeven_price_offending": {"name": "Is Breakeven Price Offending", "description": "Indicates whether the breakeven price is significantly lower than the listing price, specifically if it is less than 80% of the listed amount. This metric can be used to assess whether the price at which the property breaks even financially might be considered too low or 'offensive' in a standard real estate negotiation, suggesting a lower than expected value or profitability from the property."},
    "CoC": {"name": "CoC", "description": f"{coc_description}."},
    "adj_CoC": {"name": "Adjusted CoC", "description": f"{coc_description}, adjusted for maintenance and vacancy rates."},
    "CoC_no_prepaids": {"name": "CoC w/o Prepaids", "description": f"{coc_description}, without prepaids."},
    "adj_CoC_no_prepaids": {"name": "Adjusted CoC w/o Prepaids", "description": f"{coc_description}, adjusted for maintenance and vacancy rates, and without prepaids."},
    "monthly_rental_income": {"name": "Rental Income", "description": "The monthly income expected from renting the property, after deducting expenses like mortgage, HOA fees, and insurance."},
    "cap_rate": {"name": "Cap Rate", "description": "This is a key real estate valuation measure used to compare different real estate investments. It is calculated as the ratio of the annual rental income generated by the property to the purchase price or current market value, expressed as a percentage. It provides an indication of the potential return on investment."},
    "adj_cap_rate": {"name": "Adjusted Cap Rate", "description": "Similar to the Cap Rate, but adjusted for factors like vacancy rates and ongoing maintenance costs, providing a more realistic measure of the property's potential return on investment after accounting for common expenses that reduce net income."},
}

ADDITIONAL_DESCRIPTIONS = {
    "Alpha": "A measure of an investment's performance relative to a benchmark, representing the excess return. A positive alpha indicates outperformance.",
    "Beta": "A measure of an investment's volatility relative to the market. A beta greater than 1 indicates higher volatility than the market, while a beta less than 1 indicates lower volatility.",
    "Sharpe Ratio": "A measure of risk-adjusted return, calculated as the average excess return divided by the standard deviation of returns. Higher values indicate better risk-adjusted performance.",
    "Sortino Ratio": "A measure of risk-adjusted return that focuses on downside risk, calculated as the average excess return divided by the standard deviation of negative returns. Higher values indicate better risk-adjusted performance with a focus on downside risk.",
    "Max Drawdown (%)": "The largest peak-to-trough decline in the value of an investment, expressed as a fraction. Indicates the maximum loss from the highest value.",
    "Recovery Time (Days)": "The time, in days, taken for an investment to recover from its maximum drawdown to its previous peak value.",
    "Kendall Tau": "A measure of rank correlation between two variables, ranging from -1 to 1. Indicates the strength and direction of a monotonic relationship.",
    "Spearman Rho": "A measure of rank correlation between two variables, ranging from -1 to 1. Indicates the strength and direction of a monotonic relationship.",
}

FRONTEND_COL_NAME_TO_BACKEND_COL_NAME = {value["name"]: key for key, value in BACKEND_COL_NAME_TO_FRONTEND_COL_NAME.items()}

def create_rename_dict():
    rename_dict = {}
    for old_name, props in BACKEND_COL_NAME_TO_FRONTEND_COL_NAME.items():
        rename_dict[old_name] = props['name']
    return rename_dict

def create_description_dict():
    description_dict = {}
    for props in BACKEND_COL_NAME_TO_FRONTEND_COL_NAME.values():
        if 'description' in props:
            description_dict[props['name']] = props['description']
    for name, description in ADDITIONAL_DESCRIPTIONS.items():
        description_dict[name] = description
    return description_dict


def get_properties_from_attributes(property_attributes, page=1, properties_per_page=-1, calculate_series_metrics=False, filter_by_ids=set()):
    # Retrieve static metrics filtered by static metrics.
    filtered_properties_df = create_filtered_properties_from_static_attributes(property_attributes, filter_by_ids=filter_by_ids)

    # After filtering by static attributes, we filter by address since this is a more expensive string check.
    filter_by_address = property_attributes.get('property_address', '') or ''
    if filter_by_address:
        filtered_properties_df = filtered_properties_df[filtered_properties_df['street_address'].str.contains(filter_by_address, case=False, na=False)]

    # Calculate dynamic property metrics for properties which match the static attributes.
    down_payment_percentage = float(property_attributes.get('down_payment_percentage', 20) or 20) / 100
    override_annual_mortgage_rate = float(property_attributes.get('override_annual_mortgage_rate') or 'nan') if property_attributes.get('override_annual_mortgage_rate') else None
    filtered_properties_df = pd.concat([
        filtered_properties_df,
        calculate_dynamic_metrics(filtered_properties_df, down_payment_percentage, override_annual_mortgage_rate=override_annual_mortgage_rate).round(2)
    ], axis=1)

    # Since properties can be filtered by dynamic metrics, sort after constructing the full metrics df.
    sort_by = property_attributes.get('sortBy', 'CoC') or 'CoC'
    sort_order = property_attributes.get('sortOrder', 'asc') or 'asc'
    filtered_properties_df.sort_values(by=FRONTEND_COL_NAME_TO_BACKEND_COL_NAME[sort_by], ascending=(sort_order == 'asc'), inplace=True)

    num_filtered_properties = filtered_properties_df.shape[0]

    # Calculate series metrics after sorting by dynamic metrics we slice the target properties and calculate the
    if properties_per_page != -1:
        start_property_index, stop_property_index = (page - 1) * properties_per_page, page * properties_per_page
        filtered_properties_df = filtered_properties_df.iloc[start_property_index:stop_property_index].copy()
    if calculate_series_metrics:
        index_ticker = property_attributes.get('index_ticker', '^GSPC') or '^GSPC'
        filtered_properties_df = filtered_properties_df.merge(
            calculate_series_metrics_df(
                down_payment_percentage,
                ZESTIMATE_HISTORY_DF,
                filtered_properties_df['annual_mortgage_rate'],
                INDEX_DATA_DICT[index_ticker],
                RF_DATA,
                override_annual_mortgage_rate=override_annual_mortgage_rate,
                zpids=filtered_properties_df.index
            ).round(2),
            left_index=True,
            right_index=True,
            how='left'
        )
    
    filtered_properties_df['zpid'] = filtered_properties_df.index
    return filtered_properties_df, num_filtered_properties


def get_properties_response_from_attributes(property_attributes, filter_by_ids=set(), saved_ids=set()):
    page = int(property_attributes.get('current_page', 1)) or 1
    properties_per_page = int(property_attributes.get('num_properties_per_page', 1)) or 1
    is_advanced_search = property_attributes.get('is_advanced_search')

    properties_df, num_properties = get_properties_from_attributes(
        property_attributes,
        page=page,
        properties_per_page=properties_per_page,
        calculate_series_metrics=is_advanced_search,
        filter_by_ids=filter_by_ids
    )
    properties_df.rename(columns=create_rename_dict(), inplace=True)
    # We add a 'Saved' status after constructing the properties from the attributes since it is not universally used in calculations.
    properties_df['Save'] = properties_df.index.isin(saved_ids)
    

    num_pages = math.ceil(num_properties / properties_per_page)

    if num_properties:
        ordered_columns = TARGET_COLUMNS + [col for col in properties_df.columns if col not in set(TARGET_COLUMNS)]
        ordered_properties_data = properties_df[ordered_columns].to_json(orient="records")
    else:
        ordered_properties_data = '{}'

    return {
        "properties": json.loads(ordered_properties_data),
        "descriptions": create_description_dict(),
        "total_properties": num_properties,
        "total_pages": num_pages,
    }

def compare_properties_response_from_attributes(property_attributes):
    # Assuming 'list_id' is now part of each property's dictionary
    properties_df = pd.DataFrame(property_attributes.get('left_properties', []) + property_attributes.get('right_properties', []))
    properties_df['annual_mortgage_rate'] = property_attributes['annual_interest_rate']

    # Calculate individual property metrics
    properties_df['monthly_costs'], properties_df['cash_invested'], properties_df['prepaid_costs'] = zip(*properties_df.apply(
        lambda row: calculate_monthly_costs(row, row['down_payment_percentage'], row['annual_mortgage_rate']), axis=1))

    return properties_df


def create_filtered_properties_from_static_attributes(property_attributes, filter_by_ids=None):
    # House Options.
    home_type = property_attributes.get('home_type')

    min_price = int(property_attributes.get('min_price') or 0)
    max_price = int(property_attributes.get('max_price') or 0)

    min_year_built = int(property_attributes.get('min_year_built') or 0)
    max_year_built = int(property_attributes.get('max_year_built') or 0)

    min_bedrooms = int(property_attributes.get('min_bedrooms') or 0)
    max_bedrooms = int(property_attributes.get('max_bedrooms') or 0)

    min_bathrooms = int(property_attributes.get('min_bathrooms') or 0)
    max_bathrooms = int(property_attributes.get('max_bathrooms') or 0)

    is_waterfront = property_attributes.get('is_waterfront')

    # Location Options.
    region = property_attributes.get('region')
    city = property_attributes.get('city')

    # Advanced Options.
    is_cashflowing = property_attributes.get('is_cashflowing')

    # Initialize properties and filter by ids.
    properties_df = BACKEND_PROPERTIES_DF.copy()
    if filter_by_ids:
        properties_df = properties_df.loc[filter_by_ids]

    # Filter House Options.
    if home_type != "ANY":
        properties_df = properties_df[properties_df['home_type'] == home_type]
    if min_year_built:
        properties_df = properties_df[properties_df['year_built'] >= min_year_built]
    if max_year_built:
        properties_df = properties_df[properties_df['year_built'] <= max_year_built]
    if min_price:
        properties_df = properties_df[properties_df['purchase_price'] >= min_price]
    if max_price:
        properties_df = properties_df[properties_df['purchase_price'] <= max_price]
    if min_bedrooms:
        properties_df = properties_df[properties_df['bedrooms'] >= min_bedrooms]
    if max_bedrooms:
        properties_df = properties_df[properties_df['bedrooms'] <= max_bedrooms]
    if min_bathrooms:
        properties_df = properties_df[properties_df['bathrooms'] >= min_bathrooms]
    if max_bathrooms:
        properties_df = properties_df[properties_df['bathrooms'] <= max_bathrooms]
    if is_waterfront:
        properties_df = properties_df[properties_df['is_waterfront'] == 'True']
    
    # Filter Location Options.
    if region != "ANY_AREA":
        properties_df = properties_df[properties_df['zip_code'].isin(REGION_TO_ZIP_CODE[region])]
    if city:
        properties_df = properties_df[properties_df['city'] == city.title()]

    # Filter Advanced Options.
    if is_cashflowing:
        properties_df = properties_df[properties_df['monthly_rental_income'] >= 0.0]

    return properties_df
