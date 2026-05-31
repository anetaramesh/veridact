.PHONY: serve test demo-treasury demo-loan demo-trading report

PYTHON   ?= python3
BASE_URL ?= http://localhost:8000
DELAY    ?= 1.0
# WeasyPrint needs Homebrew Pango on macOS
export DYLD_LIBRARY_PATH ?= /opt/homebrew/lib

# ── Dev server ───────────────────────────────────────────────────────────────
serve:
	cd veridact && uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# ── Tests ────────────────────────────────────────────────────────────────────
test:
	cd veridact && pytest -q

# ── Demo scenarios ───────────────────────────────────────────────────────────
demo-treasury:
	cd veridact && $(PYTHON) -m src.demo --scenario treasury --base-url $(BASE_URL) --delay $(DELAY)

demo-loan:
	cd veridact && $(PYTHON) -m src.demo --scenario loan --base-url $(BASE_URL) --delay $(DELAY)

demo-trading:
	cd veridact && $(PYTHON) -m src.demo --scenario trading --base-url $(BASE_URL) --delay $(DELAY)

# ── PDF report (last 30 days, opens in browser) ──────────────────────────────
report:
	@FROM=$$(date -v-30d +%Y-%m-%d 2>/dev/null || date -d '-30 days' +%Y-%m-%d) ; \
	TO=$$(date +%Y-%m-%d) ; \
	OUTFILE="/tmp/veridact-report-$$FROM-$$TO.pdf" ; \
	echo "Generating report $$FROM → $$TO …" ; \
	curl -sf "$(BASE_URL)/report/pdf?from=$$FROM&to=$$TO" -o "$$OUTFILE" ; \
	echo "Saved: $$OUTFILE" ; \
	open "$$OUTFILE" 2>/dev/null || xdg-open "$$OUTFILE" 2>/dev/null || echo "Open $$OUTFILE manually."
