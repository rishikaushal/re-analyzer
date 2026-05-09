import io
import numpy as np
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, numbers, Border, Side



def _compute_hold_profit(purchase_price, build_sf, build_cost, exit_price, exit_cost_pct,
                         hard_contingency_pct, soft_cost_pct, soft_contingency,
                         ltv, interest_rate, draw_factor, loan_fee_pct,
                         build_months, hold_months, delay_months,
                         perm_mortgage_rate, amortization_years,
                         rent_per_unit, units, vacancy_pct, mgmt_fee_pct,
                         prop_tax_rate, taxable_value_psf, insurance_monthly,
                         repairs_per_unit, common_utilities, leasing_reserve,
                         const_tax_rate=2.0, const_insurance_annual=6750,
                         const_utilities_mo=450, const_misc_mo=325,
                         carry_buffer_pct=12.5,
                         staging_base=1500, staging_per_unit=3500,
                         marketing_base=2000, marketing_per_unit=1500,
                         warranty_per_unit=1750, sale_hold_months=1.5):
    """Recompute profit & equity multiple for a given build_cost/exit_price combo."""
    hc = build_cost * build_sf
    hcont = hc * (hard_contingency_pct / 100)
    sc = hc * (soft_cost_pct / 100)
    tdc = hc + hcont + sc + soft_contingency
    tpc = purchase_price + tdc

    la = tdc * (ltv / 100)
    lf = la * (loan_fee_pct / 100)

    # Carry costs (matching main model: loan interest on land+dev)
    cm = build_months + delay_months
    ci = (purchase_price + tdc) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * cm / 12
    ct = (purchase_price + 0.5 * tdc) * (const_tax_rate / 100) * cm / 12
    cins = const_insurance_annual * cm / 12
    cutil = const_utilities_mo * cm
    cmisc = const_misc_mo * cm
    csub = ci + ct + cins + cutil + cmisc
    cbuf = csub * (carry_buffer_pct / 100)
    tcarry = csub + cbuf

    # Sales costs
    rev = exit_price * build_sf
    var_sales = rev * (exit_cost_pct / 100)
    stg = staging_base + staging_per_unit * units
    mkt = marketing_base + marketing_per_unit * units
    war = warranty_per_unit * units
    hds = tcarry / max(cm, 1) * sale_hold_months
    tsales = var_sales + stg + mkt + war + hds

    if hold_months > 0:
        mpr = perm_mortgage_rate / 100 / 12
        npay = amortization_years * 12
        if mpr > 0:
            mds = la * (mpr * (1 + mpr) ** npay) / ((1 + mpr) ** npay - 1)
        else:
            mds = la / npay
        hi = mds * hold_months

        if mpr > 0:
            lbal = la * (1 + mpr) ** hold_months - mds * ((1 + mpr) ** hold_months - 1) / mpr
        else:
            lbal = la - mds * hold_months

        gr = rent_per_unit * units * hold_months
        er = gr * (1 - vacancy_pct / 100)
        mc = er * (mgmt_fee_pct / 100)
        pt = build_sf * taxable_value_psf * (prop_tax_rate / 100) * hold_months / 12
        ins = insurance_monthly * hold_months
        rep = repairs_per_unit * units * hold_months
        mi = common_utilities * hold_months
        lea = leasing_reserve * hold_months
        mnoi = (er - mc - pt - ins - rep - mi - lea) / max(hold_months, 1)
        mcf = mnoi - mds
        cum_cf = mcf * hold_months
        aeq = max(0, -cum_cf)
        tei = purchase_price + tcarry + lf + aeq

        ec = rev * (exit_cost_pct / 100)
        nsbd = rev - ec
        nsad = nsbd - lbal
        pcf = max(0, cum_cf)
        tcr = nsad + pcf
        profit = tcr - tei
        em = tcr / tei if tei > 0 else 0
    else:
        tc = tpc + lf + tcarry + tsales
        tei = tc
        profit = rev - tc
        em = rev / tc if tc > 0 else 0

    return profit, em


