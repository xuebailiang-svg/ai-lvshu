"""
历史数据导入服务
- 解析 Excel/CSV 文件
- 多店铺自动识别（以店铺名称为主键，增量导入）
- 原始文件永久保留
- 地址转经纬度（异步）
"""
import os
import hashlib
import logging
from typing import Optional
from datetime import datetime
from pathlib import Path
import pandas as pd
from sqlalchemy.orm import Session

from app.models.store import Store, UploadRecord, RevenueRecord, MemberProfile, HardwareConfig
from app.models.user import Tenant

logger = logging.getLogger(__name__)

# 上传文件存储根目录。
# 未显式配置时放在项目 data/uploads 下，避免 Linux 部署时默认写 /var 目录导致权限错误。
DEFAULT_UPLOAD_ROOT = Path(__file__).resolve().parents[3] / "data" / "uploads"
UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", str(DEFAULT_UPLOAD_ROOT))


def ensure_upload_dir(tenant_id: int, upload_type: str) -> str:
    """确保上传目录存在，返回目录路径"""
    path = os.path.join(UPLOAD_ROOT, str(tenant_id), upload_type)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise RuntimeError(
            f"上传目录不可写或无法创建: {path}。请检查目录权限，或在 .env 中设置 UPLOAD_ROOT 为可写目录。"
        ) from e
    return path


def compute_file_hash(file_bytes: bytes) -> str:
    """计算文件 SHA256 哈希"""
    return hashlib.sha256(file_bytes).hexdigest()


def save_raw_file(file_bytes: bytes, filename: str, tenant_id: int, upload_type: str) -> str:
    """
    永久保存原始文件，返回存储路径
    文件名格式: {timestamp}_{original_filename}
    """
    upload_dir = ensure_upload_dir(tenant_id, upload_type)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    original_name = os.path.basename(filename or "upload.xlsx")
    safe_filename = f"{timestamp}_{original_name}"
    stored_path = os.path.join(upload_dir, safe_filename)
    with open(stored_path, "wb") as f:
        f.write(file_bytes)
    logger.info(f"原始文件已保存: {stored_path}")
    return stored_path


def get_or_create_store(db: Session, tenant_id: int, store_name: str, address: str, extra: dict = None) -> Store:
    """
    根据店铺名称获取或创建店铺（增量导入，不重复创建）
    """
    store = db.query(Store).filter(
        Store.tenant_id == tenant_id,
        Store.name == store_name
    ).first()

    if not store:
        store = Store(
            tenant_id=tenant_id,
            name=store_name,
            address=address,
            geo_status="pending"
        )
        if extra:
            for k, v in extra.items():
                if hasattr(store, k) and v is not None:
                    setattr(store, k, v)
        db.add(store)
        db.flush()
        logger.info(f"新建店铺: {store_name}")
    else:
        # 更新地址（如果有变化）
        if address and store.address != address:
            store.address = address
            store.geo_status = "pending"  # 地址变化，重新地理编码
        logger.info(f"已存在店铺: {store_name}，执行增量更新")

    return store


def _safe_float(val, default=None):
    try:
        if pd.isna(val):
            return default
        return float(val)
    except Exception:
        return default


def _safe_int(val, default=None):
    try:
        if pd.isna(val):
            return default
        return int(float(val))
    except Exception:
        return default


