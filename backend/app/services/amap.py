"""
高德地图 API 服务
- 地址转经纬度（地理编码）
- POI 周边搜索
- 热力图数据（预留）
"""
import httpx
import logging
import math
from typing import Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.core.crypto import decrypt_config_value
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
        return decrypt_config_value(cfg.config_value)
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

def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _parse_location(location: str) -> tuple[Optional[float], Optional[float]]:
    if not location or "," not in location:
        return None, None
    lng_text, lat_text = location.split(",", 1)
    return _to_float(lng_text), _to_float(lat_text)


def _haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> int:
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return int(round(radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))))


def _normalize_poi_key(poi: dict, longitude: float, latitude: float) -> tuple:
    name = "".join(str(poi.get("name") or "").lower().split())
    lng, lat = _parse_location(str(poi.get("location") or ""))
    if lng is not None and lat is not None:
        return name, round(lng, 5), round(lat, 5)
    return name, str(poi.get("address") or "").strip()


def extract_pois(result: dict, longitude: float, latitude: float, limit: Optional[int] = None) -> list[dict]:
    """
    Convert AMap raw POIs into stable evidence items with distance and de-duplication.
    Prefer this list over AMap's broad `count` field when generating reports.
    """
    normalized: list[dict] = []
    seen = set()
    for poi in result.get("pois") or []:
        name = str(poi.get("name") or "").strip()
        if not name:
            continue
        key = _normalize_poi_key(poi, longitude, latitude)
        if key in seen:
            continue
        seen.add(key)

        lng, lat = _parse_location(str(poi.get("location") or ""))
        distance = _to_int(poi.get("distance"))
        if distance is None and lng is not None and lat is not None:
            distance = _haversine_m(longitude, latitude, lng, lat)

        normalized.append({
            "name": name,
            "address": str(poi.get("address") or "").strip(),
            "type": str(poi.get("type") or "").strip(),
            "distance": distance,
            "longitude": lng,
            "latitude": lat,
        })

    normalized.sort(key=lambda item: item["distance"] if item["distance"] is not None else 10**9)
    if limit is not None:
        return normalized[:limit]
    return normalized


async def search_poi_around_pages(
    longitude: float,
    latitude: float,
    keywords: str,
    radius: int,
    api_key: str,
    max_pages: int = 3,
) -> dict:
    """
    Search multiple AMap POI pages and attach a de-duplicated evidence list.
    """
    first_result: dict = {}
    raw_pois: list[dict] = []

    for page in range(1, max(1, max_pages) + 1):
        result = await search_poi_around(
            longitude=longitude,
            latitude=latitude,
            keywords=keywords,
            radius=radius,
            api_key=api_key,
            page=page,
        )
        if page == 1:
            first_result = dict(result)
        if result.get("status") != "1":
            return result

        page_pois = result.get("pois") or []
        raw_pois.extend(page_pois)
        if len(page_pois) < 25:
            break

    merged = dict(first_result)
    merged["api_total_count"] = _to_int(first_result.get("count")) or 0
    merged["pois"] = raw_pois
    merged["deduped_pois"] = extract_pois(merged, longitude, latitude)
    merged["deduped_count"] = len(merged["deduped_pois"])
    return merged


async def get_competitor_count(
    longitude: float,
    latitude: float,
    radius: int,
    api_key: str
) -> int:
    """获取指定坐标周边竞品（网吧/电竞馆）数量"""
    result = await search_poi_around_pages(
        longitude, latitude,
        keywords="网吧|网咖|电竞|电竞馆|电竞酒店|电竞俱乐部|电子竞技|电竞中心|互联网上网服务|游戏厅|游艺厅",
        radius=radius,
        api_key=api_key,
        max_pages=3,
    )
    if result.get("status") == "1":
        return int(result.get("deduped_count", 0))
    return 0


