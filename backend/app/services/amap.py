"""
高德地图 API 服务
- 地址转经纬度（地理编码）
- POI 周边搜索
- 热力图数据（预留）
"""
import httpx
import logging
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.models.system_config import SystemConfig

logger = logging.getLogger(__name__)

AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_POI_URL = "https://restapi.amap.com/v3/place/around"


def get_amap_key(db: Session) -> Optional[str]:
    """从数据库配置中获取高德 API Key"""
    cfg = db.query(SystemConfig).filter(
        SystemConfig.config_key == "amap_api_key",
        SystemConfig.is_active == True
    ).first()
    if cfg and cfg.config_value:
        return cfg.config_value
    return None


async def geocode_address(address: str, city: Optional[str], api_key: str) -> Optional[Tuple[float, float]]:
    """
    地址转经纬度（高德地理编码 API）
    返回 (longitude, latitude) 或 None
    """
    params = {
        "key": api_key,
        "address": address,
        "output": "JSON"
    }
    if city:
        params["city"] = city

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_GEO_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") == "1" and data.get("geocodes"):
            location = data["geocodes"][0]["location"]  # "116.397428,39.90923"
            lng, lat = map(float, location.split(","))
            return lng, lat
        else:
            logger.warning(f"高德地理编码失败: address={address}, info={data.get('info')}")
            return None
    except Exception as e:
        logger.error(f"高德地理编码异常: {e}")
        return None


async def search_poi_around(
    longitude: float,
    latitude: float,
    keywords: str,
    radius: int,
    api_key: str,
    page: int = 1
) -> dict:
    """
    周边 POI 搜索
    keywords: 如 "网吧|电竞馆|游戏厅"
    radius: 搜索半径（米）
    """
    params = {
        "key": api_key,
        "location": f"{longitude},{latitude}",
        "keywords": keywords,
        "radius": radius,
        "offset": 25,
        "page": page,
        "extensions": "base",
        "output": "JSON"
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_POI_URL, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"高德 POI 搜索异常: {e}")
        return {"status": "0", "pois": []}


async def get_competitor_count(
    longitude: float,
    latitude: float,
    radius: int,
    api_key: str
) -> int:
    """获取指定坐标周边竞品（网吧/电竞馆）数量"""
    result = await search_poi_around(
        longitude, latitude,
        keywords="网吧|电竞馆|电竞酒店|游戏厅",
        radius=radius,
        api_key=api_key
    )
    if result.get("status") == "1":
        return int(result.get("count", 0))
    return 0


async def get_heatmap_data(
    longitude: float,
    latitude: float,
    radius: int,
    api_key: str,
    huiyan_key: Optional[str] = None
) -> list[dict]:
    """
    获取消费热力图数据点

    优先级：
    1. 高德慧眼企业 API（huiyan_key 不为空时，精准消费数据）
    2. POI 密度模拟（免费，使用现有高德 Key）

    返回格式：[{"lng": float, "lat": float, "weight": float}, ...]
    weight 范围 0-100，值越大表示消费热度越高
    """
    # --- 方案 A：高德慧眼企业 API（精准消费数据）---
    if huiyan_key:
        try:
            return await _get_huiyan_heatmap(longitude, latitude, radius, huiyan_key)
        except Exception as e:
            logger.warning(f"慧眼 API 调用失败，降级为 POI 模拟: {e}")

    # --- 方案 B：POI 密度模拟（免费，使用现有高德 Key）---
    return await _get_poi_density_heatmap(longitude, latitude, radius, api_key)


async def _get_huiyan_heatmap(
    longitude: float,
    latitude: float,
    radius: int,
    huiyan_key: str
) -> list[dict]:
    """
    高德慧眼企业 API - 消费热力数据
    API 文档：https://lbs.amap.com/api/huiyan/guide/base/introduce
    需要在高德开放平台申请「慧眼」企业版权限
    """
    # 慧眼 API 端点（企业版）
    HUIYAN_URL = "https://huiyan.amap.com/api/v1/heatmap"
    params = {
        "key": huiyan_key,
        "center": f"{longitude},{latitude}",
        "radius": radius,
        "type": "consume",  # 消费热力
        "output": "JSON"
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(HUIYAN_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    points = []
    for item in data.get("data", {}).get("points", []):
        points.append({
            "lng": float(item["lng"]),
            "lat": float(item["lat"]),
            "weight": float(item.get("weight", 50))
        })
    return points


async def _get_poi_density_heatmap(
    longitude: float,
    latitude: float,
    radius: int,
    api_key: str
) -> list[dict]:
    """
    基于 POI 密度模拟消费热力（免费方案）
    通过搜索商业 POI（餐饮/购物/娱乐）的分布来模拟消费热度
    """
    import asyncio
    import math
    import random

    # 搜索多类消费型 POI
    poi_categories = [
        ("餐厅|快餐|火锅|烧烤|奶茶", 1.0),      # 餐饮权重最高
        ("购物中心|超市|便利店|商场", 0.9),        # 购物
        ("KTV|酒吧|电影院|娱乐", 0.8),             # 娱乐
        ("咖啡|甜品|茶饮", 0.7),                   # 休闲
    ]

    all_pois = []
    for keywords, weight_factor in poi_categories:
        result = await search_poi_around(
            longitude, latitude,
            keywords=keywords,
            radius=radius,
            api_key=api_key
        )
        if result.get("status") == "1":
            for poi in result.get("pois", []):
                loc = poi.get("location", "")
                if "," in loc:
                    try:
                        lng, lat = map(float, loc.split(","))
                        all_pois.append((lng, lat, weight_factor))
                    except ValueError:
                        pass
        await asyncio.sleep(0.05)

    if not all_pois:
        # 无 POI 数据时生成中心点占位
        return [{"lng": longitude, "lat": latitude, "weight": 50.0}]

    # 计算每个 POI 的热度权重（基于与中心点距离和类别权重）
    points = []
    for lng, lat, w_factor in all_pois:
        # 距离衰减：越近权重越高
        dist = math.sqrt((lng - longitude) ** 2 + (lat - latitude) ** 2) * 111000  # 近似米
        dist_factor = max(0.1, 1 - dist / radius)
        weight = round(dist_factor * w_factor * 100, 1)
        points.append({"lng": lng, "lat": lat, "weight": weight})

    return points


def get_huiyan_key(db: Session) -> Optional[str]:
    """从数据库配置中获取高德慧眼 API Key（企业版）"""
    cfg = db.query(SystemConfig).filter(
        SystemConfig.config_key == "amap_huiyan_key",
        SystemConfig.is_active == True
    ).first()
    if cfg and cfg.config_value:
        return cfg.config_value
    return None
