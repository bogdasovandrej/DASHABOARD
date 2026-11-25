# Интерфейс дашборда. Запуск: streamlit run app.py
# Здесь только отрисовка. Расчёты лежат в core/metrics.py, разбор комментариев в core/comments.py.
import time

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import comments, db, effect, ingest, llm, mail, metrics, playbook
from core.config import RED, YELLOW, demo_dir

st.set_page_config(page_title="Стажировки МГТС", layout="wide")

BLUE, ORANGE = "#2a78d6", "#eb6834"
SCALE = [[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]]  # 1 красный, 3 серый, 5 синий
# Внутри кода уровни называются высокий / средний / низкий. На экран выводим не «риск»,
# а то, что HR делать: мы не предсказываем уход, а подсказываем, с кем поговорить.
ZONE = {"высокий": "Поговорить на этой неделе", "средний": "Присмотреться", "низкий": "Всё в порядке"}
ZONE_COLOR = {"высокий": "red", "средний": "orange", "низкий": "green"}


def badge(level):
    return f":{ZONE_COLOR[level]}-background[{ZONE[level]}]"
PAGES = ["Обзор", "Стажёр", "Эффект", "Анкета", "Данные"]


@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()


def load_all():
    a = metrics.load(conn)
    # ответы на вопросы, которых нет в текущем файле сопоставления, не считаем (например, остались от старой анкеты)
    known = a[a["kind"].notna()]
    st.session_state["stale"] = len(a) > 0 and known.empty
    if known.empty:
        return None
    a = known
    mon = metrics.monthly(a)
    if mon.empty:
        return None
    com = metrics.comments(conn, a)
    risk = metrics.risk_table(mon, com, a).merge(metrics.people(a), on="intern")
    return a, mon, com, risk


def load_demo():
    db.clear(conn)
    for name, role in [("otvety_stazhery", "intern"), ("otvety_nastavniki", "mentor")]:
        ingest.ingest(conn, next(demo_dir().glob(name + ".*")), role)
    return comments.run(conn)


def style(fig, height=320):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=10, b=10),
        plot_bgcolor="white", font=dict(size=13),
        legend=dict(orientation="h", y=1.12, x=0),
        hoverlabel=dict(bgcolor="white"),
    )
    fig.update_xaxes(gridcolor="#eeeeee", zeroline=False)
    fig.update_yaxes(gridcolor="#eeeeee", zeroline=False)
    return fig


def delta(now, before):
    if pd.isna(now) or pd.isna(before):
        return None
    return f"{now - before:+.1f}"


def heatmap(table, height):
    fig = go.Figure(go.Heatmap(
        z=table.values, x=[f"{m} мес." for m in table.columns], y=list(table.index),
        zmin=1, zmax=5, colorscale=SCALE, xgap=2, ygap=2,
        text=table.round(1).astype(str).replace("nan", "нет").values, texttemplate="%{text}",
        hovertemplate="%{y}<br>%{x}: %{text}<extra></extra>",
        colorbar=dict(title="оценка", thickness=12),
    ))
    fig.update_yaxes(autorange="reversed")
    return style(fig, height)


def open_card():
    # вызывается при клике на строку в таблице "Кому нужно внимание"
    rows = st.session_state["attention"]["selection"]["rows"]
    if rows:
        st.session_state["intern"] = st.session_state["attention_names"][rows[0]]
        st.session_state["page"] = "Стажёр"


# ---------- боковая панель ----------
st.sidebar.title("Стажировки МГТС")
page = st.sidebar.radio("Раздел", PAGES, key="page")
data = load_all()
if data:
    depts = sorted(data[3]["dept"].unique())
    chosen = st.sidebar.multiselect("Подразделение", depts, placeholder="Все")
else:
    chosen = []
model = llm.name()
st.sidebar.caption(f"Нейросеть: {model}" if model else "Нейросеть не подключена, комментарии разбирает словарь")


# Раз в минуту забираем новые ответы из почты (форма шлёт письмо после каждого заполнения).
# Если что-то пришло, перерисовываем весь дашборд, чтобы новый ответ сразу попал в ленту и графики.
@st.fragment(run_every="60s")
def mail_watch():
    if not mail.configured():
        return
    # фрагмент выполняется и при каждом клике в дашборде, а заходить в почту нужно не чаще раза в минуту
    last = st.session_state.get("mail_last")
    if last is None or time.time() - last[0] >= 50:
        stats = mail.fetch(conn)
        last = (time.time(), stats)
        st.session_state["mail_last"] = last
        if stats["ответов"]:
            st.rerun(scope="app")
    _, stats = last
    if stats["ошибки"]:
        st.caption(f"Почта: {stats['ошибки'][0]}")


with st.sidebar:
    mail_watch()


