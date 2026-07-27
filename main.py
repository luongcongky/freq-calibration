import logging

from gui.session_manager import run_session_manager


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    run_session_manager()


if __name__ == "__main__":
    main()
