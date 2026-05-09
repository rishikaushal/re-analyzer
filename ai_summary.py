import requests
import time
import streamlit as st


# ── Gemini AI (optional, uses REST API — no extra package needed) ──
GEMINI_AVAILABLE = True  # Always available since we use REST API


def _get_gemini_key():
    try:
        return st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return ""


def generate_ai_summary(deal_data: dict) -> str:
    """Generate a plain-English AI deal analysis using Google Gemini REST API (no SDK needed)."""
    api_key = _get_gemini_key()
    if not api_key:
        return ""

    prompt = f"""You are a real estate investment analyst. Analyze this deal and give a clear, 
plain-English summary that a beginner investor (first-time flipper) can understand. Be specific with numbers.

You MUST answer ALL of these questions clearly with specific numbers:

## 1. SHOULD I BUY THIS DEAL?
Give a clear YES or NO with reasoning. Consider the profit margin, exit price vs comps, and risks.

## 2. FLIP OR HOLD — WHICH STRATEGY IS BETTER?
- **Flip (sell immediately after build):** What's the projected profit? Is the exit price realistic?
- **Hold & Rent:** What monthly rent should I charge? How long should I hold before selling? What's the cash flow?
- **Recommend one strategy** and explain why.

## 3. WHAT PRICE SHOULD I TARGET FOR RENTING?
- Based on Census median rents and the property size, suggest a specific monthly rent per unit.
- Census median rent for ZIP {deal_data.get('zip_code', 'N/A')}: {deal_data.get('census_median_rent', 'N/A')}/mo
- Census rent by bedrooms: {deal_data.get('census_rent_by_br', 'N/A')}
- How long to hold if renting? Give a specific timeframe (e.g., 2 years, 5 years).

## 4. WHAT SHOULD MY MAXIMUM PURCHASE PRICE BE?
- Based on the comps and desired profit margin (20%+), what is the max I should pay for this land/property?
- Show the math: Max Purchase = Exit Revenue - Build Costs - Desired Profit

## 5. WHAT EXIT PRICE PER SQUARE FOOT IS REALISTIC?
- Based on nearby sold comps, what $/sf should I realistically expect?
- Is the current exit assumption of {deal_data.get('exit_psf', 0)}/sf achievable?

CRITICAL CONTEXT: This is a fix-and-flip deal. Negative monthly rental cash flow is normal for flips — rentals are a backup plan, not the primary strategy. Focus on flip profit first.

IMPORTANT FORMATTING RULES: Do NOT use dollar signs ($) for currency. Instead write amounts like "450,000" or "575/sf". Do NOT use LaTeX or math notation. Use plain text only.

DEAL DATA:
- Address: {deal_data.get('address', 'N/A')}, ZIP: {deal_data.get('zip_code', 'N/A')}
- Purchase Price: ${deal_data.get('purchase_price', 0):,.0f}
- Total Build Size: {deal_data.get('total_sf', 0):,} sq ft ({deal_data.get('num_units', 1)} units, {deal_data.get('per_unit_sf', 0):,.0f} sf/unit)
- Exit Price/SF: ${deal_data.get('exit_psf', 0)}/sf
- Total All-In Cost: ${deal_data.get('total_cost', 0):,.0f}
- Expected Revenue: ${deal_data.get('revenue', 0):,.0f}
- Projected Profit: ${deal_data.get('profit', 0):,.0f}
- Profit Margin: {deal_data.get('margin_pct', 0):.1f}%
- Break-Even PSF: ${deal_data.get('breakeven_psf', 0):.0f}/sf
- Market Median PSF: ${deal_data.get('median_psf', 0)}/sf (from {deal_data.get('comp_count', 0)} comps)
- Risk Score: {deal_data.get('risk_score', 0)}/100
- Verdict: {deal_data.get('verdict', 'N/A')}
- Listing Status: {deal_data.get('listing_status', 'Unknown')}
- Zoning: {deal_data.get('zoning', 'N/A')}
- Monthly Rent: ${deal_data.get('monthly_rent', 0):,.0f}
- Rental NOI/Year: ${deal_data.get('rental_noi', 0):,.0f}

COMPARABLE SALES (nearby sold properties):
{deal_data.get('top_comps', 'No comp data')}

CONSTRUCTION ACTIVITY:
- Active permits on street: {deal_data.get('active_permits', 0)}
- Completed projects: {deal_data.get('completed_permits', 0)}
- Notable builders: {deal_data.get('permit_builders', 'N/A')}

HOLD/RENTAL ANALYSIS ({deal_data.get('hold_months', 0)} month hold):
- Monthly NOI: ${deal_data.get('monthly_noi', 0):,.0f}
- Monthly Cash Flow After Debt: ${deal_data.get('monthly_cf_after_debt', 0):,.0f}
- Equity Multiple: {deal_data.get('equity_multiple', 0):.2f}x
- Annualized Return: {deal_data.get('annualized_return', 0):.1f}%
- Cash-on-Cash Yield: {deal_data.get('cash_yield', 0):.1f}%

FINANCING:
- Loan Amount: ${deal_data.get('loan_amount', 0):,.0f}
- Construction Interest: ${deal_data.get('construction_interest', 0):,.0f}
- Build Cost: ${deal_data.get('build_cost_psf', 0)}/sf
- Build Timeline: {deal_data.get('build_months', 0)} months

Keep your response under 800 words. Use headers (##) for each section. Use bullet points for clarity.
End with a FINAL VERDICT: BUY or DON'T BUY, and your recommended strategy (Flip or Hold).
The app's automated verdict is: {deal_data.get('verdict', 'N/A')}. Your recommendation should be consistent with this."""

    models = ["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash"]
    last_error = ""
    try:
        for model_name in models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            try:
                resp = requests.post(url, json={
                    "contents": [{"parts": [{"text": prompt}]}]
                }, timeout=30)
            except Exception:
                continue
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif resp.status_code in (429, 404, 503):
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                time.sleep(1)
                continue  # try next model
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue  # try next model too
        # All models failed
        if "429" in last_error:
            return ("⚠️ **Gemini API quota exceeded.** The free tier has a daily limit.\n\n"
                    "**Options:**\n"
                    "- Wait until tomorrow (quota resets daily)\n"
                    "- Create a new API key at [Google AI Studio](https://aistudio.google.com/apikey) "
                    "and update it in Streamlit Cloud → Settings → Secrets")
        return f"⚠️ AI analysis error — all models failed. Last error: {last_error}"
    except Exception as e:
        return f"⚠️ AI analysis unavailable: {str(e)}"
