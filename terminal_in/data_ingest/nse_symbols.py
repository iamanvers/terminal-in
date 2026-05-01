"""
NSE equity symbol registry.

Loads from terminal_in/data/nse_equity_list.csv if present.
To get full 2000+ symbol coverage, save EQUITY_L.csv from NSE as:
    terminal_in/data/nse_equity_list.csv

Embedded fallback: ~200 key Nifty-500 symbols for offline use.
"""

import logging
from pathlib import Path

log = logging.getLogger(__name__)

_CSV_PATH = Path(__file__).parent.parent / 'data' / 'nse_equity_list.csv'

# symbol → (full_name, series)
_REGISTRY: dict[str, tuple[str, str]] = {}

# ── Embedded key symbols (Nifty 50 + key midcaps) ───────────────────────────
_EMBEDDED: dict[str, tuple[str, str]] = {
    # Nifty 50
    "RELIANCE":    ("Reliance Industries Limited", "EQ"),
    "TCS":         ("Tata Consultancy Services Limited", "EQ"),
    "HDFCBANK":    ("HDFC Bank Limited", "EQ"),
    "ICICIBANK":   ("ICICI Bank Limited", "EQ"),
    "INFY":        ("Infosys Limited", "EQ"),
    "SBIN":        ("State Bank of India", "EQ"),
    "HINDUNILVR":  ("Hindustan Unilever Limited", "EQ"),
    "BAJFINANCE":  ("Bajaj Finance Limited", "EQ"),
    "BHARTIARTL":  ("Bharti Airtel Limited", "EQ"),
    "KOTAKBANK":   ("Kotak Mahindra Bank Limited", "EQ"),
    "AXISBANK":    ("Axis Bank Limited", "EQ"),
    "LT":          ("Larsen & Toubro Limited", "EQ"),
    "WIPRO":       ("Wipro Limited", "EQ"),
    "HCLTECH":     ("HCL Technologies Limited", "EQ"),
    "ASIANPAINT":  ("Asian Paints Limited", "EQ"),
    "SUNPHARMA":   ("Sun Pharmaceutical Industries Limited", "EQ"),
    "TITAN":       ("Titan Company Limited", "EQ"),
    "MARUTI":      ("Maruti Suzuki India Limited", "EQ"),
    "ULTRACEMCO":  ("UltraTech Cement Limited", "EQ"),
    "NESTLEIND":   ("Nestle India Limited", "EQ"),
    "NTPC":        ("NTPC Limited", "EQ"),
    "POWERGRID":   ("Power Grid Corporation of India Limited", "EQ"),
    "TATASTEEL":   ("Tata Steel Limited", "EQ"),
    "JSWSTEEL":    ("JSW Steel Limited", "EQ"),
    "HINDALCO":    ("Hindalco Industries Limited", "EQ"),
    "ADANIENT":    ("Adani Enterprises Limited", "EQ"),
    "ADANIPORTS":  ("Adani Ports and Special Economic Zone Limited", "EQ"),
    "BAJAJFINSV":  ("Bajaj Finserv Limited", "EQ"),
    "TECHM":       ("Tech Mahindra Limited", "EQ"),
    "INDUSINDBK":  ("IndusInd Bank Limited", "EQ"),
    "TATAMOTORS":  ("Tata Motors Limited", "EQ"),
    "ONGC":        ("Oil & Natural Gas Corporation Limited", "EQ"),
    "COALINDIA":   ("Coal India Limited", "EQ"),
    "BPCL":        ("Bharat Petroleum Corporation Limited", "EQ"),
    "DIVISLAB":    ("Divi's Laboratories Limited", "EQ"),
    "DRREDDY":     ("Dr. Reddy's Laboratories Limited", "EQ"),
    "CIPLA":       ("Cipla Limited", "EQ"),
    "APOLLOHOSP":  ("Apollo Hospitals Enterprise Limited", "EQ"),
    "EICHERMOT":   ("Eicher Motors Limited", "EQ"),
    "BRITANNIA":   ("Britannia Industries Limited", "EQ"),
    "HEROMOTOCO":  ("Hero MotoCorp Limited", "EQ"),
    "TATACONSUM":  ("TATA CONSUMER PRODUCTS LIMITED", "EQ"),
    "ITC":         ("ITC Limited", "EQ"),
    "GRASIM":      ("Grasim Industries Limited", "EQ"),
    "BAJAJ-AUTO":  ("Bajaj Auto Limited", "EQ"),
    "TATAPOWER":   ("Tata Power Company Limited", "EQ"),
    "TATACHEM":    ("Tata Chemicals Limited", "EQ"),
    "TATAELXSI":   ("Tata Elxsi Limited", "EQ"),
    # Banks
    "HDFCLIFE":    ("HDFC Life Insurance Company Limited", "EQ"),
    "SBICARD":     ("SBI Cards and Payment Services Limited", "EQ"),
    "SBILIFE":     ("SBI Life Insurance Company Limited", "EQ"),
    "ICICIGI":     ("ICICI Lombard General Insurance Company Limited", "EQ"),
    "ICICIPRULI":  ("ICICI Prudential Life Insurance Company Limited", "EQ"),
    "FEDERALBNK":  ("The Federal Bank Limited", "EQ"),
    "RBLBANK":     ("RBL Bank Limited", "EQ"),
    "BANDHANBNK":  ("Bandhan Bank Limited", "EQ"),
    "IDFCFIRSTB":  ("IDFC First Bank Limited", "EQ"),
    "AUBANK":      ("AU Small Finance Bank Limited", "EQ"),
    "YESBANK":     ("Yes Bank Limited", "EQ"),
    "PNB":         ("Punjab National Bank", "EQ"),
    "BANKBARODA":  ("Bank of Baroda", "EQ"),
    "CANBK":       ("Canara Bank", "EQ"),
    "UNIONBANK":   ("Union Bank of India", "EQ"),
    # IT / Tech
    "HDFCAMC":     ("HDFC Asset Management Company Limited", "EQ"),
    "MPHASIS":     ("MphasiS Limited", "EQ"),
    "PERSISTENT":  ("Persistent Systems Limited", "EQ"),
    "COFORGE":     ("Coforge Limited", "EQ"),
    "LTTS":        ("L&T Technology Services Limited", "EQ"),
    "ZENSARTECH":  ("Zensar Technologies Limited", "EQ"),
    "MINDTREE":    ("MindTree Limited", "EQ"),
    "KPITTECH":    ("KPIT Technologies Limited", "EQ"),
    "OFSS":        ("Oracle Financial Services Software Limited", "EQ"),
    "ECLERX":      ("eClerx Services Limited", "EQ"),
    # Pharma / Healthcare
    "AUROPHARMA":  ("Aurobindo Pharma Limited", "EQ"),
    "LUPIN":       ("Lupin Limited", "EQ"),
    "GLENMARK":    ("Glenmark Pharmaceuticals Limited", "EQ"),
    "IPCALAB":     ("IPCA Laboratories Limited", "EQ"),
    "ALKEM":       ("Alkem Laboratories Limited", "EQ"),
    "LAURUSLABS":  ("Laurus Labs Limited", "EQ"),
    "TORNTPHARM":  ("Torrent Pharmaceuticals Limited", "EQ"),
    "NATCOPHARM":  ("Natco Pharma Limited", "EQ"),
    "SYNGENE":     ("Syngene International Limited", "EQ"),
    "LALPATHLAB":  ("Dr. Lal Path Labs Ltd.", "EQ"),
    "THYROCARE":   ("Thyrocare Technologies Limited", "EQ"),
    "METROPOLIS":  ("Metropolis Healthcare Limited", "EQ"),
    # Auto
    "TVSMOTOR":    ("TVS Motor Company Limited", "EQ"),
    "BOSCHLTD":    ("Bosch Limited", "EQ"),
    "MOTHERSUMI":  ("Motherson Sumi Systems Limited", "EQ"),
    "APOLLOTYRE":  ("Apollo Tyres Limited", "EQ"),
    "CEATLTD":     ("CEAT Limited", "EQ"),
    "ESCORTS":     ("Escorts Limited", "EQ"),
    "MAHINDCIE":   ("Mahindra CIE Automotive Limited", "EQ"),
    "TIINDIA":     ("Tube Investments of India Limited", "EQ"),
    # FMCG / Consumer
    "DABUR":       ("Dabur India Limited", "EQ"),
    "MARICO":      ("Marico Limited", "EQ"),
    "GODREJCP":    ("Godrej Consumer Products Limited", "EQ"),
    "EMAMILTD":    ("Emami Limited", "EQ"),
    "COLPAL":      ("Colgate Palmolive (India) Limited", "EQ"),
    "PGHH":        ("Procter & Gamble Hygiene and Health Care Limited", "EQ"),
    "JYOTHYLAB":   ("Jyothy Labs Limited", "EQ"),
    "VBL":         ("Varun Beverages Limited", "EQ"),
    "UBL":         ("United Breweries Limited", "EQ"),
    # Infrastructure / Capital Goods
    "ABB":         ("ABB India Limited", "EQ"),
    "SIEMENS":     ("Siemens Limited", "EQ"),
    "BHEL":        ("Bharat Heavy Electricals Limited", "EQ"),
    "KEC":         ("KEC International Limited", "EQ"),
    "KALPATPOWR":  ("Kalpataru Power Transmission Limited", "EQ"),
    "THERMAX":     ("Thermax Limited", "EQ"),
    "CUMMINSIND":  ("Cummins India Limited", "EQ"),
    "GRINDWELL":   ("Grindwell Norton Limited", "EQ"),
    "ELGIEQUIP":   ("Elgi Equipments Limited", "EQ"),
    "HAL":         ("Hindustan Aeronautics Limited", "EQ"),
    "BEL":         ("Bharat Electronics Limited", "EQ"),
    "BDL":         ("Bharat Dynamics Limited", "EQ"),
    # Real Estate
    "DLF":         ("DLF Limited", "EQ"),
    "GODREJPROP":  ("Godrej Properties Limited", "EQ"),
    "OBEROIRLTY":  ("Oberoi Realty Limited", "EQ"),
    "PHOENIXLTD":  ("The Phoenix Mills Limited", "EQ"),
    "PRESTIGE":    ("Prestige Estates Projects Limited", "EQ"),
    "SOBHA":       ("Sobha Limited", "EQ"),
    "BRIGADE":     ("Brigade Enterprises Limited", "EQ"),
    "MAHLIFE":     ("Mahindra Lifespace Developers Limited", "EQ"),
    # Cement
    "SHREECEM":    ("SHREE CEMENT LIMITED", "EQ"),
    "AMBUJACEM":   ("Ambuja Cements Limited", "EQ"),
    "ACC":         ("ACC Limited", "EQ"),
    "RAMCOCEM":    ("The Ramco Cements Limited", "EQ"),
    "DALBHARAT":   ("Dalmia Bharat Limited", "EQ"),
    "JKCEMENT":    ("JK Cement Limited", "EQ"),
    "HEIDELBERG":  ("HeidelbergCement India Limited", "EQ"),
    # Metals / Mining
    "VEDL":        ("Vedanta Limited", "EQ"),
    "HINDZINC":    ("Hindustan Zinc Limited", "EQ"),
    "NATIONALUM":  ("National Aluminium Company Limited", "EQ"),
    "HINDCOPPER":  ("Hindustan Copper Limited", "EQ"),
    "NMDC":        ("NMDC Limited", "EQ"),
    "SAIL":        ("Steel Authority of India Limited", "EQ"),
    "MOIL":        ("MOIL Limited", "EQ"),
    # Energy / Power
    "TORNTPOWER":  ("Torrent Power Limited", "EQ"),
    "TATAPOWER":   ("Tata Power Company Limited", "EQ"),
    "ADANIGREEN":  ("Adani Green Energy Limited", "EQ"),
    "ADANIPOWER":  ("Adani Power Limited", "EQ"),
    "CESC":        ("CESC Limited", "EQ"),
    "SJVN":        ("SJVN Limited", "EQ"),
    "NHPC":        ("NHPC Limited", "EQ"),
    "GAIL":        ("GAIL (India) Limited", "EQ"),
    "IGL":         ("Indraprastha Gas Limited", "EQ"),
    "MGL":         ("Mahanagar Gas Limited", "EQ"),
    "PETRONET":    ("Petronet LNG Limited", "EQ"),
    # Financials / NBFCs
    "BAJAJHLDNG":  ("Bajaj Holdings & Investment Limited", "EQ"),
    "M&MFIN":      ("Mahindra & Mahindra Financial Services Limited", "EQ"),
    "CHOLAFIN":    ("Cholamandalam Investment and Finance Company Limited", "EQ"),
    "MANAPPURAM":  ("Manappuram Finance Limited", "EQ"),
    "MUTHOOTFIN":  ("Muthoot Finance Limited", "EQ"),
    "SRTRANSFIN":  ("Shriram Transport Finance Company Limited", "EQ"),
    "LICHSGFIN":   ("LIC Housing Finance Limited", "EQ"),
    "CANFINHOME":  ("Can Fin Homes Limited", "EQ"),
    "PNBHOUSING":  ("PNB Housing Finance Limited", "EQ"),
    "IIFL":        ("IIFL Finance Limited", "EQ"),
    "L&TFH":       ("L&T Finance Holdings Limited", "EQ"),
    # Retail / Consumer Services
    "DMART":       ("Avenue Supermarts Limited", "EQ"),
    "TRENT":       ("Trent Limited", "EQ"),
    "SHOPERSTOP":  ("Shoppers Stop Limited", "EQ"),
    "VMART":       ("V-Mart Retail Limited", "EQ"),
    "INDIAMART":   ("Indiamart Intermesh Limited", "EQ"),
    "JUSTDIAL":    ("Just Dial Limited", "EQ"),
    "IRCTC":       ("Indian Railway Catering And Tourism Corporation Limited", "EQ"),
    "NAUKRI":      ("Info Edge (India) Limited", "EQ"),
    "ZOMATO":      ("Zomato Limited", "EQ"),
    "PAYTM":       ("One97 Communications Limited", "EQ"),
    # Midcap select
    "ASTRAL":      ("Astral Poly Technik Limited", "EQ"),
    "POLYCAB":     ("Polycab India Limited", "EQ"),
    "FINCABLES":   ("Finolex Cables Limited", "EQ"),
    "KEI":         ("KEI Industries Limited", "EQ"),
    "HAVELLS":     ("Havells India Limited", "EQ"),
    "VGUARD":      ("V-Guard Industries Limited", "EQ"),
    "CROMPTON":    ("Crompton Greaves Consumer Electricals Limited", "EQ"),
    "ORIENTELEC":  ("Orient Electric Limited", "EQ"),
    "AIAENG":      ("AIA Engineering Limited", "EQ"),
    "DEEPAKNTR":   ("Deepak Nitrite Limited", "EQ"),
    "AARTIIND":    ("Aarti Industries Limited", "EQ"),
    "ALKYLAMINE":  ("Alkyl Amines Chemicals Limited", "EQ"),
    "NAVINFLUOR":  ("Navin Fluorine International Limited", "EQ"),
    "PIIND":       ("PI Industries Limited", "EQ"),
    "UPL":         ("UPL Limited", "EQ"),
    "RALLIS":      ("Rallis India Limited", "EQ"),
    "KAJARIACER":  ("Kajaria Ceramics Limited", "EQ"),
    "CERA":        ("Cera Sanitaryware Limited", "EQ"),
    "ACRYSIL":     ("Acrysil Limited", "EQ"),
    "AMBER":       ("Amber Enterprises India Limited", "EQ"),
    "DIXON":       ("Dixon Technologies (India) Limited", "EQ"),
    "PGEL":        ("PG Electroplast Limited", "EQ"),
    "MCX":         ("Multi Commodity Exchange of India Limited", "EQ"),
    "BSE":         ("BSE Limited", "EQ"),
    "CDSL":        ("Central Depository Services (India) Limited", "EQ"),
    "CRISIL":      ("CRISIL Limited", "EQ"),
    "CARERATING":  ("CARE Ratings Limited", "EQ"),
    "ICRA":        ("ICRA Limited", "EQ"),
    # Current terminal_in tracked symbols
    "NIFTYBEES":   ("Nippon India ETF Nifty BeES", "EQ"),
    "ADANITRANS":  ("Adani Transmission Limited", "EQ"),
}


