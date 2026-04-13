"""
WASP / Westminster integration for rates, FX, swaps, and option-style pricing.

Depends on proprietary binaries (``PyWestminster``, ``PyWestRamp``, ``PyFPGTools``)
and network paths configured below. Forward and MTM helpers load **MESA AGG** ramp
markets per currency.

Conventions
-----------
- **Shock** / **YCParallelShift**: values are in **basis points** (e.g. ``50`` → +0.50%
  parallel yield shift) when passed to ``LoadMarketRamp`` via ``ParamRange``.
- WASP failures in ``realizedRate`` / ``forwardRate`` / ``carryCompounded`` are logged
  and return ``None`` where applicable.

This module is environment-specific (library paths, ramp names); adjust
``WESTMINSTER_LIBRARIES_FLAG`` and ``rampMarketDict`` for your deployment.
"""
import logging
import os
import os.path
import sys
import datetime as dt
from warnings import filterwarnings

import numpy as np
import pandas as pd
from pandas.tseries.offsets import BMonthEnd, BDay
from dateutil.relativedelta import relativedelta
from multiprocessing.dummy import Pool as ThreadPool

filterwarnings('ignore')

_logger = logging.getLogger(__name__)

_WASP_LOCAL_CACHE = r"C:\Temp\WaspPRD_136.0.0"
_USE_NAMED_PARAMS = os.path.isdir(_WASP_LOCAL_CACHE)


###################
# WASP Parameters #
###################


WASP_VERSION = "233.0.0"
WESTMINSTER_LIBRARIES_FLAG = os.path.join(r"\\lonwasp001\wasp\WaspRelease", WASP_VERSION, "Bin")
sys.path.append(os.path.normpath(WESTMINSTER_LIBRARIES_FLAG))

import PyWestminster as west
import PyWestRamp as wramp
import PyFPGTools as FPGTools

from PyWestRamp import LoadMarketRamp, RampReadFixings, RampReadCurve
from PyWestminster import Fwd, Add, Swap, CapGreeks, Df, FXGetMultiSpot, Level, GetRefRateList, FxFwd, GetMarketList, GetFixingDetails
from PyFPGTools import MESA_FxFwd

def datetime_to_excel_date(date):
    """Serial day count from 1899-12-30 (Excel date convention used by WASP)."""
    xldate = dt.datetime(date.year, date.month, date.day) - dt.datetime(1899, 12, 30)
    return xldate.days
    
def excel_date_to_datetime(date):
    """Inverse of ``datetime_to_excel_date`` for integer Excel serials."""
    return dt.datetime(1899, 12, 30) + dt.timedelta(days=int(date))

# WASP global variables
# WASP parameters
rampItem = "MESA AGG MARKET"
rampItemCarry = "MESA MARKET ALMT"


rampSet = "OFFICIAL"

# Indice Market Dictionnary

currDict = ['EUR', 'USD', 'GBP', 'CHF']

indiceDict = {'EUREST' : 'EUR'
              ,'ERIBO1' : 'EUR'
              ,'ERIBO3' : 'EUR'
              ,'ERIBO6' : 'EUR'
              ,'ERIB12' : 'EUR'

              ,'UOPFDF' : 'USD'
              ,'UTIBO1' : 'USD'
              ,'UTIBO3' : 'USD'

              ,'USSOFR' : 'USD'
#              ,'U1MCME' : 'USD'
#              ,'U3MCME' : 'USD'
#              ,'U6MCME' : 'USD'}
              ,'USTC1M' : 'USD'
              ,'USTC3M' : 'USD'
              ,'USTC6M' : 'USD'
              ,'USTC12' : 'USD'
              ,'CHFSON' : 'CHF'
              ,'CHFOIS' : 'CHF'
              ,'GBPOIS' : 'GBP'
              }

indiceOISDict = {'EUR' : 'EUREST'
              ,'USD' : 'USSOFR'
              ,'CHF' : 'CHFSON'
              ,'GBP' : 'GBPOIS'
              }

indiceWASPDict = {'EURIBOR1M' : 'ERIBO1'
                , 'EURIBOR3M' : 'ERIBO3'
                , 'EUR-ESTRS' : 'EUREST'
                , 'EUR-ESTSSW' : 'EUREST'
                , 'USD-OIS' : 'USSOFR'
                , 'USD-SFROIS' : 'USSOFR'
                , 'CHF-SAROIS' : 'CHFSON'
                , 'SRNCBT02' : 'CHFSON'
                , 'GBP-OIS' : 'GBPOIS'
                , '' : "Fixed"
              }


