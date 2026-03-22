# 股票数据爬取工具

一个功能强大的股票数据爬取脚本，支持A股、港股、美股、基金等多种金融数据的获取。

## 功能特点

- 📈 **A股数据**: 实时行情、历史数据
- 🎯 **基金数据**: 净值查询、业绩数据
- 🇺🇸 **美股数据**: 全球指数、个股信息
- 📊 **批量收集**: 根据配置文件批量获取
- 💾 **多格式导出**: JSON、CSV格式

## 安装依赖

```bash
# 安装必需依赖
pip install akshare yfinance pyyaml pandas

# 可选：安装Playwright用于基金详情爬取
pip install playwright
playwright install chromium
```

## 快速开始

### 1. 单只股票查询

```bash
# 查询A股
python stock_collector.py --type stock --code sh600519

# 查询基金
python stock_collector.py --type fund --code 000216

# 查询美股指数
python stock_collector.py --type index --code SPX

# 查询美股个股
python stock_collector.py --type us_stock --code AAPL

# 查询恒生指数
python stock_collector.py --type index --code HSI
```

### 2. 批量数据收集

```bash
# 根据配置文件收集所有数据
python batch_collector.py

# 导出为CSV格式
python batch_collector.py --export csv

# 同时导出JSON和CSV
python batch_collector.py --export both
```

### 3. 查看列表

```bash
# 查看A股列表
python stock_collector.py --type stock --list

# 查看基金列表
python stock_collector.py --type fund --list
```

### 4. JSON输出

```bash
# 导出为JSON格式（便于程序处理）
python stock_collector.py --type stock --code sh600519 --output json
```

## 代码示例

### 在Python代码中使用

```python
from stock_collector import AKShareCollector, YahooCollector

# 获取A股数据
ak = AKShareCollector()
stock = ak.get_stock_quote("sh600519")
print(f"茅台当前价格: ¥{stock.price}")

# 获取基金数据
fund = ak.get_fund_nav("000216")
print(f"黄金ETF净值: ¥{fund.nav}")

# 获取美股数据
yahoo = YahooCollector()
spx = yahoo.get_quote("SPX")
print(f"标普500: {spx.close}")

# 获取个股
aapl = yahoo.get_stock("AAPL")
print(f"苹果股价: ${aapl['price']}")
```

### 批量收集

```python
from batch_collector import BatchCollector

# 创建收集器
collector = BatchCollector("stock_config.yaml")

# 收集所有数据
results = collector.collect_all()

# 导出
collector.export_json("my_data.json")
collector.export_csv("./data")
```

## 配置文件

编辑 `stock_config.yaml` 来自定义你关注的标的：

```yaml
# A股关注列表
a_shares:
  - code: "sh600519"
    name: "贵州茅台"
  - code: "sz000858"
    name: "五粮液"

# 基金关注列表
funds:
  - code: "000216"
    name: "华安黄金ETF联接A"
  - code: "019455"
    name: "华泰柏瑞中韩半导体ETF联接C"

# 美股关注列表
us_stocks:
  - symbol: "AAPL"
    name: "Apple"
  - symbol: "NVDA"
    name: "NVIDIA"

# 指数关注列表
indices:
  domestic:
    - code: "sh000300"
      name: "沪深300"
  global:
    - code: "SPX"
      name: "标普500"
    - code: "VIX"
      name: "波动率指数"
```

## 支持的代码

### A股代码格式
- 上证指数: `sh000001`
- 沪深300: `sh000300`
- 创业板指: `sz399006`
- 个股: `sh600519` (茅台), `sz000858` (五粮液) 等

### 美股指数代码
- 标普500: `SPX`
- 纳斯达克: `IXIC`
- 道琼斯: `DJI`
- 恒生指数: `HSI`
- 日经225: `N225`
- VIX波动率: `VIX`
- 美元指数: `DXY`
- 黄金期货: `GLD`
- 原油期货: `CL`

### 基金代码
- 在天天基金网查询基金代码
- 例如: `000216` (华安黄金ETF)

## 数据结构

### 股票数据 (StockData)
```python
{
    "code": "sh600519",
    "name": "贵州茅台",
    "price": 1688.88,
    "change": 1.23,
    "change_pct": 0.07,
    "volume": 1234567,
    "turnover": 2087654321.0,
    "open": 1670.00,
    "high": 1695.00,
    "low": 1666.66,
    "date": "2024-01-15"
}
```

### 基金数据 (FundData)
```python
{
    "code": "000216",
    "name": "华安黄金ETF联接A",
    "nav": 1.2345,
    "nav_date": "2024-01-15",
    "daily_change": 0.56,
    "return_1m": 2.34,
    "return_3m": 5.67,
    "return_1y": 12.34
}
```

### 指数数据 (IndexData)
```python
{
    "symbol": "SPX",
    "name": "S&P 500",
    "close": 4783.35,
    "open": 4765.22,
    "high": 4793.30,
    "low": 4758.93,
    "change": 25.48,
    "change_pct": 0.54,
    "volume": 2345678900,
    "date": "2024-01-15"
}
```

## 注意事项

1. **数据源限制**: 
   - AKShare数据来自东方财富，有频率限制
   - Yahoo Finance可能有访问限制
   
2. **网络要求**: 
   - 美股数据需要能访问Yahoo Finance
   - 部分网络环境可能需要代理

3. **免责声明**: 
   - 本工具仅供学习研究使用
   - 不构成投资建议
   - 数据准确性以官方为准

## 许可证

MIT License
