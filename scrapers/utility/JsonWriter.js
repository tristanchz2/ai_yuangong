/**
 * 增量 JSON 写入器
 *
 * 每次 addRow() 立即写入磁盘，保证爬虫中途崩溃时已爬数据不丢失。
 *
 * Usage:
 *   const writer = new JsonWriter('/path/to/output.json', { source: 'XX', scrapeTime: '...' });
 *   writer.addRow({ title: '...', content: '...' });   // 立即写入磁盘
 *   writer.addRow({ title: '...', content: '...' });
 *   console.log(writer.count);  // 2
 */

const fs = require('fs');

class JsonWriter {
  /**
   * @param {string} filePath - 输出文件路径
   * @param {object} meta - 顶层元数据（如 { source, scrapeTime }）
   */
  constructor(filePath, meta) {
    this.filePath = filePath;
    this.meta = meta;
    this.rows = [];
    this._flush();
  }

  /**
   * 添加一行数据并立即写入磁盘
   * @param {object} row
   */
  addRow(row) {
    this.rows.push(row);
    this._flush();
  }

  /**
   * 替换指定位置的行并立即写入磁盘（用于两阶段爬取：先列表后详情）
   * @param {number} index
   * @param {object} row
   */
  setRow(index, row) {
    this.rows[index] = row;
    this._flush();
  }

  /** 已写入行数 */
  get count() {
    return this.rows.length;
  }

  /** 写入完整 JSON 到磁盘 */
  _flush() {
    const output = { ...this.meta, rows: this.rows };
    fs.writeFileSync(this.filePath, JSON.stringify(output, null, 2), 'utf8');
  }
}

module.exports = { JsonWriter };
