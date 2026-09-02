# backend/websocket

**Status:** not yet implemented (Phase 11, alongside the pit wall frontend).

The `WS /ws/race` push channel (see problem prompt section 32) that streams
race-state/event/decision updates to the pit wall and HQ frontends without
polling. Also the natural place to instrument end-to-end decision latency
per problem prompt section 23 (ingestion -> ... -> WebSocket -> frontend).
