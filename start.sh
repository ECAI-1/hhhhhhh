def start_user_bot(user_id, bot_id, bot_dir: Path):
    main_file = find_main_file(bot_dir)
    if not main_file:
        print("no entry file for", bot_id)
        return False

    # 🔹 Auto-install requirements if present
    req_file = bot_dir / "requirements.txt"
    if req_file.exists():
        try:
            print(f"Installing requirements for {bot_id}...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
                cwd=str(bot_dir),
                check=False
            )
        except Exception as e:
            print("requirements install failed", e)

    log_file = LOGS_DIR / f"{bot_id}.log"
    lf = open(log_file, "ab")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(main_file)],
            stdout=lf, stderr=lf,
            cwd=str(bot_dir)
        )
    except Exception as e:
        print("start subprocess error", e)
        lf.close()
        return False

    running_bots[bot_id] = {"proc": proc, "log": str(log_file)}
    print("started", bot_id, "pid", proc.pid)
    return True

