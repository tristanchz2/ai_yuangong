# 页面观察陷阱

## 登录框 vs 公开数据的误判

很多网站（特别是银行采购平台）**同一个页面既有登录框又有公开数据**。不要看到登录框就判定"需要登录"。

**观察 10 秒规则：**
- 页面左侧有公告列表 + 右侧有登录框 → **公告是公开的**，用 Playwright 提取
- 页面空白或被登录遮罩完全覆盖 → 真的需要登录，跳过

**验证方法：**
1. 用 browser_snapshot 检查页面文本内容
2. 如果能看到公告标题 + 日期 → 数据可见，可以提取
3. 如果只有"用户名"、"密码"、"登录"按钮 → 需要登录

## 日期过滤的静默失效

很多网站的 API 会**静默忽略**日期过滤参数（接受参数但不报错，返回所有数据）。

**强制规则：** `--yesterday` 和 `--date` 模式下，必须实现客户端日期过滤，不能只依赖 API 参数。

**验证方法：**
1. 固定一个日期调 API，看返回的 `total` 和实际匹配数
2. 如果 `total` 远大于实际匹配数（比如 total=5000 但只有 5 条匹配）→ API 日期过滤不生效
3. 这种情况下必须完全依赖客户端过滤

**客户端过滤实现：**
```javascript
// API 参数照传，但结果必须客户端二次过滤
const result = await fetchList(pageNo, pageSize, targetDate, targetDate);
const matchedItems = result.rows.filter(item => {
  const itemDate = (item.publishDate || '').substring(0, 10);
  return itemDate === targetDate;
});

// 打印诊断信息
console.log(`  第 ${pageNo} 页: ${result.rows.length} 条，其中 ${matchedItems.length} 条是 ${targetDate} 的`);

// 提前终止：如果当前页最后一条记录的日期比目标日期早，停止翻页
const lastDate = (result.rows[result.rows.length - 1].publishDate || '').substring(0, 10);
if (lastDate && lastDate < targetDate) {
  console.log(`  ✓ 当前页最早数据 ${lastDate} 早于目标日期 ${targetDate}，停止翻页`);
  break;
}
```

## Content 质量检查

**必须验证：**
- `content` 不能等于 `title`（最常见的 bug）
- `content` 长度应 > 200 字符
- 如果 content 只有标题，说明详情页解析失败

**验证脚本：**
```bash
python3 -c "
import json
with open('raw_data/<name>_data.json') as f:
    data = json.load(f)
row = data['rows'][0]
print(f'Title: {row[\"title\"]}')
print(f'Content length: {len(row[\"content\"])} chars')
print(f'Content preview: {row[\"content\"][:200]}')
print()
if len(row['content']) < 200:
    print('❌ FAIL: Content too short (< 200 chars)')
elif row['content'].strip() == row['title'].strip():
    print('❌ FAIL: Content equals title (extraction failed)')
else:
    print('✅ PASS: Content looks good')
"
```
