"""Independent observer. Does not import or start the forward runner."""

from quant_lab.notifications.forward_watcher import main

if __name__ == "__main__":
    raise SystemExit(main())
