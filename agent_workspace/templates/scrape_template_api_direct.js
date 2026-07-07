/**
 * 爬虫模板 — API 直连模式
 * 
 * 适用场景：目标网站有公开的 API 接口，可以直接调用获取 JSON 数据
 * 无需渲染页面，速度快，反爬风险低
 * 
 * 使用方法：
 * 1. 复制此文件为 scrape_<site_name>.js
 * 2. 修改 CONFIG 中的 API URL 和参数
 * 3. 调整 transformData() 函数转换数据格式
 * 4. 运行测试：node scrape_<site_name>.js --latest 5
 */

const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

// ==================== 配置区（需要修改）====================
const CONFIG = {
    // API 基础 URL
    baseUrl: 'https://api.example.com/v1/items',
    
    // 默认查询参数
    defaultParams: {
        pageSize: 20,
        sortBy: 'publishDate',
        order: 'desc',
    },
    
    // 请求头（可选）
    headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        // 'Authorization': 'Bearer YOUR_TOKEN',  // 如果需要认证
    },
    
    // 输出文件路径
    outputFile: '../raw_data/example_data.json',
};
// =========================================================

function httpRequest(url, options = {}) {
    /**
     * 发送 HTTP 请求
     * @param {string} url - 请求 URL
     * @param {Object} options - 请求选项
     * @returns {Promise<Object>} 响应数据
     */
    return new Promise((resolve, reject) => {
        const urlObj = new URL(url);
        const client = urlObj.protocol === 'https:' ? https : http;
        
        const requestOptions = {
            hostname: urlObj.hostname,
            port: urlObj.port,
            path: urlObj.pathname + urlObj.search,
            method: options.method || 'GET',
            headers: {
                ...CONFIG.headers,
                ...options.headers,
            },
            timeout: 30000,
        };
        
        const req = client.request(requestOptions, (res) => {
            let data = '';
            
            res.on('data', (chunk) => {
                data += chunk;
            });
            
            res.on('end', () => {
                try {
                    const jsonData = JSON.parse(data);
                    resolve({
                        statusCode: res.statusCode,
                        headers: res.headers,
                        data: jsonData,
                    });
                } catch (error) {
                    resolve({
                        statusCode: res.statusCode,
                        headers: res.headers,
                        data: data,
                    });
                }
            });
        });
        
        req.on('error', (error) => {
            reject(error);
        });
        
        req.on('timeout', () => {
            req.destroy();
            reject(new Error('请求超时'));
        });
        
        if (options.body) {
            req.write(JSON.stringify(options.body));
        }
        
        req.end();
    });
}

function transformData(apiResponse) {
    /**
     * 将 API 响应转换为统一的数据格式
     * @param {Object} apiResponse - API 原始响应
     * @returns {Array} 转换后的数据数组
     */
    // TODO: 根据实际 API 响应结构调整
    const items = apiResponse.data.items || apiResponse.data.list || apiResponse.data || [];
    
    return items.map(item => ({
        title: item.title || item.name || '',
        link: item.url || item.link || item.detailUrl || '',
        date: item.publishDate || item.date || item.createdAt || '',
        summary: item.summary || item.description || '',
        // 添加其他需要的字段
    }));
}

async function fetchPage(pageNum, pageSize = 20) {
    /**
     * 获取单页数据
     * @param {number} pageNum - 页码（从 1 开始）
     * @param {number} pageSize - 每页数量
     * @returns {Array} 提取的数据数组
     */
    const params = new URLSearchParams({
        ...CONFIG.defaultParams,
        page: pageNum,
        pageSize: pageSize,
    });
    
    const url = `${CONFIG.baseUrl}?${params.toString()}`;
    console.log(`  📡 请求 API: ${url}`);
    
    try {
        const response = await httpRequest(url);
        
        if (response.statusCode !== 200) {
            console.error(`  ❌ API 返回错误: ${response.statusCode}`);
            return [];
        }
        
        const transformed = transformData(response);
        console.log(`  ✅ 成功提取 ${transformed.length} 条数据`);
        return transformed;
    } catch (error) {
        console.error(`  ❌ 第 ${pageNum} 页请求失败:`, error.message);
        return [];
    }
}

async function main() {
    const args = process.argv.slice(2);
    const isLatest = args.includes('--latest');
    const latestCount = isLatest ? parseInt(args[args.indexOf('--latest') + 1]) || 5 : null;
    const isYesterday = args.includes('--yesterday');
    
    console.log('🚀 启动 API 爬虫...');
    console.log(`   模式: ${isYesterday ? '昨天数据' : (latestCount ? `最新 ${latestCount} 条` : '全量')}`);
    
    try {
        let allResults = [];
        let pageNum = 1;
        let hasMore = true;
        
        while (hasMore) {
            const results = await fetchPage(pageNum, latestCount || 20);
            allResults = allResults.concat(results);
            
            // 检查是否达到限制
            if (latestCount && allResults.length >= latestCount) {
                allResults = allResults.slice(0, latestCount);
                console.log(`\n✅ 已达到限制 (${latestCount} 条)，停止爬取`);
                break;
            }
            
            // 检查是否有更多数据
            if (results.length === 0 || results.length < (latestCount || 20)) {
                hasMore = false;
                console.log('\n✅ 没有更多数据');
            } else {
                pageNum++;
            }
        }
        
        // 保存结果
        const outputDir = path.dirname(CONFIG.outputFile);
        if (!fs.existsSync(outputDir)) {
            fs.mkdirSync(outputDir, { recursive: true });
        }
        
        fs.writeFileSync(CONFIG.outputFile, JSON.stringify(allResults, null, 2), 'utf-8');
        console.log(`\n💾 数据已保存到: ${CONFIG.outputFile}`);
        console.log(`   共 ${allResults.length} 条记录`);
        
    } catch (error) {
        console.error('❌ 爬虫执行失败:', error);
        process.exit(1);
    }
}

main().catch(console.error);
