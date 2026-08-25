"""
Usage Dashboard Handler

Handles usage data requests for the usage dashboard, providing aggregated
usage statistics and time-series data for visualization.
"""

import asyncio
import logging
import hashlib
import json
from typing import Callable, Dict, List, Optional, Any
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from cachetools import TTLCache
from wss.schema import SocketIOHandler
from wss.sender import send_event, ResponseEvent
from wss.receiver.client_events import UsageDataRequest, UsageLogsRequest
from utils.database_pool import DatabasePoolMixin
from repositories.usage import UsageRepo

logger = logging.getLogger(__name__)


class UsageDashboardHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for usage dashboard data requests with intelligent caching"""

    def __init__(self, sio):
        """Initialize the UsageDashboardHandler with optimized caching using cachetools"""
        super().__init__(sio)
        # TTL cache with automatic expiry (5 minutes to match frontend)
        # maxsize=500 handles ~200 concurrent users with 2-3 queries each
        # cachetools handles all TTL/expiry logic automatically
        self._cache = TTLCache(maxsize=500, ttl=300)  # 5 minutes TTL
        logger.info("[UsageDashboardHandler] Initialized with TTLCache (maxsize=500, ttl=300s)")

    def get_events(self) -> Dict[str, Callable]:
        """Register which events this handler processes"""
        return {
            "usage:data": self.handle_usage_data,
            "usage:logs": self.handle_usage_logs,
        }

    @staticmethod
    def _workspace_key(user_id: str, organization_id: Optional[str]) -> str:
        """Stable identifier for a (user, workspace) pair used in cache keys.

        Personal workspaces are per-user (events with organization_id IS NULL belong
        only to that user). Org workspaces are shared, so the key is the org id —
        the same cache row serves every member viewing that org.
        """
        if organization_id:
            return f"org_{organization_id}"
        return f"personal_{user_id}"

    @staticmethod
    def _workspace_scope(user_id: str, organization_id: Optional[str]) -> tuple:
        """The user_usage_events WHERE predicate for a workspace, as ($1-based).

        Returns (clauses, params) — the caller appends further filters starting at
        param index len(params)+1.

        - Org view: organization_id = orgX (pooled across members; gate the caller's
          membership BEFORE calling this).
        - Personal view: user_id = me across ALL workspaces. Under "organization attribution policy" the
          event row's user_id IS the charged billing entity, so this captures the
          user's untagged personal spend PLUS spend from orgs they own (billed to
          them) and EXCLUDES orgs where they're a non-owner member (billed to the
          owner). Matches plan_limits.get_credit_usage, so the dashboard total
          reconciles with the credit gate.
        """
        if organization_id:
            return ["organization_id = $1"], [organization_id]
        return ["user_id = $1"], [user_id]

    def update_cache_with_event(self, user_id: str, usage_event):
        """
        Incrementally update cached data with new usage event.

        Args:
            user_id: User ID whose cache should be updated
            usage_event: UsageEventData instance with the new event
        """
        # Create new log entry. `usage_type` is the high-level category
        # (ai_builder / ai_usage / api_usage / cpu_usage / gpu_usage) — what the
        # dashboard groups by so AI builder turns are visually distinct from
        # agent-node LLM calls and third-party API charges. `model`
        # (= usage_subtype) is the leaf identifier. Timestamp must be tz-aware:
        # a naive isoformat() has no offset suffix, so `new Date()` on the FE
        # parses it as LOCAL time and skews the log row for non-UTC users.
        new_log = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'usage_type': usage_event.usage_type,
            'model': usage_event.usage_subtype,
            'tokens': int(usage_event.quantity) if usage_event.quantity else 0,
            'unit_type': usage_event.unit_type or 'tokens',
            'cost': float(usage_event.total_cost) if usage_event.total_cost else 0.0,
            'metadata': usage_event.metadata or {}
        }

        # The cache is partitioned by workspace. `user_id` here is the BILLING
        # user (the charged pool's owner under the configured attribution policy). The event belongs in:
        #   - the billing user's PERSONAL partition — the personal view now sums
        #     user_id across all workspaces, so an owned-org event shows there too;
        #   - the org partition (when org-tagged) — the org view is pooled.
        workspace_keys = {self._workspace_key(user_id, None)}
        if usage_event.organization_id:
            workspace_keys.add(self._workspace_key(user_id, usage_event.organization_id))

        for workspace_key in workspace_keys:
            logs_prefix = f"logs_{workspace_key}_"
            for cache_key in [k for k in self._cache.keys() if k.startswith(logs_prefix)]:
                cached_data = self._cache.get(cache_key)
                if not cached_data or 'logs' not in cached_data:
                    continue

                # Prepend to logs and maintain limit.
                # cache_key format: f"logs_{workspace_key}_{limit}_{usage_type}".
                # workspace_key itself contains an underscore (e.g. "personal_<uuid>"
                # or "org_<uuid>"), so the limit is at index 3, not 2.
                try:
                    limit = int(cache_key.split('_')[3])
                    cached_data['logs'] = [new_log] + cached_data['logs'][:limit-1]
                    cached_data['count'] = len(cached_data['logs'])
                    self._cache[cache_key] = cached_data
                    logger.info(f"[UsageDashboardHandler] Updated logs cache {cache_key} with new event")
                except (IndexError, ValueError) as e:
                    logger.warning(f"[UsageDashboardHandler] Could not parse limit from cache_key {cache_key}: {e}")

        # Aggregated-data cache entries are NOT invalidated here: their keys are
        # MD5 hashes of the request params, so we can't map an event back to
        # them. The 5-minute TTL bounds staleness, and the frontend applies the
        # same event to its own copy in real time (lib/usage/events.ts).

    def _generate_cache_key(self, user_id: str, request: UsageDataRequest) -> str:
        """Generate a unique cache key for a request.

        The workspace is part of the key because the same user gets a different
        result set in their personal workspace vs each org they belong to.
        """
        workspace_key = self._workspace_key(user_id, request.organization_id)
        cache_data = {
            'workspace': workspace_key,
            'start_date': request.start_date,
            'end_date': request.end_date,
            'usage_type': request.usage_type,
            'usage_subtype': request.usage_subtype,
            'group_by': request.group_by,
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        # This is an opaque cache namespace, but SHA-256 also avoids training
        # future callers to use MD5 for identifiers with unclear sensitivity.
        return hashlib.sha256(cache_str.encode()).hexdigest()

    async def handle_usage_data(self, sid: str, request: UsageDataRequest) -> None:
        """Handle usage data request with database-level aggregation for optimal performance"""
        try:
            # Get user_id from session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[UsageDashboardHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            logger.info(f"[UsageDashboardHandler] Fetching usage data for user {user_id}")

            # Check cache first (TTLCache handles expiry automatically)
            cache_key = self._generate_cache_key(user_id, request)
            cached_data = self._cache.get(cache_key)

            if cached_data:
                # Return cached data immediately
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=cached_data
                ))
                logger.info(f"[UsageDashboardHandler] Cache HIT for user {user_id}")
                return

            logger.info(f"[UsageDashboardHandler] Cache MISS for user {user_id}")

            # Note: current_balance removed - frontend uses useBalance hook for better performance
            # No need to fetch balance here as it's already tracked client-side with caching

            # Parse date filters
            start_date = None
            end_date = None

            if request.start_date:
                try:
                    start_date = datetime.fromisoformat(request.start_date.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Invalid start_date format: {request.start_date}")

            if request.end_date:
                try:
                    end_date = datetime.fromisoformat(request.end_date.replace('Z', '+00:00'))
                except ValueError:
                    logger.warning(f"Invalid end_date format: {request.end_date}")

            # Default to last 30 days if no dates provided
            if not start_date and not end_date:
                end_date = datetime.utcnow()
                start_date = end_date - timedelta(days=30)
            elif start_date and not end_date:
                end_date = datetime.utcnow()
            elif end_date and not start_date:
                start_date = end_date - timedelta(days=30)

            # Determine date truncation based on group_by
            if request.group_by == 'day':
                date_trunc = 'day'
            elif request.group_by == 'week':
                date_trunc = 'week'
            elif request.group_by == 'month':
                date_trunc = 'month'
            else:
                date_trunc = 'day'

            # ── Repository-backed read path ──────────────────────────────────
            # SQL lives in repositories/usage.py (UsageRepo). See DB_MIGRATION.md
            # for why we're moving in this direction. Workspace scoping,
            # membership check, and concurrent-aggregate execution are all
            # inside the repo — this handler is now presentation only.
            pool = await self.get_pool()
            repo = UsageRepo(pool)

            if request.organization_id:
                # Refuse to leak another org's spend even if the client lies
                # about workspace context. Membership check lives in the repo
                # so the boundary condition can't drift from the aggregate SQL.
                if not await repo.is_org_member(request.organization_id, user_id):
                    logger.warning(
                        f"[UsageDashboardHandler] User {user_id} requested usage for org "
                        f"{request.organization_id} but is not a member"
                    )
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Not a member of this organization",
                    ))
                    return

            agg = await repo.dashboard_aggregates(
                user_id=user_id,
                organization_id=request.organization_id,
                start_date=start_date,
                end_date=end_date,
                usage_type_filter=request.usage_type,
                usage_subtype_filter=request.usage_subtype,
                date_trunc=date_trunc,
            )
            total_result = agg["total"]
            by_type_rows = agg["by_type"]
            by_subtype_rows = agg["by_subtype"]
            time_series_rows = agg["time_series"]

            # Stored usage values are already in the installation's public
            # accounting unit; the wire boundary passes them through unchanged.
            # Process results (minimal Python processing now)
            total_credits = float(total_result) if total_result else 0.0

            # Process by_type
            usage_by_type = {
                row['usage_type']: float(row['total_cost'])
                for row in (by_type_rows or [])
            }

            # Process by_subtype
            usage_by_subtype = {
                row['usage_subtype']: float(row['total_cost'])
                for row in (by_subtype_rows or [])
            }

            # Unit each subtype charges in (tokens / seconds / requests / …).
            # Shipped alongside the aggregates so the dashboard can label
            # quantities exactly instead of inferring from the recent-logs
            # sample (which only covers the last N events).
            units_by_subtype = {
                row['usage_subtype']: row['unit_type'] or 'tokens'
                for row in (by_subtype_rows or [])
            }

            # Process time series - group by period with tokens
            time_series_data: Dict[str, Dict[str, Any]] = {}
            for row in (time_series_rows or []):
                period = row['period']
                # Format period as string
                if date_trunc == 'month':
                    date_key = period.strftime('%Y-%m')
                else:
                    date_key = period.strftime('%Y-%m-%d')

                cost_credits = float(row['total_cost'])
                tokens = int(row['total_tokens']) if row['total_tokens'] else 0
                usage_type = row['usage_type']
                usage_subtype = row['usage_subtype']

                # Initialize time series entry if not exists
                if date_key not in time_series_data:
                    time_series_data[date_key] = {
                        'date': date_key,
                        'total_cost': 0.0,
                        'by_type': {},
                        'by_subtype': {},
                        'tokens_by_subtype': {}
                    }

                # Add to time series (all values in credits, see boundary comment above)
                time_series_data[date_key]['total_cost'] += cost_credits
                time_series_data[date_key]['by_type'][usage_type] = \
                    time_series_data[date_key]['by_type'].get(usage_type, 0.0) + cost_credits
                time_series_data[date_key]['by_subtype'][usage_subtype] = \
                    time_series_data[date_key]['by_subtype'].get(usage_subtype, 0.0) + cost_credits
                time_series_data[date_key]['tokens_by_subtype'][usage_subtype] = \
                    time_series_data[date_key]['tokens_by_subtype'].get(usage_subtype, 0) + tokens

            # Convert time series dict to sorted list
            time_series = sorted(time_series_data.values(), key=lambda x: x['date'])

            logger.info(f"[UsageDashboardHandler] Aggregated {len(time_series)} time periods, total: {total_credits:.4f} credits")

            # Prepare response data — every numeric usage field is in credits.
            response_data = {
                'total_cost': round(total_credits, 4),
                'usage_by_type': {k: round(v, 4) for k, v in usage_by_type.items()},
                'usage_by_subtype': {k: round(v, 4) for k, v in usage_by_subtype.items()},
                'units_by_subtype': units_by_subtype,
                'time_series': time_series,
                'period_start': start_date.isoformat() if start_date else None,
                'period_end': end_date.isoformat() if end_date else None
            }

            # Cache the response data before sending (TTLCache handles expiry automatically)
            self._cache[cache_key] = response_data

            # Send response event using ResponseEvent pattern
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response_data
            ))

            logger.info(f"[UsageDashboardHandler] Sent usage data for user {user_id}")

        except Exception as e:
            logger.error(f"[UsageDashboardHandler] Error handling usage data request: {e}", exc_info=True)
            # Send error response using ResponseEvent pattern
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))

    async def handle_usage_logs(self, sid: str, request: UsageLogsRequest) -> None:
        """Handle recent usage logs request - fetches most recent individual events"""
        try:
            # Get user_id from session
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[UsageDashboardHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data={},
                    error="User not authenticated"
                ))
                return

            logger.info(f"[UsageDashboardHandler] Fetching usage logs for user {user_id}")

            # Pagination cursor. A malformed cursor is a client bug — error out
            # rather than silently re-serving page 1 as if it were page N.
            before = None
            if request.before:
                try:
                    before = datetime.fromisoformat(request.before.replace('Z', '+00:00'))
                except ValueError:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error=f"Invalid 'before' cursor: {request.before}",
                    ))
                    return

            # Only the DEFAULT first page (no cursor, no search) is cached —
            # it's what every dashboard mount requests, and keeping the key
            # format unchanged is what lets update_cache_with_event keep
            # prepending live events into it (it parses limit out of the key
            # by index). Filtered/paginated queries are user-driven one-offs.
            workspace_key = self._workspace_key(user_id, request.organization_id)
            cache_key = None
            if before is None and not request.search:
                cache_key = f"logs_{workspace_key}_{request.limit}_{request.usage_type or 'all'}"
                cached_data = self._cache.get(cache_key)
                if cached_data:
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data=cached_data
                    ))
                    logger.info(f"[UsageDashboardHandler] Logs cache HIT for user {user_id}")
                    return

            # Membership check + fetch through the repo. Same organization-attribution
            # workspace-scoping rules as handle_usage_data; see UsageRepo
            # docstrings for rationale.
            pool = await self.get_pool()
            repo = UsageRepo(pool)

            if request.organization_id:
                if not await repo.is_org_member(request.organization_id, user_id):
                    logger.warning(
                        f"[UsageDashboardHandler] User {user_id} requested logs for org "
                        f"{request.organization_id} but is not a member"
                    )
                    await send_event(self.sio, sid, ResponseEvent(
                        request_id=request.request_id,
                        data={},
                        error="Not a member of this organization",
                    ))
                    return

            # Fetch one extra row: its presence is the has_more signal for the
            # frontend's infinite scroll, without a separate COUNT query.
            log_entries = await repo.recent_logs(
                user_id=user_id,
                organization_id=request.organization_id,
                usage_type_filter=request.usage_type,
                limit=request.limit + 1,
                before=before,
                search=request.search,
            )
            has_more = len(log_entries) > request.limit
            log_entries = log_entries[:request.limit]

            # Stored values already use the public accounting unit.
            # Process results into a simple list. usage_type is included
            # so the dashboard can render category badges/labels alongside
            # the model name (see _update_logs_cache for the same shape on
            # the realtime/incremental update path).
            logs = []
            for entry in log_entries:
                logs.append({
                    'timestamp': entry.created_at.isoformat() if entry.created_at else None,
                    'usage_type': entry.usage_type,
                    'model': entry.usage_subtype,
                    'tokens': int(entry.quantity) if entry.quantity else 0,
                    'unit_type': entry.unit_type or 'tokens',
                    'cost': float(entry.total_cost) if entry.total_cost else 0.0,
                    'metadata': entry.metadata or {},
                })

            logger.info(f"[UsageDashboardHandler] Fetched {len(logs)} log entries for user {user_id}")

            response_data = {
                'logs': logs,
                'count': len(logs),
                'has_more': has_more,
            }

            # Cache the response (TTL cache handles expiry); filtered/paginated
            # queries have cache_key=None and are never cached.
            if cache_key is not None:
                self._cache[cache_key] = response_data

            # Send response
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=response_data
            ))

            logger.info(f"[UsageDashboardHandler] Sent usage logs for user {user_id}")

        except Exception as e:
            logger.error(f"[UsageDashboardHandler] Error handling usage logs request: {e}", exc_info=True)
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={},
                error=str(e)
            ))
