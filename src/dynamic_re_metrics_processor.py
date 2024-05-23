import os
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
from copulas.bivariate import Frank, Clayton, Gumbel
from scipy.stats import kendalltau, spearmanr


# Constants
LOAN_TERM_YEARS = 30
MONTHS_IN_YEAR = 12
# Update from https://www.myfico.com/credit-education/calculators/loan-savings-calculator/ by FL state.
MIN_APR = 6.281
# Unfortunately FL is the highest state :<, expect 2% on average.
AVERAGE_HOME_INSURANCE_RATE = 0.02
# I've noticed that actual mortage rates are about 5% smaller.
PRINCIPAL_AND_INTEREST_DEDUCTION = 0.04
VACANCY_RATE = 0.1
MONTHLY_MAINTENANCE_RATE = 0.00017
CURRENT_MONTH = datetime.now().month
FIXED_FEES = {
    'credit_report_fee' : 35,
    # Between 325 and 425.
    'appraisal_fee' : 375,
    # Fee paid to certified flood inspector -> determines if flood insurance is required if in flood zone.
    'flood_life_of_loan_fee' : 20,
    # Required by lender to insure buyer pays property taxes (usually pro-rated).
    # Between 50 and 100.
    'tax_service_fee' : 85,
    # Paid to title or escrow company for services when closing.
    'closing_escrow_and_settlement_fees' : 750,
    # Charged for government agencies to record your deed, mortgage, and other necessarily registered documents.
    'recording_fee' : 225,
    'survey_fee' : 300
}
FIXED_FEE_TOTAL = sum(FIXED_FEES.values())
# This comes from https://www.newcastle.loans/mortgage-guide/mortgage-insurance-pmi
DOWN_PAYMENT_TO_ANNUAL_PMI_RATE = {0.03: 0.006, 0.05: 0.0045, 0.1: 0.003, 0.15: 0.0015, 0.2: 0}


# Get the directory of the current file.
current_directory = Path(__file__).resolve().parent
# Construct the path to the data directory.
DATA_DIR = current_directory.parent / 'backend_data'

# Construct the paths to the data files.
ZESTIMATE_HISTORY_DF_PATH = DATA_DIR / 'zestimate_history_df.parquet'
TIMESERIES_DATA_PATH = DATA_DIR / 'timeseries'


def load_zestimate_histories_parquet(path):
    return pd.read_parquet(path)
ZESTIMATE_HISTORY_DF = load_zestimate_histories_parquet(ZESTIMATE_HISTORY_DF_PATH)


MAX_DATA_AGE_DAYS = 1
INDEX_TICKERS = {
    # Known for consistent dividends, making it a solid choice for income-focused investors.
    'Realty Income': 'O',
    # Largest industrial REIT, benefiting from the growth of e-commerce.
    'Prologis': 'PLD',
    # Specializes in cell towers, benefiting from 5G expansion.
    'American Tower': 'AMT',
    # Focused on healthcare properties, an essential sector.
    'Welltower': 'WELL',
    # Largest retail REIT, providing exposure to commercial real estate.
    'Simon Property Group': 'SPG',
    # Broad market index for overall market comparison.
    'S&P 500': '^GSPC',
    # Represents an alternative investment class for comparison.
    'Bitcoin': 'BTC-USD'
}
# 13 WEEK TREASURY BILL '^IRX'
RF_TICKER = '^IRX'


def download_data(ticker):
    data = yf.download(ticker, progress=False)
    data.index = data.index.tz_localize(None)
    return data

def save_data_to_disk(data, path):
    data.to_csv(path)

def load_data_from_disk(path):
    return pd.read_csv(path, index_col=0, parse_dates=True)

def is_data_fresh(path):
    if not os.path.exists(path):
        return False
    file_mod_time = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - file_mod_time < timedelta(days=MAX_DATA_AGE_DAYS)