def _load() -> None:
    """Load from CSV if available, else use embedded symbols."""
    global _REGISTRY
    if _CSV_PATH.exists():
        import csv
        count = 0
        try:
            with open(_CSV_PATH, encoding='utf-8', errors='ignore') as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    if len(row) < 3:
                        continue
                    symbol = row[0].strip()
                    name = row[1].strip()
                    series = row[2].strip() if len(row) > 2 else 'EQ'
                    if symbol and name and symbol != 'SYMBOL':
                        _REGISTRY[symbol] = (name, series)
                        count += 1
            log.info(f'NSE symbols: loaded {count} from {_CSV_PATH}')
        except Exception as e:
            log.warning(f'Failed to load NSE CSV: {e} — using embedded symbols')
            _REGISTRY = dict(_EMBEDDED)
    else:
        _REGISTRY = dict(_EMBEDDED)
        log.info(
            f'NSE symbols: using {len(_REGISTRY)} embedded symbols. '
            f'Save EQUITY_L.csv to terminal_in/data/nse_equity_list.csv for full 2000+ coverage.'
        )


def get(symbol: str) -> dict | None:
    if not _REGISTRY:
        _load()
    entry = _REGISTRY.get(symbol.upper())
    if not entry:
        return None
    name, series = entry
    return {'symbol': symbol.upper(), 'name': name, 'series': series, 'yf_symbol': f'{symbol.upper()}.NS'}


