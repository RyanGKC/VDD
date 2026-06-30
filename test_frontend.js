const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('BROWSER_LOG:', msg.text()));
  page.on('pageerror', error => console.error('BROWSER_ERROR:', error));
  
  // Navigate to Vite dev server (we need to start it first)
  await page.goto('http://localhost:5173');
  
  // Wait for the button and click it
  await page.waitForSelector('button:has-text("Preview UI (Instant Mock)")');
  await page.click('button:has-text("Preview UI (Instant Mock)")');
  
  // Wait a second for any errors
  await page.waitForTimeout(2000);
  
  await browser.close();
})();
