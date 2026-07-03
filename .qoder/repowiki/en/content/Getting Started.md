# Getting Started

<cite>
**Referenced Files in This Document**
- [scrape_cfcpn.js](file://scrape_cfcpn.js)
</cite>

## Table of Contents
1. [Introduction](#introduction)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Basic Usage](#basic-usage)
5. [Command-Line Modes](#command-line-modes)
6. [Output Files](#output-files)
7. [Verification Steps](#verification-steps)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Data Structure](#data-structure)
10. [Best Practices](#best-practices)

## Introduction

The CFCPN Scraper is a lightweight Node.js application designed to extract procurement announcement data from the China Financial Procurement Network (金采网 - CFCPN). This tool provides an efficient way to collect structured procurement data for analysis, reporting, or integration purposes.

The scraper automatically handles pagination, rate limiting, and data formatting while providing both JSON and CSV output formats for maximum compatibility with various data processing tools.

## Prerequisites

### Node.js Requirements

- **Minimum Version**: Node.js 12.0.0 or higher
- **Recommended Version**: Node.js 18.0.0 LTS or newer
- **Architecture**: x64 or ARM64 supported
- **Operating System**: Windows, macOS, Linux

### Verification

Verify your Node.js installation by running:

```bash
node --version
```

Expected output should show version 12.0.0 or higher.

### Internet Connection

A stable internet connection is required as the scraper communicates with the CFCPN API server at `http://www.cfcpn.com`.

## Installation

The CFCPN Scraper requires no external dependencies or npm packages. Simply download the main script file to your desired location.

### Quick Setup

1. Download the `scrape_cfcpn.js` file to your preferred directory
2. Ensure you have Node.js installed (see Prerequisites section)
3. Open a terminal/command prompt in the same directory as the script

### Directory Structure

After setup, your directory should contain:

```
your-directory/
└── scrape_cfcpn.js
```

No additional configuration files or package installations are required.

## Basic Usage

### Default Execution (50 Records)

To scrape the default 50 records (first 5 pages):

```bash
node scrape_cfcpn.js
```

This command will:
- Fetch the first page to determine total record count
- Scrape up to 5 pages (50 records)
- Generate both JSON and CSV output files
- Display real-time progress information

### Custom Page Count

To scrape a specific number of pages:

```bash
node scrape_cfcpn.js 20
```

This command will:
- Fetch up to 20 pages (200 records)
- Respect the API's actual total record limit
- Provide progress updates during scraping

### Full Data Extraction

To scrape all available records:

```bash
node scrape_cfcpn.js all
```

⚠️ **Warning**: The complete dataset contains over 140,000 records. This operation may take several hours and generate large output files.

## Command-Line Modes

### Mode 1: Default Execution
**Command**: `node scrape_cfcpn.js`

- **Records**: 50 (first 5 pages)
- **Use Case**: Quick data sampling, testing, or small-scale analysis
- **Duration**: Approximately 3-5 seconds
- **Output Size**: ~50KB JSON, ~20KB CSV

### Mode 2: Custom Page Count
**Command**: `node scrape_cfcpn.js <number>`

- **Records**: `<number> × 10` (where `<number>` is your specified value)
- **Use Case**: Medium-scale data collection for reports or analysis
- **Duration**: Proportional to page count (approximately 500ms per page)
- **Example**: `node scrape_cfcpn.js 100` = 1,000 records

### Mode 3: Full Dataset Extraction
**Command**: `node scrape_cfcpn.js all`

- **Records**: All available records (140,000+)
- **Use Case**: Complete archival, comprehensive analysis, or bulk data processing
- **Duration**: Several hours depending on network conditions
- **Output Size**: Large files (hundreds of MB to GB range)

## Output Files

The scraper generates two output files in the same directory as the script:

### JSON Output File
**Filename**: `cfcpn_data.json`

**Location**: Same directory as `scrape_cfcpn.js`

**Structure**:
```json
{
  "scrapeTime": "ISO timestamp",
  "total": "Total records available",
  "scraped": "Number of records actually scraped",
  "rows": [
    {
      "id": "Record ID",
      "title": "Announcement Title",
      "publishTime": "Publication Date",
      "purchaser": "Purchasing Organization",
      "method": "Procurement Method",
      "region": "Geographic Region",
      "category": "Category Code",
      "tags": "Category Tags",
      "source": "Source Information"
    }
  ]
}
```

### CSV Output File
**Filename**: `cfcpn_data.csv`

**Location**: Same directory as `scrape_cfcpn.js`

**Format**: UTF-8 with BOM (Excel-compatible)

**Columns**:
- 序号 (Sequence Number)
- 标题 (Title)
- 发布时间 (Publish Time)
- 采购人 (Purchaser)
- 采购方式 (Procurement Method)
- 地区 (Region)
- 品类 (Category)
- 标签 (Tags)
- 来源 (Source)

### File Locations

Both output files are created in the current working directory where you execute the script:

```
your-directory/
├── scrape_cfcpn.js
├── cfcpn_data.json
└── cfcpn_data.csv
```

## Verification Steps

Follow these steps to verify that the scraper is working correctly:

### Step 1: Execute the Scraper
Run the default execution command:
```bash
node scrape_cfcpn.js
```

### Step 2: Check Console Output
You should see progress messages like:
```
[1/3] 正在获取第1页数据，确认总条数...
  共 XXXX 条记录，XX 页
[2/3] 开始爬取，目标: 5 页 (50 条)...

  第 1/5 页 ✓ (10 条)
  第 2/5 页 ✓ (10 条)
  第 3/5 页 ✓ (10 条)
  第 4/5 页 ✓ (10 条)
  第 5/5 页 ✓ (10 条)

[3/3] 保存数据...
  JSON: /path/to/cfcpn_data.json
  CSV:  /path/to/cfcpn_data.csv

✓ 完成！共爬取 50 条数据
```

### Step 3: Verify Output Files Exist
Check that both files were created:
```bash
ls -la cfcpn_data.*
```

Expected output:
```
-rw-r--r-- 1 user group 52340 date time cfcpn_data.json
-rw-r--r-- 1 user group 21560 date time cfcpn_data.csv
```

### Step 4: Validate JSON Structure
Open `cfcpn_data.json` in a text editor or use a JSON validator to ensure proper structure.

### Step 5: Test CSV Compatibility
Open `cfcpn_data.csv` in Excel or another spreadsheet application to verify proper formatting and encoding.

### Step 6: Verify Data Content
Check that the data contains expected fields and reasonable values:
- Record IDs should be unique
- Publication dates should be recent
- Purchaser names should be valid organizations
- Regions should correspond to Chinese administrative divisions

## Troubleshooting Guide

### Common Issues and Solutions

#### Network Connectivity Problems

**Symptoms**:
- Connection timeout errors
- "Request failed" messages
- No data returned from API

**Solutions**:
1. Check your internet connection
2. Verify firewall settings allow HTTP requests to `www.cfcpn.com`
3. Try using a different network if possible
4. Check if corporate proxy settings need configuration

**Error Message Example**:
```
请求失败: connect ECONNREFUSED 127.0.0.1:80
```

#### API Rate Limiting

**Symptoms**:
- Intermittent request failures
- Empty response data
- Temporary blocking messages

**Solutions**:
1. The scraper includes built-in rate limiting (500ms delay between requests)
2. If still experiencing issues, reduce the number of concurrent requests
3. Wait a few minutes before retrying
4. Consider using smaller batch sizes

**Built-in Protection**:
The scraper automatically implements:
- 500ms delay between requests
- Graceful error handling
- Automatic pagination limits

#### File Permission Errors

**Symptoms**:
- "Permission denied" when writing files
- Cannot create output files
- Write access errors

**Solutions**:
1. Ensure write permissions in the target directory
2. Run the script with appropriate user privileges
3. Change directory permissions if necessary
4. Use absolute paths if relative paths fail

**Windows-Specific**:
- Right-click terminal → "Run as administrator"
- Check folder security settings
- Disable antivirus temporarily if blocking file creation

#### Node.js Version Issues

**Symptoms**:
- Syntax errors
- Module loading failures
- Promise-related errors

**Solutions**:
1. Update Node.js to version 12.0.0 or higher
2. Verify installation with `node --version`
3. Reinstall Node.js if corrupted
4. Check PATH environment variable

#### Memory Issues with Large Datasets

**Symptoms**:
- Out of memory errors
- Slow performance with large datasets
- Application crashes during full extraction

**Solutions**:
1. Use streaming approaches for very large datasets
2. Process data in smaller batches
3. Increase Node.js memory allocation:
   ```bash
   node --max-old-space-size=4096 scrape_cfcpn.js all
   ```
4. Consider database storage instead of single file output

#### API Response Format Changes

**Symptoms**:
- JSON parsing errors
- Missing data fields
- Unexpected response structure

**Solutions**:
1. Check if the CFCPN API has updated its format
2. Review error messages for specific field names
3. Update the scraper if API changes significantly
4. Contact CFCPN support for API status

### Debugging Tips

#### Enable Verbose Logging
Add console logging statements to understand the flow:
```javascript
console.log('Debug:', { pageNo, totalPages, currentPage });
```

#### Test API Connectivity
Manually test the API endpoint:
```bash
curl -X POST http://www.cfcpn.com/jcw/noticeinfo/noticeInfo/dataNoticeList \
  -d "pageNo=1&pageSize=10&column=cggg"
```

#### Check Network Requests
Use browser developer tools or network monitoring software to inspect API calls.

#### Validate Output Data
Use data validation tools to check JSON/CSV integrity:
```bash
# JSON validation
python -m json.tool cfcpn_data.json > /dev/null

# CSV validation
head -5 cfcpn_data.csv
```

## Data Structure

### Input Parameters

The scraper sends POST requests with the following parameters:

| Parameter | Value | Description |
|-----------|-------|-------------|
| pageNo | Dynamic | Current page number |
| pageSize | 10 | Records per page |
| column | cggg | Announcement category |
| searchType | 选择分类 | Search type filter |
| searchContent | '' | Search content |
| searchNoticeType | 1 | Notice type filter |
| searchText | '' | Text search |
| region | '' | Geographic filter |
| commonLabel1 | '' | Label filter 1 |
| commonLabel2 | '' | Label filter 2 |
| beginPublishTime | '' | Start date filter |
| endPublishTime | '' | End date filter |
| searchVal | '' | Additional search value |
| searchPurId | '' | Purchaser ID filter |
| labelAllId | '' | Category ID filter |

### Output Fields

Each record contains the following standardized fields:

| Field | Type | Description |
|-------|------|-------------|
| id | string | Unique record identifier |
| title | string | Announcement title |
| publishTime | string | Publication date/time |
| purchaser | string | Purchasing organization name |
| method | string | Procurement method |
| region | string | Geographic region |
| category | string | Category classification |
| tags | string | Associated tags |
| source | string | Data source information |

## Best Practices

### Performance Optimization

1. **Batch Processing**: Use custom page counts for medium-sized datasets
2. **Rate Limiting**: Respect the built-in delays to avoid IP blocking
3. **Memory Management**: Monitor memory usage for large extractions
4. **Network Stability**: Use reliable connections for long-running tasks

### Data Quality Assurance

1. **Validation**: Always validate output files after extraction
2. **Backup**: Keep backup copies of important datasets
3. **Version Control**: Track scraper versions and data snapshots
4. **Metadata**: Include scrape timestamps and statistics

### Security Considerations

1. **Network Security**: Ensure secure network connections
2. **File Permissions**: Restrict access to sensitive data files
3. **API Compliance**: Follow CFCPN terms of service
4. **Data Privacy**: Handle any personal information appropriately

### Maintenance Guidelines

1. **Regular Updates**: Monitor for API changes and update accordingly
2. **Error Monitoring**: Implement logging for production deployments
3. **Testing**: Regularly test functionality across different environments
4. **Documentation**: Keep usage instructions current

---

**Note**: This scraper is designed for educational and research purposes. Always comply with the target website's terms of service and applicable laws when collecting data.