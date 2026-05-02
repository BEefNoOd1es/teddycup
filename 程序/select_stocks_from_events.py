from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import pandas as pd


def log(msg: str) -> None:
	print(f"[progress] {msg}", flush=True)


def read_csv_with_fallback(path: Path) -> tuple[pd.DataFrame, str]:
	encodings = ["utf-8-sig", "gb18030", "gbk", "utf-8"]
	last_error = None
	for enc in encodings:
		try:
			df = pd.read_csv(path, encoding=enc)
			return df, enc
		except Exception as exc:  # noqa: BLE001
			last_error = exc
	raise RuntimeError(f"读取失败: {path}，最后错误: {last_error}")


def pick_col(df: pd.DataFrame, exact_names: list[str], keyword_names: list[str], required: bool = True) -> str | None:
	cols = [str(c).strip() for c in df.columns]
	col_map = {str(c).strip(): c for c in df.columns}

	for name in exact_names:
		if name in col_map:
			return col_map[name]

	for c in cols:
		if any(k in c for k in keyword_names):
			return col_map[c]

	if required:
		raise KeyError(f"未找到列: exact={exact_names}, keyword={keyword_names}, 实际列={cols}")
	return None


def normalize_code(val) -> str:
	s = str(val).strip()
	if not s or s.lower() == "nan":
		return ""
	if s.endswith(".0"):
		s = s[:-2]
	return s.zfill(6)


def to_numeric(series: pd.Series) -> pd.Series:
	if pd.api.types.is_numeric_dtype(series):
		return pd.to_numeric(series, errors="coerce")
	cleaned = series.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False)
	return pd.to_numeric(cleaned, errors="coerce")


def is_st_name(name: str) -> bool:
	s = str(name)
	return bool(re.search(r"\*?ST|退", s, flags=re.IGNORECASE))


def normalize_name(name: str) -> str:
	return re.sub(r"\s+", "", str(name)).upper()


def latest_rows_asof(daily_df: pd.DataFrame, codes: list[str], asof_date: pd.Timestamp) -> pd.DataFrame:
	if not codes:
		return daily_df.iloc[0:0].copy()
	sub = daily_df[(daily_df["stock_code"].isin(codes)) & (daily_df["trade_date"] <= asof_date)]
	if sub.empty:
		return sub
	idx = sub.groupby("stock_code")["trade_date"].idxmax()
	return sub.loc[idx].copy()


def match_company_codes(concept_df: pd.DataFrame, companies: list[str]) -> list[str]:
	if not companies:
		return []
	stock_names = concept_df["stock_name_norm"]
	matched_codes: set[str] = set()
	for company in companies:
		c = normalize_name(company)
		if not c:
			continue
		mask = stock_names.str.contains(c, na=False, regex=False)
		if mask.any():
			matched_codes.update(concept_df.loc[mask, "stock_code"].astype(str).tolist())
	return sorted(matched_codes)


