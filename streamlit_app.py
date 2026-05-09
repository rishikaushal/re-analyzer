"""
Austin Deal Analyzer PRO — Streamlit Web App
=============================================
Combined due diligence + financial modeling + BUY/DON'T BUY recommendation.
Pulls real market data, runs scenario analysis, and gives a clear verdict.
"""

import streamlit as st
import numpy as np
from datetime import datetime, timedelta

from models import Permit, AnalysisResult
from fetchers import AustinPermits, RedfinComps, fetch_census_home_value, fetch_census_rents, geocode_address, fetch_plot_info, ZONING_INFO, OVERLAY_EXPLANATIONS
from analysis import run_analysis, extract_street_name
from financials import _compute_hold_profit, generate_excel_bytes
from ai_summary import generate_ai_summary, GEMINI_AVAILABLE
from report import generate_report_bytes

# ── Page Config ──
st.set_page_config(
    page_title="Austin Deal Analyzer PRO",
    page_icon="🏡",
    layout="wide",
)

# ── Custom CSS ──
st.markdown("""
<style>
/* Clean card-like metrics */
div[data-testid="stMetric"] {
    background-color: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 10px;
    padding: 15px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}
div[data-testid="stMetric"] label {
    font-size: 0.85rem !important;
    color: #6c757d !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    font-size: 1.4rem !important;
    font-weight: 700 !important;
}

/* Cleaner expander styling */
div[data-testid="stExpander"] {
    border: 1px solid #e9ecef;
    border-radius: 10px;
    margin-bottom: 8px;
}

/* Better table styling */
th {
    background-color: #1F4E79 !important;
    color: white !important;
    padding: 8px 12px !important;
}
td {
    padding: 6px 12px !important;
    border-bottom: 1px solid #e9ecef !important;
}
tr:hover td {
    background-color: #f1f3f5 !important;
}

/* Sidebar cleanup */
section[data-testid="stSidebar"] {
    background-color: #fafbfc;
}

/* Breathing room */
.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  STREAMLIT UI — Combined Due Diligence + Financial Modeling
# ══════════════════════════════════════════════════════════════

st.title("🏡 Austin Deal Analyzer PRO")
st.caption("Real market data + financial modeling → **Should you buy or not?**")

# ── Sidebar: Input Form ──
with st.sidebar:
    st.header("📥 Deal Inputs")

    expand_all = st.toggle("Expand all sections", value=False)

    with st.form("deal_form"):
        st.subheader("🏠 Property")
        address = st.text_input("Property Address", value=st.session_state.get('address', '1309 Perez St'),
                               placeholder="e.g., 2613 Nottingham Ln",
                               help="Street address of the property you're analyzing")
        zip_code = st.text_input("ZIP Code", value=st.session_state.get('zip_code', '78721'),
                                 placeholder="e.g., 78704",
                                 help="Used to pull comps, permits, and zoning data")

        submitted = st.form_submit_button("🔍 Submit", use_container_width=True, type="primary")

        with st.expander("💵 Deal Numbers", expanded=expand_all):
            purchase_price = st.number_input("Purchase Price ($)", min_value=0, value=450000, step=25000,
                                             help="Land acquisition cost or total purchase price")
            build_sf = st.number_input("Total Build Size (sf)", min_value=0, value=3000, step=500,
                                       help="Total finished square footage across all units")
            units = st.number_input("Number of Units", min_value=1, value=2, step=1,
                                    help="Number of residential units (e.g., 2 for a duplex)")
            build_cost_psf = st.number_input("Build Cost ($/sf)", min_value=0, value=250, step=25,
                                             help="Hard construction cost per square foot (labor + materials)")
            exit_psf = st.number_input("Exit Price ($/sf)", min_value=0, value=575, step=10,
                                       help="Your target sale price per square foot")

        with st.expander("💵 Cost Details", expanded=expand_all):
            hard_contingency_pct = st.number_input("Hard Cost Contingency (%)", min_value=0.0, max_value=15.0, value=6.0, step=0.5,
                                             help="Buffer for unexpected construction cost overruns (typically 5-10%)")
            split_soft = st.toggle("Split Soft Cost Categories", value=False,
                                   help="Break down soft costs into individual line items instead of one percentage")
            if split_soft:
                arch_pct = st.number_input("Architecture & Design (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.5,
                                           help="Architect fees — as % of hard cost")
                eng_pct = st.number_input("Engineering (structural/MEP) (%)", min_value=0.0, max_value=10.0, value=2.0, step=0.5,
                                          help="Structural, mechanical, electrical, plumbing engineering — as % of hard cost")
                permit_fee_pct = st.number_input("Permits & Impact Fees (%)", min_value=0.0, max_value=10.0, value=2.5, step=0.5,
                                                 help="City permits, impact fees, utility connections — as % of hard cost")
                survey_pct = st.number_input("Surveys & Geotech (%)", min_value=0.0, max_value=5.0, value=1.0, step=0.5,
                                             help="Land survey, soil testing, environmental — as % of hard cost")
                insurance_dev_pct = st.number_input("Builder's Risk Insurance (%)", min_value=0.0, max_value=5.0, value=1.0, step=0.5,
                                                    help="Builder's risk / liability during construction — as % of hard cost")
                other_soft_pct = st.number_input("Other Soft Costs (%)", min_value=0.0, max_value=10.0, value=0.9, step=0.1,
                                                 help="Legal, accounting, misc — as % of hard cost")
                soft_cost_pct = arch_pct + eng_pct + permit_fee_pct + survey_pct + insurance_dev_pct + other_soft_pct
                st.caption(f"**Total Soft: {soft_cost_pct:.1f}%**")
            else:
                soft_cost_pct = st.number_input("Soft Costs (arch/eng/permits) (%)", min_value=0.0, max_value=30.0, value=10.4, step=0.5,
                                                help="Architecture, engineering, permits, surveys — as % of hard cost")
                arch_pct = eng_pct = permit_fee_pct = survey_pct = insurance_dev_pct = other_soft_pct = 0.0
            soft_contingency = st.number_input("Soft Contingency ($)", min_value=0, value=30000, step=5000,
                                               help="Fixed buffer for unexpected soft cost items")

        with st.expander("💰 Construction Financing", expanded=expand_all):
            ltv = st.number_input("Loan to Cost (%)", min_value=0.0, max_value=100.0, value=100.0, step=1.0,
                            help="% of non-land development cost funded by debt")
            interest_rate = st.number_input("Construction Interest Rate (%)", min_value=3.0, max_value=14.0, value=8.0, step=0.25,
                                      help="Annual interest rate on construction loan")
            draw_factor = st.number_input("Draw Factor (%)", min_value=40.0, max_value=80.0, value=62.5, step=0.5,
                                    help="Avg % of loan funded during construction")
            loan_fee_pct = st.number_input("Construction Loan Fees (%)", min_value=0.0, max_value=3.0, value=1.0, step=0.1,
                                     help="Origination / lender fees on construction debt")

        with st.expander("📅 Timeline", expanded=expand_all):
            build_months = st.number_input("Build Duration (months)", min_value=6, max_value=24, value=12, step=1,
                                    help="Estimated construction timeline from permit to CO")
            hold_months = st.number_input("Hold Period After Build (months)", min_value=0, max_value=36, value=24, step=1,
                                    help="0 = flip immediately, 24 = rent then sell")
            delay_months = st.number_input("Expected Delays (months)", min_value=0, max_value=12, value=0, step=1,
                                    help="Buffer for permitting delays, weather, supply issues")

        with st.expander("🏗️ Construction Carry", expanded=expand_all):
            const_tax_rate = st.number_input("Construction Property Tax (%)", min_value=0.0, max_value=4.0, value=2.0, step=0.1,
                                        help="Annual property tax rate during construction period")
            const_insurance_annual = st.number_input("Construction Insurance ($/yr)", min_value=0, value=6750, step=250,
                                                      help="Builder's risk + liability insurance per year during construction")
            const_utilities = st.number_input("Construction Utilities ($/mo)", min_value=0, value=450, step=50,
                                               help="Water, electric, temp power during construction")
            const_misc = st.number_input("Construction Misc ($/mo)", min_value=0, value=325, step=25,
                                          help="Dumpster, portable toilet, misc during construction")
            carry_buffer_pct = st.number_input("Carry Cost Buffer (%)", min_value=0.0, max_value=25.0, value=12.5, step=0.5,
                                          help="Buffer on top of all carry costs for unexpected overruns")

        with st.expander("💸 Sale / Exit Costs", expanded=expand_all):
            broker_fee_pct = st.number_input("Broker / Agent Fee (%)", min_value=0.0, max_value=6.0, value=3.0, step=0.25,
                                       help="Listing + buyer agent commission")
            title_closing_pct = st.number_input("Title + Closing Costs (%)", min_value=0.0, max_value=3.0, value=1.3, step=0.1,
                                          help="Title insurance, escrow, recording fees")
            seller_concessions_pct = st.number_input("Seller Concessions (%)", min_value=0.0, max_value=3.0, value=1.0, step=0.1,
                                               help="Buyer credits, repairs, warranty")
            exit_cost_pct = broker_fee_pct + title_closing_pct + seller_concessions_pct
            sale_hold_months = st.number_input('Sale Hold Period (months)', min_value=0.0, max_value=6.0, value=1.5, step=0.5,
                                                help='Months property sits on market before closing')
            staging_base = st.number_input('Staging Base ($)', min_value=0, value=1500, step=500,
                                            help='Base staging cost (fixed)')
            staging_per_unit = st.number_input('Staging Per Unit ($)', min_value=0, value=3500, step=500,
                                                help='Additional staging cost per unit')
            marketing_base = st.number_input('Marketing Base ($)', min_value=0, value=2000, step=500,
                                              help='Photography, signage, MLS listing fees')
            marketing_per_unit = st.number_input('Marketing Per Unit ($)', min_value=0, value=1500, step=500,
                                                  help='Additional marketing cost per unit')
            warranty_per_unit = st.number_input('Warranty Per Unit ($)', min_value=0, value=1750, step=250,
                                                 help='Home warranty cost per unit')

        with st.expander("📉 Market Risk", expanded=expand_all):
            price_decline = st.number_input("Annual Price Change (%)", min_value=-15.0, max_value=10.0, value=0.0, step=0.5,
                                      help="Expected annual change in market prices (negative = decline)")

        with st.expander("🏘️ Rental (Hold Strategy)", expanded=expand_all):
            rent_per_unit = st.number_input("Monthly Rent / Unit ($)", min_value=0, value=3950, step=100,
                                          help="Expected monthly rent per unit after lease-up")
            vacancy_pct = st.number_input("Vacancy / Credit Loss (%)", min_value=0.0, max_value=15.0, value=5.0, step=0.5,
                                    help="% of gross rent lost to vacancy and bad debt")
            mgmt_fee_pct = st.number_input("Management Fee (%)", min_value=0.0, max_value=15.0, value=7.0, step=0.5,
                                     help="Property management fee as % of effective rent")
            perm_mortgage_rate = st.number_input("Permanent Mortgage Rate (%)", min_value=3.0, max_value=12.0, value=7.0, step=0.25,
                                           help="Rate after construction loan converts to permanent")
            amortization_years = st.number_input("Amortization (years)", min_value=15, max_value=30, value=30, step=5,
                                                help="Loan payoff schedule length (longer = lower monthly payment)")
            taxable_value_psf = st.number_input("Taxable Value ($/sf)", min_value=0, value=550, step=25,
                                                help="Assessed value for property tax during hold")
            prop_tax_rate = st.number_input("Property Tax Rate (%)", min_value=1.0, max_value=4.0, value=2.0, step=0.1,
                                      help="Annual property tax rate (Austin is typically ~2%)")
            insurance_monthly = st.number_input("Landlord Insurance ($/mo)", min_value=0, value=375, step=25,
                                                help="Monthly hazard + liability insurance premium")
            repairs_per_unit = st.number_input("Repairs Reserve ($/unit/mo)", min_value=0, value=150, step=25,
                                               help="Monthly reserve per unit for maintenance and repairs")
            common_utilities = st.number_input("Common Utilities / Misc ($/mo)", min_value=0, value=250, step=25,
                                               help="Owner-paid utilities, landscaping, pest control, etc.")
            leasing_reserve = st.number_input("Leasing / Turnover Reserve ($/mo)", min_value=0, value=250, step=25,
                                              help="Reserve for tenant turnover, marketing, and lease-up costs")


# ── Main Content ──
show_analysis = submitted and address and zip_code
result = None

if submitted and address and zip_code:
    st.session_state['address'] = address
    st.session_state['zip_code'] = zip_code
    st.session_state['analysis_done'] = True
    street_name = extract_street_name(address)

    # ══════════════════════════════════════════════
    # STEP 1: Pull real market data
    # ══════════════════════════════════════════════
    with st.spinner(f"Pulling real market data for {address}, {zip_code}..."):
        result = run_analysis(address, zip_code, street_name)
    st.session_state['result'] = result
elif st.session_state.get('analysis_done') and not submitted:
    # Rerun triggered by button click (e.g. AI Analysis) — restore cached result
    show_analysis = True
    result = st.session_state.get('result')
    street_name = extract_street_name(address)

if show_analysis and result is not None:

    # ══════════════════════════════════════════════
    # STEP 2: Financial calculations
    # ══════════════════════════════════════════════
    hard_cost = build_cost_psf * build_sf
    hard_contingency = hard_cost * (hard_contingency_pct / 100)
    soft_costs = hard_cost * (soft_cost_pct / 100)
    total_dev_cost = hard_cost + hard_contingency + soft_costs + soft_contingency
    total_project_cost = purchase_price + total_dev_cost

    # Construction financing
    loan_amount = total_dev_cost * (ltv / 100)  # LTC on development costs (not land)
    equity = total_project_cost - loan_amount
    total_months = build_months + hold_months + delay_months
    timeline_years = total_months / 12

    # Construction interest (draw factor applies during build only)
    construction_interest = loan_amount * (interest_rate / 100) * (draw_factor / 100) * (build_months + delay_months) / 12
    loan_fees = loan_amount * (loan_fee_pct / 100)

    # Construction carry costs (during build, matching Karen Ave Excel)
    carry_months = build_months + delay_months
    carry_loan_interest = (purchase_price + total_dev_cost) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * carry_months / 12
    carry_taxes = (purchase_price + 0.5 * total_dev_cost) * (const_tax_rate / 100) * carry_months / 12
    carry_insurance = const_insurance_annual * carry_months / 12
    carry_utilities = const_utilities * carry_months
    carry_misc = const_misc * carry_months
    carry_subtotal = carry_loan_interest + carry_taxes + carry_insurance + carry_utilities + carry_misc
    carry_buffer = carry_subtotal * (carry_buffer_pct / 100)
    total_carry = carry_subtotal + carry_buffer

    # Sales costs (matching Karen Ave Excel)
    user_revenue_est = exit_psf * build_sf
    staging_cost = staging_base + staging_per_unit * units
    marketing_cost = marketing_base + marketing_per_unit * units
    warranty_cost = warranty_per_unit * units
    variable_sales = user_revenue_est * (exit_cost_pct / 100)
    holding_during_sale = total_carry / max(carry_months, 1) * sale_hold_months
    total_sales_cost = variable_sales + staging_cost + marketing_cost + warranty_cost + holding_during_sale

    # Holding costs during rental period
    if hold_months > 0:
        # Permanent mortgage debt service (amortized PMT on construction debt)
        monthly_perm_rate = perm_mortgage_rate / 100 / 12
        n_payments = amortization_years * 12
        if monthly_perm_rate > 0:
            monthly_debt_service = loan_amount * (monthly_perm_rate * (1 + monthly_perm_rate) ** n_payments) / ((1 + monthly_perm_rate) ** n_payments - 1)
        else:
            monthly_debt_service = loan_amount / n_payments
        hold_interest = monthly_debt_service * hold_months

        # Loan balance after hold (amortized)
        if monthly_perm_rate > 0:
            loan_balance_after_hold = loan_amount * (1 + monthly_perm_rate) ** hold_months - monthly_debt_service * ((1 + monthly_perm_rate) ** hold_months - 1) / monthly_perm_rate
        else:
            loan_balance_after_hold = loan_amount - (monthly_debt_service * hold_months)

        # Rental income during hold
        gross_rent = rent_per_unit * units * hold_months
        effective_rent = gross_rent * (1 - vacancy_pct / 100)
        mgmt_cost = effective_rent * (mgmt_fee_pct / 100)
        # Property tax during hold (based on taxable value)
        prop_tax = build_sf * taxable_value_psf * (prop_tax_rate / 100) * hold_months / 12
        # Operating expenses during hold
        insurance = insurance_monthly * hold_months
        repairs = repairs_per_unit * units * hold_months
        misc = common_utilities * hold_months
        leasing = leasing_reserve * hold_months
        total_hold_expenses = hold_interest + mgmt_cost + prop_tax + insurance + repairs + misc + leasing

        # Monthly NOI (before debt service)
        monthly_noi = (effective_rent - mgmt_cost - prop_tax - insurance - repairs - misc - leasing) / max(hold_months, 1)
        monthly_cf_after_debt = monthly_noi - monthly_debt_service

        net_rental_income = effective_rent - total_hold_expenses
    else:
        hold_interest = 0
        gross_rent = 0
        effective_rent = 0
        net_rental_income = 0
        total_hold_expenses = 0
        loan_balance_after_hold = loan_amount
        monthly_debt_service = 0
        monthly_noi = 0
        monthly_cf_after_debt = 0
        prop_tax = 0
        insurance = 0
        repairs = 0
        misc = 0
        leasing = 0
        mgmt_cost = 0

    total_interest = construction_interest + hold_interest

    # Use REAL market median if available, otherwise use user's exit assumption
    per_unit_sf = build_sf / max(units, 1)
    # Filter comps to similar per-unit size (±30%)
    similar_comps = [c for c in result.redfin_comps
                     if c.get("sqft", 0) > 0 and abs(c["sqft"] - per_unit_sf) / per_unit_sf <= 0.30]
    if similar_comps:
        sim_psf = sorted([c["psf"] for c in similar_comps if c.get("psf", 0) > 0])
        if sim_psf:
            sim_mid = len(sim_psf) // 2
            result.similar_stats = {
                "median_psf": sim_psf[sim_mid],
                "avg_psf": round(sum(sim_psf) / len(sim_psf)),
                "min_psf": min(sim_psf),
                "max_psf": max(sim_psf),
                "count": len(sim_psf),
                "size_range": f"{int(per_unit_sf * 0.7):,}–{int(per_unit_sf * 1.3):,} sf",
            }
    similar_median = getattr(result, 'similar_stats', {}).get('median_psf', 0)
    all_median = result.market_stats.get("median_psf", 0)
    # Prefer similar-size median for market comparison
    median_psf = similar_median if similar_median > 0 else all_median
    # When Census fallback (no real comps), use user's exit price for market calcs
    # Census median includes all homes (old, small) — not valid for new construction pricing
    is_census_fallback = result.market_stats.get('source', '').startswith('Census') if result.market_stats else False
    if is_census_fallback:
        market_exit = exit_psf
    else:
        market_exit = median_psf if median_psf > 0 else exit_psf

    # Adjusted exit with market trend
    price_change_rate = price_decline / 100
    adjusted_exit = market_exit * ((1 + price_change_rate) ** timeline_years)
    adjusted_revenue = adjusted_exit * build_sf
    user_revenue = exit_psf * build_sf

    # Exit costs (realtor, title, closing)
    exit_costs_user = user_revenue * (exit_cost_pct / 100)
    exit_costs_market = adjusted_revenue * (exit_cost_pct / 100)

    # Profit calculation — Equity/Debt model (matches Excel)
    if hold_months > 0:
        # Total equity invested = Land + Construction Interest + Loan Fees + Additional Equity for negative CF
        cumulative_cf = monthly_cf_after_debt * hold_months
        additional_equity_needed = max(0, -cumulative_cf)
        total_equity_invested = purchase_price + loan_fees + total_carry + staging_cost + marketing_cost + warranty_cost + additional_equity_needed

        # At sale: pay off loan balance, keep net proceeds + any positive rental CF
        net_sale_before_debt = user_revenue - exit_costs_user - staging_cost - marketing_cost - warranty_cost - holding_during_sale
        net_sale_after_debt = net_sale_before_debt - loan_balance_after_hold
        positive_rental_cf = max(0, cumulative_cf)
        total_cash_returned = net_sale_after_debt + positive_rental_cf

        user_profit = total_cash_returned - total_equity_invested
        equity_multiple = total_cash_returned / total_equity_invested if total_equity_invested > 0 else 0

        # Market-based profit
        net_market_sale = adjusted_revenue - exit_costs_market - staging_cost - marketing_cost - warranty_cost - holding_during_sale
        market_net_after_debt = net_market_sale - loan_balance_after_hold
        market_cash_returned = market_net_after_debt + positive_rental_cf
        market_profit = market_cash_returned - total_equity_invested
    else:
        # Simple flip model (includes carry + sales costs from Karen Ave Excel)
        # Note: total_carry already includes loan interest, so don't add construction_interest separately
        total_cost = total_project_cost + loan_fees + total_carry + total_sales_cost
        total_equity_invested = total_cost
        user_profit = user_revenue - total_cost
        exit_costs_market_val = adjusted_revenue * (exit_cost_pct / 100)
        market_sales_cost = exit_costs_market_val + staging_cost + marketing_cost + warranty_cost + holding_during_sale
        market_profit = adjusted_revenue - (total_project_cost + loan_fees + total_carry + market_sales_cost)
        equity_multiple = user_revenue / total_cost if total_cost > 0 else 0
        cumulative_cf = 0
        additional_equity_needed = 0
        total_cash_returned = user_revenue - exit_costs_user

    total_cost = total_equity_invested  # for break-even calc
    total_interest = construction_interest + (hold_interest if hold_months > 0 else 0)

    annual_rent = rent_per_unit * 12 * units
    cash_yield = (annual_rent / total_equity_invested * 100) if total_equity_invested > 0 else 0
    annualized_return = ((total_cash_returned / total_equity_invested) ** (1 / max(timeline_years, 0.5)) - 1) if total_equity_invested > 0 else 0
    breakeven_psf = total_equity_invested / build_sf if build_sf > 0 else 0

    # ══════════════════════════════════════════════
    # RE INDUSTRY METRICS (new — do not alter above calculations)
    # ══════════════════════════════════════════════
    # ARV = After Repair Value (same as user_revenue)
    arv = user_revenue

    # Rehab Costs = hard cost + hard contingency + soft costs + soft contingency
    rehab_costs = total_dev_cost  # already calculated above

    # MAO = Maximum Allowable Offer (70% Rule)
    # MAO = ARV × 70% − Rehab Costs
    mao = arv * 0.70 - rehab_costs
    passes_70_rule = purchase_price <= mao

    # LTV (Loan-to-Value) — different from LTC!
    # LTC = loan / dev cost (what we use for construction financing)
    # LTV = loan / ARV (what lenders look at for permanent financing)
    ltv_ratio = (loan_amount / arv * 100) if arv > 0 else 0

    # Cash-on-Cash Return (for hold scenarios)
    if hold_months > 0 and total_equity_invested > 0:
        annual_cf = monthly_cf_after_debt * 12
        cash_on_cash = (annual_cf / total_equity_invested) * 100
    else:
        cash_on_cash = 0.0

    # DOM (Days on Market) stats from comps
    dom_values = []
    for c in result.redfin_comps:
        dom_raw = c.get("days_on_market", "")
        if dom_raw and str(dom_raw).strip():
            try:
                dom_values.append(int(float(str(dom_raw).strip())))
            except (ValueError, TypeError):
                pass
    if dom_values:
        dom_median = sorted(dom_values)[len(dom_values) // 2]
        dom_avg = round(sum(dom_values) / len(dom_values))
    else:
        dom_median = 0
        dom_avg = 0

    # Active listings DOM
    active_dom_values = []
    for c in getattr(result, 'active_comps', []) or []:
        dom_raw = c.get("days_on_market", "")
        if dom_raw and str(dom_raw).strip():
            try:
                active_dom_values.append(int(float(str(dom_raw).strip())))
            except (ValueError, TypeError):
                pass
    active_dom_median = sorted(active_dom_values)[len(active_dom_values) // 2] if active_dom_values else 0

    # ══════════════════════════════════════════════
    # STEP 3: Risk scoring (0-100, higher = more risk)
    # ══════════════════════════════════════════════
    risk_score = 0
    risk_flags = []

    active_permits = [p for p in result.street_permits if p.status == 'Active']

    # Market data risks
    comp_count = result.market_stats.get('count', 0) if result.market_stats else 0
    if median_psf > 0 and not is_census_fallback:
        exit_gap = ((exit_psf - median_psf) / median_psf) * 100
        if exit_gap > 20:
            risk_score += 30
            risk_flags.append(("🔴", f"Exit \\${exit_psf}/sf is **{exit_gap:.0f}% above** market median \\${median_psf}/sf — UNREALISTIC"))
        elif exit_gap > 10:
            risk_score += 15
            risk_flags.append(("🟡", f"Exit \\${exit_psf}/sf is **{exit_gap:.0f}% above** market median \\${median_psf}/sf — AGGRESSIVE"))
        elif exit_gap > 0:
            risk_score += 5
            risk_flags.append(("🟢", f"Exit \\${exit_psf}/sf is **{exit_gap:.0f}% above** market median \\${median_psf}/sf — Reasonable"))
        else:
            risk_flags.append(("🟢", f"Exit \\${exit_psf}/sf is **at or below** market median \\${median_psf}/sf — Conservative"))
    elif is_census_fallback:
        risk_score += 10
        risk_flags.append(("🟡", f"**No Redfin comps** — Census estimate \\${median_psf}/sf includes all homes (not just new construction). Verify exit price with actual comps."))
    else:
        risk_score += 30
        risk_flags.append(("🔴", "**No market comp data** — cannot validate exit assumptions. Redfin may be blocking this server."))

    # Competition risks
    if len(active_permits) >= 5:
        risk_score += 20
        risk_flags.append(("🔴", f"**{len(active_permits)} competing units** under active construction on {street_name} St"))
    elif len(active_permits) >= 3:
        risk_score += 10
        risk_flags.append(("🟡", f"{len(active_permits)} competing units under construction on {street_name} St"))
    elif len(active_permits) > 0:
        risk_flags.append(("🟢", f"{len(active_permits)} unit(s) under construction — manageable competition"))

    # Profitability risks
    if market_profit < 0:
        risk_score += 25
        risk_flags.append(("🔴", f"**Negative profit** at market exit (\\${adjusted_exit:.0f}/sf) — LOSS of \\${abs(market_profit):,.0f}"))
    elif market_profit < 100000:
        risk_score += 15
        risk_flags.append(("🟡", f"Thin profit margin (\\${market_profit:,.0f}) — vulnerable to overruns"))

    if delay_months > 3:
        risk_score += 10
        risk_flags.append(("🟡", f"Delays adding \\${delay_cost:,.0f} in holding costs"))

    if breakeven_psf > median_psf and median_psf > 0 and not is_census_fallback:
        risk_score += 20
        risk_flags.append(("🔴", f"Break-even (\\${breakeven_psf:.0f}/sf) is **above** market median (\\${median_psf}/sf)"))

    # ── RE Detection Flags ──
    # High DOM on active listings suggests motivated sellers in area
    if active_dom_median > 120:
        risk_score += 10
        risk_flags.append(("🟡", f"**Slow market** — active listings averaging {active_dom_median} DOM. Sellers may be motivated."))

    # 70% Rule flag
    if not passes_70_rule:
        risk_score += 10
        risk_flags.append(("🟡", f"**Fails 70% Rule** — Purchase (\\${purchase_price:,.0f}) exceeds MAO (\\${mao:,.0f}). Standard investor threshold not met."))
    else:
        risk_flags.append(("🟢", f"**Passes 70% Rule** — Purchase (\\${purchase_price:,.0f}) ≤ MAO (\\${mao:,.0f})"))

    # LTV warning
    if ltv_ratio > 80:
        risk_flags.append(("🟡", f"**High LTV** ({ltv_ratio:.0f}%) — may be difficult to refinance or get permanent financing"))
    elif ltv_ratio > 0:
        risk_flags.append(("🟢", f"LTV {ltv_ratio:.0f}% — healthy leverage ratio"))

    # Hard money / bridge loan detection
    if interest_rate > 10:
        risk_flags.append(("🟡", f"**Hard money rate** detected ({interest_rate}%) — high cost of capital"))
    if build_months + delay_months + hold_months < 24 and interest_rate > 8:
        risk_flags.append(("ℹ️", "Short-term + high rate = typical **bridge loan** structure"))

    # ══════════════════════════════════════════════
    # STEP 4: THE VERDICT
    # ══════════════════════════════════════════════
    st.markdown("---")

    if user_profit < 0 and market_profit < 0:
        verdict = "DON'T BUY"
        verdict_color = "red"
        verdict_emoji = "❌"
        verdict_detail = "Negative profit at both your exit and market rates. This deal doesn't work."
    elif user_profit < 0:
        verdict = "DON'T BUY"
        verdict_color = "red"
        verdict_emoji = "❌"
        verdict_detail = f"Negative profit (${user_profit:,.0f}) even at your exit price of ${exit_psf}/sf."
    elif risk_score >= 50 and user_profit < 100000:
        verdict = "CAUTION"
        verdict_color = "orange"
        verdict_emoji = "⚠️"
        verdict_detail = f"${user_profit:,.0f} profit at your exit, but risk score is high ({risk_score}/100). Thin margin for error."
    elif market_profit < 0 and user_profit > 0:
        verdict = "CAUTION"
        verdict_color = "orange"
        verdict_emoji = "⚠️"
        verdict_detail = f"Your exit (${exit_psf}/sf) shows ${user_profit:,.0f} profit, but market median (${adjusted_exit:.0f}/sf) shows a loss. Validate your exit price with actual new-construction comps."
    elif risk_score >= 25 or user_profit < 100000 or median_psf == 0:
        verdict = "CAUTION"
        verdict_color = "orange"
        verdict_emoji = "⚠️"
        if median_psf == 0:
            verdict_detail = "No market data to validate assumptions. Cannot confirm this is a good deal — research comps manually."
        else:
            verdict_detail = "Deal is marginal. Only proceed if you can negotiate better terms."
    else:
        verdict = "BUY"
        verdict_color = "green"
        verdict_emoji = "✅"
        verdict_detail = "Deal looks solid based on market data and financials."

    # Check listing status — override verdict if not available
    listing = result.listing_status
    listing_status = listing.get('status', 'Unknown')
    listing_url = listing.get('url', '')

    if listing_status == 'Pending':
        verdict_detail += " ⚠️ BUT this property is PENDING (under contract) — may not be available."
        verdict_emoji = "🔒" if verdict == "BUY" else verdict_emoji
        if verdict == "BUY":
            verdict = "UNDER CONTRACT"
            verdict_color = "orange"
    elif listing_status == 'Sold':
        verdict_detail += " 🏠 This property has already SOLD."
        verdict_emoji = "🔒" if verdict == "BUY" else verdict_emoji
        if verdict == "BUY":
            verdict = "ALREADY SOLD"
            verdict_color = "orange"

    # Big verdict banner
    st.markdown(f"""
    <div style="background-color: {'#ff4b4b' if verdict == "DON'T BUY" else '#ffa726' if verdict in ('CAUTION', 'UNDER CONTRACT', 'ALREADY SOLD') else '#4caf50'};
                padding: 30px; border-radius: 15px; text-align: center; margin: 10px 0 20px 0;">
        <h1 style="color: white; margin: 0; font-size: 48px;">{verdict_emoji} {verdict}</h1>
        <p style="color: white; margin: 10px 0 0 0; font-size: 18px;">{verdict_detail}</p>
    </div>
    """, unsafe_allow_html=True)

    # Key numbers
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("All-In Cost", f"${total_cost:,.0f}", help="Total Rehab + Land + Carry + Sales costs")
    c2.metric("ARV (Exit Revenue)", f"${user_revenue:,.0f}", help="After Repair Value = Exit $/sf × Build SF")
    c3.metric("Your Profit", f"${user_profit:,.0f}")
    c4.metric(f"Profit @ Mkt \\${adjusted_exit:.0f}/sf", f"${market_profit:,.0f}")
    c5.metric("Break-Even $/sf", f"${breakeven_psf:.0f}/sf", help="Minimum exit $/sf to recover all costs")
    c6.metric("Risk Score", f"{risk_score}/100")

    # RE Industry Metrics row
    st.markdown("---")
    re_c1, re_c2, re_c3, re_c4, re_c5, re_c6 = st.columns(6)
    re_c1.metric("ARV", f"${arv:,.0f}", help="After Repair Value")
    re_c2.metric("MAO (70% Rule)", f"${mao:,.0f}",
                 delta="✅ PASS" if passes_70_rule else "❌ FAIL",
                 delta_color="normal" if passes_70_rule else "inverse",
                 help="Max Allowable Offer = ARV × 70% − Rehab")
    re_c3.metric("LTV", f"{ltv_ratio:.1f}%", help="Loan-to-Value = Loan ÷ ARV")
    re_c4.metric("LTC", f"{ltv}%", help="Loan-to-Cost = Loan ÷ Dev Cost (your input)")
    re_c5.metric("Equity Multiple", f"{equity_multiple:.2f}x", help="Cash returned ÷ Cash invested")
    if hold_months > 0:
        re_c6.metric("Cash-on-Cash", f"{cash_on_cash:.1f}%", help="Annual CF ÷ Equity Invested")
    else:
        re_c6.metric("Ann. Return", f"{annualized_return*100:.1f}%", help="Annualized IRR")

    # DOM metrics (if data available)
    if dom_median > 0 or active_dom_median > 0:
        dom_c1, dom_c2, dom_c3 = st.columns(3)
        if dom_median > 0:
            dom_c1.metric("Sold DOM (Median)", f"{dom_median} days", help="Days on Market for sold comps")
        if active_dom_median > 0:
            dom_c2.metric("Active DOM (Median)", f"{active_dom_median} days", help="Days on Market for active listings")
        if dom_median > 90:
            dom_c3.warning("⚠️ High DOM — slow market")
        elif dom_median > 0 and dom_median <= 30:
            dom_c3.success("✅ Fast market (DOM < 30)")

    if median_psf > 0:
        if is_census_fallback:
            st.info(f"📊 **Market Data:** No Redfin comps available. Census estimate: **\\${median_psf}/sf** "
                    f"(includes all homes, not just new construction). "
                    f"Your exit: \\${exit_psf}/sf. Using your exit price for profit calculations.")
        else:
            median_source = f"similar-size ({int(per_unit_sf):,} sf ±30%)" if similar_median > 0 else "all comps"
            sim_count = getattr(result, 'similar_stats', {}).get('count', 0)
            all_count = result.market_stats.get('count', 0)
            st.info(f"📊 **Market Data:** Median for {median_source} is **\\${median_psf}/sf** "
                    f"({sim_count if similar_median > 0 else all_count} comps). "
                    f"All comps median: \\${all_median}/sf ({all_count}). "
                    f"Your exit: \\${exit_psf}/sf.")

    st.markdown("---")

    # ══════════════════════════════════════════════
    # TABS
    # ══════════════════════════════════════════════
    tab_verdict, tab_scenarios, tab_comps, tab_active, tab_rental, tab_permits, tab_plot, tab_ai, tab_download, tab_audit, tab_glossary = st.tabs([
        "🚦 Risk Analysis", "📈 Scenarios & Sensitivity", "📊 Sold Comps", "🏠 Active Listings", "💰 Rental Comps", "🏗️ Permits", "📋 Plot Info", "🤖 AI Analysis", "📄 Download", "📐 Audit Trail", "📖 RE Glossary"
    ])

    # ── Risk Analysis Tab ──
    with tab_verdict:
        st.subheader("Risk Factors")
        for emoji, msg in risk_flags:
            st.markdown(f"{emoji} {msg}")

        st.markdown("---")
        st.subheader("Deal Structure")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Development & Financing**")
            soft_cost_line = ""
            if split_soft:
                soft_cost_line = f"""| — Architecture & Design ({arch_pct}%) | ${hard_cost * arch_pct / 100:,.0f} |
            | — Engineering ({eng_pct}%) | ${hard_cost * eng_pct / 100:,.0f} |
            | — Permits & Impact Fees ({permit_fee_pct}%) | ${hard_cost * permit_fee_pct / 100:,.0f} |
            | — Surveys & Geotech ({survey_pct}%) | ${hard_cost * survey_pct / 100:,.0f} |
            | — Builder's Risk Insurance ({insurance_dev_pct}%) | ${hard_cost * insurance_dev_pct / 100:,.0f} |
            | — Other Soft ({other_soft_pct}%) | ${hard_cost * other_soft_pct / 100:,.0f} |
            | **Soft Costs Total ({soft_cost_pct:.1f}%)** | **${soft_costs:,.0f}** |"""
            else:
                soft_cost_line = f"| Soft Costs ({soft_cost_pct}%) | ${soft_costs:,.0f} |"
            st.markdown(f"""
            | Item | Amount |
            |------|--------|
            | Land / Purchase | ${purchase_price:,.0f} |
            | Hard Cost ({build_sf:,} sf × ${build_cost_psf}/sf) | ${hard_cost:,.0f} |
            | Hard Contingency ({hard_contingency_pct}%) | ${hard_contingency:,.0f} |
            {soft_cost_line}
            | Soft Contingency | ${soft_contingency:,.0f} |
            | **Non-Land Dev Cost** | **${total_dev_cost:,.0f}** |
            | Construction Debt ({ltv}% LTC) | ${loan_amount:,.0f} |
            | Carry Costs ({carry_months} mo) | ${total_carry:,.0f} |
            | Points ({loan_fee_pct}%) | ${loan_fees:,.0f} |
            | Sales Costs | ${total_sales_cost:,.0f} |
            | **ALL-IN COST** | **${total_cost:,.0f}** |
            """)

        with c2:
            if hold_months > 0:
                st.markdown("**Equity Investment & Returns**")
                st.markdown(f"""
                | Item | Amount |
                |------|--------|
                | Land Equity | ${purchase_price:,.0f} |
                | Carrying Costs | ${total_carry:,.0f} |
                | Points (Loan Fees) | ${loan_fees:,.0f} |
                | Staging/Marketing/Warranty | ${staging_cost + marketing_cost + warranty_cost:,.0f} |
                | Additional Equity (negative CF) | ${additional_equity_needed:,.0f} |
                | **Total Equity Invested** | **${total_equity_invested:,.0f}** |
                | | |
                | Sale Price (${exit_psf}/sf) | ${user_revenue:,.0f} |
                | Less Sale Costs ({exit_cost_pct:.1f}%) | -${exit_costs_user:,.0f} |
                | — Broker ({broker_fee_pct}%) | -${user_revenue * broker_fee_pct / 100:,.0f} |
                | — Title/Closing ({title_closing_pct}%) | -${user_revenue * title_closing_pct / 100:,.0f} |
                | — Concessions ({seller_concessions_pct}%) | -${user_revenue * seller_concessions_pct / 100:,.0f} |
                | Less Loan Payoff | -${loan_balance_after_hold:,.0f} |
                | Plus Positive Rental CF | +${max(0, cumulative_cf):,.0f} |
                | **Cash Returned** | **${total_cash_returned:,.0f}** |
                | **Profit** | **${user_profit:,.0f}** |
                | **Equity Multiple** | **{equity_multiple:.2f}x** |
                """)
            else:
                st.markdown("**Returns (Flip)**")
                st.markdown(f"""
                | Scenario | Revenue | Profit |
                |----------|---------|--------|
                | Your Exit (${exit_psf}/sf) | ${user_revenue:,.0f} | ${user_profit:,.0f} |
                | Market Exit (${adjusted_exit:.0f}/sf) | ${adjusted_revenue:,.0f} | ${market_profit:,.0f} |
                | Sale Costs ({exit_cost_pct:.1f}%) | -${exit_costs_user:,.0f} | |
                | — Broker ({broker_fee_pct}%) | -${user_revenue * broker_fee_pct / 100:,.0f} | |
                | — Title/Closing ({title_closing_pct}%) | -${user_revenue * title_closing_pct / 100:,.0f} | |
                | — Concessions ({seller_concessions_pct}%) | -${user_revenue * seller_concessions_pct / 100:,.0f} | |
                """)

        st.markdown("---")
        st.subheader("Hold Strategy (Rental)")
        if hold_months > 0:
            rc1, rc2, rc3, rc4, rc5 = st.columns(5)
            rc1.metric("Gross Rent", f"${gross_rent:,.0f}", delta=f"{hold_months} months")
            rc2.metric("Net Rental Income", f"${net_rental_income:,.0f}")
            rc3.metric("Monthly Cash Flow", f"${monthly_cf_after_debt:,.0f}")
            rc4.metric("Monthly Debt Service", f"${monthly_debt_service:,.0f}")
            rc5.metric("Loan Balance After Hold", f"${loan_balance_after_hold:,.0f}")

            st.markdown(f"""
            **Rental NOI Detail ({hold_months} months):**
            | Item | Monthly | Total ({hold_months} mo) |
            |------|---------|---------|
            | Gross Rent ({units} × ${rent_per_unit:,}/mo) | ${rent_per_unit * units:,.0f} | ${gross_rent:,.0f} |
            | Less Vacancy ({vacancy_pct}%) | -${rent_per_unit * units * vacancy_pct / 100:,.0f} | -${gross_rent * vacancy_pct / 100:,.0f} |
            | **Effective Gross Income** | **${effective_rent / hold_months:,.0f}** | **${effective_rent:,.0f}** |
            | Less Mgmt Fee ({mgmt_fee_pct}%) | -${mgmt_cost / hold_months:,.0f} | -${mgmt_cost:,.0f} |
            | Less Property Tax ({prop_tax_rate}%) | -${prop_tax / hold_months:,.0f} | -${prop_tax:,.0f} |
            | Less Insurance | -${insurance_monthly:,.0f} | -${insurance:,.0f} |
            | Less Repairs ({units} × ${repairs_per_unit}/mo) | -${repairs_per_unit * units:,.0f} | -${repairs:,.0f} |
            | Less Utilities/Misc | -${common_utilities:,.0f} | -${misc:,.0f} |
            | Less Leasing/Turnover | -${leasing_reserve:,.0f} | -${leasing:,.0f} |
            | **NOI (before debt)** | **${monthly_noi:,.0f}** | **${monthly_noi * hold_months:,.0f}** |
            | Less Debt Service ({perm_mortgage_rate}%, {amortization_years}yr) | -${monthly_debt_service:,.0f} | -${monthly_debt_service * hold_months:,.0f} |
            | **Cash Flow After Debt** | **${monthly_cf_after_debt:,.0f}** | **${monthly_cf_after_debt * hold_months:,.0f}** |
            """)

            if monthly_cf_after_debt < 0:
                st.warning(f"⚠️ **Negative cash flow** of \\${monthly_cf_after_debt:,.0f}/mo during hold period. "
                          f"You'll need \\${abs(monthly_cf_after_debt * hold_months):,.0f} additional equity to carry this property.")
        else:
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("Annual Rent (if held)", f"${annual_rent:,.0f}")
            rc2.metric("Cash-on-Cash Yield", f"{cash_yield:.1f}%")
            rc3.metric("Equity Invested", f"${equity:,.0f}")
            st.info("Hold period is 0 — this is a flip strategy. Set hold months > 0 to see rental analysis.")

        st.caption("⚠ TCAD data (appraisals, deeds, foreclosure checks) requires running the CLI tool locally for complete risk assessment.")

    # ── Scenarios & Sensitivity Tab ──
    with tab_scenarios:
        # ── Pro Forma Summary (matching Karen Ave Excel Page 1) ──
        st.subheader(f"📋 Pro Forma Summary (${exit_psf}/sf Exit)")
        st.caption("Full cost breakdown across multiple build cost scenarios")
        pf_cost_levels = sorted(set([max(100, build_cost_psf - 50), max(125, build_cost_psf - 25), build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]))

        pf_data = []
        for row_label in ["Land", "Hard Cost", "Hard Contingency", "Soft + Arch", "Soft Contingency", "Carry", "Sales Cost", "Exit Value", "Total Cost", "**Profit**"]:
            row = {"Category": row_label}
            for bc in pf_cost_levels:
                hc = bc * build_sf
                hc_cont = hc * (hard_contingency_pct / 100)
                sc = hc * (soft_cost_pct / 100)
                dev = hc + hc_cont + sc + soft_contingency
                loan = dev * (ltv / 100)
                # Carry (loan interest uses land+dev as base, matching Karen Ave Excel)
                ci = (purchase_price + dev) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * carry_months / 12
                ct = (purchase_price + 0.5 * dev) * (const_tax_rate / 100) * carry_months / 12
                cins = const_insurance_annual * carry_months / 12
                cutil = const_utilities * carry_months
                cmisc = const_misc * carry_months
                csub = ci + ct + cins + cutil + cmisc
                cbuf = csub * (carry_buffer_pct / 100)
                tcarry = csub + cbuf
                # Sales
                rev = exit_psf * build_sf
                ec = rev * (exit_cost_pct / 100)
                stg = staging_base + staging_per_unit * units
                mkt = marketing_base + marketing_per_unit * units
                war = warranty_per_unit * units
                hds = tcarry / max(carry_months, 1) * sale_hold_months
                tsc = ec + stg + mkt + war + hds
                lf = loan * (loan_fee_pct / 100)
                total = purchase_price + hc + hc_cont + sc + soft_contingency + tcarry + tsc + lf
                profit = rev - total

                val = {"Land": purchase_price, "Hard Cost": hc, "Hard Contingency": hc_cont,
                       "Soft + Arch": sc, "Soft Contingency": soft_contingency, "Carry": tcarry,
                       "Sales Cost": tsc, "Exit Value": rev, "Total Cost": total, "Profit": profit}
                clean_label = row_label.replace("**", "")
                row[f"${bc}/sf"] = f"${val[clean_label]:,.0f}"
            pf_data.append(row)
        st.dataframe(pf_data, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("Exit Scenario Matrix")
        # Build scenario table
        test_psfs = sorted(set([
            int(breakeven_psf) if breakeven_psf > 0 else 300,
            median_psf - 25 if median_psf > 0 else 325,
            median_psf if median_psf > 0 else 350,
            median_psf + 25 if median_psf > 0 else 375,
            median_psf + 50 if median_psf > 0 else 400,
            exit_psf,
        ]))
        test_psfs = [p for p in test_psfs if p > 0]

        scenario_data = []
        for psf in test_psfs:
            revenue = psf * build_sf
            # Recalculate sales cost for this exit price (variable costs change with revenue)
            var_sc = revenue * (exit_cost_pct / 100)
            hds_sc = total_carry / max(carry_months, 1) * sale_hold_months
            sc_sales = var_sc + staging_cost + marketing_cost + warranty_cost + hds_sc
            sc_cost = total_project_cost + loan_fees + total_carry + sc_sales
            profit = revenue - sc_cost + net_rental_income
            margin = (profit / sc_cost) * 100 if sc_cost > 0 else 0
            label = ""
            if median_psf > 0 and psf == median_psf:
                label = "← MARKET MEDIAN"
            elif psf == exit_psf:
                label = "← YOUR EXIT"
            elif psf == int(breakeven_psf):
                label = "← BREAK-EVEN"
            scenario_data.append({
                "Exit $/sf": f"${psf}",
                "Revenue": f"${revenue:,.0f}",
                "Profit": f"${profit:,.0f}",
                "Margin": f"{margin:.1f}%",
                "Signal": "✅" if margin > 10 else ("⚠" if margin > 0 else "❌"),
                "Note": label,
            })
        st.dataframe(scenario_data, use_container_width=True, hide_index=True)

        # Sensitivity charts
        st.subheader("📈 Sensitivity — Purchase Price vs Profit")
        price_range = np.arange(max(200000, purchase_price - 200000),
                                purchase_price + 200000, 25000)
        profits_by_price = []
        for p in price_range:
            cost = p + total_dev_cost + total_interest + (exit_psf * build_sf * exit_cost_pct / 100)
            profits_by_price.append(exit_psf * build_sf - cost + net_rental_income)
        st.line_chart({"Purchase Price": price_range, "Profit": profits_by_price},
                      x="Purchase Price", y="Profit")

        st.subheader("📊 Sensitivity — Exit $/sf vs Profit")
        exit_range = np.arange(max(200, int(breakeven_psf) - 100), int(breakeven_psf) + 200, 10)
        profits_by_exit = []
        for e in exit_range:
            rev = e * build_sf
            exit_c = rev * (exit_cost_pct / 100)
            profits_by_exit.append(rev - (total_project_cost + total_interest + exit_c) + net_rental_income)
        st.line_chart({"Exit $/sf": exit_range, "Profit": profits_by_exit},
                      x="Exit $/sf", y="Profit")

        if median_psf > 0:
            st.info(f"📍 Market median is **\\${median_psf}/sf** — your break-even is **\\${breakeven_psf:.0f}/sf**. "
                    f"You need the market to be **\\${breakeven_psf - median_psf:+.0f}/sf above median** to break even.")

        # ── Carrying Cost Breakdown (During Construction) ──
        st.markdown("---")
        st.subheader("🏗️ Carrying Cost Breakdown (Construction Period)")
        st.caption(f"Build duration: {carry_months} months ({build_months} build + {delay_months} delays)")
        carry_data = [
            {"Component": "Loan Interest", "Amount": f"${carry_loan_interest:,.0f}",
             "Assumption": f"(Land+Dev) × {ltv}% LTC × {interest_rate}% × {draw_factor}% draw × {carry_months} mo ÷ 12"},
            {"Component": "Property Taxes", "Amount": f"${carry_taxes:,.0f}",
             "Assumption": f"(Land + 50% improvements) × {const_tax_rate}% × {carry_months} mo ÷ 12"},
            {"Component": "Insurance", "Amount": f"${carry_insurance:,.0f}",
             "Assumption": f"${const_insurance_annual:,}/yr × {carry_months} mo ÷ 12"},
            {"Component": "Utilities", "Amount": f"${carry_utilities:,.0f}",
             "Assumption": f"${const_utilities:,}/mo × {carry_months} mo"},
            {"Component": "Misc", "Amount": f"${carry_misc:,.0f}",
             "Assumption": f"${const_misc:,}/mo × {carry_months} mo"},
            {"Component": f"Buffer ({carry_buffer_pct}%)", "Amount": f"${carry_buffer:,.0f}",
             "Assumption": f"{carry_buffer_pct}% of carry subtotal"},
            {"Component": "**TOTAL CARRY**", "Amount": f"**${total_carry:,.0f}**", "Assumption": ""},
        ]
        st.dataframe(carry_data, use_container_width=True, hide_index=True)

        # ── Sales Cost Breakdown ──
        st.markdown("---")
        st.subheader("💸 Sales Cost Breakdown")
        st.caption(f"Based on exit value of \\${user_revenue_est:,.0f} ({exit_psf}/sf × {build_sf:,} sf)")
        sales_data = [
            {"Component": f"Realtor ({broker_fee_pct}%)", "Amount": f"${user_revenue_est * broker_fee_pct / 100:,.0f}"},
            {"Component": f"Title + Closing ({title_closing_pct}%)", "Amount": f"${user_revenue_est * title_closing_pct / 100:,.0f}"},
            {"Component": f"Concessions ({seller_concessions_pct}%)", "Amount": f"${user_revenue_est * seller_concessions_pct / 100:,.0f}"},
            {"Component": f"Staging", "Amount": f"${staging_cost:,.0f}"},
            {"Component": f"Marketing", "Amount": f"${marketing_cost:,.0f}"},
            {"Component": f"Warranty", "Amount": f"${warranty_cost:,.0f}"},
            {"Component": f"Holding During Sale ({sale_hold_months} mo)", "Amount": f"${holding_during_sale:,.0f}"},
            {"Component": "**TOTAL SALES COST**", "Amount": f"**${total_sales_cost:,.0f}**"},
        ]
        st.dataframe(sales_data, use_container_width=True, hide_index=True)

        # ── Soft Cost Breakdown ──
        if split_soft:
            st.markdown("---")
            st.subheader("📐 Soft Cost Breakdown")
            soft_data = [
                {"Category": f"Architecture & Design ({arch_pct}%)", "Amount": f"${hard_cost * arch_pct / 100:,.0f}"},
                {"Category": f"Engineering ({eng_pct}%)", "Amount": f"${hard_cost * eng_pct / 100:,.0f}"},
                {"Category": f"Permits & Impact Fees ({permit_fee_pct}%)", "Amount": f"${hard_cost * permit_fee_pct / 100:,.0f}"},
                {"Category": f"Surveys & Geotech ({survey_pct}%)", "Amount": f"${hard_cost * survey_pct / 100:,.0f}"},
                {"Category": f"Builder's Risk Insurance ({insurance_dev_pct}%)", "Amount": f"${hard_cost * insurance_dev_pct / 100:,.0f}"},
                {"Category": f"Other Soft ({other_soft_pct}%)", "Amount": f"${hard_cost * other_soft_pct / 100:,.0f}"},
                {"Category": f"**TOTAL SOFT ({soft_cost_pct:.1f}%)**", "Amount": f"**${soft_costs:,.0f}**"},
            ]
            st.dataframe(soft_data, use_container_width=True, hide_index=True)

        # ── Cost vs Price Profit Matrix ──
        st.markdown("---")
        st.subheader("📊 Cost vs Price Profit Matrix")
        st.caption("Profit at different build cost and exit price combinations")
        matrix_build_costs = sorted(set([max(100, build_cost_psf - 50), max(125, build_cost_psf - 25), build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]))
        matrix_exit_prices = sorted(set([max(300, exit_psf - 75), max(325, exit_psf - 50), max(350, exit_psf - 25), exit_psf, exit_psf + 25, exit_psf + 50]))

        matrix_data = []
        for bc in matrix_build_costs:
            row = {"Build Cost": f"${bc}/sf"}
            for ep in matrix_exit_prices:
                hc = bc * build_sf
                hc_cont = hc * (hard_contingency_pct / 100)
                sc = hc * (soft_cost_pct / 100)
                dev = hc + hc_cont + sc + soft_contingency
                proj = purchase_price + dev
                loan = dev * (ltv / 100)
                # Carry (loan interest uses land+dev as base, matching Karen Ave Excel)
                ci = (purchase_price + dev) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * carry_months / 12
                lf = loan * (loan_fee_pct / 100)
                # Carry costs
                ct = (purchase_price + 0.5 * dev) * (const_tax_rate / 100) * carry_months / 12
                cins = const_insurance_annual * carry_months / 12
                cutil = const_utilities * carry_months
                cmisc = const_misc * carry_months
                csub = ci + ct + cins + cutil + cmisc
                cbuf = csub * (carry_buffer_pct / 100)
                tcarry = csub + cbuf
                rev = ep * build_sf
                ec = rev * (exit_cost_pct / 100)
                stg = staging_base + staging_per_unit * units
                mkt = marketing_base + marketing_per_unit * units
                war = warranty_per_unit * units
                hds = tcarry / max(carry_months, 1) * sale_hold_months
                tsc = ec + stg + mkt + war + hds
                total = purchase_price + dev + tcarry + tsc + lf
                profit = rev - total
                row[f"${ep}/sf"] = f"${profit:,.0f}"
            matrix_data.append(row)
        st.dataframe(matrix_data, use_container_width=True, hide_index=True)

        # ── Timeline Sensitivity ──
        st.markdown("---")
        st.subheader("⏱️ Timeline Sensitivity — Profit by Duration")
        st.caption(f"Exit at \\${exit_psf}/sf, build cost \\${build_cost_psf}/sf")
        timeline_durations = list(range(max(6, build_months - 3), build_months + 5))
        cost_scenarios = sorted(set([max(100, build_cost_psf - 50), max(125, build_cost_psf - 25), build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]))

        timeline_data = []
        for dur in timeline_durations:
            row = {"Duration": f"{dur} months"}
            for bc in cost_scenarios:
                hc = bc * build_sf
                hc_cont = hc * (hard_contingency_pct / 100)
                sc = hc * (soft_cost_pct / 100)
                dev = hc + hc_cont + sc + soft_contingency
                proj = purchase_price + dev
                loan = dev * (ltv / 100)
                # Carry (loan interest uses land+dev as base, matching Karen Ave Excel)
                ci = (purchase_price + dev) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * dur / 12
                lf = loan * (loan_fee_pct / 100)
                ct = (purchase_price + 0.5 * dev) * (const_tax_rate / 100) * dur / 12
                cins = const_insurance_annual * dur / 12
                cutil = const_utilities * dur
                cmisc = const_misc * dur
                csub = ci + ct + cins + cutil + cmisc
                cbuf = csub * (carry_buffer_pct / 100)
                tcarry = csub + cbuf
                rev = exit_psf * build_sf
                ec = rev * (exit_cost_pct / 100)
                stg = staging_base + staging_per_unit * units
                mkt = marketing_base + marketing_per_unit * units
                war = warranty_per_unit * units
                hds = tcarry / max(dur, 1) * sale_hold_months
                tsc = ec + stg + mkt + war + hds
                total = purchase_price + dev + tcarry + tsc + lf
                profit = rev - total
                row[f"${bc}/sf"] = f"${profit:,.0f}"
            timeline_data.append(row)
        st.dataframe(timeline_data, use_container_width=True, hide_index=True)

        # ── Rent Fallback / Hold Check ──
        st.markdown("---")
        st.subheader("🏠 Rent Fallback / Hold Check")
        rent_gross_monthly = rent_per_unit * units
        rent_gross_annual = rent_gross_monthly * 12
        # Use $250/sf scenario total cost as baseline
        baseline_total = purchase_price + total_dev_cost + total_carry + total_sales_cost + loan_fees
        rent_yield = (rent_gross_annual / baseline_total * 100) if baseline_total > 0 else 0
        rent_vs_exit = (rent_gross_annual / user_revenue_est * 100) if user_revenue_est > 0 else 0

        if rent_yield >= 5.5:
            rent_read = "✅ Reasonable fallback"
        elif rent_yield >= 4.5:
            rent_read = "⚠️ Thin fallback"
        else:
            rent_read = "❌ Weak rental coverage"

        rf1, rf2, rf3, rf4 = st.columns(4)
        rf1.metric("Units", units)
        rf2.metric("Rent / Unit / Mo", f"${rent_per_unit:,}")
        rf3.metric("Gross Annual Rent", f"${rent_gross_annual:,}")
        rf4.metric("Rent Yield", f"{rent_yield:.1f}%", delta=rent_read)

        st.markdown(f"""
        | Metric | Value | Note |
        |--------|-------|------|
        | Gross Monthly Rent | ${rent_gross_monthly:,} | {units} units × ${rent_per_unit:,}/mo |
        | Gross Annual Rent | ${rent_gross_annual:,} | Monthly × 12 |
        | Annual Rent / Total Cost | {rent_yield:.1f}% | Gross rent ÷ all-in cost |
        | Annual Rent / Exit Value | {rent_vs_exit:.1f}% | Gross rent ÷ exit value |
        | **Assessment** | **{rent_read}** | ≥5.5% = Reasonable, ≥4.5% = Thin |
        """)

    # ── Comps Tab ──
    with tab_comps:
        if result.redfin_comps:
            # Similar-size comps (per unit)
            sim_stats = getattr(result, 'similar_stats', {})
            if sim_stats:
                st.subheader(f"🎯 Similar Size Comps ({sim_stats['size_range']}, per unit = {int(per_unit_sf):,} sf)")
                sc1, sc2, sc3, sc4 = st.columns(4)
                sc1.metric("Median $/sf", f"${sim_stats.get('median_psf', 0)}")
                sc2.metric("Average $/sf", f"${sim_stats.get('avg_psf', 0)}")
                sc3.metric("Count", f"{sim_stats.get('count', 0)}")
                sc4.metric("Range", f"${sim_stats.get('min_psf', 0)}–${sim_stats.get('max_psf', 0)}")

                sim_data = []
                for c in sorted(similar_comps, key=lambda x: x.get("psf", 0), reverse=True):
                    if c.get("psf", 0) > 0:
                        sim_data.append({
                            "Address": c["address"],
                            "Price": f"${c['price']:,}",
                            "Size": f"{c['sqft']:,} sf",
                            "$/sf": c["psf"],
                            "Built": c.get("year_built", ""),
                            "Sold": c.get("sold_date", ""),
                            "DOM": c.get("days_on_market", ""),
                            "Redfin": c.get("redfin_url", ""),
                            "Zillow": c.get("zillow_url", ""),
                        })
                st.dataframe(sim_data, use_container_width=True, hide_index=True,
                             column_config={
                                 "Redfin": st.column_config.LinkColumn("Redfin", display_text="View"),
                                 "Zillow": st.column_config.LinkColumn("Zillow", display_text="View"),
                             })
                st.markdown("---")

            # All comps
            stats = result.market_stats
            if not result.sources_status.get('comps_radius', True):
                st.warning("⚠️ Could not pull comps within 1 mile — showing ZIP-wide data as fallback.")
                st.subheader(f"📍 Sold Comps — ZIP {zip_code} (past 2 years, {stats.get('count', 0)} comps)")
            else:
                st.subheader(f"📍 Sold Comps — Within 1 Mile (past 2 years, {stats.get('count', 0)} comps)")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Median $/sf", f"${stats.get('median_psf', 0)}")
            c2.metric("Average $/sf", f"${stats.get('avg_psf', 0)}")
            c3.metric("Min $/sf", f"${stats.get('min_psf', 0)}")
            c4.metric("Max $/sf", f"${stats.get('max_psf', 0)}")

            comp_data = []
            for c in sorted(result.redfin_comps, key=lambda x: x.get("distance_mi", 0)):
                if c.get("psf", 0) > 0:
                    comp_data.append({
                        "Address": c["address"],
                        "Price": f"${c['price']:,}",
                        "Size": f"{c['sqft']:,} sf",
                        "$/sf": c["psf"],
                        "Distance": f"{c.get('distance_mi', 0):.1f} mi",
                        "Built": c.get("year_built", ""),
                        "Sold": c.get("sold_date", ""),
                        "DOM": c.get("days_on_market", ""),
                        "Beds": c.get("beds", ""),
                        "Baths": c.get("baths", ""),
                        "Redfin": c.get("redfin_url", ""),
                        "Zillow": c.get("zillow_url", ""),
                    })
            st.dataframe(comp_data, use_container_width=True, hide_index=True,
                         column_config={
                             "Redfin": st.column_config.LinkColumn("Redfin", display_text="View"),
                             "Zillow": st.column_config.LinkColumn("Zillow", display_text="View"),
                         })
        else:
            if result.market_stats and result.market_stats.get('source', '').startswith('Census'):
                st.warning("⚠️ Redfin blocked — using **Census Bureau estimate** as fallback.")
                stats = result.market_stats
                st.subheader(f"📊 Estimated Market Value — ZIP {zip_code}")
                c1, c2 = st.columns(2)
                c1.metric("Estimated $/sf", f"${stats.get('median_psf', 0)}")
                c2.metric("Source", "Census ACS 2022")
                st.caption("Based on Census median home value ÷ typical new construction size. For accurate comps, check Redfin/Zillow directly.")
            else:
                st.warning("No Redfin comps available. Redfin may be blocking requests from this server.")

    # ── Active Listings Tab ──
    with tab_active:
        st.subheader(f"🏠 Active Listings — Within 1 Mile")
        if result.active_comps:
            a_stats = result.active_stats
            if a_stats:
                ac1, ac2, ac3, ac4 = st.columns(4)
                ac1.metric("Median $/sf", f"${a_stats.get('median_psf', 0)}")
                ac2.metric("Average $/sf", f"${a_stats.get('avg_psf', 0)}")
                ac3.metric("Count", f"{a_stats.get('count', 0)}")
                ac4.metric("Range", f"${a_stats.get('min_psf', 0)}–${a_stats.get('max_psf', 0)}")

            a_data = []
            for c in result.active_comps:
                if c.get("psf", 0) > 0:
                    a_data.append({
                        "Address": c["address"],
                        "List Price": f"${c['price']:,}",
                        "Size": f"{c['sqft']:,} sf",
                        "$/sf": c["psf"],
                        "Distance": f"{c.get('distance_mi', 0):.1f} mi",
                        "Built": c.get("year_built", ""),
                        "Beds": c.get("beds", ""),
                        "Baths": c.get("baths", ""),
                        "Days on Market": c.get("days_on_market", ""),
                        "Redfin": c.get("redfin_url", ""),
                        "Zillow": c.get("zillow_url", ""),
                    })
            st.dataframe(a_data, use_container_width=True, hide_index=True,
                         column_config={
                             "Redfin": st.column_config.LinkColumn("Redfin", display_text="View"),
                             "Zillow": st.column_config.LinkColumn("Zillow", display_text="View"),
                         })
            st.caption("💡 These are your competition — currently listed homes near the subject property.")
        else:
            st.info("No active listings found within 1 mile.")

    # ── Rental Comps Tab ──
    with tab_rental:
        st.subheader("💰 Rental Market Analysis")

        # ── Research Links (at top for easy access) ──
        st.markdown("### 🔍 Search Active Rentals Near You")
        zillow_rental = f"https://www.zillow.com/homes/for_rent/{zip_code}_rb/"
        apartments_url = f"https://www.apartments.com/{zip_code}/"
        rentometer_url = f"https://www.rentometer.com/analysis/new?address={zip_code}"
        redfin_rental = f"https://www.redfin.com/zipcode/{zip_code}/apartments-for-rent"

        lk1, lk2, lk3, lk4 = st.columns(4)
        lk1.markdown(f"[🏠 Zillow Rentals]({zillow_rental})")
        lk2.markdown(f"[🏢 Apartments.com]({apartments_url})")
        lk3.markdown(f"[📊 Rentometer]({rentometer_url})")
        lk4.markdown(f"[🔴 Redfin Rentals]({redfin_rental})")
        st.caption("Click above to search active rental listings in your ZIP code.")

        st.markdown("---")

        # ── Census Bureau Rental Data ──
        census_rents = fetch_census_rents(zip_code)
        if census_rents and census_rents.get('median_rent'):
            st.markdown(f"### 📊 Actual Median Rents — ZIP {zip_code}")
            st.caption(f"Source: {census_rents.get('source', 'Census ACS')}")

            cr1, cr2, cr3 = st.columns(3)
            cr1.metric("Overall Median Rent", f"${census_rents['median_rent']:,}/mo")
            beds_in_unit = max(1, int(build_sf / max(units, 1) / 500))  # rough estimate
            cr2.metric("Your Unit Size (~" + str(beds_in_unit) + "BR)", 
                       f"${census_rents.get(f'rent_{beds_in_unit}br', census_rents['median_rent']) or census_rents['median_rent']:,}/mo")
            cr3.metric("Your Assumption", f"${rent_per_unit:,}/mo",
                       delta=f"{((rent_per_unit / census_rents['median_rent']) - 1) * 100:+.0f}% vs median" if census_rents['median_rent'] else None)

            # Bedroom breakdown table
            bed_data = []
            for label, key in [("Studio", "rent_0br"), ("1 Bedroom", "rent_1br"), ("2 Bedroom", "rent_2br"), 
                               ("3 Bedroom", "rent_3br"), ("4+ Bedroom", "rent_4br_plus")]:
                val = census_rents.get(key)
                if val:
                    bed_data.append({"Type": label, "Median Rent": f"${val:,}/mo", 
                                    "Annual": f"${val * 12:,}",
                                    "vs Your Assumption": f"{((rent_per_unit / val) - 1) * 100:+.1f}%"})
            if bed_data:
                st.dataframe(bed_data, use_container_width=True, hide_index=True)

            st.markdown("---")

        # ── a) Your Rent Assumptions ──
        gross_monthly_rent = rent_per_unit * units
        gross_annual_rent = gross_monthly_rent * 12
        rent_per_sf = gross_monthly_rent / build_sf if build_sf > 0 else 0
        gross_yield = (gross_annual_rent / total_project_cost * 100) if total_project_cost > 0 else 0

        st.markdown("### 📋 Your Rent Assumptions")
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("Gross Monthly Rent", f"${gross_monthly_rent:,.0f}")
        rc2.metric("Annual Rent", f"${gross_annual_rent:,.0f}")
        rc3.metric("Rent/SF/mo", f"${rent_per_sf:.2f}")
        rc4.metric("Gross Yield", f"{gross_yield:.1f}%")

        # ── b) Market Rent Estimates ──
        st.markdown("### 📊 Market Rent Estimates")

        # 1% rule estimate
        one_pct_monthly = total_project_cost * 0.01
        one_pct_annual = one_pct_monthly * 12
        one_pct_per_sf = one_pct_monthly / build_sf if build_sf > 0 else 0

        # Cap rate estimates from sold comps
        estimated_value = median_psf * build_sf if median_psf > 0 else total_project_cost
        cap5_annual = estimated_value * 0.05
        cap5_monthly = cap5_annual / 12
        cap5_per_sf = cap5_monthly / build_sf if build_sf > 0 else 0

        cap7_annual = estimated_value * 0.07
        cap7_monthly = cap7_annual / 12
        cap7_per_sf = cap7_monthly / build_sf if build_sf > 0 else 0

        comparison_data = [
            {"Method": "Your Assumption", "Monthly Rent": f"${gross_monthly_rent:,.0f}", "Annual": f"${gross_annual_rent:,.0f}", "$/SF/mo": f"${rent_per_sf:.2f}"},
        ]
        if census_rents and census_rents.get('median_rent'):
            cm = census_rents['median_rent'] * units
            comparison_data.append({"Method": f"Census Median (×{units} units)", "Monthly Rent": f"${cm:,.0f}", "Annual": f"${cm * 12:,.0f}", "$/SF/mo": f"${cm / build_sf:.2f}" if build_sf > 0 else "—"})
        comparison_data.extend([
            {"Method": "1% Rule (of cost)", "Monthly Rent": f"${one_pct_monthly:,.0f}", "Annual": f"${one_pct_annual:,.0f}", "$/SF/mo": f"${one_pct_per_sf:.2f}"},
            {"Method": "5% Cap Rate", "Monthly Rent": f"${cap5_monthly:,.0f}", "Annual": f"${cap5_annual:,.0f}", "$/SF/mo": f"${cap5_per_sf:.2f}"},
            {"Method": "7% Cap Rate", "Monthly Rent": f"${cap7_monthly:,.0f}", "Annual": f"${cap7_annual:,.0f}", "$/SF/mo": f"${cap7_per_sf:.2f}"},
        ])
        st.dataframe(comparison_data, use_container_width=True, hide_index=True)

        if median_psf > 0:
            st.caption(f"💡 Cap rate estimates based on comps median \\${median_psf}/sf × {build_sf:,} sf = \\${estimated_value:,.0f} estimated value")
        else:
            st.caption("💡 Cap rate estimates based on total project cost (no comp data available)")

        # ── c) Rent Sensitivity Analysis ──
        st.markdown("### 📈 Rent Sensitivity Analysis")

        sensitivity_data = []
        for pct in [-20, -10, 0, 10, 20]:
            adj_rent_monthly = gross_monthly_rent * (1 + pct / 100)
            adj_rent_annual = adj_rent_monthly * 12

            # Recalc NOI and CF for this rent level
            eff_rent_mo = adj_rent_monthly * (1 - vacancy_pct / 100)
            mgmt_mo = eff_rent_mo * (mgmt_fee_pct / 100)
            tax_mo = build_sf * taxable_value_psf * (prop_tax_rate / 100) / 12
            sens_monthly_noi = eff_rent_mo - mgmt_mo - tax_mo - insurance_monthly - (repairs_per_unit * units) - common_utilities - leasing_reserve
            sens_monthly_cf = sens_monthly_noi - monthly_debt_service
            sens_annual_cf = sens_monthly_cf * 12
            sens_coc = (sens_annual_cf / total_equity_invested * 100) if total_equity_invested > 0 else 0

            label = f"{pct:+d}%" if pct != 0 else "0% (Base)"
            sensitivity_data.append({
                "Scenario": label,
                "Monthly Rent": f"${adj_rent_monthly:,.0f}",
                "Monthly NOI": f"${sens_monthly_noi:,.0f}",
                "Monthly CF After Debt": f"${sens_monthly_cf:,.0f}",
                "Annual CF": f"${sens_annual_cf:,.0f}",
                "Cash-on-Cash": f"{sens_coc:.1f}%",
            })

        st.dataframe(sensitivity_data, use_container_width=True, hide_index=True)
        st.caption("💡 The **0% (Base)** row matches your assumed rent. Negative CF means you'd need to fund the shortfall from cash reserves.")

    # ── Permits Tab ──
    with tab_permits:
        st.subheader(f"New Construction Permits — {street_name} St")
        if result.street_permits:
            active = [p for p in result.street_permits if p.status == 'Active']
            final = [p for p in result.street_permits if p.status == 'Final']

            if active:
                st.markdown(f"### 🟡 Under Construction ({len(active)})")
                st.dataframe([{"Address": p.address, "Size": f"{p.sqft:,.0f} sf",
                              "Builder": p.builder, "Contractor": p.contractor_name,
                              "Applicant": p.applicant_name or p.applicant_org,
                              "Date": p.issue_date,
                              "Type": p.permit_class,
                              "Source": f"https://data.austintexas.gov/resource/3syk-w9eu.json?permit_num={p.permit_number}" if p.permit_number else ""} for p in active],
                             use_container_width=True, hide_index=True,
                             column_config={"Source": st.column_config.LinkColumn("Source", display_text="Austin Open Data")})
            if final:
                st.markdown(f"### ✅ Completed ({len(final)})")
                st.dataframe([{"Address": p.address, "Size": f"{p.sqft:,.0f} sf",
                              "Builder": p.builder, "Contractor": p.contractor_name,
                              "Applicant": p.applicant_name or p.applicant_org,
                              "Date": p.issue_date,
                              "Type": p.permit_class,
                              "Source": f"https://data.austintexas.gov/resource/3syk-w9eu.json?permit_num={p.permit_number}" if p.permit_number else ""} for p in final],
                             use_container_width=True, hide_index=True,
                             column_config={"Source": st.column_config.LinkColumn("Source", display_text="Austin Open Data")})

            # Zip summary
            st.markdown(f"### 📊 Zip {zip_code} — Permit Trend")
            by_year = {}
            for p in result.zip_permits:
                yr = p.issue_date[:4] if p.issue_date else 'Unknown'
                by_year.setdefault(yr, []).append(p)
            year_data = []
            for yr in sorted(by_year.keys(), reverse=True):
                permits = by_year[yr]
                total_sf = sum(p.sqft for p in permits)
                year_data.append({"Year": yr, "Permits": len(permits),
                                  "Total SF": f"{total_sf:,.0f}",
                                  "Avg SF": f"{total_sf / len(permits):,.0f}" if permits else "0"})
            st.dataframe(year_data, use_container_width=True, hide_index=True)
        else:
            st.warning("No new construction permits found. This could mean:\n"
                      "- No recent builds on this street\n"
                      "- The permits API may be temporarily unavailable — try clicking **Analyze** again")

        # All permit types for the street
        st.markdown("---")
        st.subheader(f"📋 All Permits — {street_name} St (past 2 years)")
        if result.street_all_permits:
            # Group by type
            type_map = {'BP': '🏗️ Building', 'EP': '⚡ Electrical', 'PP': '🔧 Plumbing',
                        'MP': '🌬️ Mechanical', 'DP': '🚧 Demolition'}
            by_type = {}
            for p in result.street_all_permits:
                key = p.permit_type or 'Other'
                by_type.setdefault(key, []).append(p)

            # Summary counts
            type_cols = st.columns(min(len(by_type), 5))
            for i, (ptype, permits) in enumerate(sorted(by_type.items())):
                label = type_map.get(ptype, ptype)
                type_cols[i % len(type_cols)].metric(label, len(permits))

            # Table with all permits
            all_data = []
            for p in result.street_all_permits:
                all_data.append({
                    "Address": p.address,
                    "Category": type_map.get(p.permit_type, p.permit_type),
                    "Work": p.work_class,
                    "Description": (p.description or "")[:120],
                    "Submitted By": p.applicant_name or p.applicant_org or "",
                    "Contractor": p.builder if p.builder != "Unknown" else (p.contractor_name or ""),
                    "Status": p.status,
                    "Date": p.issue_date,
                })
            st.dataframe(all_data, use_container_width=True, hide_index=True)
        else:
            st.info("No permits found for this street in the past 2 years.")

    # ── Plot Info Tab ──
    with tab_plot:
        st.subheader(f"📋 Plot Information — {address}")

        # Listing status banner
        listing = result.listing_status
        listing_status = listing.get('status', 'Unknown')
        listing_url = listing.get('url', '')
        listing_price = listing.get('price', '')

        if listing_status == 'Active':
            st.success(f"🟢 **ACTIVE LISTING** — This property is for sale! "
                       f"{'Listed at $' + f'{int(listing_price):,}' if listing_price else ''} "
                       f"{'[View on Redfin →](' + listing_url + ')' if listing_url else ''}")
        elif listing_status == 'Pending':
            st.warning(f"🟡 **PENDING / UNDER CONTRACT** — Someone already has an offer accepted on this property. "
                       f"{'Listed at $' + f'{int(listing_price):,}' if listing_price else ''} "
                       f"You'd need to wait for it to fall through, or find a similar property. "
                       f"{'[View on Redfin →](' + listing_url + ')' if listing_url else ''}")
        elif listing_status == 'Sold':
            st.error(f"🔴 **SOLD** — This property has already been sold. "
                     f"{'Sale price: $' + f'{int(listing_price):,}' if listing_price else ''} "
                     f"{'[View on Redfin →](' + listing_url + ')' if listing_url else ''}")
        elif listing_status == 'Not Found':
            st.info("⚪ **OFF-MARKET** — This property is not currently listed on Redfin. "
                    "It may be a private sale, pocket listing, or not yet on the market.")
        else:
            st.info("⚪ **Listing status unknown** — Could not verify on Redfin.")

        # Property links — use Redfin URL from listing check if available
        addr_slug = address.replace(' ', '-').replace(',', '')
        addr_query = address.replace(' ', '+')
        zillow_search = f"https://www.zillow.com/homes/{addr_slug}-Austin-TX-{zip_code}_rb/"
        redfin_link = listing_url if listing_url else f"https://www.google.com/search?q=site:redfin.com+{addr_query}+Austin+TX+{zip_code}"
        tcad_search = f"https://stage.travis.prodigycad.com/property-search"
        google_maps = f"https://www.google.com/maps/search/{addr_query}+Austin+TX+{zip_code}"

        lc1, lc2, lc3, lc4 = st.columns(4)
        lc1.markdown(f"[🔗 Zillow]({zillow_search})")
        lc2.markdown(f"[🔗 Redfin]({redfin_link})")
        lc3.markdown(f"[🔗 TCAD]({tcad_search})")
        lc4.markdown(f"[🗺️ Google Maps]({google_maps})")

        st.markdown("---")

        # Geocode and fetch plot data
        with st.spinner("Fetching zoning, parcel & flood data..."):
            lat, lon = geocode_address(address, zip_code)

        if lat and lon:
            plot_data = fetch_plot_info(lat, lon, address)
            st.caption(f"📍 Coordinates: {lat:.6f}, {lon:.6f}")

            pc1, pc2 = st.columns(2)

            # Zoning
            with pc1:
                st.markdown("### 🏗️ Zoning")
                zoning = plot_data.get('zoning', {})
                if zoning:
                    ztype = zoning.get('zoning_type', 'Unknown')
                    base = zoning.get('base_zone', '')
                    name = zoning.get('zone_name', '')
                    zoning_area = zoning.get('lot_area_sf', 0)

                    st.metric("Zoning Type", ztype)

                    # Plain-English explanation
                    info = ZONING_INFO.get(base, {})
                    if info:
                        st.info(f"💡 **What this means:** {info.get('plain', '')}")

                        st.markdown(f"""
                        | | Detail |
                        |---|---|
                        | **Official Name** | {name} |
                        | **What you can build** | {info.get('can_build', 'Check with city')} |
                        | **Max height** | {info.get('height', 'Check with city')} |
                        | **Max units allowed** | {info.get('max_units', 'Unknown')} |
                        | **Min lot size required** | {info.get('min_lot_sf', 0):,} sf |
                        | **This lot size** | {zoning_area:,} sf ({zoning_area/43560:.2f} acres) |
                        """)

                        if zoning_area > 0 and isinstance(info.get('max_units'), str) and '/acre' in str(info['max_units']):
                            density = int(info['max_units'].replace('/acre', ''))
                            acres = zoning_area / 43560
                            est_units = int(acres * density)
                            st.success(f"📐 **Estimated max units on this lot:** ~{est_units} ({acres:.2f} acres × {density}/acre)")
                    else:
                        st.write(f"**Full Name:** {name}")
                        st.write(f"**Base Zone:** {base}")
                        if zoning_area > 0:
                            st.write(f"**Lot Area:** {zoning_area:,} sf ({zoning_area/43560:.2f} acres)")

                    # Overlay explanations
                    for suffix, (title, explanation) in OVERLAY_EXPLANATIONS.items():
                        if suffix in ztype:
                            st.markdown("---")
                            st.markdown(f"#### {title}")
                            st.write(explanation)
                else:
                    st.warning("Zoning data not available for this location")

            # Parcel & Flood
            with pc2:
                st.markdown("### 📐 Parcel")
                parcel = plot_data.get('parcel', {})
                if parcel:
                    parcel_sf = parcel.get('parcel_area_sf', 0)
                    st.write(f"**TCAD Property ID:** {parcel.get('prop_id', 'N/A')}")
                    st.write(f"**Parcel ID:** {parcel.get('pid', 'N/A')}")
                    st.write(f"**Lot:** {parcel.get('lot', 'N/A')}, **Block:** {parcel.get('block', 'N/A')}")
                    if parcel_sf > 0:
                        st.write(f"**Parcel Area:** {parcel_sf:,} sf ({parcel_sf/43560:.3f} acres)")
                    tcad_link = f"https://stage.travis.prodigycad.com/property-detail/{parcel.get('prop_id', '')}/2026"
                    st.markdown(f"[View on TCAD →]({tcad_link})")
                else:
                    st.warning("Parcel data not available")

                st.markdown("### 🌊 FEMA Flood Zone")
                flood = plot_data.get('flood', {})
                if flood.get('in_floodplain'):
                    st.error(f"❌ **IN FLOOD ZONE:** {flood.get('zone', 'Unknown')}")
                    st.write("**What this means:** Your property is in a flood-risk area. "
                             "You'll be **required to buy flood insurance** (can be $1,000–$5,000+/year). "
                             "Construction costs may be higher (elevated foundation). "
                             "Resale can be harder — many buyers avoid flood zones.")
                else:
                    st.success(f"✅ **Not in floodplain** — Zone: {flood.get('zone', 'X')}")
                    st.write("**What this means:** Low flood risk. No mandatory flood insurance required. "
                             "This is the best-case scenario for lenders and insurance costs.")

                st.markdown("### 🛣️ Legal Access to Road")
                st.info("**What this means:** Every buildable lot needs legal access to a public road. "
                        "If the lot is landlocked (no road frontage), you can't get a building permit. "
                        "Check the **plat map** to confirm the lot touches a public street or has a recorded easement.")
                st.markdown(f"[🗺️ View Austin GIS Map](https://www.austintexas.gov/gis/) · "
                           f"[📄 Travis County Plat Records](https://www.traviscountyclerk.org/)")

                st.markdown("### 📜 Title & Liens")
                st.info("**What this means:** Before buying, a title search checks if anyone else "
                        "has a legal claim on the property — unpaid taxes, mortgages, contractor liens, "
                        "or easements. Your title company does this at closing, but you can check early.")
                st.markdown("[🔍 Travis County Deed Records](https://deed.traviscountyclerk.org/)")

        else:
            st.error("Could not geocode address. Please verify the address and ZIP code.")

    # ── AI Analysis Tab ──
    with tab_ai:
        st.subheader("🤖 AI Deal Analysis")
        try:
            if not _get_gemini_key():
                st.info("**How to enable free AI analysis:**\n\n"
                        "1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and get a free API key\n"
                        "2. In Streamlit Cloud → Settings → Secrets, add:\n"
                        "```\nGEMINI_API_KEY = \"your-api-key-here\"\n```\n"
                        "3. Refresh the app — the 🤖 AI Analysis tab will work!\n\n"
                        "**Cost: FREE** (Google Gemini free tier: 15 requests/minute)")
            else:
                if st.button("🧠 Generate AI Analysis", type="primary"):
                    with st.spinner("AI is analyzing your deal..."):
                        # Build top comps summary
                        top_comps_text = ""
                        if result.redfin_comps:
                            for c in sorted(result.redfin_comps, key=lambda x: x.get('distance_mi', 0))[:5]:
                                top_comps_text += f"  - {c['address']}: ${c['price']:,} ({c['sqft']:,}sf, ${c['psf']}/sf, sold {c.get('sold_date', 'N/A')}, {c.get('distance_mi', 0):.1f}mi away)\n"

                        # Fetch Census rents for AI
                        _census_ai = fetch_census_rents(zip_code)
                        _census_median = f"${_census_ai.get('median_rent', 0):,}" if _census_ai and _census_ai.get('median_rent') else 'N/A'
                        _census_by_br = ', '.join([
                            f"{br}: ${_census_ai.get(k, 0):,}/mo"
                            for br, k in [('Studio', 'rent_0br'), ('1BR', 'rent_1br'), ('2BR', 'rent_2br'), ('3BR', 'rent_3br'), ('4BR+', 'rent_4br_plus')]
                            if _census_ai and _census_ai.get(k)
                        ]) if _census_ai else 'N/A'

                        deal_data = {
                            'address': address,
                            'zip_code': zip_code,
                            'purchase_price': purchase_price,
                            'total_sf': build_sf,
                            'num_units': units,
                            'per_unit_sf': per_unit_sf,
                            'exit_psf': exit_psf,
                            'total_cost': total_cost,
                            'revenue': adjusted_revenue,
                            'profit': market_profit,
                            'margin_pct': (market_profit / total_cost * 100) if total_cost > 0 else 0,
                            'breakeven_psf': breakeven_psf,
                            'median_psf': median_psf if median_psf > 0 else result.market_stats.get('median_psf', 0),
                            'comp_count': result.market_stats.get('count', 0) or len(result.redfin_comps),
                            'risk_score': risk_score,
                            'verdict': verdict,
                            'listing_status': result.listing_status.get('status', 'Unknown') if hasattr(result, 'listing_status') else 'Unknown',
                            'zoning': 'N/A',
                            'monthly_rent': rent_per_unit * units,
                            'rental_noi': monthly_noi * 12,
                            # Top 5 sold comps summary
                            'top_comps': top_comps_text,
                            # Permit activity
                            'active_permits': len([p for p in result.street_permits if p.status == 'Active']),
                            'completed_permits': len([p for p in result.street_permits if p.status == 'Final']),
                            'permit_builders': ', '.join(set(p.builder for p in result.street_permits[:5] if p.builder != 'Unknown')),
                            # Hold model financials
                            'hold_months': hold_months,
                            'monthly_noi': monthly_noi,
                            'monthly_cf_after_debt': monthly_cf_after_debt,
                            'monthly_debt_service': monthly_debt_service,
                            'equity_multiple': equity_multiple,
                            'total_equity_invested': total_equity_invested,
                            'annualized_return': annualized_return * 100,
                            'cash_yield': cash_yield,
                            # Construction
                            'build_months': build_months,
                            'construction_interest': construction_interest,
                            'loan_amount': loan_amount,
                            'build_cost_psf': build_cost_psf,
                            # Census rental data
                            'census_median_rent': _census_median,
                            'census_rent_by_br': _census_by_br,
                        }
                        ai_text = generate_ai_summary(deal_data)
                        if ai_text:
                            # Escape $ signs so Streamlit doesn't render as LaTeX math
                            ai_text = ai_text.replace('$', '\\$')
                            st.markdown(ai_text)
                        else:
                            st.error("Could not generate AI analysis. Check your API key.")
        except Exception as e:
            st.error(f"AI Analysis error: {e}")

    # ── Download Tab ──
    with tab_download:
        st.subheader("Download Report")
        if result is not None:
            report_bytes = generate_report_bytes(
                result, address, zip_code, street_name,
                purchase_price, build_sf, exit_psf, build_cost_psf
            )
            st.download_button(
                label="📥 Download Word Report (.docx)",
                data=report_bytes,
                file_name=f"{street_name.title()}_St_Analysis.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary",
            )

            # Excel download
            try:
                _nsbd = net_sale_before_debt if hold_months > 0 else (user_revenue - exit_costs_user)
                _prcf = positive_rental_cf if hold_months > 0 else 0
                _nsad = net_sale_after_debt if hold_months > 0 else (user_revenue - exit_costs_user - loan_balance_after_hold)
                excel_bytes = generate_excel_bytes(
                units=units, per_unit_sf=per_unit_sf, build_sf=build_sf,
                purchase_price=purchase_price, build_cost_psf=build_cost_psf, exit_psf=exit_psf,
                build_months=build_months, hold_months=hold_months, delay_months=delay_months,
                hard_contingency_pct=hard_contingency_pct, soft_cost_pct=soft_cost_pct,
                soft_contingency=soft_contingency,
                ltv=ltv, interest_rate=interest_rate, draw_factor=draw_factor,
                loan_fee_pct=loan_fee_pct,
                perm_mortgage_rate=perm_mortgage_rate, amortization_years=amortization_years,
                rent_per_unit=rent_per_unit, vacancy_pct=vacancy_pct, mgmt_fee_pct=mgmt_fee_pct,
                prop_tax_rate=prop_tax_rate, taxable_value_psf=taxable_value_psf,
                insurance_monthly=insurance_monthly,
                repairs_per_unit=repairs_per_unit, common_utilities=common_utilities,
                leasing_reserve=leasing_reserve,
                exit_cost_pct=exit_cost_pct, price_decline=price_decline,
                split_soft=split_soft, arch_pct=arch_pct, eng_pct=eng_pct,
                permit_fee_pct=permit_fee_pct, survey_pct=survey_pct,
                insurance_dev_pct=insurance_dev_pct, other_soft_pct=other_soft_pct,
                broker_fee_pct=broker_fee_pct, title_closing_pct=title_closing_pct,
                seller_concessions_pct=seller_concessions_pct,
                const_tax_rate=const_tax_rate, const_insurance_annual=const_insurance_annual,
                const_utilities=const_utilities, const_misc=const_misc,
                carry_buffer_pct=carry_buffer_pct,
                staging_base=staging_base, staging_per_unit=staging_per_unit,
                marketing_base=marketing_base, marketing_per_unit=marketing_per_unit,
                warranty_per_unit=warranty_per_unit, sale_hold_months=sale_hold_months,
                hard_cost=hard_cost, hard_contingency=hard_contingency, soft_costs=soft_costs,
                total_dev_cost=total_dev_cost, total_project_cost=total_project_cost,
                loan_amount=loan_amount, equity=equity,
                construction_interest=construction_interest, loan_fees=loan_fees,
                hold_interest=hold_interest, gross_rent=gross_rent,
                effective_rent=effective_rent,
                total_hold_expenses=total_hold_expenses, net_rental_income=net_rental_income,
                monthly_debt_service=monthly_debt_service,
                loan_balance_after_hold=loan_balance_after_hold,
                total_equity_invested=total_equity_invested,
                user_profit=user_profit, user_revenue=user_revenue,
                breakeven_psf=breakeven_psf, exit_costs_user=exit_costs_user,
                total_cost=total_cost, equity_multiple=equity_multiple,
                additional_equity_needed=additional_equity_needed,
                cumulative_cf=cumulative_cf,
                net_sale_before_debt=_nsbd,
                net_sale_after_debt=_nsad,
                positive_rental_cf=_prcf,
                total_cash_returned=total_cash_returned,
                mgmt_cost=mgmt_cost, prop_tax=prop_tax, insurance=insurance,
                repairs=repairs, misc=misc, leasing=leasing,
                monthly_noi=monthly_noi, monthly_cf_after_debt=monthly_cf_after_debt,
            )
                st.download_button(
                    label="📥 Download Excel Model (.xlsx)",
                    data=excel_bytes,
                    file_name=f"{street_name.title()}_Hold_Model.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_excel",
                )
                st.caption("Contains 2 sheets: **Hold Model** + **Detailed Analysis**")
            except Exception as e:
                st.error(f"Excel generation error: {e}")
        else:
            st.warning("No data to generate report.")

        st.markdown("---")
        st.subheader("📊 Key Insights")
        st.markdown(f"""
        - **Break-even exit:** ${breakeven_psf:.0f}/sf
        - **Market median:** ${median_psf}/sf (Redfin, {result.market_stats.get('count', 0)} comps)
        - **Your exit:** ${exit_psf}/sf {'✅' if exit_psf <= median_psf else '⚠️'}
        - **This deal works IF:**
          - Purchase price ≤ ${max(0, purchase_price - (exit_psf - median_psf) * build_sf):,.0f} (or lower)
          - Exit ≥ ${breakeven_psf:.0f}/sf
          - No major delays beyond {delay_months} months
        """)

    # ── Audit Trail Tab ──
    with tab_audit:
        st.subheader("📐 Calculation Audit Trail")
        st.caption("Every intermediate calculation with formulas — verify the math is correct.")

        # ── Development Costs ──
        st.markdown("#### 🏗️ Development Costs")
        audit_dev = [
            ("Hard Cost", f"{build_sf:,} sf × \\${build_cost_psf}/sf", hard_cost),
            ("Hard Contingency", f"\\${hard_cost:,.0f} × {hard_contingency_pct}%", hard_contingency),
            ("Soft Costs", f"\\${hard_cost:,.0f} × {soft_cost_pct:.1f}%", soft_costs),
            ("Soft Contingency", "Fixed amount", soft_contingency),
            ("**Total Dev Cost**", f"\\${hard_cost:,.0f} + \\${hard_contingency:,.0f} + \\${soft_costs:,.0f} + \\${soft_contingency:,.0f}", total_dev_cost),
            ("**Total Project Cost**", f"\\${purchase_price:,.0f} (land) + \\${total_dev_cost:,.0f} (dev)", total_project_cost),
        ]
        audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
        for label, formula, value in audit_dev:
            audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
        st.markdown(audit_md)

        # ── Financing ──
        st.markdown("#### 💰 Financing")
        audit_fin = [
            ("Loan Amount (LTC)", f"\\${total_dev_cost:,.0f} × {ltv}%", loan_amount),
            ("Equity Required", f"\\${total_project_cost:,.0f} − \\${loan_amount:,.0f}", equity),
            ("Construction Interest", f"\\${loan_amount:,.0f} × {interest_rate}% × {draw_factor}% × {build_months + delay_months}/12 mo", construction_interest),
            ("Loan Fees (Points)", f"\\${loan_amount:,.0f} × {loan_fee_pct}%", loan_fees),
        ]
        audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
        for label, formula, value in audit_fin:
            audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
        st.markdown(audit_md)

        # ── Carry Costs ──
        st.markdown("#### 📅 Construction Carry Costs")
        audit_carry = [
            ("Carry Period", f"{build_months} build + {delay_months} delay", carry_months),
            ("Carry Loan Interest", f"(\\${purchase_price:,.0f} + \\${total_dev_cost:,.0f}) × {ltv}% × {interest_rate}% × {draw_factor}% × {carry_months}/12", carry_loan_interest),
            ("Carry Taxes", f"(\\${purchase_price:,.0f} + 50% × \\${total_dev_cost:,.0f}) × {const_tax_rate}% × {carry_months}/12", carry_taxes),
            ("Carry Insurance", f"\\${const_insurance_annual:,}/yr × {carry_months}/12", carry_insurance),
            ("Carry Utilities", f"\\${const_utilities:,}/mo × {carry_months} mo", carry_utilities),
            ("Carry Misc", f"\\${const_misc:,}/mo × {carry_months} mo", carry_misc),
            ("Carry Subtotal", "Sum of above", carry_subtotal),
            ("Carry Buffer", f"\\${carry_subtotal:,.0f} × {carry_buffer_pct}%", carry_buffer),
            ("**Total Carry**", f"\\${carry_subtotal:,.0f} + \\${carry_buffer:,.0f}", total_carry),
        ]
        audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
        for label, formula, value in audit_carry:
            if label == "Carry Period":
                audit_md += f"| {label} | {formula} | {value} months |\n"
            else:
                audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
        st.markdown(audit_md)

        # ── Sales Costs ──
        st.markdown("#### 💸 Sales / Exit Costs")
        audit_sales = [
            ("Exit Revenue (User)", f"{build_sf:,} sf × \\${exit_psf}/sf", user_revenue),
            ("Broker + Title + Concessions", f"\\${user_revenue:,.0f} × {exit_cost_pct:.1f}%", variable_sales),
            ("Staging", f"\\${staging_base:,} base + \\${staging_per_unit:,} × {units} units", staging_cost),
            ("Marketing", f"\\${marketing_base:,} base + \\${marketing_per_unit:,} × {units} units", marketing_cost),
            ("Warranty", f"\\${warranty_per_unit:,} × {units} units", warranty_cost),
            ("Holding During Sale", f"\\${total_carry:,.0f} / {max(carry_months, 1)} mo × {sale_hold_months} mo", holding_during_sale),
            ("**Total Sales Cost**", "Sum of above", total_sales_cost),
        ]
        audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
        for label, formula, value in audit_sales:
            audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
        st.markdown(audit_md)

        # ── Hold Period (if applicable) ──
        if hold_months > 0:
            st.markdown("#### 🏘️ Hold Period (Rental)")
            audit_hold = [
                ("Gross Rent", f"\\${rent_per_unit:,}/unit × {units} units × {hold_months} mo", gross_rent),
                ("Effective Rent", f"\\${gross_rent:,.0f} × (1 − {vacancy_pct}%)", effective_rent),
                ("Management Fee", f"\\${effective_rent:,.0f} × {mgmt_fee_pct}%", mgmt_cost),
                ("Property Tax (Hold)", f"{build_sf:,} sf × \\${taxable_value_psf}/sf × {prop_tax_rate}% × {hold_months}/12", prop_tax),
                ("Insurance (Hold)", f"\\${insurance_monthly:,}/mo × {hold_months} mo", insurance),
                ("Repairs Reserve", f"\\${repairs_per_unit:,}/unit/mo × {units} units × {hold_months} mo", repairs),
                ("Utilities/Misc", f"\\${common_utilities:,}/mo × {hold_months} mo", misc),
                ("Leasing Reserve", f"\\${leasing_reserve:,}/mo × {hold_months} mo", leasing),
                ("Debt Service (Hold)", f"\\${monthly_debt_service:,.0f}/mo × {hold_months} mo", hold_interest),
                ("**Total Hold Expenses**", "Sum of above", total_hold_expenses),
                ("**Net Rental Income**", f"\\${effective_rent:,.0f} − \\${total_hold_expenses:,.0f}", net_rental_income),
                ("Monthly NOI", f"(Eff. rent − OpEx) / {hold_months} mo", monthly_noi),
                ("Monthly CF After Debt", f"\\${monthly_noi:,.0f} − \\${monthly_debt_service:,.0f}", monthly_cf_after_debt),
                ("Loan Balance After Hold", "Amortized balance", loan_balance_after_hold),
            ]
            audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
            for label, formula, value in audit_hold:
                audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
            st.markdown(audit_md)

        # ── Final Profit ──
        st.markdown("#### 🎯 Profit Summary")
        audit_profit = [
            ("Total Equity Invested", "Land + Fees + Carry + Sales + Add'l Equity", total_equity_invested),
            ("User Revenue", f"{build_sf:,} sf × \\${exit_psf}/sf", user_revenue),
            ("**User Profit**", f"Cash returned − Equity invested", user_profit),
            ("Market Revenue", f"{build_sf:,} sf × \\${adjusted_exit:.0f}/sf (adj.)", adjusted_revenue),
            ("**Market Profit**", f"Market cash returned − Equity invested", market_profit),
            ("Break-Even $/sf", f"\\${total_equity_invested:,.0f} / {build_sf:,} sf", breakeven_psf),
            ("Equity Multiple", f"Cash returned / Equity invested", equity_multiple),
            ("Annualized Return", f"Over {timeline_years:.1f} years", annualized_return),
        ]
        audit_md = "| Item | Formula | Result |\n|------|---------|--------|\n"
        for label, formula, value in audit_profit:
            if label in ("Equity Multiple",):
                audit_md += f"| {label} | {formula} | {value:.2f}x |\n"
            elif label in ("Annualized Return",):
                audit_md += f"| {label} | {formula} | {value * 100:.1f}% |\n"
            elif label in ("Break-Even $/sf",):
                audit_md += f"| {label} | {formula} | \\${value:.0f}/sf |\n"
            else:
                audit_md += f"| {label} | {formula} | \\${value:,.0f} |\n"
        st.markdown(audit_md)

        # ── Benchmark Test ──
        st.markdown("---")
        st.subheader("🧪 Benchmark Test")
        st.caption("Verify calculations against a known deal with expected results.")

        if st.button("Run Benchmark — Karen Ave Test Deal", key="benchmark_btn"):
            # Known Karen Ave deal parameters
            bm = {}
            bm['purchase_price'] = 450000
            bm['build_sf'] = 3000
            bm['units'] = 2
            bm['build_cost_psf'] = 250
            bm['exit_psf'] = 575

            bm['hard_cost'] = bm['build_cost_psf'] * bm['build_sf']  # 750,000
            bm['hard_contingency_pct'] = 6.0
            bm['hard_contingency'] = bm['hard_cost'] * (bm['hard_contingency_pct'] / 100)  # 45,000
            bm['soft_cost_pct'] = 10.4
            bm['soft_costs'] = bm['hard_cost'] * (bm['soft_cost_pct'] / 100)  # 78,000
            bm['soft_contingency'] = 30000
            bm['total_dev_cost'] = bm['hard_cost'] + bm['hard_contingency'] + bm['soft_costs'] + bm['soft_contingency']  # 903,000
            bm['total_project_cost'] = bm['purchase_price'] + bm['total_dev_cost']  # 1,353,000

            bm['ltv'] = 100.0
            bm['loan_amount'] = bm['total_dev_cost'] * (bm['ltv'] / 100)  # 903,000
            bm['equity'] = bm['total_project_cost'] - bm['loan_amount']  # 450,000
            bm['interest_rate'] = 8.0
            bm['draw_factor'] = 62.5
            bm['loan_fee_pct'] = 1.0
            bm['loan_fees'] = bm['loan_amount'] * (bm['loan_fee_pct'] / 100)  # 9,030

            bm['build_months'] = 12
            bm['delay_months'] = 0
            bm['carry_months'] = 12
            bm['construction_interest'] = bm['loan_amount'] * (bm['interest_rate'] / 100) * (bm['draw_factor'] / 100) * bm['carry_months'] / 12  # 45,150

            bm['user_revenue'] = bm['exit_psf'] * bm['build_sf']  # 1,725,000

            # Expected values for verification
            expected = {
                "Hard Cost": (bm['hard_cost'], 750000),
                "Hard Contingency": (bm['hard_contingency'], 45000),
                "Soft Costs": (bm['soft_costs'], 78000),
                "Total Dev Cost": (bm['total_dev_cost'], 903000),
                "Total Project Cost": (bm['total_project_cost'], 1353000),
                "Loan Amount": (bm['loan_amount'], 903000),
                "Equity": (bm['equity'], 450000),
                "Construction Interest": (bm['construction_interest'], 45150),
                "Loan Fees": (bm['loan_fees'], 9030),
                "Exit Revenue": (bm['user_revenue'], 1725000),
            }

            all_pass = True
            results_md = "| Calculation | Computed | Expected | Status |\n|------------|---------|----------|--------|\n"
            for label, (computed, exp) in expected.items():
                passed = abs(computed - exp) < 1  # within $1 tolerance
                status = "✅ PASS" if passed else "❌ FAIL"
                if not passed:
                    all_pass = False
                results_md += f"| {label} | \\${computed:,.0f} | \\${exp:,.0f} | {status} |\n"

            st.markdown(results_md)

            if all_pass:
                st.success("✅ All benchmark calculations match expected values — financial model is verified.")
            else:
                st.error("❌ Some calculations don't match. Review the formulas above.")

    # ── RE Glossary Tab ──
    with tab_glossary:
        st.header("📖 Real Estate Investment Glossary")
        st.markdown("Common RE investment terms and how they map to this tool's calculations.")

        with st.expander("💰 Deal Analysis", expanded=True):
            st.markdown("""
**ARV (After Repair Value)** — The estimated market value of a property after all renovations are complete. In this tool: **Exit $/sf × Build SF** = your projected sale price.

**MAO (Maximum Allowable Offer)** — The highest price an investor should pay for a property. Calculated using the 70% Rule. In this tool: shown in the RE Metrics row.

**70% Rule** — A quick investor formula: **MAO = ARV × 70% − Rehab Costs**. If your purchase price is below MAO, the deal has built-in margin. This tool flags PASS/FAIL automatically.

**Rehab Costs** — All costs to renovate or build, excluding land. In this tool: **Hard Cost + Hard Contingency + Soft Costs + Soft Contingency** = Non-Land Dev Cost.

**Scope of Work (SOW)** — The detailed list of construction/renovation tasks and their costs. In this tool: represented by the Build Cost $/sf input and the Dev Cost breakdown table.
            """)

        with st.expander("📈 Returns"):
            st.markdown("""
**ROI (Return on Investment)** — Profit divided by total investment. In this tool: **Your Profit ÷ All-In Cost**.

**Cash-on-Cash Return** — Annual cash flow divided by total cash invested. Most relevant for hold/rental scenarios. In this tool: shown in RE Metrics row when hold months > 0.

**Equity Multiple** — Total cash returned divided by total cash invested. A 2.0x multiple means you doubled your money. In this tool: **Cash Returned ÷ Total Equity Invested**.

**Equity (Built)** — The difference between what a property is worth and what you owe on it. In a new build: **ARV − Loan Balance**.

**Appreciation** — The increase in property value over time. In this tool: modeled via the **Annual Price Change %** input in the sidebar.
            """)

        with st.expander("🏦 Financing"):
            st.markdown("""
**LTC (Loan-to-Cost)** — Loan amount as a percentage of total development cost. This is what construction lenders use. In this tool: the **LTC %** slider in the sidebar.

**LTV (Loan-to-Value)** — Loan amount as a percentage of the property's value (ARV). This is what permanent/refi lenders care about. In this tool: **Loan Amount ÷ ARV**, shown in RE Metrics.

**Hard Money Loan** — Short-term, high-interest loan (typically 10-15%) from private lenders, used for flips and construction. In this tool: detected when interest rate > 10%.

**Bridge Loan** — Short-term financing that "bridges" between purchase and permanent financing or sale. In this tool: detected when timeline < 24 months with rate > 8%.

**Points** — Upfront loan fees charged as a percentage of the loan amount. 1 point = 1% of loan. In this tool: the **Loan Fee %** input = points charged by the lender.
            """)

        with st.expander("💵 Costs"):
            st.markdown("""
**Holding/Carrying Costs** — Ongoing costs of owning a property during construction or while waiting to sell: loan interest, property taxes, insurance, utilities. In this tool: the **Carry Costs** line in the Deal Structure table.

**Closing Costs** — Fees paid at purchase and sale: title insurance, escrow, recording fees, transfer taxes. In this tool: modeled as **Title/Closing %** and **Seller Concessions %** in the Exit Costs section.
            """)

        with st.expander("📊 Market"):
            st.markdown("""
**DOM (Days on Market)** — How long a property was listed before selling. Low DOM = hot market, high DOM = slow market. In this tool: shown in the Sold Comps and Active Listings tables, with median DOM in the metrics row.

**Comps (Comparables)** — Recently sold properties similar to yours, used to estimate market value. In this tool: pulled automatically from Redfin within 1 mile, filtered by size (±30%) for the most relevant comparison.
            """)

        with st.expander("🚩 Property Flags"):
            st.markdown("""
**Distressed** — A property in poor condition or financial trouble, often sold below market value. Look for keywords in listing descriptions.

**Foreclosure** — Lender repossessing a property due to loan default. In this tool: detected via TCAD deed records in the CLI version.

**REO (Real Estate Owned)** — Bank-owned property after a failed foreclosure auction. Typically sold as-is at a discount.

**Probate / Estate Sale** — Property being sold as part of a deceased owner's estate. Often priced to sell quickly.

**Short Sale** — Sale where proceeds are less than the mortgage balance, requiring lender approval. Lengthy process but can offer discounts.

**Motivated Seller** — An owner who needs to sell quickly (relocation, divorce, financial distress). In this tool: flagged when active listing DOM > 120 days.
            """)

        with st.expander("🏠 Deal Types"):
            st.markdown("""
**Exit Strategy** — Your plan for the property: flip (sell after rehab), hold (rent), or wholesale (assign contract). In this tool: modeled via Hold Months — 0 = flip, >0 = hold/rent then sell.

**Assignment Fee** — In wholesaling, the fee earned by assigning your purchase contract to another buyer. Typically $5K-$25K.

**Wholesaling** — Finding deals under contract and assigning them to other investors for a fee, without actually buying the property.

**Fixer-Upper / TLC / As-Is** — Listing keywords indicating a property needs work. These are potential flip or development opportunities — exactly what this tool analyzes.
            """)

elif submitted and not show_analysis:
    # No address/ZIP — run financial-only mode
    st.info("💡 No address entered — showing financial analysis only. Add address + ZIP for market data, comps, and permits.")

    # Create a dummy result with no market data
    class EmptyResult:
        street_permits = []
        zip_permits = []
        redfin_comps = []
        market_stats = {}
        sources_status = {}
    result = EmptyResult()

    # ── Financial calculations (same as full mode) ──
    hard_cost = build_cost_psf * build_sf
    hard_contingency = hard_cost * (hard_contingency_pct / 100)
    soft_costs = hard_cost * (soft_cost_pct / 100)
    soft_contingency = 0
    total_dev_cost = hard_cost + hard_contingency + soft_costs + soft_contingency
    total_project_cost = purchase_price + total_dev_cost

    loan_amount = total_dev_cost * (ltv / 100)
    equity = total_project_cost - loan_amount
    total_build_months = build_months + delay_months
    construction_interest = loan_amount * (interest_rate / 100) * (total_build_months / 12) * (draw_factor / 100)
    loan_fees = loan_amount * (loan_fee_pct / 100)

    hold_interest = 0
    gross_rent = 0
    effective_rent = 0
    total_hold_expenses = 0
    net_rental_income = 0
    monthly_debt_service = 0
    loan_balance_after_hold = loan_amount
    if hold_months > 0:
        monthly_rent_total = rent_per_unit * units
        gross_rent = monthly_rent_total * hold_months
        effective_rent = gross_rent * (1 - vacancy_pct / 100)
        mgmt_expense = effective_rent * (mgmt_fee_pct / 100)
        prop_tax = build_sf * taxable_value_psf * (prop_tax_rate / 100) * hold_months / 12
        insurance = insurance_monthly * hold_months
        repairs = repairs_per_unit * units * hold_months
        misc = common_utilities * hold_months
        leasing = leasing_reserve * hold_months
        # Permanent mortgage debt service
        monthly_perm = perm_mortgage_rate / 100 / 12
        n_pay = amortization_years * 12
        if monthly_perm > 0:
            monthly_debt_service = loan_amount * (monthly_perm * (1 + monthly_perm) ** n_pay) / ((1 + monthly_perm) ** n_pay - 1)
            loan_balance_after_hold = loan_amount * (1 + monthly_perm) ** hold_months - monthly_debt_service * ((1 + monthly_perm) ** hold_months - 1) / monthly_perm
        else:
            monthly_debt_service = loan_amount / n_pay
            loan_balance_after_hold = loan_amount - (monthly_debt_service * hold_months)
        hold_interest = monthly_debt_service * hold_months
        total_hold_expenses = mgmt_expense + prop_tax + insurance + repairs + misc + leasing + hold_interest
        net_rental_income = effective_rent - total_hold_expenses

    total_interest = construction_interest + hold_interest
    timeline_years = (build_months + hold_months + delay_months) / 12

    median_psf = 0
    market_exit = exit_psf

    price_change_rate = price_decline / 100
    adjusted_exit = market_exit * ((1 + price_change_rate) ** timeline_years)
    adjusted_revenue = adjusted_exit * build_sf
    user_revenue = exit_psf * build_sf

    exit_costs_user = user_revenue * (exit_cost_pct / 100)
    exit_costs_market = adjusted_revenue * (exit_cost_pct / 100)
    total_cost = total_project_cost + total_interest + exit_costs_user
    market_total_cost = total_project_cost + total_interest + exit_costs_market
    market_profit = adjusted_revenue - market_total_cost + net_rental_income
    user_profit = user_revenue - total_cost + net_rental_income

    annual_rent = rent_per_unit * 12 * units
    cash_yield = (annual_rent / equity * 100) if equity > 0 else 0
    annualized_return = ((user_revenue / total_cost) ** (1 / max(timeline_years, 0.5)) - 1) if total_cost > 0 else 0
    breakeven_psf = (total_cost - net_rental_income) / build_sf if build_sf > 0 else 0

    # ── Display financial results ──
    st.subheader("📊 Deal Snapshot")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total All-In Cost", f"${total_cost:,.0f}")
    col2.metric("Sale Revenue", f"${user_revenue:,.0f}")
    col3.metric("Profit", f"${user_profit:,.0f}", delta=f"{annualized_return*100:.1f}% ann.")
    col4.metric("Break-Even", f"${breakeven_psf:.0f}/sf")

    if user_profit > 200000:
        st.success(f"✅ STRONG — \\${user_profit:,.0f} profit at \\${exit_psf}/sf exit")
    elif user_profit > 50000:
        st.warning(f"⚠️ MARGINAL — \\${user_profit:,.0f} profit, sensitive to delays/overruns")
    else:
        st.error(f"❌ WEAK/LOSS — \\${user_profit:,.0f} at \\${exit_psf}/sf exit")

    # Cost breakdown
    st.subheader("💰 Cost Breakdown")
    soft_line_fin = ""
    if split_soft:
        soft_line_fin = f"""| — Architecture & Design ({arch_pct}%) | ${hard_cost * arch_pct / 100:,.0f} |
    | — Engineering ({eng_pct}%) | ${hard_cost * eng_pct / 100:,.0f} |
    | — Permits & Impact Fees ({permit_fee_pct}%) | ${hard_cost * permit_fee_pct / 100:,.0f} |
    | — Surveys & Geotech ({survey_pct}%) | ${hard_cost * survey_pct / 100:,.0f} |
    | — Builder's Risk Insurance ({insurance_dev_pct}%) | ${hard_cost * insurance_dev_pct / 100:,.0f} |
    | — Other Soft ({other_soft_pct}%) | ${hard_cost * other_soft_pct / 100:,.0f} |
    | **Soft Costs Total ({soft_cost_pct:.1f}%)** | **${soft_costs:,.0f}** |"""
    else:
        soft_line_fin = f"| Soft Costs ({soft_cost_pct}%) | ${soft_costs:,.0f} |"
    st.markdown(f"""
    | Item | Amount |
    |------|--------|
    | Land / Purchase | ${purchase_price:,.0f} |
    | Hard Cost ({build_sf:,} sf × ${build_cost_psf}/sf) | ${hard_cost:,.0f} |
    | Hard Contingency ({hard_contingency_pct}%) | ${hard_contingency:,.0f} |
    {soft_line_fin}
    | Construction Interest | ${construction_interest:,.0f} |
    | Hold Debt Service ({hold_months} mo) | ${hold_interest:,.0f} |
    | **Sale Costs ({exit_cost_pct:.1f}%)** | **${exit_costs_user:,.0f}** |
    | — Broker/Agent ({broker_fee_pct}%) | ${user_revenue * broker_fee_pct / 100:,.0f} |
    | — Title + Closing ({title_closing_pct}%) | ${user_revenue * title_closing_pct / 100:,.0f} |
    | — Seller Concessions ({seller_concessions_pct}%) | ${user_revenue * seller_concessions_pct / 100:,.0f} |
    | **Total All-In** | **${total_cost:,.0f}** |
    """)

    if hold_months > 0:
        st.subheader("🏠 Rental Hold Detail")
        st.markdown(f"""
        | Item | Monthly | Total ({hold_months} mo) |
        |------|---------|---------|
        | Gross Rent ({units} × ${rent_per_unit:,}/mo) | ${rent_per_unit * units:,.0f} | ${gross_rent:,.0f} |
        | Less Vacancy ({vacancy_pct}%) | -${rent_per_unit * units * vacancy_pct / 100:,.0f} | -${gross_rent * vacancy_pct / 100:,.0f} |
        | Less Mgmt ({mgmt_fee_pct}%) | | -${effective_rent * mgmt_fee_pct / 100:,.0f} |
        | Less Property Tax ({prop_tax_rate}%) | | -${prop_tax:,.0f} |
        | Less Insurance/Repairs/Misc/Leasing | | -${insurance + repairs + misc + leasing:,.0f} |
        | Less Debt Service ({perm_mortgage_rate}%, {amortization_years}yr) | -${monthly_debt_service:,.0f} | -${hold_interest:,.0f} |
        | **Net Rental Income** | | **${net_rental_income:,.0f}** |
        """)

    # Sensitivity
    st.subheader("📈 Sensitivity — Exit $/sf vs Profit")
    exit_range = np.arange(max(200, int(breakeven_psf) - 100), int(breakeven_psf) + 200, 10)
    profits_by_exit = []
    for e in exit_range:
        rev = e * build_sf
        exit_c = rev * (exit_cost_pct / 100)
        profits_by_exit.append(rev - (total_project_cost + total_interest + exit_c) + net_rental_income)
    st.line_chart({"Exit $/sf": exit_range, "Profit": profits_by_exit}, x="Exit $/sf", y="Profit")
elif not show_analysis:
    # Landing page
    st.markdown("""
    ### 🏡 How It Works

    1. **Enter property details** in the sidebar (address, ZIP, deal numbers)
    2. **Click "Analyze"** — the app pulls real market data automatically
    3. **Get a clear BUY / CAUTION / DON'T BUY verdict**

    ### What Makes This Different

    | Feature | Generic Calculator | This App |
    |---------|-------------------|----------|
    | Market comps | ❌ You guess | ✅ Pulls from Redfin |
    | Permit data | ❌ None | ✅ Austin permits API |
    | Competition check | ❌ None | ✅ Same-street construction |
    | Risk scoring | ❌ None | ✅ Automated 0-100 score |
    | BUY/DON'T BUY | ❌ None | ✅ Clear recommendation |
    | Sensitivity analysis | ✅ Manual | ✅ Auto with real median |

    > **Pro tip:** For complete analysis including TCAD records, deed history,
    > and foreclosure detection, run the CLI tool locally:
    > ```
    > python analyze_deal.py "ADDRESS" --zip XXXXX --purchase-price N
    > ```
    """)
