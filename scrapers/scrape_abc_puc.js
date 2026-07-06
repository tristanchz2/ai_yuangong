/**
 * 农银e采 (ABC PUC) 招标公告爬虫
 *
 * Usage:
 *   node scrape_abc_puc.js --yesterday        # 爬取昨天发布的公告
 *   node scrape_abc_puc.js --latest 5         # 爬取最新 N 条公告（默认5条）
 *   node scrape_abc_puc.js --date 2026-07-06  # 爬取指定日期的公告
 *
 * 使用 cycletls 模拟 Chrome TLS 指纹，绕过服务端 WAF 的 JA3 检测。
 * 依赖：npm install cycletls
 */

const initCycleTLS = require('cycletls');
const fs = require('fs');
const path = require('path');

const OUTPUT_JSON = path.join(__dirname, '..', 'row_data', 'abc_puc_data.json');
const BASE_URL = 'https://jc.abchina.com.cn/gateway/puc/portalMessage';

// Chrome TLS 指纹 (JA3) — 服务端 WAF 通过 JA3 识别非浏览器请求
const JA3 =
  '771,4865-4866-4867-49195-49199-49196-49200-52393-52392-49171-49172-156-157-47-53,0-23-65281-10-11-35-16-5-13-18-51-45-43-27-17513,29-23-24,0';
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36';

// ===================== 请求层 =====================

/**
 * 使用 cycletls 发送 API 请求
 */
async function apiRequest(cycleTLS, apiPath, reqBody) {
  const resp = await cycleTLS(
    `https://jc.abchina.com.cn${apiPath}`,
    {
      body: JSON.stringify(reqBody),
      headers: {
        'Content-Type': 'application/json',
        Referer: 'https://jc.abchina.com.cn/puc/',
        Origin: 'https://jc.abchina.com.cn',
        Accept: 'application/json, text/plain, */*',
      },
      ja3: JA3,
      userAgent: UA,
      timeout: 15,
    },
    'post'
  );

  // cycletls 在连接被重置时返回 401 + 错误字符串
  if (resp.status === 0 || resp.status === 401) {
    const errMsg = typeof resp.data === 'string' ? resp.data : '';
    if (errMsg.includes('forcibly closed') || errMsg.includes('EOF')) {
      throw new Error('ECONNRESET: 服务端断开连接');
    }
  }

  const data = resp.data || resp.json;
  if (!data) {
    throw new Error(`No response data (status ${resp.status})`);
  }

  // 检查 API 级错误 (如 "该请求无权限访问PUC服务")
  if (data.resCode && data.resCode !== '0000') {
    throw new Error(`API: ${data.resMessage || data.resCode}`);
  }

  // 标准 success/code 格式
  if (data.success === false) {
    throw new Error(`API: ${data.code} - ${data.message}`);
  }

  return data.value || data;
}

// ===================== 限频退避 =====================

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function requestWithBackoff(requestFn, label) {
  let delay = 5000;
  const MAX_ATTEMPTS = 6;
  const MAX_DELAY = 120000;

  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestFn();
    } catch (e) {
      if (attempt < MAX_ATTEMPTS) {
        console.log(`    ⚠ 请求异常: ${e.message}，等待 ${delay / 1000}s...`);
        await sleep(delay);
        delay = Math.min(delay * 2, MAX_DELAY);
      } else {
        console.log(`    ✗ ${label}: 失败，已重试 ${MAX_ATTEMPTS} 次`);
        throw e;
      }
    }
  }
}

// ===================== API 封装 =====================

function fetchList(cycleTLS, current, size = 10, extra = {}) {
  return apiRequest(cycleTLS, '/gateway/puc/portalMessage/queryInviteMessageForEie', {
    pageInfo: { current, size },
    beginTime: null,
    endTime: null,
    cOidOrgunit: null,
    messageType: '',
    publishColumn: 2,
    ...extra,
  });
}

function fetchDetail(cycleTLS, messageId) {
  return apiRequest(cycleTLS, '/gateway/puc/portalMessage/queryPortalMessageDetailForEie', {
    messageId,
  });
}

// ===================== 类型映射 =====================

const MESSAGE_TYPE_MAP = {
  3: '招标(资审)公告',
  4: '变更公告',
  5: '中标结果公示',
};

const PROJECT_TYPE_MAP = {
  1: '货物',
  2: '服务',
  3: '工程',
};

// ===================== 保存输出 =====================

function stripHtml(s) {
  if (!s) return '';
  return s
    .replace(/<[^>]+>/g, '')                  // 去掉所有 HTML 标签
    .replace(/&nbsp;/g, ' ')                  // &nbsp; → 空格
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&').replace(/&quot;/g, '"')
    .replace(/[ \t]+/g, ' ')                  // 连续空格合并
    .replace(/\n{3,}/g, '\n\n')              // 连续空行合并
    .trim();
}

function saveOutput(rows) {
  const jsonOutput = {
    scrapeTime: new Date().toISOString(),
    total: rows.length,
    rows: rows.map((r) => ({
      publishTime: (r.publishTime || r.startTime || '').substring(0, 10),
      noticeType: r.noticeType || MESSAGE_TYPE_MAP[r.messageType] || `类型${r.messageType}`,
      content: stripHtml(r.content) || stripHtml(r.messageTitle),
    })),
  };
  fs.writeFileSync(OUTPUT_JSON, JSON.stringify(jsonOutput, null, 2), 'utf8');
  return jsonOutput;
}

// ===================== 日期工具 =====================

function formatDate(d) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function getYesterday() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return formatDate(d);
}

