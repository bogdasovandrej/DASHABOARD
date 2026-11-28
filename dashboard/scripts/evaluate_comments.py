"""Offline, answer-level benchmark for the final survey comments.

No model calls or database writes. Input data and annotations stay outside git.
"""
import argparse
import csv
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.comments import SIGNAL_WORDS, TOPIC_WORDS, by_dictionary, text_hash  # noqa: E402
from core.config import SIGNALS, TOPICS  # noqa: E402

FIELDS = ["id", "kind", "label", "quote", "supported"]


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def answers(path):
    rows = read_csv(path)
    ids = [r["id"] for r in rows]
    if len(ids) != len(set(ids)) or any(not x for x in ids):
        raise ValueError("Each answer must have one unique nonempty id")
    if not {"id", "role", "qid", "text"}.issubset(rows[0] if rows else []):
        raise ValueError("Answers need id, role, qid, text columns")
    return {r["id"]: r for r in rows}


def export(db_path, output):
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = conn.execute("select uid, role, qid, text from answers "
                            "where text is not null and trim(text) != '' order by uid").fetchall()
    finally:
        conn.close()
    write_csv(output, ["id", "role", "qid", "text"],
              [dict(zip(["id", "role", "qid", "text"], row)) for row in rows])
    print(f"Final set: {len(rows)} text answers (one imported answer to one question per id).")


def evidence(text, phrase):
    # A verbatim candidate for a reviewer to validate; matching words alone do not prove a label.
    start = text.lower().replace("ё", "е").find(phrase)
    return text[max(0, start - 35):min(len(text), start + len(phrase) + 35)] if start >= 0 else ""


def rules(answer_file, output):
    a = answers(answer_file)
    rows = []
    for id_, item in a.items():
        result = by_dictionary(item["text"], item["role"])
        normalized = item["text"].lower().replace("ё", "е")
        for kind, labels, words in [("topic", result["topics"], TOPIC_WORDS),
                                    ("signal", result["signals"], SIGNAL_WORDS)]:
            for label in labels:
                phrase = next((w for w in words[label] if w in normalized), "")
                rows.append({"id": id_, "kind": kind, "label": label,
                             "quote": evidence(item["text"], phrase) if phrase else "",
                             "supported": ""})
        if not result["topics"] and not result["signals"]:
            rows.append({"id": id_, "kind": "", "label": "", "quote": "", "supported": ""})
    write_csv(output, FIELDS, rows)


def snapshot(answer_file, db_path, output):
    """Export current app results and source; inspect sources before calling it an AI run."""
    a = answers(answer_file)
    conn = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        records = {row[0]: row[1:] for row in conn.execute(
            "select hash, topics, signals, quote, source from comment_ai")}
    finally:
        conn.close()
    rows = []
    sources = defaultdict(int)
    for id_, item in a.items():
        record = records.get(text_hash(item["role"], item["text"]))
        if record is None:
            raise ValueError(f"No processed result for answer {id_}; run the app first")
        topics, signals, quote, source = record
        sources[source] += 1
        labels = [("topic", t) for t in json.loads(topics or "[]")]
        labels += [("signal", s) for s in json.loads(signals or "[]")]
        for kind, label in labels:
            rows.append({"id": id_, "kind": kind, "label": label,
                         "quote": quote if kind == "signal" else "", "supported": ""})
        if not labels:
            rows.append({"id": id_, "kind": "", "label": "", "quote": "", "supported": ""})
    write_csv(output, FIELDS, rows)
    print(f"Answer sources: {dict(sources)}. Only call this AI when the model actually processed the answers.")


def labels(path, a, require_support=False):
    rows = read_csv(path)
    if not rows or not set(FIELDS).issubset(rows[0]):
        raise ValueError(f"{path}: expected columns {', '.join(FIELDS)}")
    if {r["id"] for r in rows} != set(a):
        raise ValueError(f"{path}: answer ids differ from the final set")
    result = {}
    for r in rows:
        kind, label, id_ = r["kind"], r["label"], r["id"]
        if not kind and not label:
            continue
        allowed = TOPICS if kind == "topic" else SIGNALS if kind == "signal" else []
        if label not in allowed:
            raise ValueError(f"{path}: invalid label {kind}:{label} for {id_}")
        key = (id_, kind, label)
        if key in result:
            raise ValueError(f"{path}: duplicate {key}")
        if require_support and r["supported"] not in ("yes", "no"):
            raise ValueError(f"{path}: mark supported=yes/no for {key} after checking the open answer")
        result[key] = r
    return result