def main() -> None:
	start_ts = time.time()
	parser = argparse.ArgumentParser(description="按事件JSON和概念板块+日线数据执行选股")
	parser.add_argument("--events", default="test2.json", help="事件JSON文件")
	parser.add_argument("--concept", default="概念板块.csv", help="概念板块CSV")
	parser.add_argument("--daily", default="新日线数据.csv", help="新日线数据CSV")
	parser.add_argument("--out_csv", default="selected_stocks2.csv", help="输出CSV")
	parser.add_argument("--out_json", default="selected_stocks2.json", help="输出JSON")
	args = parser.parse_args()

	events_path = Path(args.events)
	concept_path = Path(args.concept)
	daily_path = Path(args.daily)

	log("开始读取事件JSON")

	with events_path.open("r", encoding="utf-8") as f:
		events = json.load(f)
	log(f"事件读取完成，共 {len(events)} 条")

	log("开始读取概念板块和日线数据CSV（大文件阶段可能较慢）")
	concept_raw, concept_enc = read_csv_with_fallback(concept_path)
	daily_raw, daily_enc = read_csv_with_fallback(daily_path)
	log(f"概念板块读取完成: {len(concept_raw)} 行")
	log(f"日线数据读取完成: {len(daily_raw)} 行")

	concept_col = pick_col(concept_raw, ["概念名称"], ["概念", "板块"])
	c_code_col = pick_col(concept_raw, ["股票代码", "代码", "证券代码"], ["代码"])
	c_name_col = pick_col(concept_raw, ["股票名称", "名称", "简称"], ["名称", "简称"])

	d_code_col = pick_col(daily_raw, ["代码", "股票代码", "证券代码"], ["代码"])
	d_date_col = pick_col(daily_raw, ["日期", "交易日期"], ["日期"])
	d_turn_col = pick_col(daily_raw, ["换手率(%)", "换手率%", "换手率"], ["换手"])
	d_float_col = pick_col(daily_raw, ["流通市值", "流通市值(亿)", "流通市值(亿元)"], ["流通", "市值"])

	concept_df = pd.DataFrame(
		{
			"concept_name": concept_raw[concept_col].astype(str).str.strip(),
			"stock_code": concept_raw[c_code_col].map(normalize_code),
			"stock_name": concept_raw[c_name_col].astype(str).str.strip(),
		}
	)
	concept_df = concept_df[concept_df["stock_code"] != ""]
	concept_df = concept_df[~concept_df["stock_name"].apply(is_st_name)].copy()
	concept_df["stock_name_norm"] = concept_df["stock_name"].map(normalize_name)

	daily_df = pd.DataFrame(
		{
			"stock_code": daily_raw[d_code_col].map(normalize_code),
			"trade_date": pd.to_datetime(daily_raw[d_date_col], errors="coerce"),
			"turnover_rate": to_numeric(daily_raw[d_turn_col]),
			"float_mv": to_numeric(daily_raw[d_float_col]),
		}
	)
	log("日线关键字段转换完成，开始清洗空值")
	daily_df = daily_df.dropna(subset=["trade_date", "turnover_rate", "float_mv"])
	daily_df = daily_df[daily_df["stock_code"] != ""]
	log(f"日线清洗后剩余 {len(daily_df)} 行")

	concept_name_to_codes = concept_df.groupby("concept_name")["stock_code"].apply(list).to_dict()
	code_to_name = concept_df.drop_duplicates("stock_code").set_index("stock_code")["stock_name"].to_dict()

	results: list[dict] = []
	ok_count = 0
	no_count = 0
	progress_every = max(20, len(events) // 20)
	log("开始逐条事件选股")

	for i, ev in enumerate(events, start=1):
		event_name = ev.get("event_title", "") or ev.get("event_level_2", "")  # 优先使用 event_title
		
		# 优先使用 publish_time，其次使用 date，最后使用空字符串
		event_date_raw = ev.get("publish_time") or ev.get("date", "")
		
		concepts = [str(x).strip() for x in ev.get("related_concepts", []) if str(x).strip()]
		companies = [str(x).strip() for x in ev.get("related_companies", []) if str(x).strip()]

		event_date = pd.to_datetime(event_date_raw, errors="coerce")
		if pd.isna(event_date):
			results.append(
				{
					"event_index": i,
					"event_title": event_name,
					"event_date": event_date_raw,
					"status": "no_match",
					"reason": "event_date 无法解析",
				}
			)
			no_count += 1
			if i % progress_every == 0 or i == len(events):
				elapsed = time.time() - start_ts
				log(f"已处理 {i}/{len(events)} ({i/len(events):.1%})，命中 {ok_count}，未命中 {no_count}，耗时 {elapsed:.1f}s")
			continue

		selected = None

		company_codes = match_company_codes(concept_df, companies)
		if company_codes:
			latest = latest_rows_asof(daily_df, company_codes, event_date)
			latest = latest[latest["float_mv"] < 500]
			if not latest.empty:
				row = latest.sort_values("turnover_rate", ascending=False).iloc[0]
				selected = {
					"matched_by": "company",
					"matched_value": ",".join(companies),
					"stock_code": row["stock_code"],
					"trade_date_used": row["trade_date"].strftime("%Y-%m-%d"),
					"turnover_rate": float(row["turnover_rate"]),
					"float_mv": float(row["float_mv"]),
				}

		if selected is None and concepts:
			concept_codes: set[str] = set()
			hit_concepts: list[str] = []
			for c in concepts:
				if c in concept_name_to_codes:
					concept_codes.update(concept_name_to_codes[c])
					hit_concepts.append(c)

			latest = latest_rows_asof(daily_df, sorted(concept_codes), event_date)
			latest = latest[latest["float_mv"] < 500]
			if not latest.empty:
				row = latest.sort_values("turnover_rate", ascending=False).iloc[0]
				selected = {
					"matched_by": "concept",
					"matched_value": ",".join(hit_concepts),
					"stock_code": row["stock_code"],
					"trade_date_used": row["trade_date"].strftime("%Y-%m-%d"),
					"turnover_rate": float(row["turnover_rate"]),
					"float_mv": float(row["float_mv"]),
				}

		if selected is None:
			results.append(
				{
					"event_index": i,
					"event_title": event_name,
					"event_date": event_date.strftime("%Y-%m-%d %H:%M:%S"),
					"related_companies": "|".join(companies),
					"related_concepts": "|".join(concepts),
					"status": "no_match",
					"reason": "公司未匹配或概念无候选，或候选流通市值均>=500亿",
				}
			)
			no_count += 1
			if i % progress_every == 0 or i == len(events):
				elapsed = time.time() - start_ts
				log(f"已处理 {i}/{len(events)} ({i/len(events):.1%})，命中 {ok_count}，未命中 {no_count}，耗时 {elapsed:.1f}s")
			continue

		code = selected["stock_code"]
		results.append(
			{
				"event_index": i,
				"event_title": event_name,
				"event_date": event_date.strftime("%Y-%m-%d %H:%M:%S"),
				"related_companies": "|".join(companies),
				"related_concepts": "|".join(concepts),
				"status": "ok",
				"matched_by": selected["matched_by"],
				"matched_value": selected["matched_value"],
				"stock_code": code,
				"stock_name": code_to_name.get(code, ""),
				"trade_date_used": selected["trade_date_used"],
				"turnover_rate": selected["turnover_rate"],
				"float_mv": selected["float_mv"],
			}
		)
		ok_count += 1
		if i % progress_every == 0 or i == len(events):
			elapsed = time.time() - start_ts
			log(f"已处理 {i}/{len(events)} ({i/len(events):.1%})，命中 {ok_count}，未命中 {no_count}，耗时 {elapsed:.1f}s")

	result_df = pd.DataFrame(results)
	result_df.to_csv(args.out_csv, index=False, encoding="utf-8-sig")
	Path(args.out_json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

	print(f"概念文件编码: {concept_enc}")
	print(f"日线文件编码: {daily_enc}")
	print(f"总事件数: {len(events)}")
	print(f"命中数: {(result_df['status'] == 'ok').sum() if 'status' in result_df.columns else 0}")
	print(f"输出CSV: {args.out_csv}")
	print(f"输出JSON: {args.out_json}")
	print(f"总耗时(秒): {time.time() - start_ts:.2f}")


if __name__ == "__main__":
	main()