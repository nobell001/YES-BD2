if __name__ == "__main__":
    # src/config.py turns off ok-script's check, which kills the open copy.
    from src.compat import single_instance

    if not single_instance.acquire():
        single_instance.show_existing()
        raise SystemExit(0)

    import ok

    from src.config import config
    from src.debug_profile import configure_debug_profile
    from src.tasks.debug_registry import install_debug_tasks

    configure_debug_profile(config)
    install_debug_tasks(config)
    ok_instance = ok.OK(config)
    ok_instance.start()
