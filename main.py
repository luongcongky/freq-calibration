import logging

from gui.scenario_grid import run_scenario_builder


def main():
    # Cấu hình logging toàn cục
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Điểm vào duy nhất: Scenario Builder (grid step-by-step, đa thiết bị).
    # Luồng file .txt + dashboard SMW200A/CNT-90XL cũ đã được loại bỏ.
    run_scenario_builder()


if __name__ == "__main__":
    main()