def parse_basic_template(df: pd.DataFrame, db: Session, tenant_id: int, upload_record_id: int) -> dict:
    """
    解析基础模板
    必填列: 店铺名称, 详细地址
    可选列: 城市, 区县, 面积(㎡), 机器数量, 月租金(元), 开业日期, 是否成功, 经验总结
    """
    required_cols = ["店铺名称", "详细地址"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"基础模板缺少必填列: {col}")

    success_count = 0
    failed_rows = []

    for idx, row in df.iterrows():
        try:
            store_name = str(row["店铺名称"]).strip()
            address = str(row["详细地址"]).strip()
            if not store_name or not address or store_name == "nan":
                failed_rows.append({"row": idx + 2, "reason": "店铺名称或地址为空"})
                continue

            extra = {
                "city": str(row.get("城市", "")).strip() or None,
                "district": str(row.get("区县", "")).strip() or None,
                "area_sqm": _safe_float(row.get("面积(㎡)")),
                "machine_count": _safe_int(row.get("机器数量")),
                "monthly_rent": _safe_float(row.get("月租金(元)")),
                "experience_notes": str(row.get("经验总结", "")).strip() or None,
            }

            # 成败标签处理
            is_success_val = row.get("是否成功", "")
            if str(is_success_val).strip() in ["是", "1", "True", "true", "成功", "Y", "y"]:
                extra["is_success"] = True
            elif str(is_success_val).strip() in ["否", "0", "False", "false", "失败", "N", "n"]:
                extra["is_success"] = False

            # 开业日期
            open_date_val = row.get("开业日期")
            if open_date_val and not pd.isna(open_date_val):
                try:
                    extra["open_date"] = pd.to_datetime(open_date_val)
                except Exception:
                    pass

            store = get_or_create_store(db, tenant_id, store_name, address, extra)
            store.upload_records.append(
                db.query(UploadRecord).filter(UploadRecord.id == upload_record_id).first()
            )
            success_count += 1

        except Exception as e:
            failed_rows.append({"row": idx + 2, "reason": str(e)})
            logger.warning(f"基础模板第 {idx+2} 行解析失败: {e}")

    db.flush()
    return {"success": success_count, "failed": len(failed_rows), "failed_detail": failed_rows}


def parse_revenue_template(df: pd.DataFrame, db: Session, tenant_id: int, upload_record_id: int) -> dict:
    """
    解析营收模板
    必填列: 店铺名称, 年份
    可选列: 月份, 网费收入, 水吧收入, 外设销售收入, 赛事收入, 其他收入, 租金成本, 人工成本, 水电成本, 净利润, 日均客流, 客单价
    """
    required_cols = ["店铺名称", "年份"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"营收模板缺少必填列: {col}")

    success_count = 0
    failed_rows = []

    for idx, row in df.iterrows():
        try:
            store_name = str(row["店铺名称"]).strip()
            year = _safe_int(row["年份"])
            if not store_name or not year:
                failed_rows.append({"row": idx + 2, "reason": "店铺名称或年份为空"})
                continue

            store = db.query(Store).filter(
                Store.tenant_id == tenant_id,
                Store.name == store_name
            ).first()
            if not store:
                failed_rows.append({"row": idx + 2, "reason": f"店铺 '{store_name}' 不存在，请先上传基础模板"})
                continue

            month = _safe_int(row.get("月份"))

            # 检查是否已有同期记录（避免重复）
            existing = db.query(RevenueRecord).filter(
                RevenueRecord.store_id == store.id,
                RevenueRecord.year == year,
                RevenueRecord.month == month
            ).first()

            net_fee = _safe_float(row.get("网费收入(元)"), 0)
            snack = _safe_float(row.get("水吧收入(元)"), 0)
            peripheral = _safe_float(row.get("外设销售收入(元)"), 0)
            event = _safe_float(row.get("赛事收入(元)"), 0)
            other_rev = _safe_float(row.get("其他收入(元)"), 0)
            total_rev = _safe_float(row.get("总营收(元)")) or (net_fee + snack + peripheral + event + other_rev)

            rent_cost = _safe_float(row.get("租金成本(元)"), 0)
            labor_cost = _safe_float(row.get("人工成本(元)"), 0)
            utilities = _safe_float(row.get("水电成本(元)"), 0)
            other_cost = _safe_float(row.get("其他成本(元)"), 0)
            total_cost = _safe_float(row.get("总成本(元)")) or (rent_cost + labor_cost + utilities + other_cost)
            net_profit = _safe_float(row.get("净利润(元)")) or (total_rev - total_cost)

            if existing:
                # 更新已有记录
                existing.net_fee_revenue = net_fee
                existing.snack_revenue = snack
                existing.peripheral_revenue = peripheral
                existing.event_revenue = event
                existing.other_revenue = other_rev
                existing.total_revenue = total_rev
                existing.rent_cost = rent_cost
                existing.labor_cost = labor_cost
                existing.utilities_cost = utilities
                existing.other_cost = other_cost
                existing.total_cost = total_cost
                existing.net_profit = net_profit
                existing.daily_avg_customers = _safe_float(row.get("日均客流量"))
                existing.avg_spend_per_customer = _safe_float(row.get("客单价(元)"))
            else:
                record = RevenueRecord(
                    store_id=store.id,
                    tenant_id=tenant_id,
                    upload_record_id=upload_record_id,
                    year=year,
                    month=month,
                    net_fee_revenue=net_fee,
                    snack_revenue=snack,
                    peripheral_revenue=peripheral,
                    event_revenue=event,
                    other_revenue=other_rev,
                    total_revenue=total_rev,
                    rent_cost=rent_cost,
                    labor_cost=labor_cost,
                    utilities_cost=utilities,
                    other_cost=other_cost,
                    total_cost=total_cost,
                    net_profit=net_profit,
                    daily_avg_customers=_safe_float(row.get("日均客流量")),
                    avg_spend_per_customer=_safe_float(row.get("客单价(元)"))
                )
                db.add(record)

            success_count += 1
        except Exception as e:
            failed_rows.append({"row": idx + 2, "reason": str(e)})
            logger.warning(f"营收模板第 {idx+2} 行解析失败: {e}")

    db.flush()
    return {"success": success_count, "failed": len(failed_rows), "failed_detail": failed_rows}


