/**
 * 将 HTML 转为纯文本
 * - 将块级元素转为换行
 * - 将常见 HTML 实体转为对应字符
 * - 去除所有标签
 * - 合并多余空白
 */
function stripHtml(html) {
  if (!html) return '';
  let t = html;

  // 1. 块级元素 → 换行
  t = t.replace(/<br\s*\/?>/gi, '\n');
  t = t.replace(/<\/?(p|div|li|tr|td|th|h[1-6]|table|section|article|ul|ol|dl|dt|dd|blockquote|pre)\b[^>]*>/gi, '\n');

  // 2. 常见 HTML 实体 → 字符
  t = t.replace(/&lt;/g, '<');
  t = t.replace(/&gt;/g, '>');
  t = t.replace(/&amp;/g, '&');
  t = t.replace(/&quot;/g, '"');
  t = t.replace(/&#39;/g, "'");
  t = t.replace(/&nbsp;/g, ' ');
  t = t.replace(/&ldquo;/g, '\u201C');
  t = t.replace(/&rdquo;/g, '\u201D');
  t = t.replace(/&lsquo;/g, '\u2018');
  t = t.replace(/&rsquo;/g, '\u2019');
  t = t.replace(/&mdash;/g, '\u2014');
  t = t.replace(/&ndash;/g, '\u2013');
  t = t.replace(/&hellip;/g, '\u2026');
  t = t.replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code)));
  t = t.replace(/&#x([0-9a-fA-F]+);/g, (_, code) => String.fromCharCode(parseInt(code, 16)));

  // 3. 去除所有剩余标签
  t = t.replace(/<[^>]+>/g, '');

  // 4. 清理空白
  t = t.replace(/[ \t]+/g, ' ');          // 连续空格 → 单个
  t = t.replace(/\n[ \t]+/g, '\n');        // 行首空白
  t = t.replace(/[ \t]+\n/g, '\n');        // 行尾空白
  t = t.replace(/\n{3,}/g, '\n\n');        // 连续空行 → 双换行

  return t.trim();
}

module.exports = { stripHtml };