# ---------- обзор ----------
def page_overview():
    a, mon, com, risk = data
    all_answers = data[0]
    people_names = set(all_answers["intern"].dropna().astype(str)) | set(all_answers["mentor"].dropna().astype(str))
    if chosen:
        risk = risk[risk["dept"].isin(chosen)]
    names = set(risk["intern"])
    a, mon, com = a[a["intern"].isin(names)], mon[mon["intern"].isin(names)], com[com["intern"].isin(names)]
    last = int(data[1]["month"].max())
    cur, prev = mon[mon["month"] == last], mon[mon["month"] == last - 1]

    st.title("Стажировки: общая картина")
    st.caption(f"Данные за {last} мес. из 6. Сравнение с прошлым месяцем.")
    st.caption("Зона показывает приоритет контакта по открытым правилам, а не вероятность ухода стажёра.")
    st.caption("Цитаты из комментариев показаны дословно; имена людей в них скрыты.")

    k = st.columns(6)
    k[0].metric("Стажёров", len(names), help="Число стажёров, для которых в данных есть ответы хотя бы за один месяц.")
    s_mean, s_prev = cur["s_avg"].mean(), prev["s_avg"].mean()
    m_mean, m_prev = cur["m_avg"].mean(), prev["m_avg"].mean()
    k[1].metric("Оценка стажёров", "нет данных" if pd.isna(s_mean) else f"{s_mean:.1f} / 5",
                delta(s_mean, s_prev), help="Средняя оценка стажировки в последнем месяце по ответившим стажёрам. Изменение — к прошлому месяцу.")
    k[2].metric("От наставников", "нет данных" if pd.isna(m_mean) else f"{m_mean:.1f} / 5",
                delta(m_mean, m_prev), help="Средняя оценка работы стажёров в последнем месяце по ответившим наставникам. Изменение — к прошлому месяцу.")
    e_now, e_prev = metrics.enps(mon, last), metrics.enps(mon, last - 1)
    k[3].metric("eNPS", e_now, None if e_now is None or e_prev is None else f"{e_now - e_prev:+d}",
                help="Готовность рекомендовать стажировку: доля оценок 9–10 минус доля оценок 0–6. Итог в пунктах от −100 до +100; без ответов значения нет.")
    answered = a.loc[(a["month"] == last) & (a["role"] == "intern") & a["kind"].ne("time"), "intern"].nunique()
    k[4].metric("Заполнили анкету", f"{answered}/{len(names)}",
                help="Сколько стажёров ответили в последнем месяце из общего числа стажёров в данных.")
    high, mid = (risk["level"] == "высокий").sum(), (risk["level"] == "средний").sum()
    k[5].metric("Нужно внимание", f"{high} + {mid}",
                help="Сначала число стажёров для разговора на этой неделе, затем число тех, за кем стоит присмотреться.")

    st.subheader("Кому нужно внимание на этой неделе")
    done = db.actions(conn)
    done_now = set(done[done["month"] == last]["intern"])
    att = risk[risk["level"] != "низкий"]
    todo = att[~att["intern"].isin(done_now)]
    if att.empty:
        st.success("Поговорить или присмотреться не нужно ни к кому.")
    elif todo.empty:
        st.success("Все действия на этот месяц отмечены как сделанные.")
    for r in todo.head(7).itertuples():
        act = playbook.action(r.intern, r.mentor, r.codes, r.level, last)
        quote = playbook.best_quote(com[com["intern"] == r.intern], last)
        with st.container(border=True):
            st.markdown(f"{badge(r.level)} **{r.intern}** · {r.dept} · наставник {r.mentor} · {r.score} баллов из 100")
            st.markdown(f"**Почему:** {'; '.join(r.why[:2])}")
            if quote:
                safe_quote = comments.mask(quote["quote"], people_names)
                st.markdown(f"**Цитата** ({quote['who']}, {quote['month']} мес.): «{safe_quote}»")
            st.markdown(f"**Что сделать:** {act['title']}. {act['why']}")
            with st.expander("Готовое сообщение"):
                for whom, text in act["messages"]:
                    st.caption(f"Кому: {whom}")
                    st.code(text, language=None, wrap_lines=True)
            b1, b2, _ = st.columns([1, 1, 5])
            b1.button("Сделано", key=f"done_{r.intern}", on_click=db.add_action,
                      args=(conn, r.intern, last, act["title"]))
            b2.button("Карточка", key=f"card_{r.intern}", on_click=go_to_card, args=(r.intern,))
    if len(todo) > 7:
        st.caption(f"Показаны 7 самых срочных. Ещё {len(todo) - 7} в таблице ниже.")
    if done_now:
        with st.expander(f"Сделано в этом месяце: {len(done_now)}"):
            d = done[done["month"] == last]
            st.dataframe(pd.DataFrame({"Стажёр": d["intern"], "Действие": d["title"], "Когда": d["done_at"]}),
                         hide_index=True, width="stretch")

    with st.expander("Все стажёры таблицей"):
        st.session_state["attention_names"] = list(risk["intern"])
        show = pd.DataFrame({
            "Стажёр": risk["intern"], "Подразделение": risk["dept"], "Наставник": risk["mentor"],
            "Зона": risk["level"].map(ZONE), "Балл": risk["score"],
            "Главные причины": risk["why"].map(lambda w: "; ".join(w[:3])),
        })
        st.dataframe(
            show, hide_index=True, width="stretch", key="attention",
            on_select=open_card, selection_mode="single-row",
            column_config={
                "Балл": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d", width="small"),
                "Главные причины": st.column_config.TextColumn(width="large"),
            },
        )
        st.caption("Нажмите на строку, чтобы открыть карточку стажёра.")

    ql = metrics.quality(a)
    formal = ql[(ql["month"] == last) & ql["formal"]]
    if len(formal):
        with st.expander(f"Формальные анкеты за {last} мес.: {len(formal)}. По ним нельзя сказать, что всё хорошо"):
            st.caption("Одинаковые оценки, пустой комментарий или заполнение за секунды. "
                       "Это не тревога, а пробел в данных: с этими стажёрами стоит коротко поговорить лично.")
            st.dataframe(pd.DataFrame({"Стажёр": formal["intern"], "Что не так": formal["notes"].map(", ".join)}),
                         hide_index=True, width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("##### Динамика по месяцам")
        st.caption("Показывает, как меняются оценки стажёров и наставников; каждая линия усредняет ответы за месяц.")
        g = mon.groupby("month")[["s_avg", "m_avg"]].mean().reindex(range(1, last + 1))
        fig = go.Figure()
        fig.add_scatter(x=g.index, y=g["s_avg"], name="Стажёры о стажировке", mode="lines+markers",
                        line=dict(color=BLUE, width=2), marker=dict(size=8))
        fig.add_scatter(x=g.index, y=g["m_avg"], name="Наставники о стажёрах", mode="lines+markers",
                        line=dict(color=ORANGE, width=2), marker=dict(size=8))
        fig.update_traces(hovertemplate="%{x} мес.: %{y:.2f}")
        fig.update_xaxes(title="месяц стажировки", dtick=1)
        fig.update_yaxes(range=[1, 5.1], title="средняя оценка")
        st.plotly_chart(style(fig), width="stretch")
    with right:
        st.markdown(f"##### Оценки стажёров по вопросам, {last} мес.")
        st.caption("Помогает увидеть, какой именно аспект стажировки просел; число в скобках — изменение к прошлому месяцу.")
        q = a[(a["role"] == "intern") & (a["avg"] == 1)]
        now_q = q[q["month"] == last].groupby("short")["score"].mean().sort_values(ascending=False)
        was_q = q[q["month"] == last - 1].groupby("short")["score"].mean()
        labels = [f"{v:.1f} ({v - was_q[i]:+.1f})" if i in was_q else f"{v:.1f}" for i, v in now_q.items()]
        fig = go.Figure(go.Bar(x=now_q.values, y=now_q.index, orientation="h", marker_color=BLUE,
                               text=labels, textposition="outside", hovertemplate="%{y}: %{x:.2f}<extra></extra>"))
        fig.update_xaxes(range=[0, 6], title="средняя оценка, в скобках изменение к прошлому месяцу")
        st.plotly_chart(style(fig), width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("##### Сигналы в комментариях")
        st.caption("Число стажёров с таким сигналом в комментариях за два последних месяца; это подсказка для проверки, не диагноз.")
        recent = com[com["month"] >= last - 1].explode("signals").dropna(subset=["signals"])
        if recent.empty:
            st.info("Тревожных сигналов в комментариях за два месяца нет.")
        else:
            cnt = recent.groupby("signals")["intern"].nunique().sort_values()
            fig = go.Figure(go.Bar(x=cnt.values, y=cnt.index, orientation="h", marker_color=BLUE,
                                   text=cnt.values, textposition="outside",
                                   hovertemplate="%{y}: %{x} чел.<extra></extra>"))
            fig.update_xaxes(title="сколько стажёров с таким сигналом за последние 2 месяца", dtick=1,
                             range=[0, cnt.max() + 0.6])
            st.plotly_chart(style(fig, 300), width="stretch")
    with right:
        st.markdown("##### Нагрузка наставников")
        st.dataframe(metrics.mentors(a, mon).round(1), hide_index=True, width="stretch", height=300)
        st.caption("Если стажёры низко оценивают помощь, а наставнику не хватает времени, "
                   "дело может быть в загрузке наставника. Таблица показывает число стажёров и обе стороны оценки помощи.")

    st.subheader("Карта оценок: стажёры по месяцам")
    st.caption("Средняя оценка стажёра за месяц. Сверху те, к кому нужно больше внимания. «нет» означает отсутствие оценки.")
    table = mon.pivot(index="intern", columns="month", values="s_avg").reindex(index=risk["intern"], columns=range(1, last + 1))
    st.plotly_chart(heatmap(table, 60 + 24 * len(table)), width="stretch")

    with st.expander("Как выбираем, с кем поговорить"):
        st.markdown(f"""
Балл это сумма по простым правилам, от 0 до 100. От {YELLOW} баллов зона «присмотреться». «Поговорить на этой неделе» — от {RED} баллов, если признаки пришли минимум из двух источников: оценки, текст комментариев, поведение (пропуск анкеты, формальные ответы). Прямые слова об уходе — «поговорить» сразу.

| Что случилось | Баллы |
|---|---|
| В комментарии есть намерение уйти | 50 |
| Средняя оценка месяца ниже 3.0 (ниже 3.5) | 30 (15) |
| Оценка упала на 0.8 и больше к двум прошлым месяцам (на 0.5) | 25 (12) |
| Не заполнил последнюю анкету | 20 |
| Средняя оценка наставника ниже 3.0 | 20 |
| Низкая оценка держится второй месяц | 15 |
| Оценка снижается три месяца подряд, всего на 0.8 и больше | 15 |
| Есть оценки 1-2 по отдельным вопросам (второй месяц подряд) | 15 (+10) |
| Стажёр и наставник расходятся на 1.2 балла и больше | 15 |
| Другие сигналы в комментариях: перегруз, мало задач и т.д. | 10 за каждый, максимум 20 |
| Не хочет оставаться, не рекомендует стажировку, наставник не рекомендует в штат | 10 |
| Негативный тон комментариев | 10 |
| Анкета заполнена формально (второй месяц подряд) | 8 (+8) |
| Комментарии стали намного короче | 6 |

Одна плохая цифра или одна фраза может быть случайностью, поэтому высокий балл из одного источника даёт только
«присмотреться». Все пороги лежат в `core/config.py`.
""")


# ---------- карточка стажёра ----------
def page_intern():
    a, mon, com, risk = data
    all_answers = data[0]
    people_names = set(all_answers["intern"].dropna().astype(str)) | set(all_answers["mentor"].dropna().astype(str))
    names = list(risk["intern"])
    if st.session_state.get("intern") not in names:
        st.session_state["intern"] = names[0]
    lv = dict(zip(risk["intern"], risk["level"]))
    name = st.selectbox("Стажёр", names, key="intern", format_func=lambda n: f"{n} · {ZONE[lv[n]].lower()}")
    r = risk[risk["intern"] == name].iloc[0]
    m = mon[mon["intern"] == name].sort_values("month")
    c = com[com["intern"] == name]
    last = int(mon["month"].max())
    timeline = m.set_index("month").reindex(range(1, last + 1))
    answers = a[(a["intern"] == name) & a["kind"].ne("time")]

    st.title(name)
    st.markdown(f"{badge(r['level'])} {r['dept']} · наставник {r['mentor']}")
    st.caption(f"Показатели за {last}-й месяц. Изменение видно, если у роли есть оценки за оба месяца.")
    k = st.columns(4)
    k[0].metric("Балл", f"{r['score']} из 100",
                help="Сумма объяснимых правил; зона зависит также от числа независимых источников сигналов.")
    s = m.dropna(subset=["s_avg"])
    mm = m.dropna(subset=["m_avg"])
    missing = []
    for column, role, label, key in [
        (k[1], "intern", "Оценка стажёра", "s_avg"),
        (k[2], "mentor", "Оценка наставника", "m_avg"),
    ]:
        received = set(answers.loc[answers["role"] == role, "month"])
        value = timeline.at[last, key]
        shown = "Нет оценки" if last in received else "Нет ответа"
        if pd.notna(value):
            shown = f"{value:.1f} / 5"
        column.metric(label, shown, delta(value, timeline.at[last - 1, key]) if last > 1 else None)
        missing.append(", ".join(map(str, sorted(set(timeline.index) - received))) or "нет пропусков")
    answered = answers.loc[answers["role"] == "intern", "month"].nunique()
    k[3].metric("Анкет стажёра", f"{answered} из {last}",
                help="Число месяцев, в которых стажёр дал хотя бы один ответ.")
    st.caption(f"Месяцы без ответа. Стажёр — {missing[0]}. Наставник — {missing[1]}.")

    left, right = st.columns([2, 3])
    with left:
        st.subheader("Из чего сложился балл")
        if r["parts"]:
            st.markdown("\n".join(f"- {t} **(+{p})**" for p, t in r["parts"]))
            total = sum(points for points, _ in r["parts"])
            cap = " В карточке действует предел 100 баллов." if total > 100 else ""
            st.caption(f"Сумма по правилам — {total} баллов.{cap} Источники признаков: {', '.join(r['sources'])}. "
                       "Таблица правил есть на странице «Обзор».")
            if r["score"] >= RED and r["level"] != "высокий":
                st.info(f"Балл высокий, но все признаки из одного источника ({r['sources'][0]}). "
                        "Поэтому «присмотреться», а не разговор на этой неделе.")
        else:
            st.success("Тревожных признаков нет.")

        evidence = playbook.best_quote(c, last)
        if evidence:
            quote = comments.mask(evidence["quote"], people_names)
            signals = ", ".join(evidence["signals"])
            st.markdown(f"**Цитата** ({evidence['who']}, {evidence['month']} мес., {signals}) «{quote}»")
            with st.expander("Исходный комментарий"):
                st.write(comments.mask(evidence["text"], people_names))

        st.subheader("Что сделать")
        act = playbook.action(name, r["mentor"], r["codes"], r["level"], last)
        if act:
            st.markdown(f"**{act['title']}.** {act['why']}")
            with st.expander("Готовое сообщение"):
                for whom, text in act["messages"]:
                    st.caption(f"Кому: {whom}")
                    st.code(text, language=None, wrap_lines=True)
        else:
            st.write("Отдельных действий не нужно, достаточно обычного контакта раз в месяц.")
        hist = db.actions(conn)
        hist = hist[hist["intern"] == name]
        if len(hist):
            st.markdown("**Что уже сделано:**")
            st.markdown("\n".join(f"- {x.month} мес.: {x.title} ({x.done_at[:10]})" for x in hist.itertuples()))
        if model:
            if st.button("Сводка от нейросети"):
                facts = [f"Подразделение: {r['dept']}. Идёт {last}-й месяц из 6."]
                facts.append("Оценка стажёра по месяцам: " + ", ".join(f"{int(x.month)}: {x.s_avg:.1f}" for x in s.itertuples()))
                facts.append("Оценка наставника по месяцам: " + ", ".join(f"{int(x.month)}: {x.m_avg:.1f}" for x in mm.itertuples()))
                facts.append("Почему нужен разговор: " + ("; ".join(r["why"]) or "нет"))
                quotes = [f"{'стажёр' if x.role == 'intern' else 'наставник'}, {x.month} мес.: {x.text}"
                          for x in c.itertuples() if x.signals]
                facts.append("Комментарии с сигналами: " + (" | ".join(quotes) or "нет"))
                people = list(risk["intern"]) + list(risk["mentor"])
                with st.spinner("Нейросеть пишет сводку"):
                    try:
                        st.info(comments.hr_summary(comments.mask("\n".join(facts), people)))
                    except Exception as e:
                        st.warning(f"Нейросеть не ответила: {e}")
        else:
            st.caption("Подключите нейросеть в файле .env, и здесь появится короткая сводка с советом для HR.")
    with right:
        st.subheader("Стажёр и наставник по месяцам")
        st.caption("Две линии показывают динамику и расхождение взглядов. Пробел означает отсутствие средней оценки.")
        fig = go.Figure()
        fig.add_scatter(x=list(timeline.index), y=timeline["s_avg"].tolist(), name="Стажёр о стажировке", mode="lines+markers",
                        line=dict(color=BLUE, width=2), marker=dict(size=8))
        fig.add_scatter(x=list(timeline.index), y=timeline["m_avg"].tolist(), name="Наставник о стажёре", mode="lines+markers",
                        line=dict(color=ORANGE, width=2), marker=dict(size=8))
        fig.update_traces(hovertemplate="%{x} мес.: %{y:.2f}")
        fig.update_xaxes(title="месяц стажировки", dtick=1, range=[0.8, last + 0.2])
        fig.update_yaxes(range=[1, 5.1], title="средняя оценка")
        st.plotly_chart(style(fig, 280), width="stretch")

    st.caption("Оценки ниже приведены к шкале от 1 до 5, где 5 всегда хорошо. Обратные вопросы перевёрнуты.")
    sc = a[(a["intern"] == name) & (a["kind"] == "scale")]
    left, right = st.columns(2)
    st.caption("Тепловые карты показывают оценки по каждому вопросу и месяцу; пустая клетка — нет ответа.")
    for col, role, title in [(left, "intern", "Ответы стажёра"), (right, "mentor", "Ответы наставника")]:
        with col:
            st.subheader(title)
            t = sc[sc["role"] == role].pivot_table(index="short", columns="month", values="score")
            if t.empty:
                st.caption("Ответов нет.")
            else:
                st.plotly_chart(heatmap(t.reindex(columns=range(1, last + 1)), 70 + 34 * len(t)), width="stretch")

    st.subheader("Комментарии")
    st.caption("Имена других людей скрыты. Цитата совпадает с показанным текстом комментария.")
    c = c[c["text"].notna() & c["text"].ne("")].sort_values(["month", "role"], ascending=[False, True])
    if c.empty:
        st.caption("Комментариев нет.")
    for x in c.itertuples():
        who = "Стажёр" if x.role == "intern" else "Наставник"
        shown_text = comments.mask(x.text, people_names)
        shown_quote = comments.mask(x.quote, people_names)
        with st.container(border=True):
            st.markdown(f"**{x.month} мес. · {who} · {x.short}**")
            st.write(shown_text)
            if x.signals:
                tags = " ".join(f":red-background[{s}]" for s in x.signals)
                st.markdown(tags + (f"  \nЦитата: «{shown_quote}»" if shown_quote else ""))
            st.caption(f"тон {x.sentiment:+.1f} · разобрал: {x.source}" if pd.notna(x.sentiment) else "ещё не разобран")


# ---------- эффект ----------
def rub(x):
    return f"{x:,.0f} ₽".replace(",", " ")


def page_effect():
    a, mon, com, risk = data
    last = int(mon["month"].max())
    high = int((risk["level"] == "высокий").sum())
    att = risk[risk["level"] != "низкий"]

    st.title("Эффект и как его измерить")
    st.warning("Все деньги на этой странице посчитаны из допущений слева. Настоящие цифры знает только МГТС: "
               "подставьте их, и расчёт пересчитается.")

    left, right = st.columns([2, 3])
    with left:
        st.subheader("Допущения")
        st.caption("Стартовые значения учебные. Подставьте данные МГТС перед тем, как обсуждать сумму с HR.")
        pay = st.number_input("Выплата стажёру в месяц, ₽", 0, 500000, 40000, step=5000, key="e_pay")
        months = st.number_input("На каком месяце стажёр обычно уходит", 1, 6, 4, key="e_months")
        hours = st.number_input("Часов наставника на стажёра в неделю", 0, 40, 4, key="e_hours")
        rate = st.number_input("Стоимость часа наставника, ₽", 0, 20000, 1500, step=100, key="e_rate")
        rehire = st.number_input("Набор нового стажёра на замену, ₽", 0, 1000000, 60000, step=5000, key="e_rehire")
        share = st.slider("Какую долю стажёров из зоны «поговорить» удаётся удержать, если вовремя вмешаться",
                          0, 100, 30, step=5, format="%d%%", key="e_share")
        price = st.number_input("Цена нейросети за 1000 токенов, ₽", 0.0, 100.0, 0.8, step=0.1, key="e_price")
        server = st.number_input("Сервер и поддержка в месяц, ₽", 0, 1000000, 3000, step=500, key="e_server")

    parts, loss = effect.loss_per_intern(pay, months, hours, rate, rehire)
    texts = com[com["text"].str.len() > 0]
    scale = 6 / last  # в базе пока не все шесть месяцев, пересчитываем на полный поток
    ai = effect.ai_cost(len(texts) * scale, texts["text"].str.len().sum() * scale, price)
    res = effect.summary(loss, high, share / 100, ai, server)

    with right:
        st.subheader("Результат на один поток стажёров")
        k = st.columns(3)
        k[0].metric("Потеря на одного ушедшего", rub(loss))
        k[1].metric("Сохраняем за поток", rub(res["saved"]), help="Число удержанных стажёров, умноженное на потерю на одного")
        k[2].metric("Затраты за поток", rub(res["cost"]), help="Нейросеть и сервер за шесть месяцев")
        st.markdown(
            f"Сейчас в зоне «поговорить» **{high}** из {len(risk)} стажёров. Если удержать {share}% из них "
            f"(это {res['kept']:.1f} чел.), поток сохраняет **{rub(res['saved'])}** при затратах **{rub(res['cost'])}**."
            + (f" Это примерно **{res['ratio']:.0f} к 1**." if res["ratio"] and res["ratio"] >= 1 else "")
        )
        st.caption("Сохранённая сумма — сценарная оценка из введённых допущений, не измеренная экономия.")
        st.markdown("##### Из чего складывается потеря на одного стажёра")
        st.dataframe(pd.DataFrame({"Статья": list(parts), "Сумма": [rub(v) for v in parts.values()]}),
                     hide_index=True, width="stretch")
        st.markdown("##### Из чего складываются затраты")
        st.dataframe(pd.DataFrame({
            "Статья": ["Нейросеть: разбор комментариев за 6 месяцев", "Сервер и поддержка за 6 месяцев"],
            "Сумма": [rub(ai), rub(server * 6)],
        }), hide_index=True, width="stretch")
        st.caption(f"Нейросеть считается от объёма текста: около {len(texts) * scale:.0f} комментариев за поток. "
                   "Баллы считает формула, поэтому токены тратятся только на чтение комментариев.")

    st.subheader("Как проверить, что дашборд работает")
    done = db.actions(conn)
    done_now = done[done["month"] == last]["intern"].nunique()
    answered = mon[mon["month"] == last]["s_avg"].notna().sum()
    st.dataframe(pd.DataFrame([
        ["Доля стажёров, перешедших в штат", "нужны данные HR об исходах", "сравнить поток с дашбордом и прошлый поток без него"],
        ["Доля ушедших до конца стажировки", "нужны данные HR об исходах", "то же сравнение потоков"],
        ["Опережение: за сколько месяцев до ухода появился сигнал", "на тестовых историях 1-2 месяца",
         "после потока сверить дату первого сигнала с датой ухода"],
        ["Ложные тревоги", "на тестовых данных лишних красных нет", "HR после разговора отмечает, подтвердилась ли проблема"],
        ["Тревоги, по которым HR что-то сделал", f"{done_now} из {len(att)} в этом месяце", "цель: все тревоги за неделю"],
        ["Заполненные анкеты", f"{answered} из {len(risk)} в этом месяце", "доля не должна падать от месяца к месяцу"],
    ], columns=["Показатель", "Сейчас", "Как проверяем"]), hide_index=True, width="stretch")
    st.caption("Классический A/B-тест здесь не подходит: стажёров мало, и оставлять часть без помощи неэтично. "
               "Поэтому сравниваем потоки между собой.")


# ---------- пробная анкета ----------
def go_to_card(name):
    st.session_state["intern"] = name
    st.session_state["page"] = "Стажёр"


def page_form():
    st.title("Пробная анкета")
    st.caption("Форма для проверки: пройдите анкету сами и посмотрите, что покажет дашборд. "
               "В работе ответы приходят из внешнего сервиса анкет, вопросы те же.")
    q = ingest.load_questions()
    col = dict(zip(q["id"], q["column"]))
    role = st.radio("Кто заполняет", ["intern", "mentor"], horizontal=True, key="f_role",
                    format_func=lambda r: "Стажёр" if r == "intern" else "Наставник")
    st.session_state.setdefault("f_start", time.time())  # засекаем время заполнения

    with st.form("anketa"):
        c = st.columns(4)
        name = c[0].text_input(col["intern"], "Тестов Андрей", key="f_name")
        dept = c[1].text_input(col["dept"], "Аналитика", key="f_dept")
        mentor = c[2].text_input(col["mentor"], "Белов А.", key="f_mentor")
        month = c[3].number_input(col["month"], 1, 6, int(data[1]["month"].max()) if data else 1, key="f_month",
                                  help="Зона считается на самый свежий месяц в базе, поэтому по умолчанию стоит он")
        answers = {}
        for r in q[q["role"] == role].itertuples():
            if r.kind == "scale":
                answers[r.column] = st.radio(r.column, list(range(int(r.min), int(r.max) + 1)), index=None,
                                             horizontal=True, key=f"f_{r.id}",
                                             help=f"{int(r.min)} совсем не согласен, {int(r.max)} полностью согласен")
            elif r.kind == "nps":
                answers[r.column] = st.radio(r.column, list(range(11)), index=None, horizontal=True, key=f"f_{r.id}")
            else:
                answers[r.column] = st.text_area(r.column, key=f"f_{r.id}", height=80)
        sent = st.form_submit_button("Отправить", type="primary")

    if not sent:
        return
    if not name.strip() or any(v is None for v in answers.values()):
        st.error("Ответьте на все вопросы со шкалой и укажите ФИО.")
        return
    seconds = round(time.time() - st.session_state.pop("f_start"))
    row = {col["intern"]: name.strip(), col["dept"]: dept, col["mentor"]: mentor, col["month"]: month,
           col["ts"]: time.strftime("%Y-%m-%d %H:%M:%S"), col["sec"]: seconds, **answers}
    rows, _ = ingest.to_rows(pd.DataFrame([row]), role)
    try:
        ingest.save(conn, rows)
    except ValueError as e:
        st.error(str(e))
        return
    comments.run(conn)

    a, mon, com, risk = load_all()
    person = ingest.clean_name(name)
    r = risk[risk["intern"] == person].iloc[0]
    st.success(f"Анкета сохранена. Заполнение заняло {seconds} сек.")
    st.markdown(badge(r["level"]))
    k = st.columns(2)
    k[0].metric("Балл", f"{r['score']} из 100")
    k[1].metric("Время заполнения", f"{seconds} сек")
    st.markdown("**Что увидел дашборд:**")
    st.markdown("\n".join(f"- {w}" for w in r["why"]) if r["why"] else "- тревожных признаков нет")
    mine = com[(com["intern"] == person) & (com["month"] == month) & (com["role"] == role)
               & com["text"].notna() & com["text"].ne("")]
    for x in mine.itertuples():
        tags = ", ".join(x.signals) if x.signals else "сигналов нет"
        st.markdown(f"- комментарий «{x.text}»: тон {x.sentiment:+.1f}, {tags} (разобрал: {x.source})")
    st.button("Открыть карточку стажёра", on_click=go_to_card, args=(person,))


# ---------- данные ----------
def page_data():
    st.title("Данные")
    a = metrics.load(conn)
    n_ai = int(metrics.comments(conn, a)["source"].notna().sum()) if len(a) else 0
    k = st.columns(4)
    k[0].metric("Анкет стажёров", a[a["role"] == "intern"].groupby(["intern", "month"]).ngroups)
    k[1].metric("Анкет наставников", a[a["role"] == "mentor"].groupby(["intern", "month"]).ngroups)
    k[2].metric("Комментариев", int(a["text"].notna().sum()))
    k[3].metric("Из них разобрано", n_ai)

    st.subheader("Ответы из Яндекс Форм")
    st.caption("Форма после каждого заполнения шлёт письмо с ответом. Дашборд проверяет почту раз в минуту сам, "
               "кнопка ниже проверяет сразу.")
    if mail.configured():
        if st.button("Проверить почту сейчас"):
            with st.spinner("Проверяю почту"):
                stats = mail.fetch(conn)
            if stats["ошибки"]:
                st.error(stats["ошибки"][0])
            else:
                st.success(f"Новых писем: {stats['писем']}, ответов загружено: {stats['ответов']}, "
                           f"пропущено: {stats['пропущено']}.")
    else:
        st.info("Почта не подключена. Впишите YANDEX_MAIL и YANDEX_APP_PASSWORD в файл .env и перезапустите дашборд.")

    st.subheader("Загрузить ответы файлом")
    st.caption("Подходит выгрузка из любого сервиса анкет: CSV, XLSX или JSON. Можно дать ссылку на CSV, "
               "например на опубликованную Google Таблицу с ответами формы. Повторная загрузка не создаёт дублей.")
    role = st.radio("Чьи это ответы", ["intern", "mentor"], horizontal=True,
                    format_func=lambda r: "Стажёры" if r == "intern" else "Наставники")
    file = st.file_uploader("Файл с ответами", type=["csv", "xlsx", "json"])
    sheet = 0
    file_ready = False
    if file is not None:
        try:
            if file.name.lower().endswith(".xlsx"):
                with pd.ExcelFile(file) as excel:
                    sheets = excel.sheet_names
                if len(sheets) > 1:
                    sheet = st.selectbox("В файле несколько листов. Какой загрузить?", sheets)
            file.seek(0)
            preview = ingest.read_export(file, sheet)
            file.seek(0)
            preview_stats = {}
            preview_rows, preview_unknown = ingest.to_rows(
                preview, role, stats=preview_stats, require_average=True
            )
            file_ready = True
            st.caption(f"Предварительная проверка без записи в базу: {len(preview)} строк, "
                       f"{len(preview_rows)} ответов распознано.")
            if preview_unknown:
                st.warning("Неузнанные колонки: " + ", ".join(map(str, preview_unknown)))
            dropped = sum(preview_stats.values())
            if dropped:
                st.info("При загрузке некорректные данные будут пропущены: "
                        f"{preview_stats['строк без ФИО или месяца']} строк без ФИО/месяца, "
                        f"{preview_stats['строк с месяцем вне диапазона 1–6']} строк с месяцем вне 1–6, "
                        f"{preview_stats['ответов с неверным значением']} нечисловых ответов, "
                        f"{preview_stats['ответов вне шкалы']} оценок за пределами шкалы.")
        except Exception as e:
            file.seek(0)
            st.warning(f"Предварительная проверка не пройдена: {e}")
    url = st.text_input("или ссылка на CSV")
    if st.button("Загрузить", type="primary", disabled=not (file_ready if file is not None else url)):
        try:
            if file is not None:
                file.seek(0)
            res = ingest.ingest(conn, file or url, role, sheet)
            stats = comments.run(conn)
            st.success(f"Загружено анкет: {res['анкет принято']}, ответов: {res['ответов']}. "
                       f"Строк в источнике: {res['анкет']}. "
                       f"Комментариев разобрано: {stats['всего']} (нейросеть {stats['нейросеть']}, словарь {stats['словарь']}).")
            if res["нераспознанные колонки"]:
                st.warning("Эти колонки не узнал и пропустил. Если они нужны, добавьте их в файл сопоставления: "
                           + ", ".join(res["нераспознанные колонки"]))
            if any(res[key] for key in ["строк без ФИО или месяца", "ответов с неверным значением",
                                        "ответов вне шкалы", "строк с месяцем вне диапазона 1–6"]):
                st.warning("При импорте были пропуски или исправления: "
                           f"строк без ФИО/месяца — {res['строк без ФИО или месяца']}, "
                           f"месяцев вне 1–6 — {res['строк с месяцем вне диапазона 1–6']}, "
                           f"нечисловых ответов — {res['ответов с неверным значением']}, "
                           f"оценок вне шкалы — {res['ответов вне шкалы']}.")
            for err in stats["ошибки"][:1]:
                st.warning(f"Нейросеть не ответила, сработал словарь. Ошибка: {err}")
        except Exception as e:
            st.error(f"Не получилось загрузить: {e}")

    st.subheader("Служебное")
    b = st.columns(3)
    if b[0].button("Загрузить демо-данные"):
        stats = load_demo()
        st.success(f"Демо-данные загружены. Комментариев разобрано: {stats['всего']}.")
    if b[1].button("Разобрать комментарии заново"):
        conn.execute("delete from comment_ai")
        bar = st.progress(0.0)
        stats = comments.run(conn, progress=bar.progress)
        st.success(f"Готово: нейросеть {stats['нейросеть']}, словарь {stats['словарь']}.")
        for err in stats["ошибки"][:1]:
            st.warning(f"Ошибка нейросети: {err}")
    if b[2].button("Очистить базу"):
        db.clear(conn)
        st.success("База пустая.")

    with st.expander("Какие вопросы знает дашборд"):
        q = ingest.load_questions()[["column", "role", "kind", "block", "min", "max", "reverse", "avg", "short"]]
        st.dataframe(q, hide_index=True, width="stretch")


if page == "Данные":
    page_data()
elif page == "Анкета":
    page_form()
elif data is None:
    st.title("Данных пока нет")
    if st.session_state.get("stale"):
        st.warning("В базе лежат ответы от другой анкеты: их вопросов нет в текущем файле сопоставления. "
                   "Очистите базу в разделе «Данные» и загрузите ответы заново.")
    st.write("Загрузите выгрузку опросов в разделе «Данные» или начните с демо-набора.")
    if st.button("Загрузить демо-данные", type="primary"):
        load_demo()
        st.rerun()
elif page == "Обзор":
    page_overview()
elif page == "Эффект":
    page_effect()
else:
    page_intern()