def compare_reviewers(answer_file, first, second):
    a = answers(answer_file)
    x = labels(first, a)
    y = labels(second, a)
    return {"answers": len(a), "label_disagreements": [list(k) for k in sorted(x.keys() ^ y.keys())],
            "quote_disagreements": [list(k) for k in sorted(x.keys() & y.keys())
                                    if x[k]["quote"] != y[k]["quote"]],
            "support_disagreements": [list(k) for k in sorted(x.keys() & y.keys())
                                      if x[k]["supported"] != y[k]["supported"]]}


def score(answer_file, gold_file, predictions, times_file):
    a = answers(answer_file)
    gold = labels(gold_file, a, require_support=True)
    if any(r["supported"] != "yes" or not r["quote"] or r["quote"] not in a[k[0]]["text"]
           for k, r in gold.items()):
        raise ValueError("Gold labels need a verbatim, human-confirmed supporting quote")
    times = {}
    for row in read_csv(times_file):
        method = row["method"]
        if method in times:
            raise ValueError("Duplicate time method")
        processing = float(row["processing_minutes"])
        review = float(row["human_review_minutes"])
        if processing < 0 or review < 0:
            raise ValueError("Minutes must be nonnegative")
        times[method] = {"processing_minutes": processing, "human_review_minutes": review,
                         "total_minutes": processing + review}
    report = {"unit": "one imported text answer to one question (uid)", "answers": len(a), "methods": {}}
    for method, file in predictions.items():
        if method not in times:
            raise ValueError(f"Missing real timing for {method}")
        predicted = labels(file, a, require_support=True)
        table = {}
        errors = []
        for kind, names in (("topic", TOPICS), ("signal", SIGNALS)):
            for label in names:
                g = {key for key in gold if key[1:] == (kind, label)}
                p = {key for key in predicted if key[1:] == (kind, label)}
                unsupported = {key for key in p if predicted[key]["supported"] == "no"
                               or not predicted[key]["quote"]
                               or predicted[key]["quote"] not in a[key[0]]["text"]}
                table[f"{kind}:{label}"] = {
                    "found": len(g & p), "gold_total": len(g), "missed": len(g - p),
                    "false_alarms": len(p - g), "predicted_total": len(p),
                    "unsupported": len(unsupported), "unsupported_denominator": len(p),
                }
                errors.extend({"id": key[0], "kind": kind, "label": label, "error": "missed"}
                              for key in sorted(g - p))
                errors.extend({"id": key[0], "kind": kind, "label": label, "error": "false_alarm"}
                              for key in sorted(p - g))
                errors.extend({"id": key[0], "kind": kind, "label": label, "error": "unsupported_quote"}
                              for key in sorted(unsupported))
        report["methods"][method] = {"minutes": times[method], "per_label": table,
                                      "error_examples": errors[:30], "error_count": len(errors)}
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--db", required=True); e.add_argument("--out", required=True)
    r = sub.add_parser("rules"); r.add_argument("--answers", required=True); r.add_argument("--out", required=True)
    s = sub.add_parser("snapshot"); s.add_argument("--answers", required=True)
    s.add_argument("--db", required=True); s.add_argument("--out", required=True)
    c = sub.add_parser("compare-reviewers"); c.add_argument("--answers", required=True)
    c.add_argument("--first", required=True); c.add_argument("--second", required=True)
    b = sub.add_parser("score"); b.add_argument("--answers", required=True)
    b.add_argument("--gold", required=True); b.add_argument("--manual", required=True)
    b.add_argument("--rules", required=True); b.add_argument("--ai", required=True)
    b.add_argument("--times", required=True); b.add_argument("--out", required=True)
    args = p.parse_args()
    if args.cmd == "export": export(args.db, args.out)
    elif args.cmd == "rules": rules(args.answers, args.out)
    elif args.cmd == "snapshot": snapshot(args.answers, args.db, args.out)
    else:
        result = (compare_reviewers(args.answers, args.first, args.second) if args.cmd == "compare-reviewers"
                  else score(args.answers, args.gold,
                             {"manual": args.manual, "rules": args.rules, "ai": args.ai}, args.times))
        if args.cmd == "score":
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