def _resolve_swap_indice(index_name):
    """Map Agapes swap index name to WASP indice; unknown names log warning and use ``Fixed``."""
    wasp_indice = indiceWASPDict.get(index_name)
    if wasp_indice is None:
        _logger.warning("Unknown swap index %r, treating as Fixed", index_name)
        return "Fixed"
    return wasp_indice


indiceTrueName = {'EUREST' : '€STR'
              ,'ERIBO1' : 'Euribor 1M'
              ,'ERIBO3' : 'Euribor 3M'
              ,'ERIBO6' : 'Euribor 6M'
              ,'ERIB12' : 'Euribor 12M'

              ,'UOPFDF' : 'USD Fed Funds'
              ,'UTIBO1' : 'USD 1M Libor'
              ,'UTIBO3' : 'USD 3M Libor'

              ,'USSOFR' : 'USD SOFR'
              ,'CHFSON' : 'CHF SARON'
              ,'CHFOIS' : 'CHF OIS'
              ,'GBPOIS' : 'SONIA'
#              ,'U1MCME' : 'USD 1M Term SOFR'
#              ,'U3MCME' : 'USD 3M Term SOFR'
#              ,'U6MCME' : 'USD 6M Term SOFR'}
              ,'USTC1M' : 'USD 1M Term SOFR'
              ,'USTC3M' : 'USD 3M Term SOFR'
              ,'USTC6M' : 'USD 6M Term SOFR'
              ,'USTC12' : 'USD 12M Term SOFR'}

indiceCollarDict = {'EUR' : 'ERIBO1'
                    ,'USD' : 'UTIBO1'}


rampMarketDict = {'USD' : "USD AGG NOSWAP SABRAF MARKET"
            , 'EUR' : "EUR AGG NOSWAP SABRAF MARKET"
            , 'CHF' : "CHF AGG NOSWAP SABRAF MARKET"
            , 'GBP' : "GBP AGG NOSWAP SABRAF MARKET"}

