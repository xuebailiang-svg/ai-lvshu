"""
评估报告 PDF 生成服务
使用 reportlab 生成专业的选址评估报告 PDF
"""
import io
import math
import html
from datetime import datetime
from typing import Optional

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether
    )
    from reportlab.graphics.shapes import Drawing, Polygon, Circle, Line, String
    from reportlab.graphics import renderPDF
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


def _register_fonts():
    """注册中文字体（使用系统字体）"""
    import os
    font_paths = [
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/System/Library/Fonts/PingFang.ttc",
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("ChineseFont", path))
                pdfmetrics.registerFont(TTFont("ChineseFontBold", path))
                return True
            except Exception:
                continue
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        return "cid"
    except Exception:
        return False
    return False


def _clean_pdf_text(value: object) -> str:
    """去掉 PDF 字体通常无法覆盖的 emoji 和控制字符。"""
    text = "" if value is None else str(value)
    cleaned = []
    for ch in text:
        code = ord(ch)
        if code in (9, 10, 13) or code >= 32:
            if not (0x1F000 <= code <= 0x1FAFF or 0x2600 <= code <= 0x27BF):
                cleaned.append(ch)
    return "".join(cleaned)


def _escape_html(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _nl2br(value: object) -> str:
    return _escape_html(value).replace("\n", "<br>")


def _poi_distance(value: object) -> str:
    if value is None or value == "":
        return "-"
    text = str(value)
    return text if text.endswith("m") else f"{text}m"


def _poi_rows(pois: list[dict], empty_text: str = "暂无明细") -> str:
    if not pois:
        return f"<tr><td colspan=\"4\" class=\"muted\">{_escape_html(empty_text)}</td></tr>"
    rows = []
    for poi in pois:
        type_text = poi.get('classification_label') or poi.get('type') or '-'
        if poi.get("typecode"):
            type_text = f"{type_text} / typecode:{poi.get('typecode')}"
        rows.append(
            "<tr>"
            f"<td>{_escape_html(poi.get('name') or '-')}</td>"
            f"<td>{_escape_html(type_text)}</td>"
            f"<td>{_escape_html(_poi_distance(poi.get('distance')))}</td>"
            f"<td>{_escape_html(poi.get('classification_reason') or poi.get('address') or '-')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _poi_rows_detailed(pois: list[dict], empty_text: str = "高德 API 已查询，未返回可用 POI") -> str:
    if not pois:
        return f"<tr><td colspan=\"6\" class=\"muted\">{_escape_html(empty_text)}</td></tr>"
    status_map = {
        "included": "计入",
        "pending_review": "待核验",
        "excluded": "误匹配排除",
        "manual_added": "人工补充",
    }
    rows = []
    for poi in pois:
        source = poi.get("source") or poi.get("data_source") or "高德API"
        if source in {"amap", "api"}:
            source = "高德API"
        type_text = poi.get('classification_label') or poi.get('type') or '-'
        if poi.get("typecode"):
            type_text = f"{type_text} / typecode:{poi.get('typecode')}"
        rows.append(
            "<tr>"
            f"<td>{_escape_html(poi.get('name') or '-')}</td>"
            f"<td>{_escape_html(type_text)}</td>"
            f"<td>{_escape_html(_poi_distance(poi.get('distance')))}</td>"
            f"<td>{_escape_html(poi.get('classification_reason') or poi.get('address') or poi.get('notes') or '-')}</td>"
            f"<td>{_escape_html(status_map.get(poi.get('status'), poi.get('status') or '未标注'))}</td>"
            f"<td>{_escape_html(source)}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _collect_report_rows(table: dict, *keys: str) -> list[dict]:
    rows = []
    if not isinstance(table, dict):
        return rows
    for key in keys:
        value = table.get(key)
        if isinstance(value, list):
            rows.extend([row for row in value if isinstance(row, dict)])
    return rows


def _audit_summary_rows(rows: list[dict]) -> str:
    if not rows:
        return "<tr><td colspan=\"9\" class=\"muted\">暂无原始 POI 审计统计</td></tr>"
    html_rows = []
    for row in rows:
        html_rows.append(
            "<tr>"
            f"<td>{_escape_html(row.get('label') or row.get('key') or '-')}</td>"
            f"<td>{_escape_html(row.get('keywords') or '-')}</td>"
            f"<td>{_escape_html(row.get('raw_count', 0))}</td>"
            f"<td>{_escape_html(row.get('deduped_count', 0))}</td>"
            f"<td>{_escape_html(row.get('included_count', 0))}</td>"
            f"<td>{_escape_html(row.get('pending_count', 0))}</td>"
            f"<td>{_escape_html(row.get('excluded_count', 0))}</td>"
            f"<td>{_escape_html(row.get('displayed_count', 0))}</td>"
            f"<td>{'是' if row.get('is_truncated') else '否'}</td>"
            "</tr>"
        )
    return "\n".join(html_rows)


def _research_table_rows(rows: list[dict], columns: list[tuple[str, str]], empty_text: str = "暂无调研数据") -> str:
    if not rows:
        return f"<tr><td colspan=\"{len(columns)}\" class=\"muted\">{_escape_html(empty_text)}</td></tr>"
    html_rows = []
    for row in rows:
        cells = []
        for key, _label in columns:
            value = row.get(key)
            if isinstance(value, bool):
                value = "是" if value else "否"
            cells.append(f"<td>{_escape_html(value if value not in (None, '') else '-')}</td>")
        html_rows.append(f"<tr>{''.join(cells)}</tr>")
    return "\n".join(html_rows)


def _research_table_header(columns: list[tuple[str, str]]) -> str:
    return "".join(f"<th>{_escape_html(label)}</th>" for _key, label in columns)


def _dimension_label(key: str) -> str:
    return {
        "traffic": "交通与人流",
        "competition": "竞品分析",
        "population": "目标客群",
        "rent": "租金成本",
        "facility": "配套设施",
        "policy": "政策环境",
    }.get(key, key)


def generate_evaluation_report_html(
    evaluation_result: dict,
    ai_report: str = "",
    similar_cases: list = None,
) -> str:
    """生成更适合浏览器查看和归档的 HTML 报告。"""
    similar_cases = similar_cases or []
    dimensions = evaluation_result.get("dimensions", {}) or {}
    address = evaluation_result.get("address", "未知地址")
    total_score = evaluation_result.get("total_score", 0)
    grade = evaluation_result.get("grade", "C")
    grade_label = evaluation_result.get("grade_label", "")
    model = evaluation_result.get("model_version") or {}
    data_quality = evaluation_result.get("data_quality") or {}
    manual_data = evaluation_result.get("manual_data") or {}
    research_fields = evaluation_result.get("research_required_fields") or []
    confirmed_tables = evaluation_result.get("confirmed_poi_tables") or {}
    excluded_tables = evaluation_result.get("excluded_poi_tables") or {}
    poi_audit_summary = evaluation_result.get("poi_audit_summary") or data_quality.get("poi_audit_summary") or []
    evaluated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    dimension_cards = []
    for key, dim in dimensions.items():
        score = dim.get("score", 0)
        factor_rows = []
        for factor in dim.get("factor_breakdown") or []:
            factor_score = factor.get("score")
            factor_status = "待调研/未启用" if factor_score is None else f"{factor_score} 分"
            factor_rows.append(
                "<tr>"
                f"<td>{_escape_html(factor.get('name') or factor.get('sub_factor'))}</td>"
                f"<td>{_escape_html(factor.get('weight', 0))}%</td>"
                f"<td>{_escape_html(factor_status)}</td>"
                f"<td>{_escape_html(factor.get('source') or '-')}</td>"
                f"<td>{_escape_html(factor.get('basis') or factor.get('description') or '-')}</td>"
                "</tr>"
            )
        factor_table = ""
        if factor_rows:
            factor_table = (
                "<table class=\"factor-table\"><thead><tr>"
                "<th>子因子</th><th>权重</th><th>得分/状态</th><th>来源</th><th>依据</th>"
                "</tr></thead><tbody>"
                + "\n".join(factor_rows)
                + "</tbody></table>"
            )
        dimension_cards.append(f"""
        <section class="card dimension">
          <div class="card-head">
            <h3>{_escape_html(_dimension_label(str(key)))}</h3>
            <span class="score">{_escape_html(score)} 分</span>
          </div>
          <div class="bar"><span style="width:{max(0, min(100, float(score or 0)))}%"></span></div>
          <p>{_nl2br(dim.get("detail", ""))}</p>
          {factor_table}
        </section>
        """)

    quality_items = []
    for item in data_quality.get("items") or []:
        status = "缺失/待调研" if item.get("status") == "missing" else ("模拟/估算" if item.get("status") == "simulation" else "真实数据")
        quality_items.append(
            f"<tr><td>{_escape_html(item.get('name'))}</td><td>{_escape_html(status)}</td><td>{_escape_html(item.get('source') or item.get('detail') or '')}</td></tr>"
        )
    quality_rows = "\n".join(quality_items) or "<tr><td colspan=\"3\" class=\"muted\">暂无数据质量标注</td></tr>"

    required_rows = "\n".join(
        f"<tr><td>{_escape_html(item.get('label'))}</td><td>{_escape_html(item.get('status'))}</td></tr>"
        for item in research_fields
    ) or "<tr><td colspan=\"2\" class=\"muted\">暂无调研字段状态</td></tr>"

    competition = dimensions.get("competition") or {}
    population = dimensions.get("population") or {}
    traffic = dimensions.get("traffic") or {}
    facility = dimensions.get("facility") or {}
    policy = dimensions.get("policy") or {}

    competitor_table = confirmed_tables.get("competitors") or {}
    competitor_items = _collect_report_rows(competitor_table, "amap", "manual")
    pending_competitors = _collect_report_rows(competitor_table, "pending")
    if not competitor_items:
        competitor_items = competition.get("competitor_pois_1500m") or competition.get("valid_competitor_pois") or []
    confirmed_competitors = (competition.get("local_competitor_profiles") or []) + (competition.get("manual_competitors") or [])
    excluded_competitors = excluded_tables.get("competitors") or competition.get("excluded_competitor_pois") or []
    market_capacity = competition.get("market_capacity") or {}
    education_table = confirmed_tables.get("education") or {}
    education_core_items = _collect_report_rows(education_table, "core") or population.get("education_core_pois") or []
    education_extended_items = _collect_report_rows(education_table, "extended") or population.get("education_extended_pois") or []
    education_items = (education_core_items + education_extended_items) or _collect_report_rows(education_table, "amap") or population.get("education_pois") or population.get("university_pois") or []
    pending_education = _collect_report_rows(education_table, "pending") or population.get("education_candidate_pois") or []
    excluded_education = excluded_tables.get("education") or population.get("excluded_education_pois") or []
    traffic_station_items = _collect_report_rows(confirmed_tables.get("traffic_stations") or {}, "amap", "manual") or traffic.get("transit_pois") or []
    commercial_items = _collect_report_rows(confirmed_tables.get("commercial_places") or {}, "amap", "manual") or traffic.get("commercial_pois") or []
    traffic_items = traffic_station_items + commercial_items
    facility_items = (
        _collect_report_rows(confirmed_tables.get("food_places") or {}, "amap", "manual")
        + _collect_report_rows(confirmed_tables.get("entertainment_places") or {}, "amap", "manual")
        + _collect_report_rows(confirmed_tables.get("convenience_stores") or {}, "amap", "manual")
        + _collect_report_rows(confirmed_tables.get("parking_places") or {}, "amap")
    ) or (facility.get("food_pois") or []) + (facility.get("entertainment_pois") or []) + (facility.get("convenience_pois") or []) + (facility.get("parking_pois") or [])
    entertainment_items = _collect_report_rows(confirmed_tables.get("entertainment_places") or {}, "amap", "manual") or facility.get("entertainment_pois") or []
    residential_office_items = _collect_report_rows(confirmed_tables.get("residential_office") or {}, "amap", "manual") or (population.get("residential_pois") or []) + (population.get("office_pois") or [])
    policy_redline_items = _collect_report_rows(confirmed_tables.get("policy_redline") or {}, "amap") or policy.get("policy_redline_pois") or []
    pending_policy_redline = _collect_report_rows(confirmed_tables.get("policy_redline") or {}, "pending") or policy.get("policy_redline_candidate_pois") or []
    excluded_policy_redline = excluded_tables.get("policy_redline") or policy.get("excluded_policy_redline_pois") or []
    manual_competitors = ((confirmed_tables.get("competitors") or {}).get("manual") or manual_data.get("competitors") or [])
    manual_food = ((confirmed_tables.get("food_places") or {}).get("manual") or manual_data.get("food_places") or [])
    manual_night = ((confirmed_tables.get("night_markets") or {}).get("manual") or manual_data.get("night_markets") or [])
    manual_entertainment = ((confirmed_tables.get("entertainment_places") or {}).get("manual") or manual_data.get("entertainment_places") or [])
    manual_convenience = ((confirmed_tables.get("convenience_stores") or {}).get("manual") or manual_data.get("convenience_stores") or [])
    excluded_manual_rows = []
    for key in ["competitors", "food_places", "night_markets", "entertainment_places", "convenience_stores"]:
        excluded_manual_rows.extend(excluded_tables.get(key) or [])

    competitor_columns = [
        ("name", "竞品名"), ("distance", "距离(m)"), ("configuration", "配置"), ("machine_count", "机器数"),
        ("area_sqm", "面积(㎡)"), ("hourly_price", "小时价"), ("occupancy_rate", "上座率(%)"),
        ("monthly_sales", "月售"), ("source", "来源"), ("notes", "备注")
    ]
    facility_columns = [
        ("name", "名称"), ("type", "类型"), ("distance", "距离(m)"), ("business_hours", "营业时间"),
        ("open_years", "开业年限"), ("source", "来源"), ("notes", "备注")
    ]
    night_columns = [
        ("name", "名称/位置"), ("stall_count", "摊位数量"), ("distance", "距离(m)"), ("business_hours", "营业时间"),
        ("scale", "规模"), ("source", "来源"), ("notes", "备注")
    ]
    convenience_columns = [
        ("name", "名称"), ("distance", "距离(m)"), ("is_24h", "24小时"), ("business_hours", "营业时间"),
        ("source", "来源"), ("notes", "备注")
    ]

    cases_html = []
    for case in similar_cases[:5]:
        cases_html.append(f"""
        <article class="case">
          <div class="case-title">{_escape_html(case.get('name') or case.get('address') or '历史案例')}</div>
          <div class="case-meta">相似度 {_escape_html(case.get('similarity', '-'))}% · 得分 {_escape_html(case.get('total_score', '-'))}</div>
          <p>{_escape_html(case.get('experience_notes') or case.get('summary') or case.get('address') or '')}</p>
        </article>
        """)

    if market_capacity.get("can_calculate"):
        capacity_html = f"""
        <table><thead><tr><th>指标</th><th>结果</th></tr></thead><tbody>
          <tr><td>有效消费人群</td><td>{_escape_html(market_capacity.get('effective_people'))} 人</td></tr>
          <tr><td>理论月市场规模</td><td>{_escape_html(market_capacity.get('monthly_market_size'))} 元</td></tr>
          <tr><td>单店健康月营收假设</td><td>{_escape_html(market_capacity.get('healthy_monthly_revenue'))} 元</td></tr>
          <tr><td>理论可容纳门店数</td><td>{_escape_html(market_capacity.get('supportable_store_count'))} 家</td></tr>
          <tr><td>已识别竞品供给</td><td>{_escape_html(market_capacity.get('existing_supply_count'))} 家</td></tr>
          <tr><td>剩余容量</td><td>{_escape_html(market_capacity.get('remaining_capacity'))} 家</td></tr>
          <tr><td>数据来源</td><td>{_escape_html(market_capacity.get('source_label'))}</td></tr>
        </tbody></table>
        """
    else:
        capacity_html = f"<div class=\"card muted\">商圈容量暂未计算：{_escape_html(market_capacity.get('detail') or '缺少有效人群、转化率、消费频次、客单价或健康月营收假设')}</div>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>电竞馆选址评估报告</title>
  <style>
    body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",Arial,sans-serif; background:#f4f6fb; color:#172033; }}
    .page {{ max-width:1180px; margin:0 auto; padding:32px 28px 56px; }}
    .hero {{ background:linear-gradient(135deg,#101827,#26345a); color:#fff; border-radius:14px; padding:30px 34px; box-shadow:0 18px 50px rgba(16,24,39,.18); }}
    .hero h1 {{ margin:0 0 12px; font-size:30px; letter-spacing:0; }}
    .address {{ font-size:16px; opacity:.82; line-height:1.6; }}
    .summary {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-top:24px; }}
    .metric {{ background:rgba(255,255,255,.1); border:1px solid rgba(255,255,255,.16); border-radius:10px; padding:14px; }}
    .metric span {{ display:block; opacity:.68; font-size:13px; margin-bottom:8px; }}
    .metric strong {{ font-size:24px; }}
    .section {{ margin-top:24px; }}
    .section h2 {{ margin:0 0 12px; font-size:20px; color:#121827; }}
    .grid {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }}
    .card {{ background:#fff; border:1px solid #e4e9f3; border-radius:12px; padding:18px; box-shadow:0 8px 24px rgba(20,30,55,.06); }}
    .card-head {{ display:flex; align-items:center; justify-content:space-between; gap:12px; }}
    .card h3 {{ margin:0; font-size:16px; }}
    .score {{ color:#245cff; font-weight:800; }}
    .bar {{ height:8px; background:#e8edf7; border-radius:999px; overflow:hidden; margin:12px 0; }}
    .bar span {{ display:block; height:100%; background:linear-gradient(90deg,#2f6bff,#21b6a8); }}
    p {{ line-height:1.75; margin:10px 0 0; }}
    table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 8px 24px rgba(20,30,55,.06); }}
    th,td {{ border-bottom:1px solid #e8edf5; padding:11px 12px; text-align:left; font-size:14px; vertical-align:top; }}
    th {{ background:#eef4ff; color:#1c3569; font-weight:700; }}
    .muted {{ color:#7c8799; }}
    .big-rate {{ margin:6px 0 14px; color:#245cff; font-size:34px; font-weight:850; line-height:1; }}
    .poi-title {{ margin:18px 0 8px; font-weight:800; color:#26345a; }}
    .factor-table {{ margin-top:12px; box-shadow:none; border:1px solid #e8edf5; }}
    .factor-table th,.factor-table td {{ font-size:12px; padding:8px; }}
    .ai {{ white-space:pre-wrap; background:#fff; border-left:4px solid #2f6bff; border-radius:12px; padding:18px; line-height:1.8; box-shadow:0 8px 24px rgba(20,30,55,.06); }}
    .case {{ background:#fff; border:1px solid #e4e9f3; border-radius:10px; padding:14px; margin-bottom:10px; }}
    .case-title {{ font-weight:800; }}
    .case-meta {{ margin-top:6px; color:#667085; font-size:13px; }}
    @media (max-width:800px) {{ .summary,.grid {{ grid-template-columns:1fr; }} .page {{ padding:18px 14px 36px; }} }}
  </style>
</head>
<body>
  <main class="page">
    <header class="hero">
      <h1>电竞馆选址评估报告</h1>
      <div class="address">{_escape_html(address)}</div>
      <div class="summary">
        <div class="metric"><span>综合得分</span><strong>{_escape_html(total_score)}</strong></div>
        <div class="metric"><span>评级</span><strong>{_escape_html(grade)}</strong></div>
        <div class="metric"><span>结论</span><strong>{_escape_html(grade_label)}</strong></div>
        <div class="metric"><span>模型版本</span><strong>{_escape_html(model.get('name') or '当前评分权重')}</strong></div>
      </div>
    </header>

    <section class="section">
      <h2>一、六维评分</h2>
      <div class="grid">{''.join(dimension_cards)}</div>
    </section>

    <section class="section">
      <h2>二、数据来源与质量</h2>
      <table><thead><tr><th>数据项</th><th>来源状态</th><th>说明</th></tr></thead><tbody>{quality_rows}</tbody></table>
    </section>

    <section class="section">
      <h2>三、调研工作台数据</h2>
      <div class="grid">
        <section class="card">
          <h3>调研字段完整度</h3>
          <p class="big-rate">{_escape_html(evaluation_result.get('research_completion_rate', 0))}%</p>
          <table><thead><tr><th>字段</th><th>状态</th></tr></thead><tbody>{required_rows}</tbody></table>
        </section>
        <section class="card">
          <h3>使用原则</h3>
          <p>初版报告用于筛选方向；正式投资决策前，请补齐调研工作台中的关键字段后重新生成报告。AI 报告不得补编缺失字段，人工确认数据优先于待核验 API 底表。</p>
        </section>
      </div>
      <div class="poi-title">人工/外部补充竞品</div>
      <table><thead><tr>{_research_table_header(competitor_columns)}</tr></thead><tbody>{_research_table_rows(manual_competitors, competitor_columns, '暂无人工补充竞品')}</tbody></table>
      <div class="poi-title">人工补充餐饮</div>
      <table><thead><tr>{_research_table_header(facility_columns)}</tr></thead><tbody>{_research_table_rows(manual_food, facility_columns, '暂无人工补充餐饮')}</tbody></table>
      <div class="poi-title">人工补充夜市摊</div>
      <table><thead><tr>{_research_table_header(night_columns)}</tr></thead><tbody>{_research_table_rows(manual_night, night_columns, '暂无人工补充夜市摊')}</tbody></table>
      <div class="poi-title">人工补充娱乐配套</div>
      <table><thead><tr>{_research_table_header(facility_columns)}</tr></thead><tbody>{_research_table_rows(manual_entertainment, facility_columns, '暂无人工补充娱乐配套')}</tbody></table>
      <div class="poi-title">人工补充便利店</div>
      <table><thead><tr>{_research_table_header(convenience_columns)}</tr></thead><tbody>{_research_table_rows(manual_convenience, convenience_columns, '暂无人工补充便利店')}</tbody></table>
      <div class="poi-title">人工标记排除项</div>
      <table><thead><tr><th>名称</th><th>类型</th><th>距离</th><th>依据</th></tr></thead><tbody>{_poi_rows(excluded_manual_rows, '暂无人工排除项')}</tbody></table>
    </section>

    <section class="section">
      <h2>四、真实高德 POI 明细</h2>
      <div class="poi-title">原始 POI 汇总</div>
      <table><thead><tr><th>模块</th><th>关键词</th><th>原始返回</th><th>去重后</th><th>计入</th><th>待核验</th><th>排除</th><th>展示</th><th>截断</th></tr></thead><tbody>{_audit_summary_rows(poi_audit_summary)}</tbody></table>
      <div class="poi-title">竞品明细：{_escape_html(competition.get('competitor_filter_summary') or competition.get('detail') or '')}</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(competitor_items, '高德未返回可计入竞品的 POI')}</tbody></table>
      <div class="poi-title">待人工核验竞品</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(pending_competitors, '暂无待核验竞品')}</tbody></table>
      <div class="poi-title">人工/本地确认竞品档案</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(confirmed_competitors, '暂无人工或本地确认竞品档案')}</tbody></table>
      <div class="poi-title">已排除竞品误匹配</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>排除依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(excluded_competitors, '暂无被排除的竞品误匹配')}</tbody></table>
      <div class="poi-title">教育客群明细：{_escape_html(population.get('education_filter_summary') or '')}</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(education_core_items, '核心范围内暂无教育客群明细')}</tbody></table>
      <div class="poi-title">教育扩展观察范围（3000m，不直接等同核心半径）</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(education_extended_items, '扩展范围内暂无教育客群明细')}</tbody></table>
      <div class="poi-title">待核验学校</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(pending_education, '暂无待核验学校')}</tbody></table>
      <div class="poi-title">已排除教育误匹配</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>排除依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(excluded_education, '暂无被排除的教育误匹配')}</tbody></table>
      <div class="poi-title">交通站点</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(traffic_station_items, '暂无交通站点明细')}</tbody></table>
      <div class="poi-title">商业设施</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(commercial_items, '暂无商业设施明细')}</tbody></table>
      <div class="poi-title">周边配套设施</div>
      <table><thead><tr><th>名称</th><th>类型</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(facility_items, '暂无配套设施明细')}</tbody></table>
      <div class="poi-title">娱乐配套</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(entertainment_items, '高德 API 已查询，未返回可用娱乐配套 POI')}</tbody></table>
      <div class="poi-title">住宅办公</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(residential_office_items, '暂无住宅办公明细')}</tbody></table>
      <div class="poi-title">政策红线 200m 明细：{_escape_html(policy.get('policy_redline_summary') or '小学、幼儿园、中学、政府机构距离必须大于 200m')}</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(policy_redline_items, '200m 内未发现政策红线 POI')}</tbody></table>
      <div class="poi-title">待核验/已排除红线误匹配</div>
      <table><thead><tr><th>名称</th><th>类型/判断</th><th>距离</th><th>地址/依据</th><th>状态</th><th>来源</th></tr></thead><tbody>{_poi_rows_detailed(pending_policy_redline + excluded_policy_redline, '暂无待核验或已排除红线 POI')}</tbody></table>
    </section>

    <section class="section">
      <h2>五、商圈容量模型</h2>
      {capacity_html}
    </section>

    <section class="section">
      <h2>六、AI 分析报告</h2>
      <div class="ai">{_nl2br(ai_report or '暂无 AI 报告')}</div>
    </section>

    <section class="section">
      <h2>七、相似历史案例</h2>
      {''.join(cases_html) or '<div class="card muted">暂无相似历史案例</div>'}
    </section>

    <section class="section muted">报告生成时间：{_escape_html(evaluated_at)}。本报告由系统自动生成，仅供选址决策参考，正式签约前请结合实地调研。</section>
  </main>
</body>
</html>"""


def _draw_radar_chart(dimensions: dict, size: float = 200, font_name: str = "Helvetica") -> "Drawing":
    """绘制六维雷达图"""
    d = Drawing(size, size)
    cx, cy = size / 2, size / 2
    r = size * 0.38
    n = len(dimensions)
    if n == 0:
        return d

    angle_step = 2 * math.pi / n
    dim_keys = list(dimensions.keys())
    dim_names_map = {
        "traffic": "交通", "competition": "竞品", "population": "客群",
        "rent": "租金", "facility": "配套", "policy": "政策"
    }

    # 背景网格
    for level in range(1, 6):
        lr = r * level / 5
        points = []
        for i in range(n):
            angle = i * angle_step - math.pi / 2
            points.extend([cx + lr * math.cos(angle), cy - lr * math.sin(angle)])
        if len(points) >= 4:
            poly = Polygon(points, strokeColor=HexColor("#e0e0f0"), fillColor=None, strokeWidth=0.5)
            d.add(poly)

    # 轴线
    for i in range(n):
        angle = i * angle_step - math.pi / 2
        line = Line(cx, cy, cx + r * math.cos(angle), cy - r * math.sin(angle),
                    strokeColor=HexColor("#d0d0e8"), strokeWidth=0.5)
        d.add(line)

    # 数据多边形
    scores = [dimensions[k].get("score", 0) / 100 for k in dim_keys]
    data_points = []
    for i, score in enumerate(scores):
        angle = i * angle_step - math.pi / 2
        val = score * r
        data_points.extend([cx + val * math.cos(angle), cy - val * math.sin(angle)])

    if len(data_points) >= 4:
        poly = Polygon(data_points,
                       strokeColor=HexColor("#6c63ff"),
                       fillColor=HexColor("#6c63ff"),
                       strokeWidth=1.5,
                       fillOpacity=0.25)
        d.add(poly)

    # 数据点
    for i, score in enumerate(scores):
        angle = i * angle_step - math.pi / 2
        val = score * r
        px = cx + val * math.cos(angle)
        py = cy - val * math.sin(angle)
        dot = Circle(px, py, 3, fillColor=HexColor("#6c63ff"), strokeColor=white, strokeWidth=1)
        d.add(dot)

    # 标签
    for i, key in enumerate(dim_keys):
        angle = i * angle_step - math.pi / 2
        lx = cx + (r + 18) * math.cos(angle)
        ly = cy - (r + 18) * math.sin(angle)
        label = dim_names_map.get(key, key)
        score_val = dimensions[key].get("score", 0)
        s = String(lx, ly, f"{label}\n{score_val}",
                   fontName=font_name,
                   fontSize=7,
                   textAnchor="middle",
                   fillColor=HexColor("#444444"))
        d.add(s)

    return d


def generate_evaluation_report_pdf(
    evaluation_result: dict,
    ai_report: str = "",
    similar_cases: list = None
) -> bytes:
    """
    生成评估报告 PDF
    
    :param evaluation_result: 评估结果字典（来自 scoring.py 的 final 事件）
    :param ai_report: AI 生成的文字报告
    :param similar_cases: 相似历史案例列表
    :return: PDF 文件字节
    """
    if not REPORTLAB_AVAILABLE:
        raise RuntimeError("reportlab 未安装，请运行 pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="选址评估报告"
    )

    # 注册中文字体
    font_status = _register_fonts()
    if font_status == "cid":
        font_name = "STSong-Light"
        font_bold = "STSong-Light"
    elif font_status:
        font_name = "ChineseFont"
        font_bold = "ChineseFontBold"
    else:
        font_name = "Helvetica"
        font_bold = "Helvetica-Bold"

    # 颜色定义
    PRIMARY = HexColor("#6c63ff")
    SUCCESS = HexColor("#67c23a")
    WARNING = HexColor("#e6a23c")
    DANGER = HexColor("#f56c6c")
    LIGHT_BG = HexColor("#f8f8ff")
    BORDER = HexColor("#e0e0f0")

    # 样式
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", fontName=font_bold, fontSize=20, textColor=PRIMARY,
        alignment=TA_CENTER, spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", fontName=font_name, fontSize=11, textColor=HexColor("#666666"),
        alignment=TA_CENTER, spaceAfter=4
    )
    section_title_style = ParagraphStyle(
        "SectionTitle", fontName=font_bold, fontSize=13, textColor=PRIMARY,
        spaceBefore=14, spaceAfter=8,
        borderPad=4, leftIndent=0
    )
    body_style = ParagraphStyle(
        "Body", fontName=font_name, fontSize=10, textColor=HexColor("#333333"),
        leading=16, spaceAfter=4
    )
    small_style = ParagraphStyle(
        "Small", fontName=font_name, fontSize=9, textColor=HexColor("#666666"),
        leading=14
    )

    story = []

    # ── 封面 ──────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1.5 * cm))
    story.append(Paragraph("电竞馆智能选址系统", title_style))
    story.append(Paragraph("选址评估报告", ParagraphStyle(
        "MainTitle", fontName=font_bold, fontSize=26, textColor=HexColor("#1a1a2e"),
        alignment=TA_CENTER, spaceAfter=8
    )))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=16))

    # 基本信息表
    address = _clean_pdf_text(evaluation_result.get("address", "未知地址"))
    total_score = evaluation_result.get("total_score", 0)
    grade = evaluation_result.get("grade", "C")
    grade_label = evaluation_result.get("grade_label", "一般")
    evaluated_at = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    grade_color = SUCCESS if grade == "A" else (WARNING if grade == "B" else (DANGER if grade == "D" else HexColor("#409eff")))

    info_data = [
        ["评估地址", address],
        ["综合得分", f"{total_score} 分"],
        ["评级", f"{grade}级 - {grade_label}"],
        ["报告生成时间", evaluated_at],
    ]
    info_table = Table(info_data, colWidths=[3.5 * cm, 13 * cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), font_name),
        ("FONTNAME", (0, 0), (0, -1), font_bold),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
        ("TEXTCOLOR", (1, 2), (1, 2), grade_color),
        ("FONTNAME", (1, 2), (1, 2), font_bold),
        ("FONTSIZE", (1, 2), (1, 2), 12),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [white, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.8 * cm))

    # ── 六维评分 ──────────────────────────────────────────────────────────
    dimensions = evaluation_result.get("dimensions", {})
    if dimensions:
        story.append(Paragraph("一、六维评分详情", section_title_style))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=10))

        dim_names_map = {
            "traffic": "交通便利性", "competition": "竞品分析",
            "population": "客群密度", "rent": "租金成本",
            "facility": "配套设施", "policy": "政策环境"
        }

        # 雷达图
        try:
            radar = _draw_radar_chart(dimensions, size=220, font_name=font_name)
            from reportlab.platypus import Image as RLImage
            radar_buf = io.BytesIO()
            renderPDF.drawToFile(radar, radar_buf, "radar.pdf")
            # 改用 Drawing 直接嵌入
            story.append(radar)
        except Exception:
            pass

        story.append(Spacer(1, 0.4 * cm))

        # 维度得分表
        dim_header = ["评分维度", "得分", "详情说明"]
        dim_rows = [dim_header]
        for key, dim in dimensions.items():
            score = dim.get("score", 0)
            detail = _clean_pdf_text(dim.get("detail", ""))
            score_color = "green" if score >= 80 else ("orange" if score >= 60 else "red")
            dim_rows.append([
                dim_names_map.get(key, key),
                f"{score} 分",
                detail[:60] + ("..." if len(detail) > 60 else "")
            ])

        dim_table = Table(dim_rows, colWidths=[3.5 * cm, 2 * cm, 11 * cm])
        dim_table_style = [
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("TEXTCOLOR", (0, 0), (-1, 0), white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, LIGHT_BG]),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("PADDING", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ]
        # 根据得分着色
        for row_idx, (key, dim) in enumerate(dimensions.items(), start=1):
            score = dim.get("score", 0)
            color = SUCCESS if score >= 80 else (WARNING if score >= 60 else DANGER)
            dim_table_style.append(("TEXTCOLOR", (1, row_idx), (1, row_idx), color))
            dim_table_style.append(("FONTNAME", (1, row_idx), (1, row_idx), font_bold))

        dim_table.setStyle(TableStyle(dim_table_style))
        story.append(dim_table)
        story.append(Spacer(1, 0.6 * cm))

    # ── AI 深度报告 ────────────────────────────────────────────────────────
    if ai_report:
        story.append(Paragraph("二、AI 深度分析报告", section_title_style))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=10))

        # 简单处理 Markdown：去掉 # 标记，保留文本
        import re
        clean_report = _clean_pdf_text(ai_report)
        clean_report = re.sub(r'^#{1,3}\s+', '', clean_report, flags=re.MULTILINE)
        clean_report = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_report)
        clean_report = re.sub(r'\*(.+?)\*', r'\1', clean_report)

        for para in clean_report.split('\n'):
            para = para.strip()
            if not para:
                story.append(Spacer(1, 0.2 * cm))
                continue
            if para.startswith('- ') or para.startswith('• '):
                para = '  • ' + para[2:]
            story.append(Paragraph(_clean_pdf_text(para), body_style))

        story.append(Spacer(1, 0.6 * cm))

    # ── 相似历史案例 ────────────────────────────────────────────────────────
    if similar_cases:
        story.append(Paragraph("三、相似历史案例参考", section_title_style))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=10))

        for i, case in enumerate(similar_cases[:3], 1):
            case_type = "历史门店" if case.get("type") == "store" else "历史评估"
            is_success = case.get("is_success")
            status_text = "运营中" if is_success is True else ("已关闭" if is_success is False else "历史评估")
            similarity = case.get("similarity", 0)

            case_data = [
                [f"案例 {i}：{case.get('name') or case.get('address', '未知')[:20]}", f"相似度 {similarity}%", status_text],
                ["地址", case.get("address", ""), ""],
            ]
            if case.get("total_score"):
                case_data.append(["综合得分", f"{case['total_score']} 分", case.get("grade_label", "")])
            if case.get("area_sqm"):
                case_data.append(["门店面积", f"{case['area_sqm']} ㎡", ""])
            notes = case.get("experience_notes") or case.get("summary", "")
            if notes:
                case_data.append(["经验总结", notes[:100] + ("..." if len(notes) > 100 else ""), ""])

            case_table = Table(case_data, colWidths=[3 * cm, 9 * cm, 4.5 * cm])
            case_table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), LIGHT_BG),
                ("TEXTCOLOR", (0, 0), (0, -1), PRIMARY),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("SPAN", (1, 0), (1, 0)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(case_table)
            story.append(Spacer(1, 0.4 * cm))

    # ── 页脚说明 ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=8))
    story.append(Paragraph(
        f"本报告由电竞馆智能选址系统自动生成 · {evaluated_at} · 仅供参考，实际选址请结合实地考察",
        ParagraphStyle("Footer", fontName=font_name, fontSize=8, textColor=HexColor("#aaaaaa"), alignment=TA_CENTER)
    ))

    doc.build(story)
    return buf.getvalue()
