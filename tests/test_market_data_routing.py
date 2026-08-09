# -*- coding: utf-8 -*-
"""适配层（routing.py）测试：后缀路由、各源代码格式转换。"""

import pytest

from market_data_mcp.routing import MarketCode, parse_code, to_eastmoney, to_ifind, to_sina


class TestParseCode:
    def test_a_share_sh(self):
        mc = parse_code("600519.SH")
        assert mc == MarketCode(market="A", code="600519", suffix="SH")

    def test_a_share_sz(self):
        assert parse_code("300476.SZ").market == "A"
        assert parse_code("300476.SZ").code == "300476"

    def test_b_share_same_channel(self):
        # B 股与 A 股同通道，不按开头猜市场
        assert parse_code("900901.SH").market == "A"
        assert parse_code("200725.SZ").market == "A"

    def test_bj(self):
        mc = parse_code("920002.BJ")
        assert mc.market == "BJ"
        assert mc.code == "920002"

    def test_hk(self):
        mc = parse_code("00700.HK")
        assert mc.market == "HK"
        assert mc.code == "00700"

    def test_us(self):
        mc = parse_code("AAPL.US")
        assert mc.market == "US"
        assert mc.code == "AAPL"

    def test_lowercase_suffix(self):
        assert parse_code("aapl.us").market == "US"

    def test_missing_suffix(self):
        with pytest.raises(ValueError, match="必须带市场后缀"):
            parse_code("600519")

    def test_unknown_suffix(self):
        with pytest.raises(ValueError, match="不支持的市场后缀"):
            parse_code("600519.XX")

    def test_bad_digits_a(self):
        with pytest.raises(ValueError, match="6 位数字"):
            parse_code("519.SH")

    def test_bad_digits_hk(self):
        with pytest.raises(ValueError, match="5 位数字"):
            parse_code("700.HK")

    def test_us_must_be_alpha(self):
        with pytest.raises(ValueError, match="字母代码"):
            parse_code("1234.US")


class TestConversions:
    def test_to_sina(self):
        assert to_sina(parse_code("600519.SH")) == "sh600519"
        assert to_sina(parse_code("300476.SZ")) == "sz300476"
        assert to_sina(parse_code("900901.SH")) == "sh900901"
        assert to_sina(parse_code("200725.SZ")) == "sz200725"
        assert to_sina(parse_code("920002.BJ")) == "bj920002"
        assert to_sina(parse_code("00700.HK")) == "00700"
        assert to_sina(parse_code("AAPL.US")) == "AAPL"

    def test_to_ifind(self):
        assert to_ifind(parse_code("600519.SH")) == "600519.SH"
        assert to_ifind(parse_code("300476.SZ")) == "300476.SZ"
        assert to_ifind(parse_code("920002.BJ")) == "920002.BJ"
        # 港股 4 位带前导零
        assert to_ifind(parse_code("00700.HK")) == "0700.HK"
        assert to_ifind(parse_code("00001.HK")) == "0001.HK"
        # 美股占位，provider 内探测 .O/.N
        assert to_ifind(parse_code("AAPL.US")) == "AAPL.US"

    def test_to_eastmoney(self):
        assert to_eastmoney(parse_code("600519.SH")) == "600519"
        assert to_eastmoney(parse_code("00700.HK")) == "00700"
        assert to_eastmoney(parse_code("AAPL.US")) == "105.AAPL"
