"""
单个公司公告处理模块
负责获取单个公司的公告信息并格式化
"""
import json
import time
import random
import requests
from typing import List, Dict
from datetime import datetime
from .trace_utils import trace


class CompanyAnnouncementFetcher:
    """单个公司公告获取器"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://data.eastmoney.com/notices/stock/300308.html",
            "Connection": "keep-alive",
        }
    
    def fetch_announcements(
        self,
        stock_code: str,
        page_size: int = 50,
        page_index: int = 1,
        print_raw: bool = False,
    ) -> List[Dict]:
        """
        获取单个股票的公告列表
        
        Args:
            stock_code: 股票代码
            page_size: 每页数量
            
        Returns:
            List[Dict]: 格式化后的公告数据列表
        """
        url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
        
        # 生成JSONP回调函数名
        callback = f"jQuery{random.randint(1000000000000000000, 9999999999999999999)}_{int(time.time() * 1000)}"
        
        params = {
            "cb": callback,
            "sr": "-1",  # 按时间倒序
            "page_size": str(page_size),
            "page_index": str(page_index),
            "ann_type": "A",  # 所有公告类型
            "client_source": "web",
            "stock_list": stock_code,
            "f_node": "0",
            "s_node": "0",
        }
        
        try:
            resp = requests.get(url, params=params, headers=self.headers, timeout=20)
            
            if resp.status_code != 200:
                print(f"Error fetching {stock_code}: HTTP {resp.status_code}")
                return []
            
            # 解析JSONP响应
            text = resp.text.strip()
            if text.startswith(callback + "(") and text.endswith(")"):
                json_text = text[len(callback) + 1:-1]
                data = json.loads(json_text)
                
                if not data.get("success"):
                    print(f"API error for {stock_code}: {data.get('error', 'Unknown')}")
                    return []
                
                announcements = data.get("data", {}).get("list", [])

                if print_raw:
                    # 直接打印这一页原始数据（可能很长）
                    try:
                        import json as _json
                        print(f"\n[RAW PAGE stock={stock_code} page={page_index}] 共 {len(announcements)} 条:")
                        print(_json.dumps(announcements, ensure_ascii=False, indent=2))
                    except Exception:
                        print(f"[WARN] 原始数据打印失败 page={page_index}")

                # 格式化数据
                formatted_announcements = self._format_announcements(stock_code, announcements)

                print(f"✓ {stock_code}: 获取到 {len(formatted_announcements)} 条公告 (page {page_index})")
                return formatted_announcements
                
        except Exception as e:
            print(f"Error fetching {stock_code}: {str(e)}")
            return []
    
    def _format_announcements(self, stock_code: str, announcements: List[Dict]) -> List[Dict]:
        """
        格式化公告数据
        
        Args:
            stock_code: 股票代码
            announcements: 原始公告数据
            
        Returns:
            List[Dict]: 格式化后的公告数据
        """
        formatted_announcements = []
        
        for ann in announcements:
            # 提取分类名称
            columns = ann.get("columns", [])
            column_names = [col.get("column_name", "") for col in columns]
            column_name = ", ".join(column_names) if column_names else ""
            
            # 构造PDF链接
            art_code = ann.get("art_code", "")
            pdf_url = f"https://pdf.dfcfw.com/pdf/H2_{art_code}_1.pdf" if art_code else ""
            
            # 从codes数组中提取公司简称
            short_name = ""
            codes = ann.get("codes", [])
            if codes and len(codes) > 0:
                short_name = codes[0].get("short_name", "")
            
            # 提取显示时间：原 API 的 display_time 有时为空，真实值在 eiTime
            display_time_raw = ann.get("display_time") or ann.get("eiTime") or ""
            display_time = ""
            if display_time_raw != "":
                # 若是数字（时间戳）处理成标准格式
                if isinstance(display_time_raw, (int, float)) or (
                    isinstance(display_time_raw, str) and display_time_raw.isdigit()
                ):
                    try:
                        ts = int(display_time_raw)
                        # 13位视为毫秒
                        if ts > 1e12:
                            ts = ts / 1000.0
                        display_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        display_time = str(display_time_raw)
                else:
                    val = str(display_time_raw).strip()
                    # 处理包含毫秒的 "2025-09-09 20:16:05:677"
                    if val.count(":") == 3:
                        parts = val.rsplit(":", 1)
                        if len(parts) == 2 and parts[1].isdigit():
                            val = parts[0]
                    # 处理 "2025-09-09 20:16:05.677"
                    if "." in val:
                        h, t = val.split(".", 1)
                        if t.isdigit():
                            val = h
                    display_time = val
            
            # 按照要求的字段顺序排列
            formatted_ann = {
                "short_name": short_name,
                "stock_code": stock_code,
                "display_time": display_time,
                "column_name": column_name,
                "title": ann.get("title", ""),
                "url": pdf_url,
                "code": art_code,
            }
            formatted_announcements.append(formatted_ann)
        
        return formatted_announcements


def fetch_company_announcements(stock_code: str, page_size: int = 50) -> List[Dict]:
    """
    便捷函数：获取单个公司的公告
    
    Args:
        stock_code: 股票代码
        page_size: 每页数量
        
    Returns:
        List[Dict]: 公告数据列表
    """
    fetcher = CompanyAnnouncementFetcher()
    return fetcher.fetch_announcements(stock_code, page_size)


def fetch_all_pages_announcements(
    stock_code: str,
    page_size: int = 50,
    max_pages: int | None = None,
    delay_sec: float = 0.3,
    print_raw: bool = False,
) -> List[Dict]:
    """
    循环翻页抓取指定股票的全部公告，返回合并后的列表。

    参数:
        stock_code: 股票代码
        page_size: 每页数量（接口上限通常为 50）
    max_pages: 最大页数限制；None 表示不限制（直到接口返回空列表）。默认 None。
        delay_sec: 每页抓取间隔，避免触发限流
        print_raw: 是否打印每页原始 JSON

    注意:
        - 不限制页数可能导致大量请求，务必谨慎。
        - 如需根据时间窗口截断，可在外层自行过滤。
    """
    fetcher = CompanyAnnouncementFetcher()
    all_items: List[Dict] = []
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            break
        trace(f"[ann] 拉取第 {page} 页 (page_size={page_size}) ...")
        items = fetcher.fetch_announcements(
            stock_code,
            page_size=page_size,
            page_index=page,
            print_raw=print_raw,
        )
        if not items:
            trace("[ann] 返回空页，停止。")
            break
        all_items.extend(items)
        trace(f"[ann] 本页 {len(items)} 条，累计 {len(all_items)} 条")
        page += 1
        time.sleep(delay_sec)
    return all_items


def save_announcements_to_excel(stock_code: str, announcements: List[Dict], base_dir: str = "data/processed/announcements/excel") -> str:
    """
    将公告列表保存为Excel，目录按 base_dir/，文件名为 {stock_code}.xlsx。
    返回保存的文件路径。
    """
    import os
    import pandas as pd

    if not announcements:
        raise ValueError("没有可保存的公告数据")

    os.makedirs(base_dir, exist_ok=True)
    df = pd.DataFrame(announcements)

    # 统一列顺序（若存在）
    preferred_cols = ["short_name", "stock_code", "display_time", "column_name", "title", "url", "code"]
    cols = [c for c in preferred_cols if c in df.columns]
    if cols:
        df = df[cols]

    # 增加后缀，避免与旧目录混淆
    file_path = os.path.join(base_dir, f"{stock_code}_announcements.xlsx")
    df.to_excel(file_path, index=False)
    return file_path


if __name__ == "__main__":
    # 测试代码
    test_stock = "300308"
    print(f"测试获取 {test_stock} 的公告...")
    
    announcements = fetch_company_announcements(test_stock, page_size=5)
    
    if announcements:
        print(f"\n获取到 {len(announcements)} 条公告:")
        for i, ann in enumerate(announcements[:3], 1):
            print(f"{i}. [{ann['stock_code']}] {ann['short_name']}")
            print(f"   标题: {ann['title'][:60]}...")
            print(f"   时间: {ann['display_time']}")
            print(f"   分类: {ann['column_name']}")
            print(f"   PDF: {ann['url']}")
            print()
    else:
        print("未获取到公告数据")