def update_data_if_needed(ticker, path):
    if not is_data_fresh(path):
        data = download_data(ticker)
        data = clean_and_sort_index_data(data)  # Clean and sort before saving
        save_data_to_disk(data, path)
    return load_data_from_disk(path)

def clean_and_sort_index_data(index_data):
    # Remove rows with NaN values in critical columns
    index_data.dropna(subset=['Adj Close'], inplace=True)
    # Ensure the index is a DatetimeIndex
    index_data.index = pd.to_datetime(index_data.index)
    # Sort by the index
    index_data.sort_index(inplace=True)
    return index_data

def initialize_data():
    index_data_dict = {}
    for _, ticker in INDEX_TICKERS.items():
        path = os.path.join(TIMESERIES_DATA_PATH, f'{ticker}_data.csv')
        index_data = update_data_if_needed(ticker, path)
        index_data_dict[ticker] = index_data
    
    rf_data_path = os.path.join(TIMESERIES_DATA_PATH, f'{RF_TICKER}_data.csv')
    rf_data = update_data_if_needed(RF_TICKER, rf_data_path)
    rf_data['Risk Free Rate'] = rf_data['Adj Close'].apply(lambda x: deannualize(x / 100))
    rf_data = clean_and_sort_index_data(rf_data)
    return index_data_dict, rf_data[['Risk Free Rate']]

def deannualize(annual_rate, periods=365):
    return (1 + annual_rate) ** (1 / periods) - 1

INDEX_DATA_DICT, RF_DATA = initialize_data()



def calculate_purchase_fees(purchase_price, down_payment):
    FLORIDA_ORIGINATION_FEE_RATE = 0.0075
    FLORIDA_LENDERS_TITLE_INSURANCE_BASE_FEE = 575
    FLORIDA_OWNERS_TITLE_INSURANCE_BASE_FEE = 40
    FLORIDA_OWNERS_TITLE_INSURANCE_RATE = 2.4411138235
    FLORIDA_MORTGAGES_TAX_RATE = 0.0035
    FLORIDA_DEEDS_TAX_RATE = 0.007
    FLORIDA_INTANGIBLE_TAX_RATE = 0.002

    origination_fee = FLORIDA_ORIGINATION_FEE_RATE * purchase_price
    lenders_title_insurance_fee = np.where(
        purchase_price >= 100000,
        FLORIDA_LENDERS_TITLE_INSURANCE_BASE_FEE + 5 * ((purchase_price - 100000) / 1000),
        FLORIDA_LENDERS_TITLE_INSURANCE_BASE_FEE
    )
    owners_title_insurance_fee = np.where(
        purchase_price >= 100000,
        FLORIDA_OWNERS_TITLE_INSURANCE_BASE_FEE + FLORIDA_OWNERS_TITLE_INSURANCE_RATE * ((purchase_price - 100000) / 1000),
        FLORIDA_OWNERS_TITLE_INSURANCE_BASE_FEE
    )
    financed_amount = purchase_price * (1 - down_payment)
    state_and_stamps_tax = (FLORIDA_MORTGAGES_TAX_RATE + FLORIDA_DEEDS_TAX_RATE) * financed_amount
    intangible_tax = FLORIDA_INTANGIBLE_TAX_RATE * financed_amount

    total_fees = origination_fee + lenders_title_insurance_fee + owners_title_insurance_fee + state_and_stamps_tax + intangible_tax
    return total_fees

def calculate_monthly_mortgage_rate(annual_mortgage_rate, loan_term_years=30):
    monthly_mortgage_rate = annual_mortgage_rate / MONTHS_IN_YEAR
    n_payments = loan_term_years * MONTHS_IN_YEAR
    mortgage_rate = np.where(
        annual_mortgage_rate == 0,
        0,
        (monthly_mortgage_rate * (1 + monthly_mortgage_rate) ** n_payments) * (1 - PRINCIPAL_AND_INTEREST_DEDUCTION) / ((1 + monthly_mortgage_rate) ** n_payments - 1)
    )
    return mortgage_rate