def generate_excel_bytes(
    # Sidebar inputs
    units, per_unit_sf, build_sf, purchase_price, build_cost_psf, exit_psf,
    build_months, hold_months, delay_months,
    hard_contingency_pct, soft_cost_pct, soft_contingency,
    ltv, interest_rate, draw_factor, loan_fee_pct,
    perm_mortgage_rate, amortization_years,
    rent_per_unit, vacancy_pct, mgmt_fee_pct,
    prop_tax_rate, taxable_value_psf, insurance_monthly,
    repairs_per_unit, common_utilities, leasing_reserve,
    exit_cost_pct, price_decline,
    split_soft, arch_pct, eng_pct, permit_fee_pct, survey_pct, insurance_dev_pct, other_soft_pct,
    broker_fee_pct, title_closing_pct, seller_concessions_pct,
    # Carry/sales cost params
    const_tax_rate, const_insurance_annual,
    const_utilities, const_misc, carry_buffer_pct,
    staging_base, staging_per_unit,
    marketing_base, marketing_per_unit,
    warranty_per_unit, sale_hold_months,
    # Computed values
    hard_cost, hard_contingency, soft_costs, total_dev_cost, total_project_cost,
    loan_amount, equity, construction_interest, loan_fees,
    hold_interest, gross_rent, effective_rent,
    total_hold_expenses, net_rental_income,
    monthly_debt_service, loan_balance_after_hold,
    total_equity_invested, user_profit, user_revenue,
    breakeven_psf, exit_costs_user, total_cost, equity_multiple,
    # Hold-specific
    additional_equity_needed, cumulative_cf, net_sale_before_debt, net_sale_after_debt,
    positive_rental_cf, total_cash_returned,
    # OPEX
    mgmt_cost, prop_tax, insurance, repairs, misc, leasing,
    monthly_noi, monthly_cf_after_debt,
):
    """Build a multi-sheet Excel workbook and return bytes."""
    wb = Workbook()

    # Styles
    bold = Font(bold=True)
    bold_white = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    yellow_fill = PatternFill("solid", fgColor="FFF2CC")
    green_fill = PatternFill("solid", fgColor="E2EFDA")
    orange_fill = PatternFill("solid", fgColor="FCE4D6")
    light_blue_fill = PatternFill("solid", fgColor="D6E4F0")
    dollar_fmt = '$#,##0'
    dollar_fmt2 = '$#,##0.00'
    pct_fmt = '0.0%'
    pct_fmt2 = '0.00%'
    num_fmt = '#,##0'
    mult_fmt = '0.00x'
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )

    def _header_row(ws, row, cols, fill=header_fill):
        for c, val in enumerate(cols, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.font = bold_white
            cell.fill = fill
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')

    def _data_row(ws, row, vals, fills=None, fmts=None):
        for c, val in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=val)
            cell.border = thin_border
            if fills and c <= len(fills) and fills[c - 1]:
                cell.fill = fills[c - 1]
            if fmts and c <= len(fmts) and fmts[c - 1]:
                cell.number_format = fmts[c - 1]

    # ═══════════════════════════════════════════
    # SHEET 1: Hold Model
    # ═══════════════════════════════════════════
    ws1 = wb.active
    ws1.title = "Hold Model"
    ws1.sheet_properties.tabColor = "4472C4"

    # Set column widths
    ws1.column_dimensions['A'].width = 35
    ws1.column_dimensions['B'].width = 18
    ws1.column_dimensions['C'].width = 14
    ws1.column_dimensions['D'].width = 14
    ws1.column_dimensions['E'].width = 30

    r = 1
    # ── Section 1: Assumptions ──
    ws1.cell(row=r, column=1, value="ASSUMPTIONS").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws1, r, ["Assumption", "Value", "Unit", "Type", "Notes"])
    r += 1

    assumptions = [
        ("Units", units, "units", "Input", ""),
        ("Sq Ft / Unit", per_unit_sf, "sf", "Calc", "build_sf / units"),
        ("Total Sq Ft", build_sf, "sf", "Input", ""),
        ("Land Equity", purchase_price, "$", "Input", "Purchase price"),
        ("Build Cost $/sf", build_cost_psf, "$/sf", "Input", ""),
        ("Exit Price $/sf", exit_psf, "$/sf", "Input", "Target sale price"),
        ("Build Duration", build_months, "months", "Input", ""),
        ("Hold Period", hold_months, "months", "Input", "After build completion"),
        ("Expected Delays", delay_months, "months", "Input", ""),
        ("Hard Cost Contingency %", hard_contingency_pct / 100, "%", "Input", ""),
        ("Soft Cost %", soft_cost_pct / 100, "%", "Input", "Of hard cost"),
        ("Soft Contingency $", soft_contingency, "$", "Input", "Fixed amount"),
        ("Construction Debt Funding %", ltv / 100, "%", "Input", "LTC on dev costs"),
        ("Construction Interest Rate %", interest_rate / 100, "%", "Input", "Annual"),
        ("Draw Factor %", draw_factor / 100, "%", "Input", ""),
        ("Loan Fees %", loan_fee_pct / 100, "%", "Input", ""),
        ("Perm Mortgage Rate %", perm_mortgage_rate / 100, "%", "Input", "Annual"),
        ("Amortization", amortization_years, "years", "Input", ""),
        ("Rent / Unit / Month", rent_per_unit, "$/mo", "Input", ""),
        ("Vacancy %", vacancy_pct / 100, "%", "Input", ""),
        ("Management Fee %", mgmt_fee_pct / 100, "%", "Input", "Of EGI"),
        ("Property Tax Rate %", prop_tax_rate / 100, "%", "Input", "Annual"),
        ("Taxable Value Basis $/sf", taxable_value_psf, "$/sf", "Input", ""),
        ("Insurance $/mo", insurance_monthly, "$/mo", "Input", ""),
        ("Repairs Reserve $/unit/mo", repairs_per_unit, "$/mo", "Input", ""),
        ("Common Utilities $/mo", common_utilities, "$/mo", "Input", ""),
        ("Leasing Reserve $/mo", leasing_reserve, "$/mo", "Input", ""),
        ("Exit Cost %", exit_cost_pct / 100, "%", "Calc", f"Broker {broker_fee_pct}% + Title {title_closing_pct}% + Concessions {seller_concessions_pct}%"),
    ]

    for label, val, unit, typ, note in assumptions:
        fmt_b = None
        if unit == "$" or unit == "$/sf" or unit == "$/mo":
            fmt_b = dollar_fmt
        elif unit == "%":
            fmt_b = pct_fmt
        _data_row(ws1, r, [label, val, unit, typ, note],
                  fills=[None, yellow_fill, None, None, None],
                  fmts=[None, fmt_b, None, None, None])
        r += 1

    # ── Section 2: Development Cost & Construction Debt ──
    r += 1
    ws1.cell(row=r, column=1, value="DEVELOPMENT COST & CONSTRUCTION DEBT").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws1, r, ["Line Item", "Formula / Basis", "Amount", "Notes"])
    r += 1

    dev_items = [
        ("Hard Cost", f"{build_cost_psf} × {build_sf:,} sf", hard_cost, ""),
        ("Hard Cost Contingency", f"{hard_contingency_pct}% of Hard Cost", hard_contingency, ""),
        ("Soft Cost", f"{soft_cost_pct:.1f}% of Hard Cost", soft_costs, ""),
        ("Soft Contingency", "Fixed", soft_contingency, ""),
        ("Non-Land Development Cost", "Sum above", total_dev_cost, ""),
        ("Construction Debt", f"{ltv}% LTC", loan_amount, ""),
        ("Construction Interest During Build", f"{interest_rate}% × {draw_factor}% draw × {build_months + delay_months} mo", construction_interest, ""),
        ("Construction Loan Fees", f"{loan_fee_pct}% of loan", loan_fees, ""),
    ]
    for label, basis, amt, note in dev_items:
        _data_row(ws1, r, [label, basis, amt, note],
                  fills=[None, None, green_fill, None],
                  fmts=[None, None, dollar_fmt, None])
        r += 1

    # ── Section 3: Monthly Rental OPEX & Cash Flow ──
    r += 1
    ws1.cell(row=r, column=1, value="MONTHLY RENTAL OPEX & CASH FLOW").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws1, r, ["Line Item", "Formula / Basis", "Monthly", "Annual", "Notes"])
    r += 1

    hm = max(hold_months, 1)
    monthly_gross = rent_per_unit * units
    monthly_vacancy = monthly_gross * (vacancy_pct / 100)
    monthly_egi = monthly_gross - monthly_vacancy
    monthly_mgmt = monthly_egi * (mgmt_fee_pct / 100)
    monthly_proptax = build_sf * taxable_value_psf * (prop_tax_rate / 100) / 12
    monthly_ins = insurance_monthly
    monthly_repairs = repairs_per_unit * units
    monthly_utils = common_utilities
    monthly_leasing = leasing_reserve
    monthly_total_opex = monthly_mgmt + monthly_proptax + monthly_ins + monthly_repairs + monthly_utils + monthly_leasing

    opex_items = [
        ("Gross Rent", f"{rent_per_unit:,.0f} × {units} units", monthly_gross, monthly_gross * 12, ""),
        ("Vacancy", f"{vacancy_pct}%", -monthly_vacancy, -monthly_vacancy * 12, ""),
        ("Effective Gross Income", "", monthly_egi, monthly_egi * 12, ""),
        ("Management Fee", f"{mgmt_fee_pct}% of EGI", -monthly_mgmt, -monthly_mgmt * 12, ""),
        ("Property Taxes", f"{prop_tax_rate}% of {taxable_value_psf}×{build_sf:,}", -monthly_proptax, -monthly_proptax * 12, ""),
        ("Insurance", "", -monthly_ins, -monthly_ins * 12, ""),
        ("Repairs", f"{repairs_per_unit}/unit/mo", -monthly_repairs, -monthly_repairs * 12, ""),
        ("Utilities / Misc", "", -monthly_utils, -monthly_utils * 12, ""),
        ("Leasing Reserve", "", -monthly_leasing, -monthly_leasing * 12, ""),
        ("Total OPEX", "", -monthly_total_opex, -monthly_total_opex * 12, ""),
        ("NOI", "EGI - OPEX", monthly_noi, monthly_noi * 12, ""),
        ("Permanent Debt Service", f"{perm_mortgage_rate}%, {amortization_years}yr amort", -monthly_debt_service, -monthly_debt_service * 12, ""),
        ("Monthly Cash Flow After Debt", "", monthly_cf_after_debt, monthly_cf_after_debt * 12, ""),
    ]
    for label, basis, mo, ann, note in opex_items:
        _data_row(ws1, r, [label, basis, mo, ann, note],
                  fills=[None, None, green_fill, green_fill, None],
                  fmts=[None, None, dollar_fmt, dollar_fmt, None])
        r += 1

    # ── Section 4: Profit/Loss After Hold ──
    r += 1
    ws1.cell(row=r, column=1, value="PROFIT / LOSS AFTER HOLD").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws1, r, ["Line Item", "Formula / Basis", "Amount", "Notes"])
    r += 1

    profit_items = [
        ("Land Equity", "Purchase price", purchase_price, "Cash in"),
        ("Construction Interest", "During build", construction_interest, "Cash in"),
        ("Loan Fees", "", loan_fees, "Cash in"),
        ("Cumulative Rental CF", f"{hold_months} months", cumulative_cf, "Pos = cash returned"),
        ("Additional Equity for Negative CF", "max(0, -cumCF)", additional_equity_needed, "Cash in if CF negative"),
        ("Total Equity Invested", "Sum of cash in", total_equity_invested, ""),
        ("", "", "", ""),
        ("Final Sale Price", f"{exit_psf} × {build_sf:,} sf", user_revenue, ""),
        ("Exit Costs", f"{exit_cost_pct:.1f}%", -exit_costs_user, ""),
        ("Net Sale Before Debt", "", net_sale_before_debt, ""),
        ("Loan Balance After Hold", f"{hold_months} mo amort", -loan_balance_after_hold, ""),
        ("Net Sale After Debt", "", net_sale_after_debt, ""),
        ("Positive Rental CF Returned", "", positive_rental_cf, ""),
        ("Total Cash Returned", "", total_cash_returned, ""),
        ("Profit / (Loss)", "Cash returned - equity", user_profit, ""),
        ("Equity Multiple", "Cash returned / equity", equity_multiple, ""),
    ]
    for label, basis, amt, note in profit_items:
        fill_c = None
        fmt_c = dollar_fmt
        if label == "Equity Multiple":
            fmt_c = '0.00x'
            fill_c = orange_fill
        elif label == "Profit / (Loss)":
            fill_c = orange_fill
        elif label == "Total Equity Invested" or label == "Total Cash Returned":
            fill_c = light_blue_fill
        _data_row(ws1, r, [label, basis, amt, note],
                  fills=[None, None, fill_c, None],
                  fmts=[None, None, fmt_c, None])
        r += 1

    # ── Section 5: Hold Sweep — Build Cost vs Exit Price (Profit) ──
    r += 1
    ws1.cell(row=r, column=1, value="HOLD SWEEP — BUILD COST vs EXIT PRICE (Profit)").font = Font(bold=True, size=14)
    r += 1

    sweep_build_costs = [build_cost_psf - 25, build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]
    sweep_exit_prices = [exit_psf - 25, exit_psf, exit_psf + 25]

    common_args = dict(
        purchase_price=purchase_price, build_sf=build_sf, exit_cost_pct=exit_cost_pct,
        hard_contingency_pct=hard_contingency_pct, soft_cost_pct=soft_cost_pct,
        soft_contingency=soft_contingency, ltv=ltv, interest_rate=interest_rate,
        draw_factor=draw_factor, loan_fee_pct=loan_fee_pct,
        build_months=build_months, hold_months=hold_months, delay_months=delay_months,
        perm_mortgage_rate=perm_mortgage_rate, amortization_years=amortization_years,
        rent_per_unit=rent_per_unit, units=units, vacancy_pct=vacancy_pct,
        mgmt_fee_pct=mgmt_fee_pct, prop_tax_rate=prop_tax_rate,
        taxable_value_psf=taxable_value_psf, insurance_monthly=insurance_monthly,
        repairs_per_unit=repairs_per_unit, common_utilities=common_utilities,
        leasing_reserve=leasing_reserve,
        const_tax_rate=const_tax_rate, const_insurance_annual=const_insurance_annual,
        const_utilities_mo=const_utilities, const_misc_mo=const_misc,
        carry_buffer_pct=carry_buffer_pct,
        staging_base=staging_base, staging_per_unit=staging_per_unit,
        marketing_base=marketing_base, marketing_per_unit=marketing_per_unit,
        warranty_per_unit=warranty_per_unit, sale_hold_months=sale_hold_months,
    )

    # Header row
    ws1.cell(row=r, column=1, value="Build Cost \\ Exit $/sf").font = bold
    ws1.cell(row=r, column=1).fill = header_fill
    ws1.cell(row=r, column=1).font = bold_white
    for j, ep in enumerate(sweep_exit_prices, 2):
        cell = ws1.cell(row=r, column=j, value=f"${ep}/sf")
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    r += 1

    for bc in sweep_build_costs:
        ws1.cell(row=r, column=1, value=f"${bc}/sf").font = bold
        for j, ep in enumerate(sweep_exit_prices, 2):
            profit_val, _ = _compute_hold_profit(build_cost=bc, exit_price=ep, **common_args)
            cell = ws1.cell(row=r, column=j, value=profit_val)
            cell.number_format = dollar_fmt
            cell.fill = green_fill if profit_val >= 0 else PatternFill("solid", fgColor="FFC7CE")
            cell.border = thin_border
        r += 1

    # ── Section 6: Equity Multiple Sweep ──
    r += 1
    ws1.cell(row=r, column=1, value="EQUITY MULTIPLE SWEEP").font = Font(bold=True, size=14)
    r += 1

    ws1.cell(row=r, column=1, value="Build Cost \\ Exit $/sf").font = bold_white
    ws1.cell(row=r, column=1).fill = header_fill
    for j, ep in enumerate(sweep_exit_prices, 2):
        cell = ws1.cell(row=r, column=j, value=f"${ep}/sf")
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    r += 1

    for bc in sweep_build_costs:
        ws1.cell(row=r, column=1, value=f"${bc}/sf").font = bold
        for j, ep in enumerate(sweep_exit_prices, 2):
            _, em_val = _compute_hold_profit(build_cost=bc, exit_price=ep, **common_args)
            cell = ws1.cell(row=r, column=j, value=em_val)
            cell.number_format = '0.00x'
            cell.fill = orange_fill if em_val >= 1 else PatternFill("solid", fgColor="FFC7CE")
            cell.border = thin_border
        r += 1

    # ═══════════════════════════════════════════
    # SHEET 2: Detailed Analysis
    # ═══════════════════════════════════════════
    ws2 = wb.create_sheet("Detailed Analysis")
    ws2.sheet_properties.tabColor = "70AD47"

    ws2.column_dimensions['A'].width = 28
    for col_letter in ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
        ws2.column_dimensions[col_letter].width = 16
    ws2.column_dimensions['K'].width = 25
    ws2.column_dimensions['L'].width = 16

    r = 1

    # ── Section 1: Pro Forma Summary ──
    ws2.cell(row=r, column=1, value="PRO FORMA SUMMARY").font = Font(bold=True, size=14)
    r += 1

    cost_levels = [build_cost_psf - 25, build_cost_psf, build_cost_psf + 25, build_cost_psf + 50]
    _header_row(ws2, r, ["Line Item"] + [f"${cl}/sf" for cl in cost_levels] + ["", "Model Assumptions", "Value"])
    r += 1

    model_assumptions_right = [
        ("Units", units),
        ("Sq Ft / Unit", per_unit_sf),
        ("Total Sq Ft", build_sf),
        ("Land Cost", purchase_price),
        ("Exit $/sf", exit_psf),
        ("Build Duration (mo)", build_months),
        ("Hold Period (mo)", hold_months),
        ("Hard Contingency %", hard_contingency_pct / 100),
        ("Soft Cost %", soft_cost_pct / 100),
        ("LTV %", ltv / 100),
        ("Construction Rate %", interest_rate / 100),
        ("Perm Mortgage %", perm_mortgage_rate / 100),
    ]

    def _proforma_row_at_cost(bc):
        hc_l = bc * build_sf
        hcont_l = hc_l * (hard_contingency_pct / 100)
        sc_l = hc_l * (soft_cost_pct / 100)
        tdc_l = hc_l + hcont_l + sc_l + soft_contingency
        tpc_l = purchase_price + tdc_l
        la_l = tdc_l * (ltv / 100)
        lf_l = la_l * (loan_fee_pct / 100)
        # Carry (matching main model: loan interest on land+dev)
        cm = build_months + delay_months
        ci_l = (purchase_price + tdc_l) * (ltv / 100) * (interest_rate / 100) * (draw_factor / 100) * cm / 12
        ct_l = (purchase_price + 0.5 * tdc_l) * (const_tax_rate / 100) * cm / 12
        cins_l = const_insurance_annual * cm / 12
        cutil_l = const_utilities * cm
        cmisc_l = const_misc * cm
        csub_l = ci_l + ct_l + cins_l + cutil_l + cmisc_l
        cbuf_l = csub_l * (carry_buffer_pct / 100)
        tcarry_l = csub_l + cbuf_l
        # Sales (matching main model)
        rev_l = exit_psf * build_sf
        var_sales_l = rev_l * (exit_cost_pct / 100)
        stg_l = staging_base + staging_per_unit * units
        mkt_l = marketing_base + marketing_per_unit * units
        war_l = warranty_per_unit * units
        hds_l = tcarry_l / max(cm, 1) * sale_hold_months
        tsc_l = var_sales_l + stg_l + mkt_l + war_l + hds_l
        total_l = tpc_l + lf_l + tcarry_l + tsc_l
        profit_l = rev_l - total_l + (net_rental_income if hold_months > 0 else 0)
        return {
            "Land": purchase_price,
            "Hard Cost": hc_l,
            f"Hard Cost Contingency ({hard_contingency_pct}%)": hcont_l,
            "Soft + Arch": sc_l + soft_contingency,
            "Soft Contingency": soft_contingency,
            "Carry": tcarry_l,
            "Sales Cost": tsc_l,
            "Total Cost": total_l,
            "Exit Value": rev_l,
            "Profit": profit_l,
        }

    proforma_rows = list(_proforma_row_at_cost(cost_levels[0]).keys())
    proforma_data = [_proforma_row_at_cost(cl) for cl in cost_levels]

    for i, row_label in enumerate(proforma_rows):
        vals = [row_label] + [proforma_data[j][row_label] for j in range(4)]
        fill_r = orange_fill if row_label == "Profit" else (light_blue_fill if row_label == "Total Cost" else None)
        fmts_r = [None] + [dollar_fmt] * 4

        # Add model assumptions on the right
        k_val = ""
        l_val = ""
        if i < len(model_assumptions_right):
            k_val, l_val = model_assumptions_right[i]
        vals += ["", k_val, l_val]
        k_fmt = None
        if isinstance(l_val, float) and l_val < 1:
            k_fmt = pct_fmt
        elif isinstance(l_val, (int, float)) and l_val >= 100:
            k_fmt = dollar_fmt
        fmts_r += [None, None, k_fmt]

        fills_r = [None] + [fill_r] * 4 + [None, None, yellow_fill if l_val != "" else None]
        _data_row(ws2, r, vals, fills=fills_r, fmts=fmts_r)
        r += 1

    # ── Section 2: Sales Cost Breakdown ──
    r += 1
    ws2.cell(row=r, column=1, value="SALES COST BREAKDOWN").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws2, r, ["Category", "Rate", "Amount"])
    r += 1

    rev = exit_psf * build_sf
    sales_items = [
        ("Realtor / Agent", broker_fee_pct / 100, rev * broker_fee_pct / 100),
        ("Title + Closing", title_closing_pct / 100, rev * title_closing_pct / 100),
        ("Seller Concessions", seller_concessions_pct / 100, rev * seller_concessions_pct / 100),
        ("Total", exit_cost_pct / 100, exit_costs_user),
    ]
    for label, rate, amt in sales_items:
        fill_r = light_blue_fill if label == "Total" else None
        _data_row(ws2, r, [label, rate, amt],
                  fills=[fill_r, fill_r, fill_r],
                  fmts=[None, pct_fmt, dollar_fmt])
        r += 1

    # ── Section 3: Soft Cost Breakdown ──
    r += 1
    ws2.cell(row=r, column=1, value="SOFT COST BREAKDOWN").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws2, r, ["Category", "Rate"] + [f"${cl}/sf" for cl in cost_levels])
    r += 1

    soft_categories = [
        ("Architecture & Design", arch_pct),
        ("Engineering (struct/MEP)", eng_pct),
        ("Permits & Impact Fees", permit_fee_pct),
        ("Surveys & Geotech", survey_pct),
        ("Builder's Risk Insurance", insurance_dev_pct),
        ("Other Soft Costs", other_soft_pct),
        ("Total Soft %", soft_cost_pct),
    ]
    for label, pct_val in soft_categories:
        hc_vals = [pct_val / 100] + [(cl * build_sf) * pct_val / 100 for cl in cost_levels]
        fill_r = light_blue_fill if "Total" in label else None
        _data_row(ws2, r, [label] + hc_vals,
                  fills=[fill_r, fill_r] + [fill_r] * 4,
                  fmts=[None, pct_fmt] + [dollar_fmt] * 4)
        r += 1

    # ── Section 4: Carrying Cost Breakdown ──
    r += 1
    ws2.cell(row=r, column=1, value="CARRYING COST BREAKDOWN").font = Font(bold=True, size=14)
    r += 1
    _header_row(ws2, r, ["Category", "Amount", "Notes"])
    r += 1

    carry_items = [
        ("Loan Interest (Construction)", construction_interest, f"{interest_rate}% × {draw_factor}% draw"),
        ("Loan Fees", loan_fees, f"{loan_fee_pct}% of loan"),
        ("Hold Interest (Perm Debt Service)", hold_interest, f"{hold_months} months"),
        ("Property Taxes (Hold)", prop_tax, f"{prop_tax_rate}%"),
        ("Insurance (Hold)", insurance, f"{hold_months} months"),
        ("Utilities / Misc (Hold)", misc, ""),
        ("Total Carry", construction_interest + loan_fees + hold_interest + prop_tax + insurance + misc, ""),
    ]
    for label, amt, note in carry_items:
        fill_r = light_blue_fill if "Total" in label else None
        _data_row(ws2, r, [label, amt, note],
                  fills=[fill_r, fill_r, fill_r],
                  fmts=[None, dollar_fmt, None])
        r += 1

    # ── Section 5: Cost vs Price Profit Matrix ──
    r += 1
    ws2.cell(row=r, column=1, value="COST vs PRICE PROFIT MATRIX").font = Font(bold=True, size=14)
    r += 1

    ws2.cell(row=r, column=1, value="Build Cost \\ Exit $/sf").font = bold_white
    ws2.cell(row=r, column=1).fill = header_fill
    for j, ep in enumerate(sweep_exit_prices, 2):
        cell = ws2.cell(row=r, column=j, value=f"${ep}/sf")
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    r += 1

    for bc in sweep_build_costs:
        ws2.cell(row=r, column=1, value=f"${bc}/sf").font = bold
        for j, ep in enumerate(sweep_exit_prices, 2):
            profit_val, _ = _compute_hold_profit(build_cost=bc, exit_price=ep, **common_args)
            cell = ws2.cell(row=r, column=j, value=profit_val)
            cell.number_format = dollar_fmt
            cell.fill = green_fill if profit_val >= 0 else PatternFill("solid", fgColor="FFC7CE")
            cell.border = thin_border
        r += 1

    # ── Section 6: Timeline Sensitivity ──
    r += 1
    ws2.cell(row=r, column=1, value="TIMELINE SENSITIVITY — Profit by Build Duration").font = Font(bold=True, size=14)
    r += 1

    durations = list(range(9, 16))
    ws2.cell(row=r, column=1, value="Duration (mo) \\ Build Cost").font = bold_white
    ws2.cell(row=r, column=1).fill = header_fill
    for j, bc in enumerate(cost_levels, 2):
        cell = ws2.cell(row=r, column=j, value=f"${bc}/sf")
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
    r += 1

    for dur in durations:
        ws2.cell(row=r, column=1, value=f"{dur} months").font = bold
        for j, bc in enumerate(cost_levels, 2):
            profit_val, _ = _compute_hold_profit(
                build_cost=bc, exit_price=exit_psf,
                purchase_price=purchase_price, build_sf=build_sf,
                exit_cost_pct=exit_cost_pct,
                hard_contingency_pct=hard_contingency_pct,
                soft_cost_pct=soft_cost_pct, soft_contingency=soft_contingency,
                ltv=ltv, interest_rate=interest_rate, draw_factor=draw_factor,
                loan_fee_pct=loan_fee_pct,
                build_months=dur, hold_months=hold_months, delay_months=delay_months,
                perm_mortgage_rate=perm_mortgage_rate, amortization_years=amortization_years,
                rent_per_unit=rent_per_unit, units=units, vacancy_pct=vacancy_pct,
                mgmt_fee_pct=mgmt_fee_pct, prop_tax_rate=prop_tax_rate,
                taxable_value_psf=taxable_value_psf, insurance_monthly=insurance_monthly,
                repairs_per_unit=repairs_per_unit, common_utilities=common_utilities,
                leasing_reserve=leasing_reserve,
            )
            cell = ws2.cell(row=r, column=j, value=profit_val)
            cell.number_format = dollar_fmt
            cell.fill = green_fill if profit_val >= 0 else PatternFill("solid", fgColor="FFC7CE")
            cell.border = thin_border
        r += 1

    # Save to bytes
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