def search(query: str, max_results: int = 20) -> list[dict]:
    """Search by symbol or company name (case-insensitive)."""
    if not _REGISTRY:
        _load()
    q = query.strip().upper()
    if not q:
        return []
    results = []
    # Exact symbol match first
    if q in _REGISTRY:
        name, series = _REGISTRY[q]
        results.append({'symbol': q, 'name': name, 'series': series, 'yf_symbol': f'{q}.NS'})
    # Prefix match on symbol
    for sym, (name, series) in _REGISTRY.items():
        if sym != q and sym.startswith(q) and len(results) < max_results:
            results.append({'symbol': sym, 'name': name, 'series': series, 'yf_symbol': f'{sym}.NS'})
    # Name substring match
    q_lower = query.strip().lower()
    for sym, (name, series) in _REGISTRY.items():
        if q_lower in name.lower() and not any(r['symbol'] == sym for r in results):
            results.append({'symbol': sym, 'name': name, 'series': series, 'yf_symbol': f'{sym}.NS'})
            if len(results) >= max_results:
                break
    return results


def get_all_symbols() -> list[str]:
    if not _REGISTRY:
        _load()
    return list(_REGISTRY.keys())


def yf_symbol(symbol: str) -> str:
    """Return Yahoo Finance symbol (SYMBOL.NS)."""
    return f'{symbol.upper()}.NS'


# Load on import
_load()