async def get_heatmap_data(
    longitude: float,
    latitude: float,
    radius: int,
    api_key: str,
    huiyan_key: Optional[str] = None,
    allow_mock_data: bool = False,
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
            if not allow_mock_data:
                logger.warning(f"慧眼 API 调用失败，且未授权模拟数据: {e}")
                raise
            logger.warning(f"慧眼 API 调用失败，用户已授权降级为 POI 模拟: {e}")

    if not allow_mock_data:
        return []

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
        # 无 POI 数据（API Key 无效或超时）时，生成地理分布合理的模拟热力点
        # 模拟市区商业居住混合分布：中心区域热度高，向外逐渐减弱
        return _generate_simulated_heatmap(longitude, latitude, radius)

    # 计算每个 POI 的热度权重（基于与中心点距离和类别权重）
    points = []
    for lng, lat, w_factor in all_pois:
        # 距离衰减：越近权重越高
        dist = math.sqrt((lng - longitude) ** 2 + (lat - latitude) ** 2) * 111000  # 近似米
        dist_factor = max(0.1, 1 - dist / radius)
        weight = round(dist_factor * w_factor * 100, 1)
        points.append({"lng": lng, "lat": lat, "weight": weight})

    return points


def _generate_simulated_heatmap(
    longitude: float,
    latitude: float,
    radius: int,
    point_count: int = 120
) -> list[dict]:
    """
    生成地理分布合理的模拟热力点
    当高德 API Key 无效或调用失败时作为降级方案
    模拟市区商业居住混合分布：中心区域热度高，向外逐渐减弱
    """
    import math
    import random

    # 度数转弧度系数（第一层近似）
    lat_per_meter = 1.0 / 111000
    lng_per_meter = 1.0 / (111000 * math.cos(math.radians(latitude)))

    points = []
    random.seed(int(longitude * 1000 + latitude * 1000))  # 固定种子，相同坐标结果一致

    # 生成多个热点聚集（模拟商业中心、居住区、学校等）
    cluster_centers = [
        (0.0, 0.0, 1.0),           # 中心商业区
        (0.3, 0.2, 0.85),          # 居住商业混合
        (-0.25, 0.35, 0.75),       # 居住区
        (0.4, -0.3, 0.7),          # 居住区
        (-0.15, -0.4, 0.65),       # 居住区
        (0.6, 0.1, 0.55),          # 边缘商业
        (-0.5, 0.2, 0.5),          # 边缘居住
    ]

    per_cluster = point_count // len(cluster_centers)

    for cx_ratio, cy_ratio, intensity in cluster_centers:
        # 聚集中心坐标
        cx = longitude + cx_ratio * radius * lng_per_meter * 0.7
        cy = latitude + cy_ratio * radius * lat_per_meter * 0.7
        cluster_radius = radius * 0.35  # 聚集半径

        for _ in range(per_cluster):
            # 高斯分布采样
            angle = random.uniform(0, 2 * math.pi)
            r = abs(random.gauss(0, cluster_radius * 0.4))
            r = min(r, cluster_radius)

            pt_lng = cx + r * math.cos(angle) * lng_per_meter
            pt_lat = cy + r * math.sin(angle) * lat_per_meter

            # 距聚集中心越近，热度越高
            dist_to_center = math.sqrt((pt_lng - cx) ** 2 + (pt_lat - cy) ** 2) * 111000
            dist_factor = max(0.1, 1 - dist_to_center / cluster_radius)
            weight = round(intensity * dist_factor * 100 * random.uniform(0.7, 1.0), 1)
            weight = max(5.0, min(100.0, weight))

            points.append({"lng": pt_lng, "lat": pt_lat, "weight": weight})

    return points


def get_huiyan_key(db: Session) -> Optional[str]:
    """从数据库配置中获取高德慧眼 API Key（企业版）"""
    cfg = db.query(SystemConfig).filter(
        SystemConfig.config_key == "amap_huiyan_key",
        SystemConfig.is_active == True
    ).first()
    if cfg and cfg.config_value:
        return decrypt_config_value(cfg.config_value)
    return None