def parse_member_template(df: pd.DataFrame, db: Session, tenant_id: int, upload_record_id: int) -> dict:
    """解析会员画像模板"""
    required_cols = ["店铺名称", "年份"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"会员画像模板缺少必填列: {col}")

    success_count = 0
    failed_rows = []

    for idx, row in df.iterrows():
        try:
            store_name = str(row["店铺名称"]).strip()
            year = _safe_int(row["年份"])
            if not store_name or not year:
                continue

            store = db.query(Store).filter(
                Store.tenant_id == tenant_id,
                Store.name == store_name
            ).first()
            if not store:
                failed_rows.append({"row": idx + 2, "reason": f"店铺 '{store_name}' 不存在"})
                continue

            profile = MemberProfile(
                store_id=store.id,
                tenant_id=tenant_id,
                upload_record_id=upload_record_id,
                stat_year=year,
                stat_month=_safe_int(row.get("月份")),
                age_under_18=_safe_float(row.get("18岁以下占比%"), 0),
                age_18_22=_safe_float(row.get("18-22岁占比%"), 0),
                age_23_25=_safe_float(row.get("23-25岁占比%"), 0),
                age_26_30=_safe_float(row.get("26-30岁占比%"), 0),
                age_31_35=_safe_float(row.get("31-35岁占比%"), 0),
                age_over_35=_safe_float(row.get("35岁以上占比%"), 0),
                male_ratio=_safe_float(row.get("男性占比%"), 0),
                female_ratio=_safe_float(row.get("女性占比%"), 0),
                student_ratio=_safe_float(row.get("学生占比%"), 0),
                worker_ratio=_safe_float(row.get("上班族占比%"), 0),
                freelancer_ratio=_safe_float(row.get("自由职业占比%"), 0),
                avg_monthly_visits=_safe_float(row.get("月均到店次数")),
                avg_session_hours=_safe_float(row.get("平均消费时长(小时)")),
                avg_monthly_spend=_safe_float(row.get("月均消费金额(元)")),
                revenue_age_under_18=_safe_float(row.get("18岁以下营收贡献(元)"), 0),
                revenue_age_18_22=_safe_float(row.get("18-22岁营收贡献(元)"), 0),
                revenue_age_23_25=_safe_float(row.get("23-25岁营收贡献(元)"), 0),
                revenue_age_26_30=_safe_float(row.get("26-30岁营收贡献(元)"), 0),
                revenue_age_31_35=_safe_float(row.get("31-35岁营收贡献(元)"), 0),
                revenue_age_over_35=_safe_float(row.get("35岁以上营收贡献(元)"), 0),
            )
            db.add(profile)
            success_count += 1
        except Exception as e:
            failed_rows.append({"row": idx + 2, "reason": str(e)})

    db.flush()
    return {"success": success_count, "failed": len(failed_rows), "failed_detail": failed_rows}


