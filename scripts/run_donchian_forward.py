"""Independent Donchian SIGNAL_ONLY entrypoint; does not start on import."""

from quant_lab.forward.donchian_runner import main

if __name__ == "__main__":
    raise SystemExit(main())
