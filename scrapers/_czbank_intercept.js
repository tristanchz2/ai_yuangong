const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  page.on('response', async response => {
    const url = response.url();
    if ((url.includes('luban') || url.includes('search') || url.includes('category') || url.includes('article') || url.includes('api')) && !url.includes('.js') && !url.includes('.css') && !url.includes('.png') && !url.includes('.jpg') && !url.includes('.woff')) {
      try {
        const body = await response.text();
        console.log(`\n--- Response: ${response.request().method()} ${url} (status: ${response.status()}) ---`);
        const postData = response.request().postData();
        if (postData) console.log(`POST data: ${postData.substring(0, 300)}`);
        console.log(body.substring(0, 1500));
      } catch(e) {}
    }
  });
  
  await page.goto('https://ccgp.szcgpt.czbank.com/luban/category?parentId=700835&childrenCode=134-848230', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);
  
  await browser.close();
})();
