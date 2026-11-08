"""EGP model for the quiz email-step leak. Run: python calc/egp_model.py  (data-room inputs, ASSUMPTIONS marked)"""
US_SPEND, CPC, LTV = 350_000, 1.00, 68.0           # orig $120k + mods $230k; CPC $1; 12-month LTV forecast
REACH_4, REACH_5, PAY = 0.58, 0.36, 0.020           # share of clicks reaching step 4, step 5, paying
clicks = US_SPEND / CPC
lost = REACH_4 - REACH_5                             # 22 pp of clicks leave on the email step
down = PAY / REACH_5                                 # conversion from step 5 to payment (5.56%)

# ASSUMPTIONS: r = share of the 22 pp that fixes win back; q = how well the recovered users convert vs average step-5 users
SCENARIOS = {"pessimistic": dict(r=0.05, q=0.6), "base": dict(r=0.10, q=0.8), "optimistic": dict(r=0.20, q=1.0)}


def run(r, q, spend_mult=1.0):
    d_to_step5 = lost * r                            # extra share of clicks reaching step 5
    d_cr = d_to_step5 * q * down                     # extra share of clicks that buy
    purchases = clicks * spend_mult * d_cr
    return dict(step_conv=(REACH_5 + d_to_step5) / REACH_4, cr=PAY + d_cr, purchases=purchases, egp=purchases * LTV)


if __name__ == "__main__":
    print(f"clicks/month {clicks:,.0f} | lost on email step {lost:.0%} of clicks ({lost / REACH_4:.0%} of those who reach it) "
          f"| step5->pay {down:.2%} | step4->5 now {REACH_5 / REACH_4:.1%}\n")
    print(f"{'scenario':<12}{'r':>5}{'q':>5}{'step4->5':>10}{'CR':>8}{'CPA':>8}{'+purch/mo':>11}{'+EGP/mo':>10}{'@$700k US':>11}")
    for name, p in SCENARIOS.items():
        x = run(**p)
        print(f"{name:<12}{p['r']:>5.0%}{p['q']:>5.1f}{x['step_conv']:>10.1%}{x['cr']:>8.3%}{CPC / x['cr']:>8.2f}"
              f"{x['purchases']:>11,.0f}{x['egp']:>10,.0f}{run(**p, spend_mult=2)['egp']:>11,.0f}")
    base = run(**SCENARIOS["base"])
    US_EGP = 36_000 + 92_000                         # data room: US originals + US modifications
    print(f"\nbase: ROMI {LTV * PAY / CPC:.0%} -> {LTV * base['cr'] / CPC:.0%}; US EGP ${US_EGP:,} -> +{base['egp'] / US_EGP:.0%}")
    print(f"ceiling if NOBODY left on this step: ${clicks * lost * down * LTV:,.0f}/month (not realistic; shows the size of the pool)")
    print("\nManual analysis today: ~4 h each (PM quote 'half a day'); assume 4 per month = 16 h/month saved.")
