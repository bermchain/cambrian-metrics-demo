# Cambrian homepage metrics preview (disposable)

A password-protected copy of the cambrian.org homepage with a new strip of five Cambrian API
coverage metrics between the hero and the first beige section. The numbers refresh daily via a
GitHub Action, and the page is taken down automatically after `EXPIRES_ON`.

## Setup (about 5 minutes)

1. Create a new **public** GitHub repository (GitHub Pages is free only for public repos)
   and upload everything in this folder, keeping the `.github/workflows/update.yml` path.
2. In the repo: **Settings > Secrets and variables > Actions > New repository secret**. Add:
   - `CAMBRIAN_API_KEY` - your Cambrian API key
   - `PAGE_PASSWORD` - the password viewers will type (12+ characters; use a long passphrase)
3. **Settings > Pages > Build and deployment > Source**: choose **GitHub Actions**.
4. **Actions > Update metrics page > Run workflow** to publish the first version.
   The first run takes roughly 10-20 minutes because it counts every pool and token list.
5. The page is at `https://<your-username>.github.io/<repo-name>/`.

## How it works

- `fetch_metrics.py` calls the Cambrian API with the key from the secret and writes the numbers.
- `homepage/` is a static copy of cambrian.org (HTML, styles, fonts, images). `index.template.html`
  has a `<!--CAMBRIAN_METRICS-->` marker where the metrics strip is inserted.
- `build_page.py` drops the metrics into the homepage, then encrypts the whole page with the
  password (PBKDF2-SHA256, AES-256-GCM). Only ciphertext is published; the browser decrypts it
  after the viewer enters the password. Images, fonts and styles are public cambrian.org assets.
- The API key never appears in the repo, the logs or the page.
- Last good values are kept in an encrypted Actions cache, so one failed API call shows the
  previous value instead of a blank.

## Expiry

`EXPIRES_ON` in `.github/workflows/update.yml` is the last day the page is live. On the first
daily run after that date the workflow replaces the page with an "expired" placeholder, tries
to remove the Pages site, and disables itself. To remove every trace, delete the repository.

## Changing things

- Password: update the `PAGE_PASSWORD` secret and run the workflow again.
- Expiry date: edit `EXPIRES_ON`.
- Refresh time: edit the `cron` line (UTC).

## Limits of the homepage copy

The copy is static: navigation dropdowns, the use-case tabs, the newsletter form and the animated
leaf and globe do not run. Links point to the live cambrian.org.