def get_annual_pmi_rate(down_payment_percentage):
    if down_payment_percentage >= 0.2: return 0
    
    down_payments = sorted(DOWN_PAYMENT_TO_ANNUAL_PMI_RATE.keys())
    highest_pmi_rate = DOWN_PAYMENT_TO_ANNUAL_PMI_RATE[down_payments[0]]
    if down_payment_percentage < down_payments[0]: return highest_pmi_rate

    # Use numpy interpolation for efficiency
    pmi_rates = [DOWN_PAYMENT_TO_ANNUAL_PMI_RATE[dp] for dp in down_payments]
    interpolated_pmi_rate = np.interp(down_payment_percentage, down_payments, pmi_rates)
    return interpolated_pmi_rate

def purchase_price_from_cash_flow_percentage(purchase_price, down_payment_percentage, monthly_restimate, monthly_hoa, monthly_homeowners_insurance, annual_mortgage_rate, annual_property_tax_rate, annual_cash_flow_rate=0):
    monthly_cost_rate = (MONTHLY_MAINTENANCE_RATE +
                (get_annual_pmi_rate(down_payment_percentage) / MONTHS_IN_YEAR) * (1 - down_payment_percentage) +
                calculate_monthly_mortgage_rate(annual_mortgage_rate) +
                (annual_property_tax_rate / MONTHS_IN_YEAR) +
                (monthly_homeowners_insurance / purchase_price))
    return (monthly_restimate * (1 - VACANCY_RATE) - monthly_hoa) / (monthly_cost_rate + (annual_cash_flow_rate / MONTHS_IN_YEAR))

def calculate_monthly_costs(df, down_payment_percentage):
    down_payment = df['purchase_price'] * down_payment_percentage
    loan_amount = df['purchase_price'] - down_payment
    
    monthly_mortgage_payment = loan_amount * calculate_monthly_mortgage_rate(df['annual_mortgage_rate'] / 100)
    monthly_property_tax = (df['purchase_price'] * df['annual_property_tax_rate'] / 100) / MONTHS_IN_YEAR
    monthly_pmi = df['purchase_price'] * get_annual_pmi_rate(down_payment_percentage) / MONTHS_IN_YEAR
    monthly_costs = (
        monthly_mortgage_payment + 
        monthly_pmi + 
        monthly_property_tax + 
        df['monthly_homeowners_insurance'] + 
        df['monthly_hoa']
    )

    prepaid_real_estate_tax_escrow = monthly_property_tax * CURRENT_MONTH
    prepaid_insurance_escrow = df['monthly_homeowners_insurance'] * CURRENT_MONTH
    prepaid_costs = prepaid_real_estate_tax_escrow + prepaid_insurance_escrow

    cash_invested = (
        down_payment + 
        FIXED_FEE_TOTAL + 
        prepaid_costs + 
        calculate_purchase_fees(df['purchase_price'], down_payment_percentage)
    )
    return monthly_costs, cash_invested, prepaid_costs

