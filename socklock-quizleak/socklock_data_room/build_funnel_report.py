"""One-page funnel report from the REAL SockLock data-room numbers (aggregates only, no per-user data).
Run from socklock-quizleak/:  python3 socklock_data_room/build_funnel_report.py"""
from pathlib import Path

CLICKS = 350_000           # US: $350k spend / $1 CPC (data room)
LTV = 68                   # data room, 12-month forecast
# (step, % of all clicks who reached it) - data room "Кроки квізу". Step 2 is not given in the data room.
FUNNEL = [("Клік на рекламу", 100.0), ("Відкрили квіз", 88.0), ("Крок 3 з 6", 61.0), ("Крок 4 з 6 (розмір + email)", 58.0),
          ("Крок 5 з 6", 36.0), ("Персональна пропозиція", 31.0), ("Оплата", 2.0)]
NOTES = {1: "кліки, що не відкрили квіз (лендінг, не квіз)", 2: "тут два екрани: крок 2 у data room не вказано",
         3: "", 4: "ГОЛОВНИЙ ВИТІК: крок з email", 5: "", 6: "рішення про оплату (ціна й пропозиція), інша проблема"}
PAY = FUNNEL[-1][1]


def fmt(n): return f"{n:,.0f}".replace(",", " ")


rows = []
for i in range(len(FUNNEL) - 1):
    (a, ra), (b, rb) = FUNNEL[i], FUNNEL[i + 1]
    lost = ra - rb
    people = lost / 100 * CLICKS
    money = people * (PAY / rb) * LTV if i < len(FUNNEL) - 2 else None     # last hop: passing it IS buying, no meaningful ceiling
    rows.append(dict(i=i, a=a, b=b, ra=ra, rb=rb, lost=lost, share=lost / ra * 100, people=people, money=money, note=NOTES.get(i + 1, "")))

focus = max((r for r in rows if r["i"] not in (0, len(rows) - 1)), key=lambda r: r["lost"])
bars = "".join(
    f'<div class="row"><div class="lbl">{s}</div><div class="track"><div class="bar{" focus" if s.startswith("Крок 4") else ""}" '
    f'style="width:{max(r, 0.8)}%"></div></div><div class="val">{r:g}%</div></div>' for s, r in FUNNEL)
trs = "".join(
    f'<tr class="{"hl" if r is focus else ""}"><td>{r["a"]} → {r["b"]}</td><td class="n">{r["ra"]:g} → {r["rb"]:g}</td>'
    f'<td class="n"><b>−{r["lost"]:g}</b></td><td class="n">{r["share"]:.0f}%</td><td class="n">{fmt(r["people"])}</td>'
    f'<td class="n">{("$" + fmt(r["money"])) if r["money"] is not None else "—"}</td><td>{r["note"]}</td></tr>' for r in rows)

html = f"""<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SockLock · воронка квізу</title><style>
:root{{--bg:#fff;--fg:#1d2433;--mut:#667;--bar:#9db6d6;--focus:#d9534f;--line:#e3e7ee;--hl:#fdecea;--box:#f5f7fb}}
@media(prefers-color-scheme:dark){{:root{{--bg:#12161d;--fg:#e8ebf0;--mut:#98a2b3;--bar:#4a6a94;--focus:#e5645f;--line:#2a3140;--hl:#3a1f22;--box:#1a2029}}}}
body{{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif}}
main{{max-width:1000px;margin:auto}} h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:17px;margin-top:28px}} .dim{{color:var(--mut)}}
.row{{display:grid;grid-template-columns:220px 1fr 60px;gap:8px;align-items:center;margin:5px 0}}
.track{{background:var(--line);border-radius:4px;height:20px}} .bar{{background:var(--bar);height:100%;border-radius:4px}} .bar.focus{{background:var(--focus)}}
table{{border-collapse:collapse;width:100%;font-size:13px}} td,th{{border-bottom:1px solid var(--line);padding:7px 8px;text-align:left;vertical-align:top}}
td.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}} tr.hl{{background:var(--hl)}} .scroll{{overflow-x:auto}}
.box{{background:var(--box);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin-top:10px}}
</style></head><body><main>
<h1>SockLock: де відвалюються люди в квізі</h1>
<p class="dim">Джерело: data room домашнього завдання (відсотки від усіх, хто клікнув на рекламу). Масштаб: США, {fmt(CLICKS)} кліків на місяць ($350 000 ÷ $1), LTV ${LTV}.</p>

<h2>Воронка: скільки людей зі 100 лишається на кожному кроці</h2>{bars}

<h2>Де саме втрачаємо</h2>
<div class="scroll"><table><tr><th>Перехід</th><th>З 100 кліків</th><th>Втрата</th><th>Не пішли далі (від тих, хто дійшов)</th><th>Людей на місяць</th><th>Максимум $ на місяць</th><th>Що це</th></tr>{trs}</table></div>
<p class="dim">«Максимум $» — скільки було б, якби ніхто не відпадав на цьому переході (людина, що пройшла, купує з тією ж ймовірністю, що й усі на наступному кроці). Це не прогноз. Для переходу «пропозиція → оплата» грошей не рахуємо: це рішення про покупку.</p>

<div class="box"><b>Головне.</b> На кроці з email ({focus["ra"]:g} → {focus["rb"]:g}) зникають <b>{focus["lost"]:g} людей зі 100</b>, тобто {focus["share"]:.0f}% тих, хто до нього дійшов.
Це приблизно <b>{fmt(focus["people"])} людей на місяць</b>, а теоретичний максимум, якщо б не втрачали нікого, ≈ <b>${fmt(focus["money"])}</b> на місяць (реально повернути лише частину, див. розрахунок у документі).
Більші цифри втрат є ще на двох переходах, але вони іншого типу: «відкрили квіз → крок 3» ({rows[1]["lost"]:g}) охоплює два екрани, а «пропозиція → оплата» ({rows[-1]["lost"]:g}) це рішення про покупку, а не проблема форми.</div>

<h2>«Хто саме відпав?»</h2>
<div class="box">У data room є лише відсотки по кроках. <b>Списку людей, їхніх пристроїв, браузерів, креативів і помилок у ньому немає</b>, тому показати тут, хто саме відпав, не можна, не вигадуючи даних.
<ol><li>Growth PM вигружає експорт подій квізу з Amplitude (за словами з завдання, у нього такий CSV є).</li>
<li>Ви запускаєте <code>bash check.sh файл.csv</code> у папці <code>socklock-quizleak</code>.</li>
<li>Скрипт показує те саме, що вище, а також групи людей, що відпадають сильніше за решту, і список конкретних користувачів: хто, коли, де зупинився, з якого пристрою, яку помилку бачив.</li></ol>
Для демонстрації я згенерував <b>вигаданий</b> експорт квізу SockLock на 20 000 сесій (відкалібрований під цифри data room, з закладеними проблемами): <a href="../out/SockLock_quiz_events_SYNTHETIC/report.html">звіт «хто і де відвалився»</a>.</div>
</main></body></html>"""
out = Path(__file__).with_name("socklock_funnel_report.html")
out.write_text(html, encoding="utf-8")
print(out)
for r in rows:
    print(f'{r["a"]:>30} -> {r["b"]:<30} lost {r["lost"]:>4g} share {r["share"]:>4.0f}% people {fmt(r["people"]):>8} money {("$" + fmt(r["money"])) if r["money"] else "-"}')
