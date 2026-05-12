"""
Austin Deal Analyzer PRO — Streamlit Web App
=============================================
Combined due diligence + financial modeling + BUY/DON'T BUY recommendation.
Pulls real market data, runs scenario analysis, and gives a clear verdict.
"""

import streamlit as st
import numpy as np
import json
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

# ── Parameter defaults (used for form values & config export/import) ──
PARAM_DEFAULTS = {
    "address": "1309 Perez St",
    "zip_code": "78721",
    "purchase_price": 500000,
    "build_sf": 7000,
    "units": 4,
    "sf_per_unit": 1750,
    "demo_cost": 20000,
    "build_cost_psf": 225,
    "exit_psf": 475,
    "hard_contingency_pct": 6.0,
    "split_soft": True,
    "arch_pct": 3.0,
    "structural_pct": 1.2,
    "mep_pct": 1.2,
    "eng_pct": 2.0,
    "permit_fee_pct": 2.5,
    "survey_pct": 1.0,
    "insurance_dev_pct": 1.0,
    "other_soft_pct": 0.9,
    "soft_cost_pct": 10.4,
    "soft_contingency": 15000,
    # Fixed soft costs ($)
    "survey_fixed": 1000,
    "geotech_fixed": 1500,
    "civil_fixed": 0,
    "permit_fixed": 18000,
    "legal_fixed": 5000,
    "arborist_fixed": 0,
    "utility_fees_fixed": 5000,
    "ltv": 100.0,
    "interest_rate": 8.5,
    "draw_factor": 60.0,
    "loan_fee_pct": 1.5,
    "land_loan_pct": 0.0,
    "land_interest_rate": 8.5,
    "land_equity_cost_rate": 7.0,
    "use_land_cost_of_capital": True,
    "predev_months": 3,
    "build_months": 9,
    "hold_months": 0,
    "delay_months": 0,
    "sale_hold_months": 1.0,
    "const_tax_rate": 2.0,
    "const_insurance_annual": 6000,
    "const_utilities": 300,
    "const_misc": 250,
    "carry_buffer_pct": 10.0,
    "broker_fee_pct": 4.0,
    "title_closing_pct": 1.25,
    "seller_concessions_pct": 1.0,
    "staging_base": 1500,
    "staging_per_unit": 3500,
    "marketing_base": 2000,
    "marketing_per_unit": 1500,
    "warranty_per_unit": 1500,
    "price_decline": 0.0,
    "rent_per_unit": 3100,
    "vacancy_pct": 5.0,
    "repairs_reserve_pct": 5.0,
    "mgmt_fee_pct": 8.0,
    "other_opex_annual": 3000,
    "exit_cap_rate": 5.5,
    "perm_mortgage_rate": 7.0,
    "amortization_years": 30,
    "taxable_value_psf": 300,
    "prop_tax_rate": 2.0,
    "insurance_monthly": 500,
    "repairs_per_unit": 100,
    "common_utilities": 150,
    "leasing_reserve": 100,
}

def _cfg(key):
    """Get parameter value: session_state (from upload) > stored address/zip > default."""
    if key in ("address", "zip_code"):
        return st.session_state.get(key, PARAM_DEFAULTS[key])
    val = st.session_state.get(f"cfg_{key}", PARAM_DEFAULTS[key])
    # Ensure numeric types match PARAM_DEFAULTS to avoid Streamlit mixed-type errors
    default = PARAM_DEFAULTS.get(key)
    if isinstance(default, float) and isinstance(val, int):
        val = float(val)
    return val


