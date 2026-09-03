# backend/websocket

**Status:** implemented (Phases 22-24).

The `WS /ws/race` push channel (see problem prompt section 32) that streams
race-state/event/decision updates to the pit wall and HQ frontends without
polling. Implemented via `ConnectionManager` in `backend/websocket/manager.py` and
fastapi endpoint in `backend/api/app.py`.
