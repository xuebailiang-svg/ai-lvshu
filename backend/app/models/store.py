"""
电竞馆店铺相关数据模型
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base_class import Base


class Store(Base):
    """电竞馆店铺基础信息表"""
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    # 基础信息
    name = Column(String(100), nullable=False, comment="店铺名称")
    code = Column(String(50), nullable=True, comment="店铺编码（用于去重）")
    address = Column(String(500), nullable=False, comment="详细地址（用户填写）")
    city = Column(String(50), nullable=True, comment="城市")
    district = Column(String(50), nullable=True, comment="区/县")

    # 经纬度（由系统自动转换）
    longitude = Column(Float, nullable=True, comment="经度（高德API自动转换）")
    latitude = Column(Float, nullable=True, comment="纬度（高德API自动转换）")
    geo_status = Column(String(20), default="pending", comment="地理编码状态: pending/success/failed")

    # 运营基础信息
    area_sqm = Column(Float, nullable=True, comment="面积（平方米）")
    machine_count = Column(Integer, nullable=True, comment="机器数量")
    monthly_rent = Column(Float, nullable=True, comment="月租金（元）")
    open_date = Column(DateTime, nullable=True, comment="开业日期")
    close_date = Column(DateTime, nullable=True, comment="关店日期（null=在营）")
    status = Column(String(20), default="operating", comment="状态: operating/closed/planned")

    # 成败标签
    is_success = Column(Boolean, nullable=True, comment="是否成功（用于训练评分模型）")
    experience_notes = Column(Text, nullable=True, comment="经验总结（自由文本，将被向量化）")

    # 元数据
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    revenue_records = relationship("RevenueRecord", back_populates="store", cascade="all, delete-orphan")
    member_profiles = relationship("MemberProfile", back_populates="store", cascade="all, delete-orphan")
    hardware_configs = relationship("HardwareConfig", back_populates="store", cascade="all, delete-orphan")
    upload_records = relationship("UploadRecord", back_populates="store")


class UploadRecord(Base):
    """原始文件上传记录表（永久保留原始文件）"""
    __tablename__ = "upload_records"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=True, comment="关联店铺（解析后填入）")

    # 文件信息
    original_filename = Column(String(255), nullable=False, comment="原始文件名")
    stored_path = Column(String(500), nullable=False, comment="服务器存储路径（永久保留）")
    file_size = Column(Integer, nullable=True, comment="文件大小（字节）")
    file_hash = Column(String(64), nullable=True, comment="文件 SHA256 哈希（防重复上传）")

    # 上传类型
    upload_type = Column(String(50), nullable=False, comment="上传类型: basic/revenue/member/hardware")
    template_version = Column(String(20), default="v1", comment="使用的模板版本")

    # 解析状态
    parse_status = Column(String(20), default="pending", comment="解析状态: pending/processing/success/failed")
    parse_message = Column(Text, nullable=True, comment="解析结果消息或错误信息")
    parsed_rows = Column(Integer, default=0, comment="成功解析的行数")
    failed_rows = Column(Integer, default=0, comment="解析失败的行数")
    parse_detail = Column(JSON, nullable=True, comment="逐行解析详情（JSON）")

    # 分析状态
    analysis_status = Column(String(20), default="pending", comment="分析状态: pending/processing/success/failed")
    analysis_summary = Column(Text, nullable=True, comment="大模型分析总结")
    weight_updated = Column(Boolean, default=False, comment="是否已触发评分权重更新")

    # 上传者
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    store = relationship("Store", back_populates="upload_records")


class RevenueRecord(Base):
    """营收数据表"""
    __tablename__ = "revenue_records"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    upload_record_id = Column(Integer, ForeignKey("upload_records.id"), nullable=True)

    # 时间维度
    year = Column(Integer, nullable=False, comment="年份")
    month = Column(Integer, nullable=True, comment="月份（null=年度汇总）")

    # 营收明细
    net_fee_revenue = Column(Float, default=0, comment="网费收入（元）")
    snack_revenue = Column(Float, default=0, comment="水吧/零食收入（元）")
    peripheral_revenue = Column(Float, default=0, comment="外设销售收入（元）")
    event_revenue = Column(Float, default=0, comment="赛事/活动收入（元）")
    other_revenue = Column(Float, default=0, comment="其他收入（元）")
    total_revenue = Column(Float, default=0, comment="总营收（元）")

    # 成本
    rent_cost = Column(Float, default=0, comment="租金成本（元）")
    labor_cost = Column(Float, default=0, comment="人工成本（元）")
    utilities_cost = Column(Float, default=0, comment="水电成本（元）")
    other_cost = Column(Float, default=0, comment="其他成本（元）")
    total_cost = Column(Float, default=0, comment="总成本（元）")

    # 利润
    gross_profit = Column(Float, default=0, comment="毛利润（元）")
    net_profit = Column(Float, default=0, comment="净利润（元）")

    # 客流
    daily_avg_customers = Column(Float, nullable=True, comment="日均客流量")
    avg_spend_per_customer = Column(Float, nullable=True, comment="客单价（元）")

    created_at = Column(DateTime, default=datetime.utcnow)
    store = relationship("Store", back_populates="revenue_records")


class MemberProfile(Base):
    """会员画像数据表"""
    __tablename__ = "member_profiles"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    upload_record_id = Column(Integer, ForeignKey("upload_records.id"), nullable=True)

    # 统计周期
    stat_year = Column(Integer, nullable=False)
    stat_month = Column(Integer, nullable=True)

    # 年龄分布（各年龄段占比 %）
    age_under_18 = Column(Float, default=0, comment="18岁以下占比%")
    age_18_22 = Column(Float, default=0, comment="18-22岁占比%")
    age_23_25 = Column(Float, default=0, comment="23-25岁占比%")
    age_26_30 = Column(Float, default=0, comment="26-30岁占比%")
    age_31_35 = Column(Float, default=0, comment="31-35岁占比%")
    age_over_35 = Column(Float, default=0, comment="35岁以上占比%")

    # 性别分布
    male_ratio = Column(Float, default=0, comment="男性占比%")
    female_ratio = Column(Float, default=0, comment="女性占比%")

    # 职业分布（占比 %）
    student_ratio = Column(Float, default=0, comment="学生占比%")
    worker_ratio = Column(Float, default=0, comment="上班族占比%")
    freelancer_ratio = Column(Float, default=0, comment="自由职业占比%")
    other_occupation_ratio = Column(Float, default=0, comment="其他职业占比%")

    # 消费行为
    avg_monthly_visits = Column(Float, nullable=True, comment="月均到店次数")
    avg_session_hours = Column(Float, nullable=True, comment="平均单次消费时长（小时）")
    avg_monthly_spend = Column(Float, nullable=True, comment="月均消费金额（元）")

    # 各年龄段营收贡献（元）
    revenue_age_under_18 = Column(Float, default=0)
    revenue_age_18_22 = Column(Float, default=0)
    revenue_age_23_25 = Column(Float, default=0)
    revenue_age_26_30 = Column(Float, default=0)
    revenue_age_31_35 = Column(Float, default=0)
    revenue_age_over_35 = Column(Float, default=0)

    # 扩展字段（JSON存储其他画像维度）
    extra_data = Column(JSON, nullable=True, comment="扩展画像数据")

    created_at = Column(DateTime, default=datetime.utcnow)
    store = relationship("Store", back_populates="member_profiles")


class HardwareConfig(Base):
    """硬件配置数据表"""
    __tablename__ = "hardware_configs"

    id = Column(Integer, primary_key=True, index=True)
    store_id = Column(Integer, ForeignKey("stores.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False)
    upload_record_id = Column(Integer, ForeignKey("upload_records.id"), nullable=True)

    stat_year = Column(Integer, nullable=False)

    # 显卡配置分布（台数）
    gpu_rtx_3060 = Column(Integer, default=0)
    gpu_rtx_3070 = Column(Integer, default=0)
    gpu_rtx_3080 = Column(Integer, default=0)
    gpu_rtx_4060 = Column(Integer, default=0)
    gpu_rtx_4070 = Column(Integer, default=0)
    gpu_rtx_4080 = Column(Integer, default=0)
    gpu_rtx_4090 = Column(Integer, default=0)
    gpu_other = Column(Integer, default=0)

    # 座位分类（台数）
    standard_seats = Column(Integer, default=0, comment="普通区座位数")
    vip_seats = Column(Integer, default=0, comment="VIP区座位数")
    private_room_seats = Column(Integer, default=0, comment="包间座位数")

    # 外设品牌（主要品牌）
    main_monitor_brand = Column(String(50), nullable=True, comment="主要显示器品牌")
    main_keyboard_brand = Column(String(50), nullable=True, comment="主要键盘品牌")
    main_chair_brand = Column(String(50), nullable=True, comment="主要椅子品牌")

    # 网络配置
    bandwidth_mbps = Column(Integer, nullable=True, comment="带宽（Mbps）")

    # 扩展字段
    extra_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    store = relationship("Store", back_populates="hardware_configs")


class ScoringRule(Base):
    """评分规则与动态权重表"""
    __tablename__ = "scoring_rules"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=False, index=True)

    # 评分维度
    dimension = Column(String(50), nullable=False, comment="评分维度: traffic/competition/population/rent/facility/policy")
    dimension_name = Column(String(100), nullable=False, comment="维度中文名")
    sub_factor = Column(String(100), nullable=True, comment="子因子（如: age_26_30_density）")

    # 权重
    base_weight = Column(Float, nullable=False, comment="基础权重（系统默认）")
    dynamic_weight = Column(Float, nullable=True, comment="数据驱动动态权重（由历史数据分析更新）")
    effective_weight = Column(Float, nullable=False, comment="实际生效权重（取 dynamic 或 base）")

    # 权重更新记录
    last_updated_by = Column(String(50), default="system", comment="更新来源: system/data_analysis/manual")
    update_reason = Column(Text, nullable=True, comment="更新原因（大模型分析总结）")
    update_count = Column(Integer, default=0, comment="被更新次数")

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
