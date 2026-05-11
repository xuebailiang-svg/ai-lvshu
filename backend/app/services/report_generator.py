"""
评估报告 PDF 生成服务
使用 reportlab 生成专业的选址评估报告 PDF
"""
import io
import math
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
    return False


def _draw_radar_chart(dimensions: dict, size: float = 200) -> "Drawing":
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
                   fontName="ChineseFont" if REPORTLAB_AVAILABLE else "Helvetica",
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
    has_chinese_font = _register_fonts()
    font_name = "ChineseFont" if has_chinese_font else "Helvetica"
    font_bold = "ChineseFontBold" if has_chinese_font else "Helvetica-Bold"

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
    story.append(Paragraph("🎮 电竞馆智能选址系统", title_style))
    story.append(Paragraph("选址评估报告", ParagraphStyle(
        "MainTitle", fontName=font_bold, fontSize=26, textColor=HexColor("#1a1a2e"),
        alignment=TA_CENTER, spaceAfter=8
    )))
    story.append(HRFlowable(width="100%", thickness=2, color=PRIMARY, spaceAfter=16))

    # 基本信息表
    address = evaluation_result.get("address", "未知地址")
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
            radar = _draw_radar_chart(dimensions, size=220)
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
            detail = dim.get("detail", "")
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
        clean_report = re.sub(r'^#{1,3}\s+', '', ai_report, flags=re.MULTILINE)
        clean_report = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_report)
        clean_report = re.sub(r'\*(.+?)\*', r'\1', clean_report)

        for para in clean_report.split('\n'):
            para = para.strip()
            if not para:
                story.append(Spacer(1, 0.2 * cm))
                continue
            if para.startswith('- ') or para.startswith('• '):
                para = '  • ' + para[2:]
            story.append(Paragraph(para, body_style))

        story.append(Spacer(1, 0.6 * cm))

    # ── 相似历史案例 ────────────────────────────────────────────────────────
    if similar_cases:
        story.append(Paragraph("三、相似历史案例参考", section_title_style))
        story.append(HRFlowable(width="100%", thickness=1, color=BORDER, spaceAfter=10))

        for i, case in enumerate(similar_cases[:3], 1):
            case_type = "历史门店" if case.get("type") == "store" else "历史评估"
            is_success = case.get("is_success")
            status_text = "✅ 运营中" if is_success is True else ("❌ 已关闭" if is_success is False else "📋 历史评估")
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
