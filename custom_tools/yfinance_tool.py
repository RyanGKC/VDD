import yfinance as yf
import pandas as pd
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def _df_to_markdown(df: pd.DataFrame) -> str:
    """Converts a pandas DataFrame to a markdown table string."""
    if df.empty:
        return ""
    # Reset index so the line item names (or dates) become a column
    df_reset = df.reset_index()
    # Format column names to strings (dates often become datetime objects)
    df_reset.columns = [str(col).split(" ")[0] for col in df_reset.columns]
    
    # Create the markdown table using pandas built-in markdown exporter
    return df_reset.to_markdown(index=False)

def get_company_info(ticker: str) -> Dict[str, Any]:
    """
    Fetches general company metadata (sector, industry, business summary, market cap).
    """
    logger.info(f"Fetching company info for: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        if not info or len(info) <= 1:
            return {"error": f"No company info found for ticker {ticker}. Please verify the ticker symbol."}
            
        # Extract the most useful fields to keep the payload size reasonable for LLMs
        keys_to_extract = [
            "shortName", "longName", "sector", "industry", 
            "longBusinessSummary", "marketCap", "currentPrice", 
            "currency", "exchange", "website"
        ]
        
        extracted_info = {k: info.get(k) for k in keys_to_extract if k in info}
        return {"ticker": ticker, "info": extracted_info}
        
    except Exception as e:
        logger.error(f"Error fetching company info for {ticker}: {e}")
        return {"error": str(e)}

def get_financial_statement(ticker: str, statement_type: str, annual: bool = True) -> Dict[str, Any]:
    """
    Fetches the core accounting statements.
    statement_type must be one of: 'income', 'balance_sheet', 'cash_flow'
    """
    logger.info(f"Fetching {statement_type} (annual={annual}) for: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        
        if statement_type == "income":
            df = stock.financials if annual else stock.quarterly_financials
        elif statement_type == "balance_sheet":
            df = stock.balance_sheet if annual else stock.quarterly_balance_sheet
        elif statement_type == "cash_flow":
            df = stock.cashflow if annual else stock.quarterly_cashflow
        else:
            return {"error": f"Invalid statement_type: {statement_type}. Must be 'income', 'balance_sheet', or 'cash_flow'."}
            
        if df.empty:
            return {"error": f"No financial data found for ticker {ticker} ({statement_type}). Please verify the ticker symbol."}
            
        markdown_table = _df_to_markdown(df)
        return {
            "ticker": ticker,
            "statement_type": statement_type,
            "annual": annual,
            "data_markdown": markdown_table
        }
        
    except Exception as e:
        logger.error(f"Error fetching {statement_type} for {ticker}: {e}")
        return {"error": str(e)}

def get_historical_prices(ticker: str, period: str = "1y") -> Dict[str, Any]:
    """
    Fetches historical price action. 
    Valid periods: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    """
    logger.info(f"Fetching historical prices ({period}) for: {ticker}")
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period=period)
        
        if df.empty:
            return {"error": f"No historical price data found for ticker {ticker}. Please verify the ticker symbol."}
            
        # We drop Dividends and Stock Splits to keep the table cleaner for LLMs
        if "Dividends" in df.columns:
            df = df.drop(columns=["Dividends"])
        if "Stock Splits" in df.columns:
            df = df.drop(columns=["Stock Splits"])
            
        markdown_table = _df_to_markdown(df)
        
        return {
            "ticker": ticker,
            "period": period,
            "data_markdown": markdown_table
        }
    except Exception as e:
        logger.error(f"Error fetching historical prices for {ticker}: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import json
    
    print("\n=== Testing Company Info ===")
    info = get_company_info("AAPL")
    print(json.dumps(info, indent=2))
    
    print("\n=== Testing Income Statement ===")
    income = get_financial_statement("AAPL", "income")
    if "data_markdown" in income:
        print(income["data_markdown"])
    else:
        print(income)
