# Decision: durable investigations with manual-only proposals

Status: accepted, 2026-10-05.

The product needs continuity between questions and conversations. The user has
explicitly prohibited application changes to printer configuration and permits
application-owned storage for memory.

Use an application-owned SQLite repository and typed investigation/evidence objects.
Keep timestamps and config revisions with observations. Share relevant historical
evidence across this printer's chats by default, with a setting for isolated chats.
Do not persist private model reasoning or present old observations as fresh state.

Run every proposal through deterministic static review and show a section comparison.
End the lifecycle at manual review. Users edit printer files themselves. Rechecking
only reads configuration and writes the resulting review into application storage.
Remove the unused approval/apply scaffold rather than suggesting it can authorize
printer writes.

The supported model remains a single daemon for one configured printer. No extra
database service or agent framework is required. The existing trusted local/proxy
boundary remains; this decision does not introduce user accounts or background
execution recovery.

Next work, deferred at the user's request: simplify the frontend/installer and
measure real diagnostic quality with representative printer investigations.
