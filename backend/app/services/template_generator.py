"""
Excel 上传模板生成服务
为用户提供标准化的上传模板下载
"""
import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# 样式定义
HEADER_FILL = PatternFill(start_color="1A1A2E", end_color="1A1A2E", fill_type="solid")
REQUIRED_FILL = PatternFill(start_color="E8F4FD", end_color="E8F4FD", fill_type="solid")
OPTIONAL_FILL = PatternFill(start_color="F9F9F9", end_color="F9F9F9", fill_type="solid")
EXAMPLE_FILL = PatternFill(start_color="FFF9E6", end_color="FFF9E6", fill_type="solid")
HEADER_FONT = Font(name="微软雅黑", bold=True, color="FFFFFF", size=11)
REQUIRED_FONT = Font(name="微软雅黑", bold=True, color="C0392B", size=10)
NORMAL_FONT = Font(name="微软雅黑", size=10)
THIN_BORDER = Border(
    left=Side(style="thin", color="CCCCCC"),
    right=Side(style="thin", color="CCCCCC"),
    top=Side(style="thin", color="CCCCCC"),
    bottom=Side(style="thin", color="CCCCCC"),
)


def _set_header(ws, headers: list, col_widths: list = None):
    """设置表头样式"""
    for col_idx, (col_name, is_required, description) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

        # 说明行
        desc_cell = ws.cell(row=2, column=col_idx, value=description)
        desc_cell.font = Font(name="微软雅黑", size=9, color="666666", italic=True)
        desc_cell.fill = REQUIRED_FILL if is_required else OPTIONAL_FILL
        desc_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        desc_cell.border = THIN_BORDER

    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 40

    if col_widths:
        for i, width in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = width


def _add_example_row(ws, values: list, row: int = 3):
    """添加示例数据行"""
    for col_idx, value in enumerate(values, 1):
        cell = ws.cell(row=row, column=col_idx, value=value)
        cell.font = NORMAL_FONT
        cell.fill = EXAMPLE_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 22


