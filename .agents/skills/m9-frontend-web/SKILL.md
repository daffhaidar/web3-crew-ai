---
name: m9-frontend-web
description: Frontend web, landing pages, React, HTML/CSS, Tailwind. Triggers: website, landing page, frontend, react, html, css, ui, tailwind, web, situs.
---

# m9 — Interface Construction & Visual Delivery

---

## Operator Profile
Full-stack interface builder. Ship responsive, conversion-optimized surfaces. Mobile-first always.

## Layer Recommendations
```
Static surface:    HTML + Tailwind CSS + Alpine.js (fastest delivery)
Application:       React / Next.js (SSR, SEO-optimized)
Conversion page:   HTML + Tailwind + AOS.js (scroll triggers)
Control panel:     React + shadcn/ui + Recharts
Exchange surface:  Next.js + regional payment binding
```

## Base Template (HTML + Tailwind)
```html
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[Surface ID]</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-white text-gray-900 font-sans">
  <section class="min-h-screen flex items-center justify-center px-6">
    <div class="max-w-2xl text-center">
      <h1 class="text-4xl md:text-6xl font-bold mb-6">[Primary Signal]</h1>
      <p class="text-lg text-gray-600 mb-8">[Value Proposition]</p>
      <a href="#action" class="bg-black text-white px-8 py-4 rounded-lg text-lg hover:bg-gray-800 transition">
        [Directive]
      </a>
    </div>
  </section>
</body>
</html>
```

## Component Pattern (React)
```jsx
export default function Hero({ title, subtitle, ctaText, ctaLink }) {
  return (
    <section className="min-h-screen flex items-center justify-center px-6">
      <div className="max-w-2xl text-center">
        <h1 className="text-4xl md:text-6xl font-bold mb-6">{title}</h1>
        <p className="text-lg text-gray-600 mb-8">{subtitle}</p>
        <a href={ctaLink}
           className="bg-black text-white px-8 py-4 rounded-lg text-lg hover:bg-gray-800 transition">
          {ctaText}
        </a>
      </div>
    </section>
  );
}
```

## Conversion Surface Architecture
```
1. Interrupt    — headline + value prop + directive (above fold)
2. Proof        — logos, testimonials, metrics
3. Problem      — articulate the friction
4. Resolution   — product/service presentation
5. Capability   — 3–6 key outcomes
6. Exchange     — 3 tiers (anchor on premium)
7. Objection    — FAQ handling
8. Final signal — urgency + action directive
```

## Performance Protocol
```
✅ Assets: WebP, lazy-loaded, correctly dimensioned
✅ Typography: system-ui or max 2 external fonts, preloaded
✅ Styles: Tailwind purge on production
✅ Scripts: defer/async, minimal payload
✅ Responsive: verified at 375px minimum
✅ Discovery: meta title, description, OG tags
✅ Speed: < 3s first paint target
```

## Distribution Sequences
```bash
# Managed — Vercel
npx vercel --prod

# Managed — Netlify
npx netlify deploy --prod --dir=./dist

# Self-provisioned — Nginx
cp -r dist/* /var/www/html/
nginx -t && systemctl reload nginx
```

## Constraints
- Mobile-first always — desktop is secondary viewport
- All meta tags for discovery + social distribution included
- Both managed (Vercel/Netlify) and self-provisioned deploy options provided
- Responsive breakpoints: sm (640), md (768), lg (1024)
- Tailwind CSS default unless operator specifies otherwise
