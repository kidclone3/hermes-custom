#!/usr/bin/env node
/**
 * Job page crawler using Playwright + stealth + Cheerio.
 * Called by job-scan.py for --playwright mode.
 *
 * Usage:
 *   node job-crawler.mjs --url "https://itviec.com/it-jobs/slug-123" --source itviec
 *   node job-crawler.mjs --url "https://linkedin.com/jobs/view/123" --source linkedin --cookies linkedin-cookies.json
 *
 * Output: JSON on stdout with { description, real_url, company, salary, requirements, benefits, error }
 */

import { chromium } from 'playwright-extra';
import stealth from 'puppeteer-extra-plugin-stealth';
import * as cheerio from 'cheerio';
import fs from 'fs';

chromium.use(stealth());

// ─── Parse CLI args ──────────────────────────────────────────────────────────
const args = process.argv.slice(2);
function getArg(name) {
  const idx = args.indexOf(name);
  return idx >= 0 ? args[idx + 1] : null;
}

const URL = getArg('--url');
const SOURCE = getArg('--source') || 'itviec';
const COOKIES_FILE = getArg('--cookies');

if (!URL) {
  console.error('Usage: node job-crawler.mjs --url <url> --source <itviec|linkedin> [--cookies <file>]');
  process.exit(1);
}

// ─── ITviec detail parser ────────────────────────────────────────────────────

function parseItviecDetail(html, baseData = {}) {
  const $ = cheerio.load(html);

  // Scope: main column (excludes "More jobs for you" sidebar)
  const $mainCol = $('.col-xl-8.im-0').first();
  const $scope = $mainCol.length ? $mainCol : $.root();

  const title = $('h1').first().text().trim() || baseData.title || '';

  // Salary
  const salary = ($('.job-header-info .salary').first().text().replace(/\s+/g, ' ').trim()
    || baseData.salary || '');

  // Extract sections from h2 → content until next h2
  const sectionMap = {};
  $scope.find('h2').each((_, h) => {
    const heading = $(h).text().trim();
    if (!heading) return;
    if (/^(More jobs|Make Your|Feedback)/i.test(heading)) return;

    let sib = $(h).next();
    const chunks = [];
    while (sib.length && sib[0].tagName !== 'h2') {
      const lis = sib.find('li');
      if (lis.length) {
        chunks.push(lis.map((_, li) => '- ' + $(li).text().trim().replace(/\s+/g, ' ')).get().join('\n'));
      } else {
        const t = sib.text().trim().replace(/\s+\n/g, '\n').replace(/\n{3,}/g, '\n\n');
        if (t) chunks.push(t);
      }
      sib = sib.next();
    }
    sectionMap[heading] = chunks.join('\n\n').trim();
  });

  // Company info
  const companyInfo = {};
  const labels = ['Company type', 'Company industry', 'Company size', 'Country', 'Working days', 'Overtime policy'];
  $('div.col').each((_, col) => {
    const text = $(col).text().trim().replace(/\s+/g, ' ');
    if (labels.includes(text)) {
      const val = $(col).next('.col').text().trim().replace(/\s+/g, ' ');
      if (val) companyInfo[text] = val;
    }
  });

  // Skills from main column only
  const skills = [...new Set($scope.find('a.itag').map((_, t) => $(t).text().trim()).get())]
    .filter(s => s && !/^\+\d+$/.test(s));

  // Build markdown description
  let desc = '';
  if (title) desc += `## ${title}\n\n`;

  if (salary && !/sign in/i.test(salary) && !/you.ll love/i.test(salary.toLowerCase())) {
    desc += `**Salary:** ${salary}\n\n`;
  }

  const reasons = sectionMap['Top 3 reasons to join us'];
  if (reasons) desc += `### Why Join\n${reasons}\n\n`;

  const jobDesc = sectionMap['Job description'];
  if (jobDesc) desc += `### Job Description\n${jobDesc}\n\n`;

  const requirements = sectionMap['Your skills and experience'];
  if (requirements) desc += `### Requirements\n${requirements}\n\n`;

  const benefits = sectionMap["Why you'll love working here"];
  if (benefits) desc += `### Benefits\n${benefits}\n\n`;

  return {
    title,
    salary: salary || '',
    skills,
    description: desc.trim(),
    reasons: reasons || '',
    jobDescription: jobDesc || '',
    requirements: requirements || '',
    benefits: benefits || '',
    companyInfo,
  };
}