def loadAllRampMarket(calcDate, Shock=0):
    """Load USD/EUR/CHF/GBP aggregate markets; ``Shock`` is YCParallelShift in bps."""
    ParamRange = [['*MESAMARKET', 'YCParallelShift', Shock]]
    calcDate = datetime_to_excel_date(calcDate)
    
    mktUSD = LoadMarketRamp("mktUSD",[rampItem, rampMarketDict['USD']], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')
    mktEUR = LoadMarketRamp("mktEUR",[rampItem, rampMarketDict['EUR']], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')
    mktCHF = LoadMarketRamp("mktCHF",[rampItem, rampMarketDict['CHF']], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')   
    mktGBP = LoadMarketRamp("mktGBP",[rampItem, rampMarketDict['GBP']], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')   
    
    marketDict = {'USD' : mktUSD
                , 'EUR' : mktEUR
                , 'CHF' : mktCHF
                , 'GBP' : mktGBP}
    
    return marketDict


def lastBusinessDay(dateC):
    """Return the most recent weekday on or before ``dateC`` (Mon–Fri; no holiday calendar)."""
    offset = 0 if (dateC.weekday() <=4) else ((dateC.weekday() + 6) % 7 - 3)
    dateC = dateC - relativedelta(days=offset) # most recent previous business day
    return dateC


##################
# WASP Functions #
##################


#################################################################################################################
# WASP FORWARD                                                                                                  #       
#################################################################################################################
def getFxRate(dateC, curr='EUR', mkt = None):
    '''Function returns all Forward Rate curves indices in indiceDict
    dateC: Calculation date
    Use example: getFxRate(dateC=dt.datetime(2022, 5, 31))
    '''
    dateC = lastBusinessDay(dateC)
    # Function return Forward Rate curve for 120 months for all indice in indiceDict
    calcDate = datetime_to_excel_date(dateC) #nombre de jours depuis le 1er janvier 1900

    if not mkt:
        if _USE_NAMED_PARAMS:
            mkt = LoadMarketRamp("mkt","SPOT FX RATES",rampSet, calcDate)
        else:
            LoadMarketRamp("mkt","SPOT FX RATES",rampSet, calcDate)
            mkt = "mkt"

    # Load Fwd Curve for all indice listed in indiceDict
    results = FXGetMultiSpot(mkt,  curr)
    return pd.DataFrame(results.to_list()[0], columns=["Curr1", "Curr2", "FxRate"]).T  

def realizedRate(dateC, i, ind, mkt):
    '''Function returns the Realized Rate curve value on one date for one indice
    dateC: Calculation date
    i: The number of days
    ind: Indice ex 'USSOFR'
    mkt: market USD or EUR
    WASP function replication
    '''
    dtC = datetime_to_excel_date(dateC + relativedelta(days = i))
    
    try:
        res = Fwd(dtC, Add(dtC, int(ind[-1]) if ind[-1].isdigit() else 1, "m" if ind[-1].isdigit() else "bd"), ind, mkt)
        res = res.to_list()[0][0][0]
    except Exception as exc:
        _logger.warning("realizedRate failed day=%d indice=%s: %s", i, ind, exc)
        res = None
    return res

def forwardRate(dateC, i, ind, mkt):
    '''Function returns the Forward Rate curve value on one date for one indice
    dateC: Calculation date
    i: The number of months
    ind: Indice ex 'USSOFR'
    mkt: market USD or EUR
    WASP function replication
    '''
    dtC = datetime_to_excel_date(dateC + relativedelta(months=i) + relativedelta(day = 31))
    
    try:
        res = Fwd(dtC, Add(dtC, int(ind[-1]) if ind[-1].isdigit() else 1, "m" if ind[-1].isdigit() else "bd"), ind, mkt)
        res = res.to_list()[0][0][0]
    except Exception as exc:
        _logger.warning("forwardRate failed month=%d indice=%s: %s", i, ind, exc)
        res = None
    return res

def dailyFwdRate(dateC, indice, mktUSD = None, mkt = None, startDay = -3630, endDay = 3630, Shock = 0):
    '''Function returns Realized Rate curve for one indice
    dateC: Calculation date
    indice: Indice ex 'USSOFR'
    mkt: Pre-loaded market handle; if None the function loads one from rampMarketDict.
    startDay: The first day of which we want the rate. -3630 by default.
    endDay: The last day of which we want the rate. 3630 by default.
    Shock: YCParallelShift in basis points (e.g. 50 = +0.50% parallel shift).
    Use example:  dailyFwdRate(dateC=dt.datetime(2022, 5, 31), indice='USSOFR')
    '''
    
    calcDate = datetime_to_excel_date(lastBusinessDay(dateC))
    currency = indiceDict[indice]
    ParamRange = [['*MESAMARKET', 'YCParallelShift', Shock]]

    if mkt is None:
        if currency not in rampMarketDict:
            raise ValueError(f"No ramp market configured for currency {currency!r}")
        LoadMarketRamp(
            "mkt",
            [rampItem, rampMarketDict[currency]],
            rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False',
        )
        mkt = "mkt"

    # Load Fwd Curve for all indice listed in indiceDict
    results = pd.DataFrame([[indice, i, realizedRate(dateC, i, indice, mkt)] for i in range(startDay,endDay)])
    
    results.columns = ['indice', 'day', 'value']
    results['dateRef'] = dateC
    results['Indice'] = indice
    results['Date'] = dateC + pd.to_timedelta(results['day'], unit='D')
    results['dateY'] = results['Date'].dt.strftime("%Y")
    results['dateQ'] = results['Date'].dt.to_period('Q')
    return results

def monthlyForwardRate(dateC, indice, mkt = None, startMonth = -121, endMonth = 160):
    '''Function returns Forward Rate curve for 120 months for one indice
    dateC: Calculation date
    indice: Indice ex 'USSOFR'
    startMonth: The first month of which we want the rate. -121 by default.
    endMonth: The last month of which we want the rate. 121 by default.
    Use example:  monthlyForwardRate(dateC=dt.datetime(2022, 5, 31), indice='USSOFR')
    '''
    dateC = lastBusinessDay(dateC)
    calcDate = datetime_to_excel_date(dateC)

    currency = indiceDict[indice]

    if mkt is None:
        if currency not in rampMarketDict:
            raise ValueError(f"No ramp market configured for currency {currency!r}")
        LoadMarketRamp("mkt", [rampItem, rampMarketDict[currency]], rampSet, calcDate)
        mkt = "mkt"

    offset = BMonthEnd()
    dateM = offset.rollforward(dateC)
    endofMonthDate = dateM.to_pydatetime()

    results = pd.DataFrame([[indice, i, forwardRate(endofMonthDate, i, indice, mkt)] for i in range(startMonth,endMonth)])
    
    results.columns = ['indice', 'month', 'value']
    results['dateRef'] = dateC
    results['Indice'] = indice
    results['monthDate'] = (
        pd.to_datetime(dateC) + results['month'].apply(lambda m: relativedelta(months=int(m), day=31))
    )
    results['dateY'] = results['monthDate'].dt.strftime("%Y")
    results['dateQ'] = results['monthDate'].dt.to_period('Q')
    return results

def monthlyForwardRateMean(dateC, indice, mkt = None, startMonth = -121, endMonth = 160):
    '''Function returns Forward Rate curve for 120 months for one indice. The foraward rate of every month is the average of everyday's rate of that month. 
    In the contrast, monthlyForwardRate applies the rate of the last business day of every month. 
    dateC: Calculation date
    indice: Indice ex 'USSOFR'
    mtkUSD: Market USD
    mktEUR: Market EUR
    startMonth: The first month of which we want the rate. -121 by default.
    endMonth: The last month of which we want the rate. 121 by default.
    Use example:  monthlyForwardRate(dateC=dt.datetime(2022, 5, 31), indice='USSOFR')
    '''
    dateC = lastBusinessDay(dateC)
    calcDate = datetime_to_excel_date(dateC)
    
    currency = indiceDict[indice]

    if mkt is None:
        if currency not in rampMarketDict:
            raise ValueError(f"No ramp market configured for currency {currency!r}")
        LoadMarketRamp("mkt", [rampItem, rampMarketDict[currency]], rampSet, calcDate)
        mkt = "mkt"
    
    businessDaysInMonth = pd.bdate_range(start=dateC.strftime('%Y-%m-1'), end=(dateC + relativedelta(day = 31)), freq=BDay())

    results = pd.DataFrame([[indice, i, np.average([forwardRate(businessDay, i, indice, mkt) for businessDay in businessDaysInMonth])] for i in range(startMonth,endMonth)])
    results.columns = ['indice', 'month', 'value']
    results['dateRef'] = dateC
    results['Indice'] = indice
    results['monthDate'] = (
        pd.to_datetime(dateC) + results['month'].apply(lambda m: relativedelta(months=int(m)))
    )
    results['dateY'] = results['monthDate'].dt.strftime("%Y")
    results['dateQ'] = results['monthDate'].dt.to_period('Q')
    return results

#To be uopdated
def monthlyFxRate(dateC, curr, startMonth = -121, endMonth = 121):
    '''Function returns exchange rates of a certain currency with EUR for 120 months
    dateC: Calculation date
    curr: currency of which we want the exchange rate with EUR. ex: 'USD'
    startMonth: The first month of which we want the rate. 0 by default.
    endMonth: The last month of which we want the exchange rate. 121 by default.
    Use example:  monthlyFxRate(dateC=dt.datetime(2022, 5, 31), curr = 'USD')
    '''

    # Load Fwd Curve for all indice listed in indiceDict
    diff = 1 if dateC == lastBusinessDay(dateC + relativedelta(day = 31)) else 0 #A difference 0 or 1 to show the right fx rate we are on the last day of the last month or not.

    LoadMarketRamp("RAMPSpots","SPOT FX RATES",rampSet, dateC)  if dateC == lastBusinessDay(dateC + relativedelta(day = 31)) else LoadMarketRamp("RAMPSpots","SPOT FX RATES"
        ,rampSet, lastBusinessDay(dateC + relativedelta(months=-1) + relativedelta(day = 31)))
    mktFX = "RAMPSpots"

    Mesa_mkt = LoadMarketRamp('AggMarket',['MESA MARKET', 'SPOT FX RATES'], 'OFFICIAL', dateC)                               

    if _USE_NAMED_PARAMS:
        resultsFuture = pd.DataFrame([[curr, i, MESA_FxFwd(Mesa_mkt,datetime_to_excel_date(lastBusinessDay(dateC + relativedelta(months=i) + relativedelta(day = 31))),'EUR', curr)] 
        for i in range(0+diff,endMonth)])
    else:
        resultsFuture = pd.DataFrame([[curr, i, MESA_FxFwd("AggMarket",datetime_to_excel_date(lastBusinessDay(dateC + relativedelta(months=i) + relativedelta(day = 31))),'EUR', curr)] 
        for i in range(0+diff,endMonth)])
                                    
    resultsRealized = pd.DataFrame([[curr, i, getFxRate(lastBusinessDay(dateC + relativedelta(months=i) + relativedelta(day = 31)),mkt = mktFX).T.loc[getFxRate(lastBusinessDay(dateC + relativedelta(months=i)
     + relativedelta(day = 31)),mkt = mktFX).T['Curr2'] == curr]['FxRate'].values[0]] for i in range(startMonth, 0+diff)]) if curr != 'EUR' else pd.DataFrame([[curr, i, 1] for i in range(startMonth,0+diff)])
    results = pd.concat([resultsRealized, resultsFuture], ignore_index= True)
    results.columns = ['curr', 'month', 'value']
    results['dateRef'] = dateC
    results['monthDate'] = results['month'].apply(
        lambda m: lastBusinessDay(dateC + relativedelta(months=int(m), day=31))
    )
    results['dateY'] = results['monthDate'].dt.strftime("%Y")
    results['dateQ'] = results['monthDate'].dt.to_period('Q')
    return results 


def monthlyForwardAllRate(dateC):
    '''Function returns all LoadMarketRamp("EUR AGG NOSWAP SABRAF MARKET",[rampItem,"EUR AGG NOSWAP SABRAF MARKET"],rampSet, calcDate)Forward Rate curves indices in indiceDict
    dateC: Calculation date
    Use example: monthlyForwardAllRate(dateC=dt.datetime(2022, 5, 31))
    '''
    dateC = lastBusinessDay(dateC)
    
    # Load Fwd Curve for all indice listed in indiceDict
    pool = ThreadPool(4)

    results = pd.concat(pool.starmap(monthlyForwardRate, zip([dateC for indice in indiceDict.keys()],[indice for indice in indiceDict.keys()], [None for indice in indiceDict.keys()])))
    return results

def monthlyFxAllRate(dateC):
    '''Function returns all monthly exchange rates for the currencies in currDict
    dateC: Calculation date
    Use example: monthlyFxAllRate(dateC=dt.datetime(2022, 5, 31))
    '''
    dateC = lastBusinessDay(dateC)
    pool = ThreadPool(1)
    results = pd.concat(pool.starmap(monthlyFxRate, zip([dateC for curr in currDict],[curr for curr in currDict])))
    return results


def swapPricing(dateC, startDate, matMonths, indice, mkt = None, rampSet="OFFICIAL", Frq = 'A'):
    '''Function returns the swap rate of a swap with caracteritics:
    dateC: Calculation date
    startDate: Forward starting date
    matMonths: Nb months to maturity
    indice: Indice ex 'USSOFR'
    Use exemple: swapPricing(dateC='8-30-2022', startDate='1-1-2023', matMonths=24, indice='USSOFR')
    '''
    startDt = datetime_to_excel_date(dt.datetime.strptime(startDate, '%m-%d-%Y'))
    matDate = datetime_to_excel_date(dt.datetime.strptime(startDate, '%m-%d-%Y') + relativedelta(months=matMonths))

    if (mkt == None):
        if _USE_NAMED_PARAMS:
            mkt = LoadMarketRamp("mkt",[rampItem,"USD AGG NOSWAP SABRAF MARKET"],rampSet, 0 if rampSet== 'LIVE' else dateC)
        else:
            LoadMarketRamp("mkt",[rampItem,"USD AGG NOSWAP SABRAF MARKET"],rampSet, 0 if rampSet== 'LIVE' else dateC)
            mkt = "mkt"

    if _USE_NAMED_PARAMS:
        res = Swap(C_ActStartObj = startDt, C_TheoMatOrPrdsObj = matDate, s_FixFrq = Frq, s_FixBasis = 'BB', s_Mkt = mkt, s_RefR = indice, s_FltPayFrq = Frq)
    else:
        res = Swap(startDt, matDate,  Frq, 'BB', mkt, indice)

    swapPricing = res.to_list()[0][0][0]
    return(swapPricing)

def swapPricingHist(dateC, startDate, matMonths, indice):
    '''Function return the swap rate with caracteritics for the last 3 business days and 6 months before dateC:
    dateC: Calculation date
    startDate: Forward starting date
    matMonths: Nb months to maturity
    indice: Indice ex 'USSOFR'
    Use exemple: swapPricingHist(dateC=dt.date.today(), startDate='1-1-2023', matMonths=24, indice='USSOFR')
    '''
    dateRange = [*pd.bdate_range(end=dateC, periods=6, freq='BM').strftime('%m-%d-%Y'), *pd.bdate_range(end=dt.date.today(), periods=3, freq='B').strftime('%m-%d-%Y')] 
    swapPricingDT = pd.DataFrame({'date': dateRange, 'swapPricing': [swapPricing(dateC=date, startDate=startDate, matMonths=matMonths, indice=indice) for date in dateRange]})
    return(swapPricingDT)


#################################################################################################################
# WASP Optional Hedges pricing                                                                                  #       
#################################################################################################################

def collarPricing(dateC, startDate, maturityDate, currency, notional, optionType, strike, indice, buySell, mkt = None, ValeurIntrinseque = False):
    '''Pricing of a single Collar 
    if no market is defined, then by default it reload a market from Ramp (which may be time consuming when called in a loop)
    dateC : calculation date in a DateTime format 
    startDate : start date in a DateTime format
    maturityDate : maturity date in a DateTime format
    currency (string) : currency of the collar ("USD" or "EUR" only)
    notional (double): notional of the collar
    optionType (string): "Cap" or "Floor"
    strike (double): strike of the collar (cap or floor level)
    indice (string) : reference rate of the collar
    buysell (string) : buyer or seller of the cap/floor option
    ValeurIntrinseque (boolean) : if true then returns the valeur intrinsèque of the collar (price assuming 0 volatility)

    To use westminster function, needs to convert date from string to excel format
    '''
    dateCExcel = datetime_to_excel_date(dateC)
    startDateExcel = datetime_to_excel_date(startDate)
    maturityDateExcel = datetime_to_excel_date(maturityDate)

    if (buySell == "buy"):
        sens = 1  
    else:
        sens = -1
 
    if (mkt == None):
        if _USE_NAMED_PARAMS:
            if(currency == 'USD'):
                mkt = LoadMarketRamp("mkt",[rampItem,"USD AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
            else:
                mkt = LoadMarketRamp("mkt",[rampItem,"EUR AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
        else:
            if(currency == 'USD'):
                LoadMarketRamp("mkt",[rampItem,"USD AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
                mkt = "mkt"
            else:
                LoadMarketRamp("mkt",[rampItem,"EUR AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
                mkt = "mkt"

    if _USE_NAMED_PARAMS:
        if ValeurIntrinseque:
            res = sens * notional * CapGreeks(i_lActStart = startDateExcel, i_lTheoMat = maturityDateExcel, d_dStrike = strike, s_cRefRate = indice, s_cPayRec = optionType, d_dVol = 0.0000000001, s_cVolType = "Normal", s_cGreek = 'Premium', s_cMarketID = mkt, s_cFreq = 'M', s_cBasis = 'MM', s_cCSA = '-4017')
        else:
            res = sens * notional * CapGreeks(i_lActStart = startDateExcel, i_lTheoMat = maturityDateExcel, d_dStrike = strike, s_cRefRate = indice, s_cPayRec = optionType, s_cVolType = "Normal", s_cGreek = 'Premium', s_cMarketID = mkt, s_cFreq = 'M', s_cBasis = 'MM', s_cCSA = '-4017')
    else:
        if ValeurIntrinseque:
            res = sens * notional * CapGreeks(startDateExcel, maturityDateExcel, strike, indice, optionType, 0.0000000001, "Normal", 'Premium', mkt, False, False, False, False, '', 'M', 'MM','',False,-4017)
        else:
            res = sens * notional * CapGreeks(startDateExcel, maturityDateExcel, strike, indice, optionType, False, "Normal", 'Premium', mkt, False, False, False, False, '', 'M', 'MM','',False,-4017)
        
    return(res)

def swapLegPricing(dateC, startDate, maturityDate, currency, notional, indice, buySell, mkt = None, strike = 0, Shock=0):
    '''Pricing of a single leg of a swap
    if no market is defined, then by default it reload a market from Ramp (which may be time consuming when called in a loop)
    dateC : calculation date in a DateTime format 
    startDate : start date in a DateTime format
    maturityDate : maturity date in a DateTime format
    currency (string) : currency of the collar ("USD" or "EUR" only)
    notional (double): notional of the collar
    indice (string) : reference rate of the collar
    strike (double): strike of the collar (cap or floor level)
    buysell (string) : buyer or seller of the swap leg

    To use westminster function, needs to convert date from string to excel format
    '''
    startDateExcel = datetime_to_excel_date(startDate)
    maturityDateExcel = datetime_to_excel_date(maturityDate)
    calcDate = datetime_to_excel_date(dateC)
    ParamRange = [['*MESAMARKET', 'YCParallelShift', Shock]]
    
    if mkt is None:
        if currency not in rampMarketDict:
            raise ValueError(f"No ramp market configured for currency {currency!r}")
        LoadMarketRamp("mkt", [rampItem, rampMarketDict[currency]], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')
        mkt = "mkt"

    if (buySell == "Loan"):
        sens = 1  
    else:
        sens = -1

    if (indice == "Fixed"):
        SwapRate = strike
    else:
        SwapRate = Swap(startDateExcel,  maturityDateExcel, 'Q', 'MM',  mkt, indice).to_list()[0][0][0]
        
    Duration = Level(startDateExcel, maturityDateExcel, 'Q', 'MM', mkt, '', -4017, currency) 

    res = sens * notional * SwapRate * Duration
    
    return(res)


def stockSwapMTM(dateC, stockSwapsMTM, useMRX = False, Shock=0):
    '''This function prices the stock of our optional hedges (collars and swaps) at a given date (dateStock), and at a given calculation date (dateC)
    Prices are computed by Wasp
    stock definition is get from the file run parameters located in the input path
    dateC : calculation date in a datetime format 
    dateStock : loading date of the stock in a datetime format 

    YCParallelShift unit: basis points (e.g. 50 = +0.50% parallel shift)
    '''
    result = stockSwapsMTM.copy()
        
    ParamRange = [['*MESAMARKET', 'YCParallelShift', Shock]]
    dateC = lastBusinessDay(dateC)
    calcDate = datetime_to_excel_date(dateC)

    _ccy_to_mkt = {}
    for ccy, ramp_name in rampMarketDict.items():
        handle = f"mkt{ccy}"
        LoadMarketRamp(handle, [rampItem, ramp_name], rampSet, calcDate, calcDate, ParamRange, '', 1, 0, '', 'False')
        _ccy_to_mkt[ccy] = handle

    def _price_row(row):
        mkt_handle = _ccy_to_mkt.get(row['Currency Code (ISO)'])
        if mkt_handle is None:
            _logger.warning("No market for currency %s, skipping MTM", row['Currency Code (ISO)'])
            return 0.0
        return swapLegPricing(
            dateC,
            row['Value Date'],
            row['Maturity Date'],
            row['Currency Code (ISO)'],
            row['Amount'],
            _resolve_swap_indice(row['Index']),
            row['Buy / Sell'],
            mkt_handle,
            row['Rate'] / 100,
        )

    result['MTM'] = result.apply(_price_row, axis=1)
    return result


def waspRatesProbability(dateC, forwardDate, currency, strike, indice, mkt = None):
    '''Function which returns Proba (Rate (ForwardDate, indice, currency) < strike) with the market loaded at DateC
    if no market is defined, then by default it reload a market from Ramp (which may be time consuming when called in a loop)
    '''
    dateCExcel = datetime_to_excel_date(dateC)
    forwardDateExcel = datetime_to_excel_date(forwardDate)
    maturityDateExcel = datetime_to_excel_date(forwardDate + relativedelta(days=1))

    if (mkt == None):
        if(currency == 'USD'):
            LoadMarketRamp("mkt",[rampItem,"USD AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
        elif(currency == 'EUR'):
            LoadMarketRamp("mkt",[rampItem,"EUR AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)
        elif(currency == 'CHF'):
            LoadMarketRamp("mkt",[rampItem,"CHF AGG NOSWAP SABRAF MARKET"],rampSet, dateCExcel)   
        mkt = "mkt"
    
        res = -100* CapGreeks(forwardDateExcel,  maturityDateExcel,  strike,  indice, "Floor", False , "Normal", 'Delta', mkt, False, -1, False, False, '', 'A', 'MM','',False,-4017)

    return(res)



def plot_WaspRatesProbability(dateC, forwardDate, currency, indice, mkt = None):
    
    results = pd.DataFrame([[i/1000 - 4/100, waspRatesProbability(dateC, forwardDate, currency, i/1000- 4/100, indice, mkt)] for i in range(0,190)])
    results.columns = ['strike',forwardDate]

    return(results)


def loadCarryCompoundedMarket(RefDate, Shock=0):
    #loadCarryCompoundedMarket(RefDate = dt.datetime(2025, 8, 22), Shock=0)

    ParamRange = [['*MESAMARKET', 'YCParallelShift', Shock]]
    calcDateExcel = datetime_to_excel_date(lastBusinessDay(RefDate))
        
    LoadMarketRamp("mktUSD",[rampItemCarry, rampMarketDict['USD']], rampSet, calcDateExcel, calcDateExcel, ParamRange, '', 1, 0, '', 'False')
    LoadMarketRamp("mktEUR",[rampItemCarry, rampMarketDict['EUR']], rampSet, calcDateExcel, calcDateExcel, ParamRange, '', 1, 0, '', 'False')
    LoadMarketRamp("mktCHF",[rampItemCarry, rampMarketDict['CHF']], rampSet, calcDateExcel, calcDateExcel, ParamRange, '', 1, 0, '', 'False')     
    LoadMarketRamp("mktGBP",[rampItemCarry, rampMarketDict['GBP']], rampSet, calcDateExcel, calcDateExcel, ParamRange, '', 1, 0, '', 'False') 

    

def carryCompounded(StartDate, EndDate, Currency):
    '''This function prices the stock of our optional hedges (collars and swaps) at a given date (dateStock), and at a given calculation date (dateC)
    Prices are computed by Wasp
    stock definition is get from the file run parameters located in the input path
    dateC : calculation date in a datetime format 
    dateStock : loading date of the stock in a datetime format 
    '''
    
    if(Currency == 'USD'):
        indice = "USSOFR"
    elif(Currency == 'EUR'):
        indice = "ESAVB1"
    elif(Currency == 'CHF'):
        indice = "CSCML5"
    elif(Currency == 'GBP'):
        indice = "GBPOIS"        
    
    startDateExcel = datetime_to_excel_date(StartDate)
    maturityDateExcel = datetime_to_excel_date(EndDate)
    
    try:
        res = Fwd(startDateExcel, maturityDateExcel, indice, "mktUSD" if Currency =="USD" else "mktEUR" if Currency =="EUR" else "mktCHF" if Currency =="CHF" else "mktGBP")
        carry = res.to_list()[0][0][0]
    except Exception as exc:
        _logger.warning("carryCompounded failed %s [%s, %s]: %s", Currency, StartDate, EndDate, exc)
        carry = None        

    return(carry)


def carryCompoundedFwd(Dealid="001", StartDate=None, EndDate=None, Currency=None):
    '''This function prices the stock of our optional hedges (collars and swaps) at a given date (dateStock), and at a given calculation date (dateC)
    Prices are computed by Wasp
    stock definition is get from the file run parameters located in the input path
    dateC : calculation date in a datetime format 
    dateStock : loading date of the stock in a datetime format 
    carryCompoundedFwd(StartDate= dt.datetime(2025, 8, 24), EndDate = dt.datetime(2025, 11, 15), Currency = "CHF")
    carryCompoundedFwd(StartDate= dt.datetime(2025, 8, 24), EndDate = dt.datetime(2025, 11, 30), Currency = "CHF")
    '''
    
    carryFwd = [{'Dealid':Dealid
                 , 'Currency':Currency
                 , 'Maturitydate': EndDate
                 , 'Date': dateMat + relativedelta(day=31)
                 ,  'CarryCompounded': carryCompounded(StartDate, dateMat, Currency)
                 }  for dateMat in set([dateMat.to_pydatetime() for dateMat in pd.date_range(start=StartDate, end= EndDate, freq='M').to_list()] + [EndDate])]    

    return(pd.DataFrame(carryFwd))