// ===================== 主流程 =====================

async function main() {
  const args = process.argv.slice(2);

  let mode = 'latest';
  let count = 5;
  let targetDate = null;

  const yesterdayIdx = args.indexOf('--yesterday');
  const latestIdx = args.indexOf('--latest');
  const dateIdx = args.indexOf('--date');

  if (yesterdayIdx >= 0) {
    mode = 'date';
    targetDate = getYesterday();
    console.log(`📅 模式：爬取昨天的公告 (${targetDate})\n`);
  } else if (dateIdx >= 0) {
    mode = 'date';
    targetDate = args[dateIdx + 1];
    if (!targetDate || !/^\d{4}-\d{2}-\d{2}$/.test(targetDate)) {
      console.error('⚠ --date 参数格式错误，应为 yyyy-MM-dd');
      process.exit(1);
    }
    console.log(`📅 模式：爬取指定日期的公告 (${targetDate})\n`);
  } else if (latestIdx >= 0) {
    mode = 'latest';
    count = parseInt(args[latestIdx + 1]) || 5;
    console.log(`📋 模式：爬取最新 ${count} 条公告\n`);
  } else {
    console.log(`📋 模式：爬取最新 ${count} 条公告（默认）\n`);
  }

  console.log('🔧 初始化 cycletls (Chrome TLS 指纹)...');
  const cycleTLS = await initCycleTLS();

  let allItems = [];

  try {
    if (mode === 'latest') {
      console.log('[1/2] 获取公告列表...');
      const result = await requestWithBackoff(
        () => fetchList(cycleTLS, 1, Math.max(count, 10)),
        '列表'
      );

      if (!result || !result.records || result.records.length === 0) {
        console.log('  无数据');
        await cycleTLS.exit();
        return;
      }

      console.log(`  API 共 ${result.total} 条，当前页 ${result.records.length} 条`);
      allItems = result.records.slice(0, count);
      console.log(`  选取前 ${allItems.length} 条\n`);
    } else {
      console.log(`[1/2] 获取 ${targetDate} 的公告列表...`);

      const beginTs = new Date(targetDate + 'T00:00:00+08:00').getTime();
      const endTs = beginTs + 86400000;

      const extra = { beginTime: beginTs, endTime: endTs };

      let pageNo = 1;
      let foundAll = false;

      while (!foundAll) {
        await sleep(1500);
        const result = await requestWithBackoff(
          () => fetchList(cycleTLS, pageNo, 20, extra),
          `列表第${pageNo}页`
        );

        if (!result || !result.records || result.records.length === 0) {
          if (pageNo === 1) console.log('  无数据');
          break;
        }

        if (pageNo === 1) console.log(`  API 共 ${result.total} 条`);

        allItems.push(...result.records);
        console.log(
          `  第 ${pageNo} 页 ✓ (已匹配 ${allItems.length} 条，本页 ${result.records.length} 条)`
        );

        if (pageNo >= (result.pages || 1)) foundAll = true;
        pageNo++;
      }

      console.log(`  日期筛选完成: ${allItems.length} 条匹配 ${targetDate}\n`);
    }

    if (allItems.length === 0) {
      console.log('✓ 无匹配数据');
      saveOutput([]);
      await cycleTLS.exit();
      return;
    }

    // ---- 详情爬取 ----
    console.log(`[2/2] 爬取 ${allItems.length} 条公告正文...`);
    let detailOk = 0;
    let detailFail = 0;

    for (let i = 0; i < allItems.length; i++) {
      const item = allItems[i];
      const title = item.messageTitle || '';
      process.stdout.write(`  [${i + 1}/${allItems.length}] ${title.substring(0, 40)}... `);

      // 请求间隔，避免触发限频
      if (i > 0) await sleep(3000 + Math.random() * 2000);

      try {
        const detail = await fetchDetail(cycleTLS, item.messageId);
        const content = stripHtml(detail.messageContent || detail.content || '');
        if (content) {
          item.content = content;
          item.publishTime = item.startTime;
          detailOk++;
          console.log(`✓ (${content.length} 字)`);
        } else {
          // detail 返回了但没有 content 字段，记录可用字段
          const keys = Object.keys(detail);
          console.log(`⚠ 无 content 字段 (keys: ${keys.join(', ')})`);
          detailFail++;
        }
      } catch (e) {
        console.log(`✗ ${e.message}`);
        detailFail++;
      }
    }

    console.log(`\n  详情爬取完成: ${detailOk} 成功, ${detailFail} 失败\n`);

    // ---- 保存 ----
    console.log('[保存] 写入 JSON...');
    const output = saveOutput(allItems);
    console.log(`  ${OUTPUT_JSON}`);
    console.log(`  共 ${output.total} 条`);
    console.log('\n✓ 完成！');

    // 打印摘要
    console.log('\n--- 数据摘要 ---');
    allItems.forEach((r, i) => {
      const type = MESSAGE_TYPE_MAP[r.messageType] || `类型${r.messageType}`;
      const projType = PROJECT_TYPE_MAP[r.projectType] || '';
      const contentLen = r.content ? r.content.length : 0;
      const title = r.messageTitle || '';
      console.log(
        `  ${i + 1}. [${type}/${projType}] ${title.substring(0, 50)} (${(r.startTime || '').substring(0, 10)}) ${contentLen ? `[${contentLen}字]` : '[仅标题]'}`
      );
    });
  } finally {
    await cycleTLS.exit();
  }
}

main().catch((e) => {
  console.error('失败:', e.message);
  process.exit(1);
});
