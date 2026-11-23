"""Headless CLI chat — talk to Jarvis without the web UI.

    uv run python -m app.cli [--profile FENRIR] [--session <id>]

Same instruction, tools and memory as voice/web: messages go through the
generateContent tool-loop and persist into the dialogue session.
"""

import argparse
import asyncio
import sys

from app import agent as agent_mod
from app import store
from app.db import close_pool, init_pool


async def _run(profile_id: str | None, session_id: str | None) -> None:
    await init_pool()
    await store.seed_defaults()
    try:
        profile = (
            await store.get_profile(profile_id)
            if profile_id
            else await store.get_active_profile()
        )
        if profile is None:
            print(f"Профиль '{profile_id}' не найден")
            return

        if session_id:
            session = await store.get_session(session_id)
        else:
            session = None
        if session is None:
            session = await store.create_session(profile.id)

        agent_session = agent_mod.AgentSession(session, profile)
        agent_session.entries = await store.get_messages(session.id)

        print(f"Jarvis CLI · профиль «{profile.display_name}» · сессия {session.id}")
        print("Введите сообщение (пустая строка — выход).")
        loop = asyncio.get_running_loop()
        while True:
            try:
                text = await loop.run_in_executor(None, lambda: input("\nВы > ").strip())
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                break
            result = await agent_mod.chat_turn(agent_session, text)
            for t in result.get("traces", []):
                print(f"  [{t.get('name')}] {t.get('summary')}")
            print(f"{profile.display_name} > {result.get('text') or result.get('error') or ''}")
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis headless CLI chat")
    parser.add_argument("--profile", default=None, help="profile id (FENRIR/KORE/PUCK/AOEDE)")
    parser.add_argument("--session", default=None, help="resume a dialogue session id")
    args = parser.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    asyncio.run(_run(args.profile, args.session))


if __name__ == "__main__":
    main()
