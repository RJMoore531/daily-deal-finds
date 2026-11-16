# Daily Deal Finds

A family-friendly static site of daily Amazon finds in kids' toys, LEGO, tech, and holiday deals. Every product link is a plain Amazon URL with the Associates tag `russmoore-20`.

```
https://www.amazon.com/dp/<ASIN>?tag=russmoore-20
```

The page does **not** show exact Amazon prices or star ratings, because this project does not use the Product Advertising API. Shoppers click **Check price on Amazon** to see the live offer.

## Daily update

From this folder:

```bash
python3 update.py
```

That stamps today's date and rebuilds `index.html` from `deals.json`.

To also scan public deal roundups, verify new ASINs, and drop only listings that clearly 404:

```bash
python3 update.py --fetch
```

To re-check the current list without adding new items:

```bash
python3 update.py --verify
```

Amazon often serves a captcha or a short interstitial to datacenter IPs. If a check is blocked, the script keeps the existing deal instead of deleting it. It only drops a product when the Amazon page is a clear not-found result. It never invents ASINs, product names, or prices.

## Files

- `deals.json` — curated, verified deals and section copy
- `update.py` — fetch / verify / render
- `index.html` — generated homepage
- `styles.css` — site styles

## Hosting

The site is a plain static folder and is ready for GitHub Pages (preferred) or Netlify. This environment does not have a logged-in GitHub or Netlify CLI, so it has not been published yet.

To publish with GitHub Pages after connecting GitHub:

1. Create a public repository and push this folder.
2. Enable GitHub Pages from the `main` branch root (or `/docs` if you move the files there).
3. The homepage will be `https://<user>.github.io/<repo>/`.

## Compliance notes

- Affiliate disclosure: “As an Amazon Associate I earn from qualifying purchases.”
- Links open in a new tab with `rel="nofollow sponsored"`.
- No Amazon logos, and the footer states this is an independent guide.
- No cloaked or shortened links.