def calculate_dynamic_metrics(df, down_payment_percentage):
    monthly_costs, cash_invested, prepaid_costs = calculate_monthly_costs(df, down_payment_percentage)

    monthly_rental_income = df['monthly_restimate'] * (1 - VACANCY_RATE) - monthly_costs - (MONTHLY_MAINTENANCE_RATE * df['purchase_price'])
    breakeven_purchase_price = purchase_price_from_cash_flow_percentage(
        df['purchase_price'], down_payment_percentage, df['monthly_restimate'],
        df['monthly_hoa'], df['monthly_homeowners_insurance'], df['annual_mortgage_rate'] / 100,
        df['annual_property_tax_rate'] / 100
    )

    is_breakeven_price_offending = np.abs(df['purchase_price'] - breakeven_purchase_price) > 0.2 * df['purchase_price']

    metrics = pd.DataFrame({
        'monthly_rental_income': monthly_rental_income,
        'breakeven_price': breakeven_purchase_price,
        'is_breakeven_price_offending': np.where(is_breakeven_price_offending, "True", "False"),
        'CoC_no_prepaids': MONTHS_IN_YEAR * monthly_rental_income / cash_invested,
        'CoC': MONTHS_IN_YEAR * monthly_rental_income / (cash_invested - prepaid_costs),
        'adj_CoC_no_prepaids': MONTHS_IN_YEAR * monthly_rental_income / cash_invested,
        'adj_CoC': MONTHS_IN_YEAR * monthly_rental_income / (cash_invested - prepaid_costs),
        'cap_rate': MONTHS_IN_YEAR * monthly_rental_income / df['purchase_price'],
        'adj_cap_rate': MONTHS_IN_YEAR * monthly_rental_income / df['purchase_price']
    })
    return metrics