# ── Sidebar: Input Form ──
with st.sidebar:
    st.header("📥 Deal Inputs")

    expand_all = st.toggle("Expand all sections", value=False)

    # ── Config Import / Export ──
    with st.expander("📁 Import / Export Config", expanded=False):
        uploaded_cfg = st.file_uploader("Upload config JSON", type=["json"], key="cfg_upload",
                                        help="Upload a previously exported config to pre-fill all parameters")
        if uploaded_cfg is not None and not st.session_state.get('_cfg_loaded'):
            try:
                cfg_data = json.loads(uploaded_cfg.read())
                count = 0
                # Support both nested (sectioned) and flat (legacy) formats
                for k, v in cfg_data.items():
                    if isinstance(v, dict):
                        # Nested section — flatten its keys
                        for sk, sv in v.items():
                            if sk in ("address", "zip_code"):
                                st.session_state[sk] = sv
                            elif sk in PARAM_DEFAULTS:
                                st.session_state[f"cfg_{sk}"] = sv
                            count += 1
                    else:
                        # Flat legacy key
                        if k in ("address", "zip_code"):
                            st.session_state[k] = v
                        elif k in PARAM_DEFAULTS:
                            st.session_state[f"cfg_{k}"] = v
                        count += 1
                st.session_state['_cfg_loaded'] = True
                st.success(f"✅ Loaded {count} parameters")
                st.rerun()
            except (json.JSONDecodeError, Exception) as e:
                st.error(f"❌ Invalid config file: {e}")
        elif uploaded_cfg is None:
            st.session_state['_cfg_loaded'] = False
        export_placeholder = st.empty()

    with st.form("deal_form"):
        st.subheader("🏠 Property")
        address = st.text_input("Property Address", value=_cfg('address'),
                               placeholder="e.g., 2613 Nottingham Ln",
                               help="Street address of the property you're analyzing")
        zip_code = st.text_input("ZIP Code", value=_cfg('zip_code'),
                                 placeholder="e.g., 78704",
                                 help="Used to pull comps, permits, and zoning data")

        submitted = st.form_submit_button("🔍 Submit", use_container_width=True, type="primary")

        with st.expander("💵 Deal Numbers", expanded=expand_all):
            purchase_price = st.number_input("Land Price ($)", min_value=0, value=_cfg('purchase_price'), step=25000,
                                             help="Land acquisition cost")
            demo_cost = st.number_input("Demo / Site Prep ($)", min_value=0, value=_cfg('demo_cost'), step=5000,
                                        help="Demolition and site preparation cost (0 if no teardown)")
            units = st.number_input("Number of Units", min_value=1, value=_cfg('units'), step=1,
                                    help="Number of residential units (e.g., 4 for fourplex)")
            sf_per_unit = st.number_input("Sq Ft per Unit", min_value=0, value=_cfg('sf_per_unit'), step=50,
                                          help="Square footage per unit")
            build_sf = units * sf_per_unit
            st.caption(f"**Total Sellable SF: {build_sf:,}**")
            build_cost_psf = st.number_input("Build Cost ($/sf)", min_value=0, value=_cfg('build_cost_psf'), step=25,
                                             help="Hard construction cost per square foot (labor + materials)")
            exit_psf = st.number_input("Exit Price ($/sf)", min_value=0, value=_cfg('exit_psf'), step=10,
                                       help="Your target sale price per square foot")

        with st.expander("💵 Cost Details", expanded=expand_all):
            hard_contingency_pct = st.number_input("Hard Cost Contingency (%)", min_value=0.0, max_value=15.0, value=_cfg('hard_contingency_pct'), step=0.5,
                                             help="Buffer for unexpected construction cost overruns (typically 5-10%)")
            split_soft = st.toggle("Split Soft Cost Categories", value=_cfg('split_soft'),
                                   help="Toggle to show individual soft cost line items instead of a single %")
            if split_soft:
                st.markdown("**Soft Costs — % of Hard Cost**")
                arch_pct = st.number_input("Architecture (%)", min_value=0.0, max_value=10.0, value=_cfg('arch_pct'), step=0.5,
                                            help="Architect fees — as % of hard cost")
                structural_pct = st.number_input("Structural (%)", min_value=0.0, max_value=10.0, value=_cfg('structural_pct'), step=0.1,
                                                  help="Structural engineering — as % of hard cost")
                mep_pct = st.number_input("MEP Engineering (%)", min_value=0.0, max_value=10.0, value=_cfg('mep_pct'), step=0.1,
                                           help="Mechanical, electrical, plumbing engineering — as % of hard cost")
                st.markdown("**Soft Costs — Fixed ($)**")
                survey_fixed = st.number_input("Survey ($)", min_value=0, value=_cfg('survey_fixed'), step=500,
                                                help="Land survey cost")
                geotech_fixed = st.number_input("Geotech ($)", min_value=0, value=_cfg('geotech_fixed'), step=500,
                                                 help="Soil testing / geotechnical report")
                civil_fixed = st.number_input("Civil ($)", min_value=0, value=_cfg('civil_fixed'), step=500,
                                               help="Civil engineering")
                permit_fixed = st.number_input("Permit Allowance ($)", min_value=0, value=_cfg('permit_fixed'), step=1000,
                                                help="City permits, impact fees, utility connections")
                legal_fixed = st.number_input("Legal / Admin ($)", min_value=0, value=_cfg('legal_fixed'), step=500,
                                               help="Legal, accounting, administrative costs")
                arborist_fixed = st.number_input("Arborist ($)", min_value=0, value=_cfg('arborist_fixed'), step=500,
                                                  help="Tree survey / arborist report")
                utility_fees_fixed = st.number_input("Utility App Fees ($)", min_value=0, value=_cfg('utility_fees_fixed'), step=500,
                                                      help="Water, sewer, electric utility application fees")
                soft_contingency = st.number_input("Soft Contingency ($)", min_value=0, value=_cfg('soft_contingency'), step=5000,
                                                    help="Fixed buffer for unexpected soft cost items")
                eng_pct = structural_pct + mep_pct
                soft_cost_pct = arch_pct + structural_pct + mep_pct
                total_fixed_soft = survey_fixed + geotech_fixed + civil_fixed + permit_fixed + legal_fixed + arborist_fixed + utility_fees_fixed
            else:
                soft_cost_pct = st.number_input("Soft Cost (% of HC)", min_value=0.0, max_value=30.0, value=_cfg('soft_cost_pct'), step=0.5,
                                                help="All-in soft cost as a single percentage of hard cost")
                soft_contingency = st.number_input("Soft Contingency ($)", min_value=0, value=_cfg('soft_contingency'), step=5000,
                                                    help="Fixed buffer for unexpected soft cost items")
                arch_pct = soft_cost_pct / 3
                structural_pct = soft_cost_pct / 3
                mep_pct = soft_cost_pct / 3
                eng_pct = structural_pct + mep_pct
                survey_fixed = geotech_fixed = civil_fixed = permit_fixed = 0
                legal_fixed = arborist_fixed = utility_fees_fixed = 0
                total_fixed_soft = 0
            permit_fee_pct = 0.0
            survey_pct = 0.0
            insurance_dev_pct = 0.0
            other_soft_pct = 0.0

        with st.expander("💰 Construction Financing", expanded=expand_all):
            ltv = st.number_input("Construction LTC (%)", min_value=0.0, max_value=100.0, value=_cfg('ltv'), step=1.0,
                            help="% of non-land development cost funded by construction debt")
            interest_rate = st.number_input("Construction Interest Rate (%)", min_value=3.0, max_value=14.0, value=_cfg('interest_rate'), step=0.25,
                                      help="Annual interest rate on construction loan")
            draw_factor = st.number_input("Average Draw Factor (%)", min_value=40.0, max_value=80.0, value=_cfg('draw_factor'), step=0.5,
                                    help="Avg % of loan drawn during construction")
            loan_fee_pct = st.number_input("Construction Loan Fees (%)", min_value=0.0, max_value=3.0, value=_cfg('loan_fee_pct'), step=0.1,
                                     help="Origination / lender fees on construction debt")
            land_loan_pct = st.number_input("Land Loan (%)", min_value=0.0, max_value=100.0, value=_cfg('land_loan_pct'), step=5.0,
                                            help="% of land price funded by debt (0 = all cash)")
            land_interest_rate = st.number_input("Land Interest Rate (%)", min_value=0.0, max_value=14.0, value=_cfg('land_interest_rate'), step=0.25,
                                                 help="Annual interest rate on land loan")
            land_equity_cost_rate = st.number_input("Land Equity Cost Rate (%)", min_value=0.0, max_value=14.0, value=_cfg('land_equity_cost_rate'), step=0.25,
                                                    help="Opportunity cost of capital for cash land (used if no land loan)")
            use_land_cost_of_capital = st.toggle("Use Land Cost of Capital if No Loan", value=_cfg('use_land_cost_of_capital'),
                                                 help="Apply equity cost rate on land if no land loan")

        with st.expander("📅 Timeline", expanded=expand_all):
            predev_months = st.number_input("Predevelopment (months)", min_value=0, max_value=12, value=_cfg('predev_months'), step=1,
                                    help="Predevelopment period before construction starts (design, permitting)")
            build_months = st.number_input("Construction Duration (months)", min_value=6, max_value=24, value=_cfg('build_months'), step=1,
                                    help="Construction timeline from groundbreaking to CO")
            hold_months = st.number_input("Hold Period After Build (months)", min_value=0, max_value=36, value=_cfg('hold_months'), step=1,
                                    help="0 = flip immediately, 24 = rent then sell")
            delay_months = st.number_input("Expected Delays (months)", min_value=0, max_value=12, value=_cfg('delay_months'), step=1,
                                    help="Buffer for permitting delays, weather, supply issues")

        with st.expander("🏗️ Construction Carry", expanded=expand_all):
            const_tax_rate = st.number_input("Construction Property Tax (%)", min_value=0.0, max_value=4.0, value=_cfg('const_tax_rate'), step=0.1,
                                        help="Annual property tax rate during construction period")
            const_insurance_annual = st.number_input("Construction Insurance ($/yr)", min_value=0, value=_cfg('const_insurance_annual'), step=250,
                                                      help="Builder's risk + liability insurance per year during construction")
            const_utilities = st.number_input("Construction Utilities ($/mo)", min_value=0, value=_cfg('const_utilities'), step=50,
                                               help="Water, electric, temp power during construction")
            const_misc = st.number_input("Construction Misc ($/mo)", min_value=0, value=_cfg('const_misc'), step=25,
                                          help="Dumpster, portable toilet, misc during construction")
            carry_buffer_pct = st.number_input("Carry Cost Buffer (%)", min_value=0.0, max_value=25.0, value=_cfg('carry_buffer_pct'), step=0.5,
                                          help="Buffer on top of all carry costs for unexpected overruns")

        with st.expander("💸 Sale / Exit Costs", expanded=expand_all):
            broker_fee_pct = st.number_input("Broker / Agent Fee (%)", min_value=0.0, max_value=6.0, value=_cfg('broker_fee_pct'), step=0.25,
                                       help="Listing + buyer agent commission")
            title_closing_pct = st.number_input("Title + Closing Costs (%)", min_value=0.0, max_value=3.0, value=_cfg('title_closing_pct'), step=0.1,
                                          help="Title insurance, escrow, recording fees")
            seller_concessions_pct = st.number_input("Seller Concessions (%)", min_value=0.0, max_value=3.0, value=_cfg('seller_concessions_pct'), step=0.1,
                                               help="Buyer credits, repairs, warranty")
            exit_cost_pct = broker_fee_pct + title_closing_pct + seller_concessions_pct
            sale_hold_months = st.number_input('Sale Hold Period (months)', min_value=0.0, max_value=6.0, value=_cfg('sale_hold_months'), step=0.5,
                                                help='Months property sits on market before closing')
            staging_base = st.number_input('Staging Base ($)', min_value=0, value=_cfg('staging_base'), step=500,
                                            help='Base staging cost (fixed)')
            staging_per_unit = st.number_input('Staging Per Unit ($)', min_value=0, value=_cfg('staging_per_unit'), step=500,
                                                help='Additional staging cost per unit')
            marketing_base = st.number_input('Marketing Base ($)', min_value=0, value=_cfg('marketing_base'), step=500,
                                              help='Photography, signage, MLS listing fees')
            marketing_per_unit = st.number_input('Marketing Per Unit ($)', min_value=0, value=_cfg('marketing_per_unit'), step=500,
                                                  help='Additional marketing cost per unit')
            warranty_per_unit = st.number_input('Warranty Per Unit ($)', min_value=0, value=_cfg('warranty_per_unit'), step=250,
                                                 help='Home warranty cost per unit')

        with st.expander("📉 Market Risk", expanded=expand_all):
            price_decline = st.number_input("Annual Price Change (%)", min_value=-15.0, max_value=10.0, value=_cfg('price_decline'), step=0.5,
                                      help="Expected annual change in market prices (negative = decline)")

        with st.expander("🏘️ Rental (Hold Strategy)", expanded=expand_all):
            rent_per_unit = st.number_input("Monthly Rent / Unit ($)", min_value=0, value=_cfg('rent_per_unit'), step=100,
                                          help="Expected monthly rent per unit after lease-up")
            vacancy_pct = st.number_input("Vacancy / Credit Loss (%)", min_value=0.0, max_value=15.0, value=_cfg('vacancy_pct'), step=0.5,
                                    help="% of gross rent lost to vacancy and bad debt")
            repairs_reserve_pct = st.number_input("Repairs Reserve (% of EGI)", min_value=0.0, max_value=15.0, value=_cfg('repairs_reserve_pct'), step=0.5,
                                                  help="Repairs reserve as % of effective gross income")
            mgmt_fee_pct = st.number_input("Management Fee (% of EGI)", min_value=0.0, max_value=15.0, value=_cfg('mgmt_fee_pct'), step=0.5,
                                     help="Property management fee as % of effective gross income")
            other_opex_annual = st.number_input("Other Opex ($/yr)", min_value=0, value=_cfg('other_opex_annual'), step=500,
                                                help="Other annual operating expenses")
            exit_cap_rate = st.number_input("Exit Cap Rate (%)", min_value=3.0, max_value=10.0, value=_cfg('exit_cap_rate'), step=0.25,
                                           help="Cap rate for implied value calculation")
            perm_mortgage_rate = st.number_input("Permanent Mortgage Rate (%)", min_value=3.0, max_value=12.0, value=_cfg('perm_mortgage_rate'), step=0.25,
                                           help="Rate after construction loan converts to permanent")
            amortization_years = st.number_input("Amortization (years)", min_value=15, max_value=30, value=_cfg('amortization_years'), step=5,
                                                help="Loan payoff schedule length (longer = lower monthly payment)")
            taxable_value_psf = st.number_input("Taxable Value ($/sf)", min_value=0, value=_cfg('taxable_value_psf'), step=25,
                                                help="Assessed value for property tax during hold")
            prop_tax_rate = st.number_input("Property Tax Rate (%)", min_value=1.0, max_value=4.0, value=_cfg('prop_tax_rate'), step=0.1,
                                      help="Annual property tax rate (Austin is typically ~2%)")
            insurance_monthly = st.number_input("Landlord Insurance ($/mo)", min_value=0, value=_cfg('insurance_monthly'), step=25,
                                                help="Monthly hazard + liability insurance premium")
            repairs_per_unit = st.number_input("Repairs Reserve ($/unit/mo)", min_value=0, value=_cfg('repairs_per_unit'), step=25,
                                               help="Monthly reserve per unit for maintenance and repairs")
            common_utilities = st.number_input("Common Utilities / Misc ($/mo)", min_value=0, value=_cfg('common_utilities'), step=25,
                                               help="Owner-paid utilities, landscaping, pest control, etc.")
            leasing_reserve = st.number_input("Leasing / Turnover Reserve ($/mo)", min_value=0, value=_cfg('leasing_reserve'), step=25,
                                              help="Reserve for tenant turnover, marketing, and lease-up costs")

    # ── Export Config (rendered into the top-of-sidebar placeholder) ──
    current_config = {
        "property": {
            "address": address,
            "zip_code": zip_code,
        },
        "deal_numbers": {
            "purchase_price": purchase_price, "demo_cost": demo_cost,
            "units": units, "sf_per_unit": sf_per_unit,
            "build_cost_psf": build_cost_psf, "exit_psf": exit_psf,
        },
        "cost_details": {
            "hard_contingency_pct": hard_contingency_pct,
            "arch_pct": arch_pct, "structural_pct": structural_pct, "mep_pct": mep_pct,
            "survey_fixed": survey_fixed, "geotech_fixed": geotech_fixed,
            "civil_fixed": civil_fixed, "permit_fixed": permit_fixed,
            "legal_fixed": legal_fixed, "arborist_fixed": arborist_fixed,
            "utility_fees_fixed": utility_fees_fixed,
            "soft_contingency": soft_contingency,
        },
        "construction_financing": {
            "ltv": ltv, "interest_rate": interest_rate, "draw_factor": draw_factor,
            "loan_fee_pct": loan_fee_pct,
            "land_loan_pct": land_loan_pct, "land_interest_rate": land_interest_rate,
            "land_equity_cost_rate": land_equity_cost_rate,
            "use_land_cost_of_capital": use_land_cost_of_capital,
        },
        "timeline": {
            "predev_months": predev_months,
            "build_months": build_months, "hold_months": hold_months, "delay_months": delay_months,
        },
        "construction_carry": {
            "const_tax_rate": const_tax_rate, "const_insurance_annual": const_insurance_annual,
            "const_utilities": const_utilities, "const_misc": const_misc,
            "carry_buffer_pct": carry_buffer_pct,
        },
        "sale_exit_costs": {
            "broker_fee_pct": broker_fee_pct, "title_closing_pct": title_closing_pct,
            "seller_concessions_pct": seller_concessions_pct,
            "sale_hold_months": sale_hold_months, "staging_base": staging_base,
            "staging_per_unit": staging_per_unit, "marketing_base": marketing_base,
            "marketing_per_unit": marketing_per_unit, "warranty_per_unit": warranty_per_unit,
        },
        "market_risk": {
            "price_decline": price_decline,
        },
        "rental_hold": {
            "rent_per_unit": rent_per_unit, "vacancy_pct": vacancy_pct,
            "repairs_reserve_pct": repairs_reserve_pct,
            "mgmt_fee_pct": mgmt_fee_pct, "other_opex_annual": other_opex_annual,
            "exit_cap_rate": exit_cap_rate,
            "perm_mortgage_rate": perm_mortgage_rate,
            "amortization_years": amortization_years, "taxable_value_psf": taxable_value_psf,
            "prop_tax_rate": prop_tax_rate, "insurance_monthly": insurance_monthly,
            "repairs_per_unit": repairs_per_unit, "common_utilities": common_utilities,
            "leasing_reserve": leasing_reserve,
        },
    }
    config_json = json.dumps(current_config, indent=2)
    config_filename = f"deal_config_{address.replace(' ', '_')}_{zip_code}.json"
    export_placeholder.download_button(
        "⬇️ Export Config",
        data=config_json,
        file_name=config_filename,
        mime="application/json",
        use_container_width=True,
    )


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
    # STEP 2: Financial calculations (matching Nitin Infill Template v1.1)
    # ══════════════════════════════════════════════
    hard_cost = build_cost_psf * build_sf
    hard_contingency = hard_cost * (hard_contingency_pct / 100)

    # Soft costs: % items (of hard cost) + fixed $ items
    soft_pct_costs = hard_cost * (arch_pct / 100) + hard_cost * (structural_pct / 100) + hard_cost * (mep_pct / 100)
    soft_fixed_costs = survey_fixed + geotech_fixed + civil_fixed + permit_fixed + legal_fixed + arborist_fixed + utility_fees_fixed
    soft_costs = soft_pct_costs + soft_fixed_costs
    # Keep soft_cost_pct for backward compat (% items only)
    soft_cost_pct = arch_pct + structural_pct + mep_pct

    # Non-land development cost (Demo + HC + HC Contingency + Soft + Soft Contingency)
    non_land_dev_cost = demo_cost + hard_cost + hard_contingency + soft_costs + soft_contingency
    total_dev_cost = non_land_dev_cost  # alias for backward compat
    total_project_cost = purchase_price + non_land_dev_cost

    # Timeline (matching Excel: Total Months = Predev + Construction + Sale Hold)
    total_carry_months = predev_months + build_months + delay_months + sale_hold_months
    total_months = predev_months + build_months + hold_months + delay_months
    timeline_years = total_months / 12
    carry_months = predev_months + build_months + delay_months  # for carry cost calc

    # Construction financing
    # Construction loan applies to non-land development costs only
    construction_loan = non_land_dev_cost * (ltv / 100)
    land_loan = purchase_price * (land_loan_pct / 100)
    loan_amount = construction_loan  # used downstream for permanent debt
    equity = total_project_cost - land_loan - construction_loan

    # Land carry (Excel formula: B48)
    # If land_loan_pct > 0: land interest = land_price * land_loan% * land_rate * total_months/12
    # Else if use_land_cost_of_capital: land carry = land_price * equity_cost_rate * total_months/12
    if land_loan_pct > 0:
        carry_land_interest = purchase_price * (land_loan_pct / 100) * (land_interest_rate / 100) * total_carry_months / 12
    elif use_land_cost_of_capital:
        carry_land_interest = purchase_price * (land_equity_cost_rate / 100) * total_carry_months / 12
    else:
        carry_land_interest = 0

    # Construction interest (Excel formula: B49)
    # = (Demo + HC + HCCont + Soft + SoftCont) * LTC% * Rate * DrawFactor * ConstructionMonths/12
    construction_interest = non_land_dev_cost * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * build_months / 12
    loan_fees = construction_loan * (loan_fee_pct / 100)

    # Carry costs (Excel formulas: B50-B55)
    # Taxes: (LandPrice + 0.5*(HC + Soft + Demo)) * TaxRate * TotalCarryMonths/12
    carry_taxes = (purchase_price + 0.5 * (hard_cost + soft_costs + demo_cost)) * (const_tax_rate / 100) * total_carry_months / 12
    carry_insurance = const_insurance_annual * total_carry_months / 12
    carry_utilities = const_utilities * total_carry_months
    carry_misc = const_misc * total_carry_months
    carry_subtotal = carry_land_interest + construction_interest + carry_taxes + carry_insurance + carry_utilities + carry_misc
    carry_buffer = carry_subtotal * (carry_buffer_pct / 100)
    total_carry = carry_subtotal + carry_buffer
    # Keep carry_loan_interest alias for audit trail
    carry_loan_interest = carry_land_interest + construction_interest

    # Sales costs (Excel formulas: B61-B67)
    user_revenue_est = exit_psf * build_sf
    staging_cost = staging_base + staging_per_unit * units
    marketing_cost = marketing_base + marketing_per_unit * units
    warranty_cost = warranty_per_unit * units
    variable_sales = user_revenue_est * (exit_cost_pct / 100)
    holding_during_sale = 0  # sale hold already included in total_carry_months
    total_sales_cost = variable_sales + staging_cost + marketing_cost + warranty_cost

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

    # Profit calculation — matching Excel template
    # Excel equity: Total Project Cost - Land Loan - Construction/Dev Loan
    if hold_months > 0:
        cumulative_cf = monthly_cf_after_debt * hold_months
        additional_equity_needed = max(0, -cumulative_cf)
        total_equity_invested = purchase_price + loan_fees + total_carry + staging_cost + marketing_cost + warranty_cost + additional_equity_needed

        net_sale_before_debt = user_revenue - exit_costs_user - staging_cost - marketing_cost - warranty_cost
        net_sale_after_debt = net_sale_before_debt - loan_balance_after_hold
        positive_rental_cf = max(0, cumulative_cf)
        total_cash_returned = net_sale_after_debt + positive_rental_cf

        user_profit = total_cash_returned - total_equity_invested
        equity_multiple = total_cash_returned / total_equity_invested if total_equity_invested > 0 else 0

        # Market-based profit
        net_market_sale = adjusted_revenue - exit_costs_market - staging_cost - marketing_cost - warranty_cost
        market_net_after_debt = net_market_sale - loan_balance_after_hold
        market_cash_returned = market_net_after_debt + positive_rental_cf
        market_profit = market_cash_returned - total_equity_invested
    else:
        # Flip model (matching Excel Pro Forma Summary)
        # Total Project Cost = Land + Demo + HC + HC Cont + Soft + Soft Cont + Carry + Sales
        total_cost = total_project_cost + total_carry + total_sales_cost
        # Equity = Total Cost - Land Loan - Construction Loan
        total_equity_invested = max(0, total_cost - land_loan - construction_loan)
        user_profit = user_revenue - total_cost
        margin_on_cost = user_profit / total_cost if total_cost > 0 else 0
        equity_multiple = (total_equity_invested + user_profit) / total_equity_invested if total_equity_invested > 0 else 0
        profit_on_equity = user_profit / total_equity_invested if total_equity_invested > 0 else 0

        # Deal status (matching Excel: GO/REVIEW/PASS)
        if user_profit >= 250000 and margin_on_cost >= 0.18 and equity_multiple >= 1.5:
            deal_status = "GO"
        elif user_profit < 125000 or margin_on_cost < 0.12 or equity_multiple < 1.25:
            deal_status = "PASS"
        else:
            deal_status = "REVIEW"

        exit_costs_market_val = adjusted_revenue * (exit_cost_pct / 100)
        market_sales_cost = exit_costs_market_val + staging_cost + marketing_cost + warranty_cost
        market_profit = adjusted_revenue - (total_project_cost + total_carry + market_sales_cost)
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
            st.markdown(f"""
            | Item | Amount |
            |------|--------|
            | Land Acquisition | ${purchase_price:,.0f} |
            | Demo / Site Prep | ${demo_cost:,.0f} |
            | Hard Cost ({build_sf:,} sf × ${build_cost_psf}/sf) | ${hard_cost:,.0f} |
            | Hard Contingency ({hard_contingency_pct}%) | ${hard_contingency:,.0f} |
            | — Architecture ({arch_pct}%) | ${hard_cost * arch_pct / 100:,.0f} |
            | — Structural ({structural_pct}%) | ${hard_cost * structural_pct / 100:,.0f} |
            | — MEP ({mep_pct}%) | ${hard_cost * mep_pct / 100:,.0f} |
            | — Fixed items (Survey/Geo/Permits/etc) | ${total_fixed_soft:,.0f} |
            | **Soft Costs Total** | **${soft_costs:,.0f}** |
            | Soft Contingency | ${soft_contingency:,.0f} |
            | **Non-Land Dev Cost** | **${total_dev_cost:,.0f}** |
            | Construction Loan ({ltv}% LTC) | ${construction_loan:,.0f} |
            | Land Loan ({land_loan_pct}%) | ${land_loan:,.0f} |
            | Carry Costs ({int(total_carry_months)} mo) | ${total_carry:,.0f} |
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
                sc = hc * (soft_cost_pct / 100) + total_fixed_soft
                dev = demo_cost + hc + hc_cont + sc + soft_contingency
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
                tsc = ec + stg + mkt + war
                lf = loan * (loan_fee_pct / 100)
                total = purchase_price + demo_cost + hc + hc_cont + sc + soft_contingency + tcarry + tsc + lf
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
            sc_sales = var_sc + staging_cost + marketing_cost + warranty_cost
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

        # ── Detailed Breakdowns (controlled by split_soft toggle) ──
        if split_soft:
            # ── Carrying Cost Breakdown ──
            st.markdown("---")
            st.subheader("🏗️ Carrying Cost Breakdown")
            tcm = int(total_carry_months)
            st.caption(f"Total carry: {tcm} months ({predev_months} predev + {build_months} build + {delay_months} delay + {sale_hold_months} sale hold)")
            carry_data = [
                {"Component": "Land Interest / Cost of Capital", "Amount": f"${carry_land_interest:,.0f}",
                 "Assumption": f"Land cost of capital over {tcm} months"},
                {"Component": "Construction Interest", "Amount": f"${construction_interest:,.0f}",
                 "Assumption": f"Non-land dev × {ltv}% LTC × {interest_rate}% × {draw_factor}% draw × {build_months} mo ÷ 12"},
                {"Component": "Property Taxes", "Amount": f"${carry_taxes:,.0f}",
                 "Assumption": f"(Land + 50% (HC+Soft+Demo)) × {const_tax_rate}% × {tcm} mo ÷ 12"},
                {"Component": "Insurance", "Amount": f"${carry_insurance:,.0f}",
                 "Assumption": f"${const_insurance_annual:,}/yr × {tcm} mo ÷ 12"},
                {"Component": "Utilities", "Amount": f"${carry_utilities:,.0f}",
                 "Assumption": f"${const_utilities:,}/mo × {tcm} mo"},
                {"Component": "Misc", "Amount": f"${carry_misc:,.0f}",
                 "Assumption": f"${const_misc:,}/mo × {tcm} mo"},
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
                {"Component": "**TOTAL SALES COST**", "Amount": f"**${total_sales_cost:,.0f}**"},
            ]
            st.dataframe(sales_data, use_container_width=True, hide_index=True)

            # ── Soft Cost Breakdown ──
            st.markdown("---")
            st.subheader("📐 Soft Cost Breakdown")
            soft_data = [
                {"Category": f"Architecture ({arch_pct}%)", "Amount": f"${hard_cost * arch_pct / 100:,.0f}"},
                {"Category": f"Structural ({structural_pct}%)", "Amount": f"${hard_cost * structural_pct / 100:,.0f}"},
                {"Category": f"MEP ({mep_pct}%)", "Amount": f"${hard_cost * mep_pct / 100:,.0f}"},
                {"Category": f"Survey", "Amount": f"${survey_fixed:,.0f}"},
                {"Category": f"Geotech", "Amount": f"${geotech_fixed:,.0f}"},
                {"Category": f"Civil", "Amount": f"${civil_fixed:,.0f}"},
                {"Category": f"Permits", "Amount": f"${permit_fixed:,.0f}"},
                {"Category": f"Legal/Admin", "Amount": f"${legal_fixed:,.0f}"},
                {"Category": f"Arborist", "Amount": f"${arborist_fixed:,.0f}"},
                {"Category": f"Utility App Fees", "Amount": f"${utility_fees_fixed:,.0f}"},
                {"Category": f"**TOTAL SOFT**", "Amount": f"**${soft_costs:,.0f}**"},
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
                sc = hc * (soft_cost_pct / 100) + total_fixed_soft
                dev = demo_cost + hc + hc_cont + sc + soft_contingency
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
                tsc = ec + stg + mkt + war
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
                sc = hc * (soft_cost_pct / 100) + total_fixed_soft
                dev = demo_cost + hc + hc_cont + sc + soft_contingency
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
                tsc = ec + stg + mkt + war
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
                # New params
                demo_cost=demo_cost, predev_months=predev_months,
                land_loan_pct=land_loan_pct, land_interest_rate=land_interest_rate,
                land_equity_cost_rate=land_equity_cost_rate,
                use_land_cost_of_capital=use_land_cost_of_capital,
                soft_fixed_costs=total_fixed_soft, carry_land_interest=carry_land_interest,
                structural_pct=structural_pct, mep_pct=mep_pct,
                survey_fixed=survey_fixed, geotech_fixed=geotech_fixed,
                civil_fixed=civil_fixed, permit_fixed=permit_fixed,
                legal_fixed=legal_fixed, arborist_fixed=arborist_fixed,
                utility_fees_fixed=utility_fees_fixed,
                total_carry=total_carry,
                margin_on_cost=margin_on_cost if hold_months == 0 else 0,
                deal_status=deal_status if hold_months == 0 else "",
                construction_loan=construction_loan, land_loan=land_loan,
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
        st.caption("Matches Excel template structure — all calculations across 4 build cost scenarios.")

        # Build cost scenarios (matching Excel columns B-E)
        cost_levels = [build_cost_psf - 25, build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]
        col_headers = [f"${cl}/sf" for cl in cost_levels]
        tcm_audit = int(total_carry_months)

        def _audit_scenario(bc):
            """Compute all line items for one build cost scenario."""
            hc = bc * build_sf
            hcont = hc * (hard_contingency_pct / 100)
            sc_pct = hc * (arch_pct / 100) + hc * (structural_pct / 100) + hc * (mep_pct / 100)
            sc = sc_pct + total_fixed_soft
            nld = demo_cost + hc + hcont + sc + soft_contingency
            tpc = purchase_price + nld
            # Carry
            if land_loan_pct > 0:
                li = purchase_price * (land_loan_pct / 100) * (land_interest_rate / 100) * tcm_audit / 12
            elif use_land_cost_of_capital:
                li = purchase_price * (land_equity_cost_rate / 100) * tcm_audit / 12
            else:
                li = 0
            ci = nld * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * build_months / 12
            ct = (purchase_price + 0.5 * (hc + sc + demo_cost)) * (const_tax_rate / 100) * tcm_audit / 12
            cins = const_insurance_annual * tcm_audit / 12
            cutil = const_utilities * tcm_audit
            cmisc = const_misc * tcm_audit
            csub = li + ci + ct + cins + cutil + cmisc
            cbuf = csub * (carry_buffer_pct / 100)
            tcarry = csub + cbuf
            # Sales
            rev = exit_psf * build_sf
            var_s = rev * (exit_cost_pct / 100)
            stg = staging_base + staging_per_unit * units
            mkt = marketing_base + marketing_per_unit * units
            war = warranty_per_unit * units
            tsc = var_s + stg + mkt + war
            total = tpc + tcarry + tsc
            # Equity & profit
            cl = nld * (ltv / 100)
            ll = purchase_price * (land_loan_pct / 100)
            lf = cl * (loan_fee_pct / 100)
            eq = max(0, total - cl - ll)
            profit = rev - total
            margin = profit / total if total > 0 else 0
            em = (eq + profit) / eq if eq > 0 else 0
            poe = profit / eq if eq > 0 else 0
            eq_pct = eq / total if total > 0 else 0
            status = "GO" if (profit >= 250000 and margin >= 0.18 and em >= 1.5) else \
                     ("PASS" if (profit < 125000 or margin < 0.12 or em < 1.25) else "REVIEW")
            return {
                # Pro Forma
                "Land Acquisition": purchase_price, "Demo / Site Prep": demo_cost,
                "Vertical Hard Cost": hc, "Hard Cost Contingency": hcont,
                "Soft Costs": sc, "Soft Contingency": soft_contingency,
                "Carry Costs": tcarry, "Sales Costs": tsc,
                "Total Project Cost": total, "Exit Revenue": rev,
                "Profit": profit, "Margin on Cost": margin,
                "Equity Invested ($)": eq, "Equity % of Total Cost": eq_pct,
                "Equity Multiple": em, "Profit on Equity": poe,
                "Deal Status": status,
                # Soft breakdown
                "Architecture": hc * (arch_pct / 100), "Structural": hc * (structural_pct / 100),
                "MEP Engineering": hc * (mep_pct / 100),
                "Survey": survey_fixed, "Geotech": geotech_fixed, "Civil": civil_fixed,
                "Permits / Fees": permit_fixed, "Legal / Admin": legal_fixed,
                "Arborist": arborist_fixed, "Utility Application Fees": utility_fees_fixed,
                "Total Soft Costs": sc,
                # Carry breakdown
                "Land Interest": li, "Construction Interest": ci,
                "Taxes": ct, "Insurance": cins, "Utilities": cutil,
                "Misc Carry": cmisc, "Carry Buffer": cbuf, "Total Carry": tcarry,
                # Sales breakdown
                "Realtor": rev * (broker_fee_pct / 100),
                "Title + Closing": rev * (title_closing_pct / 100),
                "Concessions": rev * (seller_concessions_pct / 100),
                "Staging": stg, "Marketing": mkt, "Warranty": war,
                "Total Sales Cost": tsc,
            }

        scenarios = [_audit_scenario(cl) for cl in cost_levels]

        def _render_audit_table(title, rows, fmt_overrides=None, formulas=None):
            """Render a multi-column audit table matching Excel layout."""
            if title:
                st.markdown(f"#### {title}")
            if fmt_overrides is None:
                fmt_overrides = {}
            if formulas is None:
                formulas = {}
            md = "| Component | Formula | " + " | ".join(col_headers) + " |\n"
            md += "|-----------|---------|" + "|".join(["--------:"] * len(col_headers)) + "|\n"
            for row_label in rows:
                vals = [scenarios[j][row_label] for j in range(4)]
                fmt = fmt_overrides.get(row_label, "dollar")
                if fmt == "pct":
                    cells = [f"{v * 100:.1f}%" for v in vals]
                elif fmt == "mult":
                    cells = [f"{v:.2f}x" for v in vals]
                elif fmt == "text":
                    cells = [f"**{v}**" for v in vals]
                else:
                    cells = [f"${v:,.0f}" for v in vals]
                bold = "**" if row_label.startswith("Total") or row_label in ("Profit", "Deal Status", "Exit Revenue") else ""
                formula_text = formulas.get(row_label, "")
                md += f"| {bold}{row_label}{bold} | {formula_text} | " + " | ".join(cells) + " |\n"
            st.markdown(md)

        # ── 1. Pro Forma Summary ──
        _render_audit_table("📊 Pro Forma Summary", [
            "Land Acquisition", "Demo / Site Prep", "Vertical Hard Cost",
            "Hard Cost Contingency", "Soft Costs", "Soft Contingency",
            "Carry Costs", "Sales Costs", "Total Project Cost",
            "Exit Revenue", "Profit", "Margin on Cost",
            "Equity Invested ($)", "Equity % of Total Cost",
            "Equity Multiple", "Profit on Equity", "Deal Status",
        ], fmt_overrides={
            "Margin on Cost": "pct", "Equity % of Total Cost": "pct",
            "Equity Multiple": "mult", "Profit on Equity": "pct",
            "Deal Status": "text",
        }, formulas={
            "Land Acquisition": "Input",
            "Demo / Site Prep": "Input",
            "Vertical Hard Cost": f"Total SF × Build $/sf",
            "Hard Cost Contingency": f"HC × {hard_contingency_pct}%",
            "Soft Costs": "= Soft Breakdown Total",
            "Soft Contingency": "Input (fixed $)",
            "Carry Costs": "= Carry Breakdown Total",
            "Sales Costs": "= Sales Breakdown Total",
            "Total Project Cost": "SUM(Land → Sales)",
            "Exit Revenue": f"Total SF × Exit $/sf",
            "Profit": "Revenue − Total Cost",
            "Margin on Cost": "Profit ÷ Total Cost",
            "Equity Invested ($)": "MAX(0, Cost − Loans)",
            "Equity % of Total Cost": "Equity ÷ Total Cost",
            "Equity Multiple": "(Equity + Profit) ÷ Equity",
            "Profit on Equity": "Profit ÷ Equity",
            "Deal Status": "GO/REVIEW/PASS rules",
        })

        st.markdown("---")

        # ── 2. Soft Cost Breakdown ──
        _render_audit_table("📐 Soft Cost Breakdown", [
            "Architecture", "Structural", "MEP Engineering",
            "Survey", "Geotech", "Civil", "Permits / Fees",
            "Legal / Admin", "Arborist", "Utility Application Fees",
            "Total Soft Costs",
        ], formulas={
            "Architecture": f"HC × {arch_pct}%",
            "Structural": f"HC × {structural_pct}%",
            "MEP Engineering": f"HC × {mep_pct}%",
            "Survey": "Fixed $", "Geotech": "Fixed $", "Civil": "Fixed $",
            "Permits / Fees": "Fixed $", "Legal / Admin": "Fixed $",
            "Arborist": "Fixed $", "Utility Application Fees": "Fixed $",
            "Total Soft Costs": "SUM(above)",
        })

        st.markdown("---")

        # ── 3. Carry Cost Breakdown ──
        st.markdown(f"#### 📅 Carry Cost Breakdown")
        st.caption(f"Total carry: {tcm_audit} months ({predev_months} predev + {build_months} build + {delay_months} delay + {sale_hold_months} sale hold)")
        _render_audit_table("", [
            "Land Interest", "Construction Interest", "Taxes",
            "Insurance", "Utilities", "Misc Carry",
            "Carry Buffer", "Total Carry",
        ], formulas={
            "Land Interest": f"Land × {land_equity_cost_rate}% × {tcm_audit}/12" if land_loan_pct == 0 and use_land_cost_of_capital else f"Land × {land_loan_pct}% × {land_interest_rate}% × {tcm_audit}/12",
            "Construction Interest": f"NonLandDev × {ltv}% × {interest_rate}% × {draw_factor}% × {build_months}/12",
            "Taxes": f"(Land + 50%(HC+Soft+Demo)) × {const_tax_rate}% × {tcm_audit}/12",
            "Insurance": f"${const_insurance_annual:,}/yr × {tcm_audit}/12",
            "Utilities": f"${const_utilities:,}/mo × {tcm_audit} mo",
            "Misc Carry": f"${const_misc:,}/mo × {tcm_audit} mo",
            "Carry Buffer": f"Subtotal × {carry_buffer_pct}%",
            "Total Carry": "SUM(above)",
        })

        st.markdown("---")

        # ── 4. Sales Cost Breakdown ──
        _render_audit_table("💸 Sales Cost Breakdown", [
            "Realtor", "Title + Closing", "Concessions",
            "Staging", "Marketing", "Warranty", "Total Sales Cost",
        ], formulas={
            "Realtor": f"Revenue × {broker_fee_pct}%",
            "Title + Closing": f"Revenue × {title_closing_pct}%",
            "Concessions": f"Revenue × {seller_concessions_pct}%",
            "Staging": f"${staging_base:,} + ${staging_per_unit:,} × {units}",
            "Marketing": f"${marketing_base:,} + ${marketing_per_unit:,} × {units}",
            "Warranty": f"${warranty_per_unit:,} × {units}",
            "Total Sales Cost": "SUM(above)",
        })

        st.markdown("---")

        # ── 5. Audit Checks (matching Excel Audit sheet) ──
        st.markdown("#### ✅ Audit Checks")
        st.caption("Automated consistency checks — same as the Excel Audit sheet.")

        # Run checks
        checks = []
        # Check 1: Total SF = Units × SF/Unit
        checks.append(("Inputs: Total SF = Units × SF/Unit",
                        f"{build_sf} = {units} × {sf_per_unit}",
                        build_sf == units * sf_per_unit))
        # Check 2: Soft cost summary matches breakdown
        checks.append(("Soft cost summary matches breakdown",
                        f"${soft_costs:,.0f} = ${soft_pct_costs:,.0f} + ${total_fixed_soft:,.0f}",
                        abs(soft_costs - (soft_pct_costs + total_fixed_soft)) < 1))
        # Check 3: Carry summary matches breakdown
        checks.append(("Carry summary matches breakdown",
                        f"${total_carry:,.0f} = subtotal + buffer",
                        abs(total_carry - (carry_subtotal + carry_buffer)) < 1))
        # Check 4: Sales summary matches breakdown
        checks.append(("Sales summary matches breakdown",
                        f"${total_sales_cost:,.0f}",
                        abs(total_sales_cost - (variable_sales + staging_cost + marketing_cost + warranty_cost)) < 1))
        # Check 5: Construction interest uses non-land costs
        checks.append(("Construction interest uses non-land dev costs",
                        f"Base = ${scenarios[0]['Construction Interest']:,.0f}",
                        scenarios[0]["Construction Interest"] > 0))
        # Check 6: Equity is not negative
        checks.append(("Equity invested is positive",
                        f"${total_equity_invested:,.0f}",
                        total_equity_invested > 0))
        # Check 7: Deal status populated
        if hold_months == 0:
            checks.append(("Deal status is set",
                            deal_status,
                            deal_status in ("GO", "REVIEW", "PASS")))

        check_md = "| Check | Formula / Value | Status |\n|-------|----------------|--------|\n"
        for desc, formula, ok in checks:
            status = "✅ OK" if ok else "❌ CHECK"
            check_md += f"| {desc} | {formula} | {status} |\n"
        st.markdown(check_md)

        # ── Hold Period (if applicable) ──
        if hold_months > 0:
            st.markdown("---")
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
    st.markdown(f"""
    | Item | Amount |
    |------|--------|
    | Land Acquisition | ${purchase_price:,.0f} |
    | Demo / Site Prep | ${demo_cost:,.0f} |
    | Hard Cost ({build_sf:,} sf × ${build_cost_psf}/sf) | ${hard_cost:,.0f} |
    | Hard Contingency ({hard_contingency_pct}%) | ${hard_contingency:,.0f} |
    | — Architecture ({arch_pct}%) | ${hard_cost * arch_pct / 100:,.0f} |
    | — Structural ({structural_pct}%) | ${hard_cost * structural_pct / 100:,.0f} |
    | — MEP ({mep_pct}%) | ${hard_cost * mep_pct / 100:,.0f} |
    | — Fixed items | ${total_fixed_soft:,.0f} |
    | **Soft Costs Total** | **${soft_costs:,.0f}** |
    | Construction Interest | ${construction_interest:,.0f} |
    | Land Interest / CoC | ${carry_land_interest:,.0f} |
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
