LABEL := com.pbairol.daily-lookback

.PHONY: test run dry-run catch-up install-agent uninstall-agent run-now logs

test:
	uv run --group dev pytest -q

run:
	uv run lookback.py

dry-run:
	uv run lookback.py --dry-run

catch-up:
	uv run lookback.py --catch-up

install-agent:
	./scripts/install_launchd.sh

uninstall-agent:
	launchctl bootout gui/$$(id -u)/$(LABEL) || true
	rm -f ~/Library/LaunchAgents/$(LABEL).plist

run-now:
	launchctl kickstart -k gui/$$(id -u)/$(LABEL)

logs:
	tail -n 50 logs/lookback.out.log logs/lookback.err.log
