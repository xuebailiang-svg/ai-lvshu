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