def parse_hardware_template(df: pd.DataFrame, db: Session, tenant_id: int, upload_record_id: int) -> dict:
    """解析硬件配置模板"""
    required_cols = ["店铺名称", "年份"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"硬件配置模板缺少必填列: {col}")

    success_count = 0
    failed_rows = []

    for idx, row in df.iterrows():
        try:
            store_name = str(row["店铺名称"]).strip()
            year = _safe_int(row["年份"])
            if not store_name or not year:
                continue

            store = db.query(Store).filter(
                Store.tenant_id == tenant_id,
                Store.name == store_name
            ).first()
            if not store:
                failed_rows.append({"row": idx + 2, "reason": f"店铺 '{store_name}' 不存在"})
                continue

            hw = HardwareConfig(
                store_id=store.id,
                tenant_id=tenant_id,
                upload_record_id=upload_record_id,
                stat_year=year,
                gpu_rtx_3060=_safe_int(row.get("RTX 3060(台)"), 0),
                gpu_rtx_3070=_safe_int(row.get("RTX 3070(台)"), 0),
                gpu_rtx_3080=_safe_int(row.get("RTX 3080(台)"), 0),
                gpu_rtx_4060=_safe_int(row.get("RTX 4060(台)"), 0),
                gpu_rtx_4070=_safe_int(row.get("RTX 4070(台)"), 0),
                gpu_rtx_4080=_safe_int(row.get("RTX 4080(台)"), 0),
                gpu_rtx_4090=_safe_int(row.get("RTX 4090(台)"), 0),
                gpu_other=_safe_int(row.get("其他显卡(台)"), 0),
                standard_seats=_safe_int(row.get("普通区座位数"), 0),
                vip_seats=_safe_int(row.get("VIP区座位数"), 0),
                private_room_seats=_safe_int(row.get("包间座位数"), 0),
                main_monitor_brand=str(row.get("主要显示器品牌", "")).strip() or None,
                main_keyboard_brand=str(row.get("主要键盘品牌", "")).strip() or None,
                main_chair_brand=str(row.get("主要椅子品牌", "")).strip() or None,
                bandwidth_mbps=_safe_int(row.get("带宽(Mbps)")),
            )
            db.add(hw)
            success_count += 1
        except Exception as e:
            failed_rows.append({"row": idx + 2, "reason": str(e)})

    db.flush()
    return {"success": success_count, "failed": len(failed_rows), "failed_detail": failed_rows}


PARSERS = {
    "basic": parse_basic_template,
    "revenue": parse_revenue_template,
    "member": parse_member_template,
    "hardware": parse_hardware_template,
}


def process_upload(
    file_bytes: bytes,
    filename: str,
    upload_type: str,
    tenant_id: int,
    user_id: int,
    db: Session
) -> UploadRecord:
    """
    完整上传处理流程:
    1. 保存原始文件（永久保留）
    2. 创建上传记录
    3. 解析 Excel
    4. 写入数据库
    5. 更新上传记录状态
    """
    # 1. 保存原始文件
    stored_path = save_raw_file(file_bytes, filename, tenant_id, upload_type)
    file_hash = compute_file_hash(file_bytes)

    # 2. 创建上传记录
    upload_record = UploadRecord(
        tenant_id=tenant_id,
        original_filename=filename,
        stored_path=stored_path,
        file_size=len(file_bytes),
        file_hash=file_hash,
        upload_type=upload_type,
        parse_status="processing",
        uploaded_by=user_id,
    )
    db.add(upload_record)
    db.flush()

    # 3. 解析 Excel
    try:
        import io
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]

        parser = PARSERS.get(upload_type)
        if not parser:
            raise ValueError(f"不支持的上传类型: {upload_type}")

        result = parser(df, db, tenant_id, upload_record.id)

        upload_record.parse_status = "success"
        upload_record.parsed_rows = result["success"]
        upload_record.failed_rows = result["failed"]
        upload_record.parse_message = f"解析完成: 成功 {result['success']} 行，失败 {result['failed']} 行"
        upload_record.parse_detail = result.get("failed_detail", [])
        db.commit()

    except Exception as e:
        db.rollback()
        upload_record.parse_status = "failed"
        upload_record.parse_message = str(e)
        db.add(upload_record)
        db.commit()
        logger.error(f"文件解析失败: {e}")

    return upload_record