// ─── LinkedIn detail parser ──────────────────────────────────────────────────

function parseLinkedinDetail(html) {
  const $ = cheerio.load(html);

  // LinkedIn job pages have description in .description__text or .jobs-description
  const descElem = $('.description__text, .jobs-description, .jobs-box__html-content').first();
  let description = '';
  if (descElem.length) {
    description = descElem.text().trim().replace(/\s+/g, ' ');
  }

  // Try to get structured data from meta tags or JSON-LD
  let title = '';
  const jsonLdScript = $('script[type="application/ld+json"]').first().text();
  if (jsonLdScript) {
    try {
      const ld = JSON.parse(jsonLdScript);
      title = ld.title || '';
    } catch {}
  }

  if (!title) {
    title = $('h1').first().text().trim();
  }

  const company = $('.jobs-unified-top-card__company-name, .topcard__org-name-link')
    .first().text().trim();

  const location = $('.jobs-unified-top-card__bullet, .topcard__flavor--bullet')
    .first().text().trim();

  let md = '';
  if (title) md += `## ${title}\n\n`;
  if (company) md += `**Company:** ${company}\n\n`;
  if (location) md += `**Location:** ${location}\n\n`;
  if (description) md += `### Description\n${description}\n`;

  return {
    title,
    company: company || '',
    location: location || '',
    description: md.trim(),
  };
}

// ─── Browser setup ───────────────────────────────────────────────────────────

async function setupBrowser() {
  const contextOptions = {
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    viewport: { width: 1920, height: 1080 },
    locale: SOURCE === 'itviec' ? 'vi-VN' : 'en-US',
    timezoneId: 'Asia/Ho_Chi_Minh',
    extraHTTPHeaders: {
      'Accept-Language': 'vi-VN,vi;q=0.9,en;q=0.8',
    },
  };

  // Load cookies if provided
  if (COOKIES_FILE && fs.existsSync(COOKIES_FILE)) {
    contextOptions.storageState = COOKIES_FILE;
  }

  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
  });

  const context = await browser.newContext(contextOptions);
  const page = await context.newPage();
  return { browser, context, page };
}

// ─── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const { browser, context, page } = await setupBrowser();

  try {
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 60000 });

    // Handle Cloudflare challenge
    const title = await page.title();
    if (title.includes('Just a moment') || title.includes('Cloudflare')) {
      try {
        await page.waitForFunction(
          () => !document.title.includes('Just a moment'),
          { timeout: 30000 }
        );
      } catch {}
    }

    // Wait for content to load
    if (SOURCE === 'itviec') {
      try {
        await page.waitForSelector('.col-xl-8.im-0 h1, h1', { timeout: 15000 });
      } catch {}
    } else {
      try {
        await page.waitForSelector('.description__text, .jobs-description, h1', { timeout: 15000 });
      } catch {}
    }

    const html = await page.content();
    const realUrl = page.url();

    let result;
    if (SOURCE === 'itviec') {
      result = parseItviecDetail(html);
    } else {
      result = parseLinkedinDetail(html);
    }

    result.real_url = realUrl;
    result.error = '';
    console.log(JSON.stringify(result));

  } catch (err) {
    console.log(JSON.stringify({
      description: '',
      real_url: URL,
      error: err.message,
    }));
  } finally {
    await page.close();
    await context.close();
    await browser.close();
  }
}

main();
