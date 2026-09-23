"""Allow ``python -m gateway.hosted`` to start the hosted gateway."""

from gateway.hosted.run import main

if __name__ == "__main__":
    raise SystemExit(main())
