import { cli, Strategy } from '@jackwener/opencli/registry';
import { ArgumentError, CommandExecutionError } from '@jackwener/opencli/errors';

/*
Strategy: PUBLIC_API
Contract: stable public JobPosting JSON-LD plus visible canonical page URL
Evidence:
- Public GET requests to both direct ITviec listing URLs and links.itviec.com
  tracking URLs return the rendered listing HTML without authentication.
- Active pages expose schema.org JobPosting JSON-LD with title, employer,
  location, dates, salary, skills, description, benefits, and apply URL.
- Expired listings return HTTP 410. The final redirect URL still identifies the
  exact ITviec listing, so closed state is explicit and identity remains stable.
- The adapter rejects non-ITviec redirects and direct-URL path mismatches.
*/

function clean(value) {
  return String(value ?? '').replace(/[\u00a0\u202f]+/g, ' ').replace(/\s+/g, ' ').trim();
}

function decodeEntities(value) {
  const named = {
    amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
    ndash: '–', mdash: '—', hellip: '…', rsquo: '’', lsquo: '‘',
    rdquo: '”', ldquo: '“', bull: '•', middot: '·', copy: '©',
  };
  return String(value ?? '').replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (match, entity) => {
    if (entity[0] === '#') {
      const hex = entity[1]?.toLowerCase() === 'x';
      const code = Number.parseInt(entity.slice(hex ? 2 : 1), hex ? 16 : 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return named[entity.toLowerCase()] ?? match;
  });
}

function htmlMarkdown(value) {
  let text = String(value ?? '')
    .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, '')
    .replace(/<li\b[^>]*>/gi, '\n- ')
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<\/(?:p|li|ul|ol|h[1-6]|section|div)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ');
  text = decodeEntities(text)
    .replace(/\r/g, '')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  const headings = [
    [/^Top 3 Reasons To Join Us$/gim, '### Why Join'],
    [/^The Job$/gim, '### Job Description'],
    [/^Your Skills and Experience$/gim, '### Requirements'],
    [/^Why You(?:'|’)ll Love Working Here$/gim, '### Benefits'],
  ];
  for (const [pattern, replacement] of headings) text = text.replace(pattern, replacement);
  return text.replace(/\n{3,}/g, '\n\n').trim();
}

function normalizeInput(value) {
  let parsed;
  try {
    parsed = new URL(clean(value));
  } catch {
    throw new ArgumentError('job-url must be an ITviec job or tracking URL');
  }
  const host = parsed.hostname.toLowerCase();
  if (parsed.protocol !== 'https:' || !['itviec.com', 'www.itviec.com', 'links.itviec.com'].includes(host)) {
    throw new ArgumentError('job-url must use https://itviec.com or https://links.itviec.com');
  }
  if (host !== 'links.itviec.com' && !parsed.pathname.startsWith('/it-jobs/')) {
    throw new ArgumentError('direct ITviec job URLs must use the /it-jobs/<slug> path');
  }
  return {
    requestedUrl: parsed.toString(),
    requestedPath: host === 'links.itviec.com' ? '' : parsed.pathname.replace(/\/$/, ''),
  };
}

function canonicalJob(responseUrl, requestedPath) {
  let parsed;
  try {
    parsed = new URL(responseUrl);
  } catch {
    throw new CommandExecutionError('ITviec returned an invalid final URL');
  }
  const host = parsed.hostname.toLowerCase();
  if (!['itviec.com', 'www.itviec.com'].includes(host) || !parsed.pathname.startsWith('/it-jobs/')) {
    throw new CommandExecutionError(`ITviec tracking URL redirected outside a job listing: ${parsed.toString()}`);
  }
  const finalPath = parsed.pathname.replace(/\/$/, '');
  if (requestedPath && finalPath !== requestedPath) {
    throw new CommandExecutionError(`ITviec returned ${finalPath} while requesting ${requestedPath}`);
  }
  return {
    jobKey: finalPath.slice('/it-jobs/'.length),
    listingUrl: `https://itviec.com${finalPath}`,
    finalPath,
  };
}

function jsonLdDocuments(html) {
  const documents = [];
  const pattern = /<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  for (const match of String(html).matchAll(pattern)) {
    try {
      const parsed = JSON.parse(match[1].trim());
      if (Array.isArray(parsed)) documents.push(...parsed);
      else documents.push(parsed);
    } catch {
      // Ignore unrelated malformed JSON-LD blocks; JobPosting is validated below.
    }
  }
  return documents.filter((item) => item && typeof item === 'object');
}

function typeMatches(document, expected) {
  const value = document?.['@type'];
  return Array.isArray(value) ? value.includes(expected) : value === expected;
}

function breadcrumbPath(documents) {
  const breadcrumb = documents.find((item) => typeMatches(item, 'BreadcrumbList'));
  const items = Array.isArray(breadcrumb?.itemListElement) ? breadcrumb.itemListElement : [];
  const last = items.at(-1)?.item;
  if (!last) return '';
  try {
    return new URL(last).pathname.replace(/\/$/, '');
  } catch {
    return '';
  }
}

function formatLocation(jobPosting) {
  const places = Array.isArray(jobPosting?.jobLocation)
    ? jobPosting.jobLocation
    : jobPosting?.jobLocation ? [jobPosting.jobLocation] : [];
  const locations = places.map((place) => {
    const address = place?.address || {};
    const parts = [address.streetAddress, address.addressLocality, address.addressRegion, address.addressCountry]
      .map(clean)
      .filter(Boolean);
    return [...new Set(parts)].join(', ');
  }).filter(Boolean);
  return [...new Set(locations)].join(' / ');
}

function formatSalary(jobPosting) {
  const salary = jobPosting?.baseSalary || {};
  const value = salary.value || {};
  const explicit = clean(value.value);
  if (explicit) return explicit;
  const minimum = value.minValue;
  const maximum = value.maxValue;
  if (minimum == null && maximum == null) return '';
  const range = minimum != null && maximum != null
    ? `${minimum} - ${maximum}`
    : String(minimum ?? maximum);
  return clean(`${range} ${salary.currency || ''} ${value.unitText || ''}`);
}

function availabilityFor(jobPosting) {
  const validThrough = clean(jobPosting?.validThrough);
  const expiry = validThrough ? Date.parse(`${validThrough}T23:59:59Z`) : Number.NaN;
  if (Number.isFinite(expiry) && expiry < Date.now()) {
    return { availability: 'closed', accepting: false, reason: 'valid_through_elapsed' };
  }
  const applyUrl = clean(jobPosting?.potentialAction?.target);
  if (applyUrl || String(jobPosting?.directApply).toUpperCase() === 'TRUE') {
    return { availability: 'accepting', accepting: true, reason: 'jobposting_apply_action' };
  }
  return { availability: 'unknown', accepting: false, reason: 'no_apply_or_expired_signal' };
}

function unavailableRow(job, availability, reason) {
  return {
    job_id: job.jobKey,
    availability,
    accepting_applications: false,
    status_reason: reason,
    title: '',
    company: '',
    location: '',
    listed: '',
    applicants: '',
    criteria: {},
    links: { listing: job.listingUrl, company: '', apply: '' },
    description: '',
  };
}

function parseJob(html, job) {
  const documents = jsonLdDocuments(html);
  const canonicalPath = breadcrumbPath(documents);
  if (canonicalPath && canonicalPath !== job.finalPath) {
    throw new CommandExecutionError(`ITviec page identity mismatch: ${canonicalPath} != ${job.finalPath}`);
  }
  const posting = documents.find((item) => typeMatches(item, 'JobPosting'));
  if (!posting) {
    const pageText = clean(decodeEntities(String(html).replace(/<[^>]+>/g, ' ')));
    if (/job expired|việc làm đã hết hạn|job is no longer available/i.test(pageText)) {
      return unavailableRow(job, 'closed', 'itviec_job_expired');
    }
    return unavailableRow(job, 'unavailable', 'jobposting_not_found');
  }

  const state = availabilityFor(posting);
  const skills = Array.isArray(posting.skills)
    ? posting.skills.map(clean).filter(Boolean)
    : clean(posting.skills).split(',').map(clean).filter(Boolean);
  const benefits = htmlMarkdown(posting.jobBenefits);
  let description = htmlMarkdown(posting.description);
  if (benefits && !description.includes(benefits)) {
    description = `${description}\n\n### Benefits\n\n${benefits}`.trim();
  }
  const company = clean(posting.hiringOrganization?.name);
  const companyUrl = clean(posting.hiringOrganization?.sameAs || posting.hiringOrganization?.url);

  return {
    job_id: job.jobKey,
    availability: state.availability,
    accepting_applications: state.accepting,
    status_reason: state.reason,
    title: clean(posting.title),
    company,
    location: formatLocation(posting),
    listed: clean(posting.datePosted),
    applicants: '',
    criteria: {
      job_type: clean(posting.employmentType),
      valid_through: clean(posting.validThrough),
      salary: formatSalary(posting),
      skills: skills.join(', '),
      experience: clean(posting.experienceRequirements),
    },
    links: {
      listing: job.listingUrl,
      company: companyUrl,
      apply: clean(posting.potentialAction?.target),
    },
    description,
  };
}

async function fetchJob(input) {
  let response;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      response = await fetch(input.requestedUrl, {
        headers: {
          accept: 'text/html,application/xhtml+xml',
          'accept-language': 'vi-VN,vi;q=0.9,en;q=0.8',
          'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36',
        },
        redirect: 'follow',
        signal: AbortSignal.timeout(30_000),
      });
    } catch (error) {
      if (attempt < 4) {
        await new Promise((resolve) => setTimeout(resolve, 2 ** attempt * 1000));
        continue;
      }
      throw new CommandExecutionError(`ITviec job request failed: ${error?.message || error}`);
    }
    if (![429, 503].includes(response.status) || attempt === 4) break;
    const retryAfter = Number.parseInt(response.headers.get('retry-after') || '', 10);
    const delayMs = Number.isFinite(retryAfter) ? retryAfter * 1000 : 2 ** attempt * 1500;
    await response.body?.cancel();
    await new Promise((resolve) => setTimeout(resolve, delayMs));
  }

  const job = canonicalJob(response.url, input.requestedPath);
  if (response.status === 404) return unavailableRow(job, 'unavailable', 'http_404_job_not_found');
  if (response.status === 410) return unavailableRow(job, 'closed', 'http_410_job_expired');
  if (!response.ok) throw new CommandExecutionError(`ITviec job request failed with HTTP ${response.status}`);
  const html = await response.text();
  if (!html.trim()) throw new CommandExecutionError(`ITviec returned an empty response for ${job.jobKey}`);
  return parseJob(html, job);
}

async function mapConcurrent(items, concurrency, worker) {
  const results = new Array(items.length);
  let cursor = 0;
  async function run() {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await worker(items[index]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, run));
  return results;
}

cli({
  site: 'itviec',
  name: 'job-public-detail',
  description: 'Fetch identity-verified ITviec job details and application availability from public JobPosting HTML',
  access: 'read',
  example: 'opencli itviec job-public-detail <job-url[,job-url...]> -f json',
  domain: 'itviec.com',
  strategy: Strategy.PUBLIC,
  browser: false,
  args: [
    { name: 'job-urls', type: 'string', required: true, positional: true, help: 'One ITviec job URL, or up to 25 comma-separated ITviec job or tracking URLs' },
  ],
  columns: [
    'job_id', 'availability', 'accepting_applications', 'status_reason', 'title',
    'company', 'location', 'listed', 'applicants', 'criteria', 'links', 'description',
  ],
  func: async (args) => {
    const values = clean(args['job-urls']).split(',').map(clean).filter(Boolean);
    if (!values.length || values.length > 25) {
      throw new ArgumentError('job-urls must contain between 1 and 25 ITviec job URLs');
    }
    return mapConcurrent(values.map(normalizeInput), 2, fetchJob);
  },
});
