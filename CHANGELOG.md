# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **`POST /api/track` returned `"success": true` with every field empty.** When the
  CAPTCHA answer was wrong, `tracking.post.ir` responds with HTTP 200 and an empty
  `#pnlResult` div. The guard meant to catch this compared the div against two hardcoded
  literal strings ending in `"> </div>"` and `"></div>"`, but the site actually sends
  `...20px;">\n</div>` — with a newline. `.strip()` only trims the outside of the whole
  string, so neither literal ever matched. The guard was dead code, the retry never
  fired, and the empty page was parsed as a success. The check is now semantic
  (`pnl.get_text(strip=True) == ""`).
- Exhausting the CAPTCHA retries now returns `success: false` with status
  `CAPTCHA_FAILED`, instead of an empty success.
- A result panel that is present but empty is now reported as `NO_DATA`, never a success.
- `receiver_name` was being filled with a *location*. The lookup matched the bare word
  `گیرنده`, which also occurs inside the ordinary status text
  `مرسوله تحویل گیرنده گردیده است`, so it picked up the adjacent location cell. It now
  matches the full `نام گیرنده` label and rejects values that look like a location.

### Changed

- **CAPTCHA solving rewritten.** The old greyscale threshold sweep was actively harmful:
  on 8 live samples, the threshold of `127` it tried *first* scored 0/8 (it truncates
  4-digit answers to 3), while the untouched image scored 3/8. The digits are dark navy
  on light blue under brightly coloured noise curves, so preprocessing now uses a navy
  colour mask and the solver majority-votes across three renderings (masked + cropped,
  raw, wider mask).
- `solve_image_captcha` returns `None` when no rendering yields exactly 4 digits, so the
  caller retries with a fresh CAPTCHA. It previously returned a short partial answer,
  spending an attempt on a guaranteed rejection.
- An unsolved CAPTCHA now skips straight to a retry instead of submitting a POST already
  known to fail.
- `MAX_RETRIES` raised from `2` to `5` (in code defaults and `.env.example`) to match the
  measured per-attempt solve rate.
- Verbose per-request diagnostics (full HTML snippets, every form input, every parsed
  row) demoted from `INFO` to `DEBUG`, and guarded so they aren't built when disabled.

### Added

- `.liaraignore`, so deploys don't depend on `.gitignore` fallback. Upload size dropped
  from a potential 552 MB (`.venv`) to 20 KB.
- Optional `phone` field on `POST /api/track`, with Iranian mobile normalisation
  (`09xxxxxxxxx`, `+989xxxxxxxxx`, `989xxxxxxxxx`).
- `CAPSOLVER_API_KEY`, `TRUECAPTCHA_USERID`, and `TRUECAPTCHA_APIKEY` settings as
  optional fallback solvers. None are required — `ddddocr` solves locally and offline.
- `run_local.sh` for local venv setup and startup.

### Known issues

- `receiver_name` is unverified and empty in all testing so far. Iran Post gates it
  behind a `CustomerMob` postback; that flow is implemented and the POST succeeds, but
  submitting a number that doesn't belong to the shipment changes the response by
  nothing — no name and no error — so it could not be confirmed either way.
- The `Dockerfile` runs `playwright install chromium`, but `playwright` is not in
  `requirements.txt`, so a Docker build fails. Liara deploys are unaffected because
  `liara.json` sets `"platform": "python"`, which ignores the Dockerfile entirely.
- The `Dockerfile` no longer drops to a non-root user.
