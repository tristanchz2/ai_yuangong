const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  page.on('response', async response => {
    const url = response.url();
    if (!url.includes('.js') && !url.includes('.css') && !url.includes('.png') && !url.includes('.jpg') && !url.includes('.woff') && !url.includes('.ttf') && !url.includes('.svg') && !url.includes('.ico')) {
      try {
        const body = await response.text();
        if (body.length > 50) {
          console.log(`\n--- Response: ${response.request().method()} ${url} (status: ${response.status()}, len=${body.length}) ---`);
          const postData = response.request().postData();
          if (postData) console.log(`POST data: ${postData.substring(0, 500)}`);
          console.log(body.substring(0, 2000));
        }
      } catch(e) {}
    }
  });
  
  await page.goto('https://ccgp.szcgpt.czbank.com/luban/detail?parentId=700835&articleId=XdiWm1lrgqdfx7LwzZRbGQ==', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(5000);
  
  await browser.close();
})();