def calculate_series_metrics_df(down_payment_percentage, zestimate_histories_df, index_df, rf_df, zpids=None, simplified=False, logger=None, ignore_nonlinear=False, var_confidence_level=0.95):
    # Define metric keys
    metric_keys = ['Alpha', 'Beta', 'Sharpe Ratio', 'Sortino Ratio', 'Max Drawdown (%)', 'Recovery Time (Days)', 'Kendall Tau', 'Spearman Rho', 'Historical VaR']
    
    # Check for missing zpids
    provided_zpids_set = set(zpids) if zpids is not None else set()
    available_zpids_set = set(zestimate_histories_df['zpid'].unique())
    missing_zpids = provided_zpids_set - available_zpids_set
    
    # Prepare reasons for missing zpids
    missing_zpids_reasons = {zpid: {key: 'Missing zestimate history' for key in metric_keys} for zpid in missing_zpids}

    # Filter for zpids if provided
    if zpids is not None and len(zpids) > 0:
        zestimate_histories_df = zestimate_histories_df[zestimate_histories_df['zpid'].isin(zpids)]

    # Initialize a DataFrame to keep track of reasons for zpids filtered out during processing
    filtered_out_zpids_reasons = {}

    def append_filtered_out_zpids(zpids, reason):
        for zpid in zpids:
            filtered_out_zpids_reasons[zpid] = {key: reason for key in metric_keys}

    # Check if the filtered zestimate_histories_df is empty
    if zestimate_histories_df.empty:
        result_df = pd.DataFrame.from_dict(missing_zpids_reasons, orient='index')
        return result_df

    # Align dates based on the earliest date in the price series
    start_date = zestimate_histories_df.index.min()
    index_df = index_df.loc[start_date:]
    rf_df = rf_df.loc[start_date:]

    # Perform the merges
    aligned_df = pd.merge_asof(zestimate_histories_df.reset_index(), index_df[['Adj Close']].reset_index(), on='Date', direction='nearest')
    aligned_df = pd.merge_asof(aligned_df, rf_df[['Risk Free Rate']].reset_index(), on='Date', direction='nearest')

    # Check if the aligned DataFrame is empty
    if aligned_df.empty:
        result_df = pd.DataFrame.from_dict(missing_zpids_reasons, orient='index')
        return result_df

    # Calculate price returns and handle mortgage payments
    if simplified:
        aligned_df['Price Returns'] = aligned_df.groupby('zpid')['Price'].pct_change(fill_method=None)
    else:
        initial_price = aligned_df.groupby('zpid')['Price'].transform('first')
        down_payment_amount = initial_price * down_payment_percentage
        loan_amount = initial_price - down_payment_amount
        monthly_mortgage_payment = loan_amount * MIN_APR / MONTHS_IN_YEAR

        aligned_df['Cumulative Mortgage Payments'] = monthly_mortgage_payment.groupby(aligned_df['zpid']).cumsum()
        aligned_df['Equity'] = aligned_df['Price'] - loan_amount + down_payment_amount - aligned_df['Cumulative Mortgage Payments']
        aligned_df['Price Returns'] = aligned_df.groupby('zpid')['Equity'].pct_change()

    # Calculate stock returns and set index
    aligned_df['Stock Returns'] = aligned_df['Adj Close'].pct_change(fill_method=None)
    aligned_df.set_index('Date', inplace=True)

    # Track zpids before dropping NaNs
    zpids_before_dropping_na = set(aligned_df['zpid'].unique())

    # Drop NaN values from returns
    aligned_df.dropna(subset=['Price Returns', 'Stock Returns'], inplace=True)

    # Identify zpids that were filtered out due to NaN values
    zpids_after_dropping_na = set(aligned_df['zpid'].unique())
    filtered_out_due_to_nan = zpids_before_dropping_na - zpids_after_dropping_na
    append_filtered_out_zpids(filtered_out_due_to_nan, 'Insufficient data after dropping NaNs')

    # Check if aligned_df is empty after dropping NaNs
    if aligned_df.empty:
        result_df = pd.DataFrame.from_dict({**missing_zpids_reasons, **filtered_out_zpids_reasons}, orient='index')
        return result_df

    # Adjust returns by subtracting the risk-free rate
    aligned_df['Excess Price Returns'] = aligned_df['Price Returns'] - aligned_df['Risk Free Rate']
    aligned_df['Excess Stock Returns'] = aligned_df['Stock Returns'] - aligned_df['Risk Free Rate']

    def calculate_series_metrics(group):
        metrics = {
            'Alpha': '', 'Beta': '', 'Sharpe Ratio': '', 'Sortino Ratio': '',
            'Max Drawdown (%)': '', 'Recovery Time (Days)': '', 'Kendall Tau': '', 'Spearman Rho': '',
            'Historical VaR': ''
        }

        # Check for sufficient data points
        if len(group) < 2:
            return pd.Series({key: 'Insufficient data points' for key in metrics})

        # Extract and reshape the returns
        price_returns = group['Excess Price Returns'].dropna().values.reshape(-1, 1)
        stock_returns = group['Excess Stock Returns'].dropna().values.reshape(-1, 1)

        # Ensure sufficient data remains after dropping NaNs
        if len(price_returns) < 2 or len(stock_returns) < 2:
            return pd.Series({key: 'Insufficient data after dropping NaNs' for key in metrics})
        
        # Check for variability in returns to avoid degenerate regression
        if np.std(stock_returns) == 0 or np.std(price_returns) == 0:
            return pd.Series({key: 'Insufficient variance in returns' for key in metrics})
        
        alpha, beta = np.nan, np.nan

        # Check for extreme values with a guard against division by zero for alpha and beta calculations only
        extreme_values_detected = False
        if (np.min(stock_returns) != 0 and np.max(stock_returns) / np.min(stock_returns) > 10) or \
           (np.min(price_returns) != 0 and np.max(price_returns) / np.min(price_returns) > 10):
            extreme_values_detected = True
            metrics['Alpha'], metrics['Beta'] = 'Extreme values detected', 'Extreme values detected'

        if not extreme_values_detected:
            # Perform the linear regression for alpha and beta
            reg = LinearRegression().fit(stock_returns, price_returns)
            beta = reg.coef_[0][0]
            alpha = reg.intercept_[0]

            # Check for non-linear patterns (large deviations can be considered non-linear)
            residuals = price_returns - reg.predict(stock_returns)
            if np.std(residuals) / np.std(price_returns) > 0.5:
                metrics['Alpha'], metrics['Beta'] = 'Non-linear pattern detected', 'Non-linear pattern detected'
            else:
                metrics['Alpha'], metrics['Beta'] = round(alpha, 8), round(beta, 8)

        # Calculate Sharpe Ratio
        mean_excess_return = np.mean(group['Excess Price Returns'])
        std_excess_return = np.std(group['Excess Price Returns'])
        if std_excess_return != 0:
            sharpe_ratio = mean_excess_return / std_excess_return
            metrics['Sharpe Ratio'] = round(sharpe_ratio, 8)
        else:
            metrics['Sharpe Ratio'] = 'Zero standard deviation in returns'

        # Calculate Sortino Ratio
        downside_std = np.std(group['Excess Price Returns'][group['Excess Price Returns'] < 0])
        if downside_std != 0:
            sortino_ratio = mean_excess_return / downside_std
            metrics['Sortino Ratio'] = round(sortino_ratio, 8)
        else:
            metrics['Sortino Ratio'] = 'Zero downside deviation in returns'

        # Calculate maximum drawdown using cumulative returns
        cumulative_return = (1 + group['Price Returns']).cumprod()
        peak = cumulative_return.cummax()
        drawdown = (cumulative_return - peak) / peak
        max_drawdown = drawdown.min()
        
        if max_drawdown == 0:
            metrics['Max Drawdown (%)'] = 'No drawdown detected'
            metrics['Recovery Time (Days)'] = 'No drawdown detected'
        else:
            metrics['Max Drawdown (%)'] = round(abs(max_drawdown) * 100, 2)

            # Calculate recovery time
            recovery_time = np.nan
            if max_drawdown < 0:
                trough_date = drawdown.idxmin()
                recovery_dates = group[trough_date:].index[cumulative_return[trough_date:] >= peak[trough_date]]
                if not recovery_dates.empty:
                    recovery_date = recovery_dates[0]
                    recovery_time = (recovery_date - trough_date).days
            metrics['Recovery Time (Days)'] = round(recovery_time, 8) if not np.isnan(recovery_time) else 'Recovery not achieved'

        # Calculate copula-based metrics
        price_returns_flat = group['Excess Price Returns'].dropna().values
        stock_returns_flat = group['Excess Stock Returns'].dropna().values
        
        kendall_tau, _ = kendalltau(price_returns_flat, stock_returns_flat)
        metrics['Kendall Tau'] = round(kendall_tau, 8)
        spearman_rho, _ = spearmanr(price_returns_flat, stock_returns_flat)
        metrics['Spearman Rho'] = round(spearman_rho, 8)

        # Calculate Historical VaR
        historical_var = -np.percentile(price_returns_flat, (1 - var_confidence_level) * 100)
        metrics['Historical VaR'] = round(historical_var, 8)
        
        return pd.Series(metrics)

    # Group by zpid and apply the metrics calculation
    result_df = aligned_df.groupby('zpid').apply(calculate_series_metrics)

    # Include reasons for missing zpids and filtered out zpids
    final_result_df = pd.concat([result_df, pd.DataFrame.from_dict({**missing_zpids_reasons, **filtered_out_zpids_reasons}, orient='index')])

    return final_result_df
    


if __name__ == '__main__':
    print('zestimate data: ')
    print(ZESTIMATE_HISTORY_DF.shape, ZESTIMATE_HISTORY_DF.index.name)
    print(ZESTIMATE_HISTORY_DF.head(), ZESTIMATE_HISTORY_DF.tail())
    print(ZESTIMATE_HISTORY_DF.columns, ZESTIMATE_HISTORY_DF.shape)

    print('rf data: ')
    print(RF_DATA.shape, RF_DATA.index.name)
    print(RF_DATA.head(), RF_DATA.tail())
    print(RF_DATA.columns, RF_DATA.shape)

    print('examp index data: ')
    print(INDEX_DATA_DICT['O'].shape, INDEX_DATA_DICT['O'].index.name)
    print(INDEX_DATA_DICT['O'].head(), INDEX_DATA_DICT['O'].tail())
    print(INDEX_DATA_DICT['O'].columns, INDEX_DATA_DICT['O'].shape)