def generate_basic_template() -> bytes:
    """生成基础信息模板"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "基础信息"

    headers = [
        ("店铺名称", True, "必填 | 唯一标识，用于关联其他模板数据"),
        ("详细地址", True, "必填 | 完整地址，系统自动转换经纬度\n例：陕西省西安市雁塔区电子城街道XX路XX号"),
        ("城市", False, "可选 | 如：西安市"),
        ("区县", False, "可选 | 如：雁塔区"),
        ("面积(㎡)", False, "可选 | 店铺实际经营面积"),
        ("机器数量", False, "可选 | 总台数（含VIP区）"),
        ("月租金(元)", False, "可选 | 月租金总额"),
        ("开业日期", False, "可选 | 格式：2023-01-01"),
        ("是否成功", False, "可选 | 填写：是/否\n用于训练评分模型"),
        ("经验总结", False, "可选 | 自由填写运营经验、选址心得\n系统将自动向量化用于AI参考"),
    ]
    col_widths = [18, 45, 12, 12, 12, 12, 14, 14, 12, 40]
    _set_header(ws, headers, col_widths)

    example = ["西安电竞旗舰店", "陕西省西安市雁塔区电子城街道高新路88号", "西安市", "雁塔区",
               500, 120, 35000, "2023-03-01", "是",
               "位于大学城附近，周边高校密集，18-25岁客群占比高，工作日下午和周末客流稳定。"]
    _add_example_row(ws, example)

    # 冻结首行
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_revenue_template() -> bytes:
    """生成营收数据模板"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "营收数据"

    headers = [
        ("店铺名称", True, "必填 | 需与基础信息模板一致"),
        ("年份", True, "必填 | 如：2024"),
        ("月份", False, "可选 | 1-12，不填则视为年度汇总"),
        ("网费收入(元)", False, "可选"),
        ("水吧收入(元)", False, "可选"),
        ("外设销售收入(元)", False, "可选"),
        ("赛事收入(元)", False, "可选"),
        ("其他收入(元)", False, "可选"),
        ("总营收(元)", False, "可选 | 不填则自动求和"),
        ("租金成本(元)", False, "可选"),
        ("人工成本(元)", False, "可选"),
        ("水电成本(元)", False, "可选"),
        ("其他成本(元)", False, "可选"),
        ("总成本(元)", False, "可选 | 不填则自动求和"),
        ("净利润(元)", False, "可选 | 不填则自动计算"),
        ("日均客流量", False, "可选 | 日均到店人数"),
        ("客单价(元)", False, "可选 | 人均消费金额"),
    ]
    col_widths = [18, 8, 8, 14, 14, 16, 12, 12, 12, 14, 14, 14, 12, 12, 12, 12, 12]
    _set_header(ws, headers, col_widths)

    example = ["西安电竞旗舰店", 2024, 6, 85000, 12000, 3000, 5000, 1000, 106000,
               35000, 18000, 8000, 3000, 64000, 42000, 280, 68]
    _add_example_row(ws, example)
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_member_template() -> bytes:
    """生成会员画像模板"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "会员画像"

    headers = [
        ("店铺名称", True, "必填"),
        ("年份", True, "必填"),
        ("月份", False, "可选"),
        ("18岁以下占比%", False, "可选 | 填数字，如：5"),
        ("18-22岁占比%", False, "可选"),
        ("23-25岁占比%", False, "可选"),
        ("26-30岁占比%", False, "可选"),
        ("31-35岁占比%", False, "可选"),
        ("35岁以上占比%", False, "可选"),
        ("男性占比%", False, "可选"),
        ("女性占比%", False, "可选"),
        ("学生占比%", False, "可选"),
        ("上班族占比%", False, "可选"),
        ("自由职业占比%", False, "可选"),
        ("月均到店次数", False, "可选"),
        ("平均消费时长(小时)", False, "可选"),
        ("月均消费金额(元)", False, "可选"),
        ("18岁以下营收贡献(元)", False, "可选 | 该年龄段贡献的营收总额"),
        ("18-22岁营收贡献(元)", False, "可选"),
        ("23-25岁营收贡献(元)", False, "可选"),
        ("26-30岁营收贡献(元)", False, "可选"),
        ("31-35岁营收贡献(元)", False, "可选"),
        ("35岁以上营收贡献(元)", False, "可选"),
    ]
    col_widths = [18, 8, 8] + [16] * 20
    _set_header(ws, headers, col_widths)

    example = ["西安电竞旗舰店", 2024, None, 3, 25, 20, 35, 12, 5,
               82, 18, 45, 40, 15, 6.5, 3.2, 180,
               3180, 26500, 21200, 37100, 12720, 5300]
    _add_example_row(ws, example)
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def generate_hardware_template() -> bytes:
    """生成硬件配置模板"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "硬件配置"

    headers = [
        ("店铺名称", True, "必填"),
        ("年份", True, "必填"),
        ("RTX 3060(台)", False, "可选"),
        ("RTX 3070(台)", False, "可选"),
        ("RTX 3080(台)", False, "可选"),
        ("RTX 4060(台)", False, "可选"),
        ("RTX 4070(台)", False, "可选"),
        ("RTX 4080(台)", False, "可选"),
        ("RTX 4090(台)", False, "可选"),
        ("其他显卡(台)", False, "可选"),
        ("普通区座位数", False, "可选"),
        ("VIP区座位数", False, "可选"),
        ("包间座位数", False, "可选"),
        ("主要显示器品牌", False, "可选 | 如：AOC、飞利浦"),
        ("主要键盘品牌", False, "可选 | 如：雷蛇、罗技"),
        ("主要椅子品牌", False, "可选 | 如：傲风、迪锐克斯"),
        ("带宽(Mbps)", False, "可选 | 如：1000"),
    ]
    col_widths = [18, 8] + [14] * 15
    _set_header(ws, headers, col_widths)

    example = ["西安电竞旗舰店", 2024, 0, 0, 20, 40, 35, 15, 10, 0,
               80, 30, 10, "AOC", "雷蛇", "傲风", 1000]
    _add_example_row(ws, example)
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


TEMPLATE_GENERATORS = {
    "basic": generate_basic_template,
    "revenue": generate_revenue_template,
    "member": generate_member_template,
    "hardware": generate_hardware_template,
}

TEMPLATE_NAMES = {
    "basic": "基础信息模板",
    "revenue": "营收数据模板",
    "member": "会员画像模板",
    "hardware": "硬件配置模板",
}
